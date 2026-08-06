import tempfile
from datetime import date, timedelta
from pathlib import Path

from app.maintenance import MaintenanceService, easter_sunday, is_workday, workdays_until
from app.document_lifecycle import Analysis
from test_source_access import activate
from test_document_lifecycle import setup, submit


def workday_after(start: date, count: int) -> date:
    current = start
    remaining = count
    while remaining:
        current += timedelta(days=1)
        if is_workday(current):
            remaining -= 1
    return current


def test_niedersachsen_workdays_include_movable_holidays():
    assert easter_sunday(2026) == date(2026, 4, 5)
    assert not is_workday(date(2026, 4, 3))  # Karfreitag
    assert not is_workday(date(2026, 5, 14))  # Himmelfahrt
    assert workdays_until(date(2026, 4, 2), date(2026, 4, 7)) == 1


def test_expiry_notifications_are_one_digest_per_recipient_with_role_escalation():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        governance, lifecycle, kb_id = setup(root)
        active = activate(lifecycle, kb_id)
        today = date(2026, 8, 6)
        with governance.store.connect() as db:
            db.execute("UPDATE document_versions SET valid_until = ? WHERE version_id = ?", (workday_after(today, 1).isoformat(), active.version_id))
        service = MaintenanceService(governance.store, today=lambda: today)
        messages = service.generate_expiry_digest()
        recipients = {message.recipient for message in messages}
        assert recipients == {"employee@kahle.de", "manager@kahle.de", "admin@kahle.de", "portal@kahle.de"}
        assert all("Arbeitsdokumente" not in message.body for message in messages)
        assert all("In 1 Arbeitstag:" in message.body for message in messages)
        assert service.generate_expiry_digest() == []  # idempotent daily outbox


def test_expired_versions_are_removed_from_all_active_publications():
    with tempfile.TemporaryDirectory() as directory:
        governance, lifecycle, kb_id = setup(Path(directory))
        active = activate(lifecycle, kb_id)
        with governance.store.connect() as db:
            db.execute("UPDATE document_versions SET valid_until = '2026-08-05' WHERE version_id = ?", (active.version_id,))
        service = MaintenanceService(governance.store, today=lambda: date(2026, 8, 6))
        assert service.expire_due_versions() == [active.document_id]
        assert lifecycle.version_record(active.version_id)["status"] == "expired"
        with governance.store.connect() as db:
            status = db.execute("SELECT status FROM document_publications WHERE document_id = ?", (active.document_id,)).fetchone()["status"]
        assert status == "inactive"


def test_trash_reminders_and_physical_deletion_at_day_90(tmp_path: Path):
    governance, lifecycle, kb_id = setup(tmp_path)
    active = activate(lifecycle, kb_id)
    files = tmp_path / "files"
    version_dir = files / active.document_id / active.version_id
    version_dir.mkdir(parents=True)
    (version_dir / "original.md").write_text("secret", encoding="utf-8")
    service = MaintenanceService(governance.store, today=lambda: date(2026, 8, 6))
    service.move_to_trash(active.document_id, "admin", "Veraltet")
    with governance.store.connect() as db:
        db.execute("UPDATE document_trash SET trashed_at = '2026-07-07' WHERE document_id = ?", (active.document_id,))
    day30 = service.process_trash(files)
    assert day30["reminders"]
    service.today = lambda: date(2026, 10, 5)  # day 90
    day90 = service.process_trash(files)
    assert day90["deleted"] == [active.document_id]
    assert not (files / active.document_id).exists()
    with governance.store.connect() as db:
        assert db.execute("SELECT 1 FROM deletion_audit WHERE document_id = ?", (active.document_id,)).fetchone()
        assert not db.execute("SELECT 1 FROM canonical_documents WHERE document_id = ?", (active.document_id,)).fetchone()


def pending_case(governance, lifecycle, kb_id):
    case = submit(lifecycle, kb_id)
    case = lifecycle.record_analysis(
        case_id=case.case_id, normalized_sha256="b" * 64,
        markdown_sha256="c" * 64, analysis=Analysis(),
    )
    return lifecycle.choose_action(case_id=case.case_id, actor_user_id="employee", action="create")


def test_pending_approval_reminds_delegates_and_escalates_after_2_4_6_workdays(tmp_path: Path):
    governance, lifecycle, kb_id = setup(tmp_path)
    governance.sync_identity(user_id="delegate", email="delegate@kahle.de", display_name="Vertretung")
    governance.assign_delegate("admin", "manager", "delegate")
    case = pending_case(governance, lifecycle, kb_id)
    service = MaintenanceService(governance.store, today=lambda: date(2026, 8, 6))

    with governance.store.connect() as db:
        db.execute("UPDATE document_cases SET created_at='2026-08-04T09:00:00+00:00' WHERE case_id=?", (case.case_id,))
    assert service.process_pending_approvals()["reminders"]

    with governance.store.connect() as db:
        db.execute("UPDATE document_cases SET created_at='2026-07-31T09:00:00+00:00' WHERE case_id=?", (case.case_id,))
    assert service.process_pending_approvals()["delegated"]
    assert lifecycle.tasks_for("delegate")[0].case_id == case.case_id

    with governance.store.connect() as db:
        db.execute("UPDATE document_cases SET created_at='2026-07-29T09:00:00+00:00' WHERE case_id=?", (case.case_id,))
    assert service.process_pending_approvals()["escalated"]
    assert lifecycle.tasks_for("admin")[0].case_id == case.case_id


def test_active_absence_routes_new_case_to_configured_delegate_immediately(tmp_path: Path):
    governance, lifecycle, kb_id = setup(tmp_path)
    governance.sync_identity(user_id="delegate", email="delegate@kahle.de", display_name="Vertretung")
    governance.assign_delegate("admin", "manager", "delegate")
    governance.set_absence("admin", "manager", "2026-08-01", "2026-08-10", "Urlaub")
    case = pending_case(governance, lifecycle, kb_id)
    assert lifecycle.tasks_for("delegate")[0].case_id == case.case_id

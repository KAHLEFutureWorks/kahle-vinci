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
        assert service.REMINDER_STAGES == (7, 5, 1)
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


def test_superseded_version_files_are_purged_after_ninety_days():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        governance, lifecycle, kb_id = setup(root)
        first = activate(lifecycle, kb_id)
        files = root / "files"
        old_version_dir = files / first.document_id / first.version_id
        old_version_dir.mkdir(parents=True)
        (old_version_dir / "original.docx").write_bytes(b"old source")
        (old_version_dir / "rag.md").write_text("old knowledge", encoding="utf-8")

        replacement = submit(
            lifecycle, kb_id, sha="d" * 64, document_id=first.document_id,
        )
        lifecycle.record_analysis(
            case_id=replacement.case_id, normalized_sha256="e" * 64,
            markdown_sha256="f" * 64, analysis=Analysis(same_kb_similarity="very_high"),
        )
        lifecycle.choose_action(
            case_id=replacement.case_id, actor_user_id="employee", action="replace",
        )
        lifecycle.decide(
            case_id=replacement.case_id, actor_user_id="manager",
            decision="approve", reason="Neue Version fachlich geprüft",
        )
        replacement = lifecycle.activate(case_id=replacement.case_id)
        new_version_dir = files / replacement.document_id / replacement.version_id
        new_version_dir.mkdir(parents=True)
        (new_version_dir / "rag.md").write_text("current knowledge", encoding="utf-8")

        service = MaintenanceService(governance.store, today=lambda: date(2026, 11, 3))
        assert service.purge_superseded_version_files(files) == []
        assert old_version_dir.is_dir()

        service.today = lambda: date(2026, 11, 4)
        assert service.purge_superseded_version_files(files) == [first.version_id]
        assert not old_version_dir.exists()
        assert (new_version_dir / "rag.md").is_file()
        assert lifecycle.version_record(first.version_id)["status"] == "purged"
        with governance.store.connect() as db:
            event = db.execute(
                "SELECT actor_user_id, event_type FROM document_events WHERE case_id=? ORDER BY sequence DESC LIMIT 1",
                (first.case_id,),
            ).fetchone()
        assert tuple(event) == ("system", "superseded_version_purged")


def test_trash_reminders_and_physical_deletion_at_day_90(tmp_path: Path):
    governance, lifecycle, kb_id = setup(tmp_path)
    active = activate(lifecycle, kb_id)
    files = tmp_path / "files"
    version_dir = files / active.document_id / active.version_id
    version_dir.mkdir(parents=True)
    (version_dir / "original.md").write_text("secret", encoding="utf-8")
    service = MaintenanceService(
        governance.store,
        today=lambda: date(2026, 8, 6),
        portal_public_url="https://vinci.kahle.de",
    )
    service.move_to_trash(active.document_id, "admin", "Veraltet")
    with governance.store.connect() as db:
        db.execute("UPDATE document_trash SET trashed_at = '2026-07-07' WHERE document_id = ?", (active.document_id,))
    assert service.process_trash(files)["reminders"] == []
    service.today = lambda: date(2026, 9, 29)  # four workdays before 2026-10-05
    warning = service.process_trash(files)
    assert warning["reminders"]
    with governance.store.connect() as db:
        mails = db.execute(
            "SELECT subject, body FROM notification_outbox WHERE kind='trash_deletion_digest'"
        ).fetchall()
    assert len(mails) == 2  # admin and portal admin each receive one digest
    assert all("Endgültige Löschung aus dem Papierkorb" in mail["subject"] for mail in mails)
    assert all("Arbeitsanweisung" in mail["body"] for mail in mails)
    assert all(
        f"https://vinci.kahle.de/wissen/?document={active.document_id}" in mail["body"]
        for mail in mails
    )
    service.today = lambda: date(2026, 10, 5)  # day 90
    day90 = service.process_trash(files)
    assert day90["deleted"] == [active.document_id]
    assert not (files / active.document_id).exists()
    with governance.store.connect() as db:
        assert db.execute("SELECT 1 FROM deletion_audit WHERE document_id = ?", (active.document_id,)).fetchone()
        assert not db.execute("SELECT 1 FROM canonical_documents WHERE document_id = ?", (active.document_id,)).fetchone()


def test_trash_unread_count_is_personal_and_cleared_when_opened(tmp_path: Path):
    governance, lifecycle, kb_id = setup(tmp_path)
    active = activate(lifecycle, kb_id)
    service = MaintenanceService(governance.store, today=lambda: date(2026, 8, 6))
    service.move_to_trash(active.document_id, "admin", "Veraltet")

    assert service.list_removals("admin")["unread_count"] == 1
    assert service.list_removals("portal")["unread_count"] == 1
    service.mark_trash_read("admin")
    assert service.list_removals("admin")["unread_count"] == 0
    assert service.list_removals("portal")["unread_count"] == 1


def pending_case(governance, lifecycle, kb_id):
    case = submit(lifecycle, kb_id)
    case = lifecycle.record_analysis(
        case_id=case.case_id, normalized_sha256="b" * 64,
        markdown_sha256="c" * 64, analysis=Analysis(),
    )
    return case


def test_pending_approval_reminds_delegates_and_escalates_after_2_4_6_workdays(tmp_path: Path):
    governance, lifecycle, kb_id = setup(tmp_path)
    governance.sync_identity(user_id="delegate", email="delegate@kahle.de", display_name="Vertretung")
    governance.set_role("portal", "delegate", "manager")
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
    assert lifecycle.tasks_for("portal")[0].case_id == case.case_id


def test_active_absence_routes_new_case_to_configured_delegate_immediately(tmp_path: Path):
    governance, lifecycle, kb_id = setup(tmp_path)
    governance.sync_identity(user_id="delegate", email="delegate@kahle.de", display_name="Vertretung")
    governance.set_role("portal", "delegate", "manager")
    governance.assign_delegate("admin", "manager", "delegate")
    governance.set_absence("admin", "manager", "2026-08-01", "2026-08-10", "Urlaub")
    case = pending_case(governance, lifecycle, kb_id)
    assert lifecycle.tasks_for("delegate")[0].case_id == case.case_id


def test_absent_delegate_routes_case_directly_to_admin(tmp_path: Path):
    governance, lifecycle, kb_id = setup(tmp_path)
    governance.sync_identity(user_id="delegate", email="delegate@kahle.de", display_name="Vertretung")
    governance.set_role("portal", "delegate", "manager")
    governance.assign_delegate("admin", "manager", "delegate")
    governance.assign_delegate("admin", "delegate", "portal")
    governance.set_absence("admin", "manager", "2026-08-01", "2026-08-10", "Urlaub")
    governance.set_absence("admin", "delegate", "2026-08-01", "2026-08-10", "Urlaub")
    case = pending_case(governance, lifecycle, kb_id)

    service = MaintenanceService(governance.store, today=lambda: date(2026, 8, 6))
    result = service.process_pending_approvals()

    assert result["admin_fallback"]
    assert lifecycle.submission(case.case_id).status == "pending_admin_approval"
    assert lifecycle.version_record(case.version_id)["status"] == "pending_admin_approval"
    assert case.case_id in {task.case_id for task in lifecycle.tasks_for("admin")}

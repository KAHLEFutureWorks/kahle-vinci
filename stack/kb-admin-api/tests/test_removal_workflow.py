import tempfile
from datetime import date
from pathlib import Path

from app.maintenance import MaintenanceService
from test_document_lifecycle import setup
from test_source_access import activate


def test_employee_removal_request_requires_admin_and_restore_reactivates_valid_version():
    with tempfile.TemporaryDirectory() as directory:
        governance, lifecycle, kb_id = setup(Path(directory))
        active = activate(lifecycle, kb_id)
        service = MaintenanceService(governance.store, today=lambda: date(2026, 8, 6))
        request_id = service.request_removal(active.document_id, "employee", "delete", "Nicht mehr verwenden")
        assert service.list_removals()["requests"][0]["status"] == "pending"
        service.decide_removal(request_id, "admin", True, "Entfernung bestätigt")
        assert service.list_removals()["trash"][0]["document_id"] == active.document_id
        assert lifecycle.active_version(active.document_id) is None
        service.restore_from_trash(active.document_id, "admin", "Versehentlich entfernt")
        assert lifecycle.active_version(active.document_id) == active.version_id


def test_legal_hold_suspends_automatic_physical_deletion(tmp_path: Path):
    governance, lifecycle, kb_id = setup(tmp_path)
    active = activate(lifecycle, kb_id)
    service = MaintenanceService(governance.store, today=lambda: date(2026, 8, 6))
    service.request_removal(active.document_id, "admin", "delete", "Aufräumen")
    service.set_legal_hold(active.document_id, "admin", True, "Rechtsprüfung", "2026-09-01")
    with governance.store.connect() as db:
        db.execute("UPDATE document_trash SET trashed_at='2026-01-01' WHERE document_id=?", (active.document_id,))
    assert service.process_trash(tmp_path / "files")["deleted"] == []

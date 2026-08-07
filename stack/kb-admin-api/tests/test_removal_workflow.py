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


def test_trashed_documents_disappear_from_both_listings():
    """
    Ein Dokument im Papierkorb darf weder in der eigenen Dokumentliste noch in
    der Adminuebersicht stehen. Sonst sieht es aus, als waere es weiterhin
    Bestandteil des Wissens, und niemand erkennt, dass es entfernt wurde.
    """
    import tempfile
    from pathlib import Path
    from fastapi.testclient import TestClient
    from test_portal_api import identity, load_app

    with tempfile.TemporaryDirectory() as directory:
        module = load_app(Path(directory))
        current = {"user": identity("portal", "admin")}
        module.app.dependency_overrides[module.require_openwebui_user] = lambda: current["user"]
        client = TestClient(module.app)
        assert client.get("/portal/session").status_code == 200

        kb = module.PORTAL_GOVERNANCE.request_knowledgebase_change(
            "portal", "create", payload={"slug": "service", "label": "Service"},
        )
        module.PORTAL_GOVERNANCE.grant_access(
            "portal", "portal", kb.knowledgebase_id, can_read=True, can_upload=True,
        )
        case = module.DOCUMENT_LIFECYCLE.submit(
            uploaded_by_user_id="portal", owner_user_id="portal",
            target_knowledgebase_id=kb.knowledgebase_id, title="Wegwerfdokument",
            original_filename="weg.md", original_file_id="weg",
            original_sha256="f" * 64, valid_workdays=30, confidentiality="internal",
        )

        titles = lambda: [item["title"] for item in client.get("/portal/documents").json()["documents"]]
        assert "Wegwerfdokument" in titles()

        module.MAINTENANCE.move_to_trash(case.document_id, "portal", "Nicht mehr benoetigt")

        assert "Wegwerfdokument" not in titles()
        overview = client.get("/portal/admin/knowledgebase-overview").json()["knowledgebases"]
        assert not any(
            doc["title"] == "Wegwerfdokument"
            for base in overview for doc in base["documents"]
        )
        # Im Papierkorb steht er weiterhin, jetzt aber mit lesbarem Titel.
        trash = client.get("/portal/admin/removals").json()["trash"]
        assert any(item.get("title") == "Wegwerfdokument" for item in trash), trash

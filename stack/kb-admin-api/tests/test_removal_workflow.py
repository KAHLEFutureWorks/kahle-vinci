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


def test_only_portal_admins_delete_immediately_and_legal_hold_still_blocks():
    """
    Der regulaere Weg loescht erst nach 90 Tagen. Ein Portal-Admin darf das
    abkuerzen; ein Legal Hold bleibt aber auch fuer ihn bindend.
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
        module.PORTAL_GOVERNANCE.sync_identity(
            user_id="admin2", email="admin2@kahle.de", display_name="Zweiter Admin",
        )
        module.PORTAL_GOVERNANCE.set_role("portal", "admin2", "admin")

        kb = module.PORTAL_GOVERNANCE.request_knowledgebase_change(
            "portal", "create", payload={"slug": "service", "label": "Service"},
        )
        def trashed(title: str) -> str:
            case = module.DOCUMENT_LIFECYCLE.submit(
                uploaded_by_user_id="portal", owner_user_id="portal",
                target_knowledgebase_id=kb.knowledgebase_id, title=title,
                original_filename=f"{title}.md", original_file_id=title,
                original_sha256=("a" * 63 + title[-1]), valid_workdays=30,
                confidentiality="internal",
            )
            module.MAINTENANCE.move_to_trash(case.document_id, "portal", "Weg damit")
            return case.document_id

        normal = trashed("Dokument1")
        held = trashed("Dokument2")
        module.MAINTENANCE.set_legal_hold(held, "portal", True, "Laufendes Verfahren", "2026-12-01")

        # Ein normaler Admin darf nicht sofort loeschen.
        current["user"] = identity("admin2", "user")
        assert client.get("/portal/session").status_code == 200
        forbidden = client.post(f"/portal/admin/trash/{normal}/delete", json={"reason": "Weg"})
        assert forbidden.status_code == 403
        assert forbidden.json()["detail"] == "portal_admin_required"

        current["user"] = identity("portal", "admin")
        blocked = client.post(f"/portal/admin/trash/{held}/delete", json={"reason": "Weg damit"})
        assert blocked.status_code == 409
        assert blocked.json()["detail"] == "legal_hold_blocks_deletion"

        deleted = client.post(f"/portal/admin/trash/{normal}/delete", json={"reason": "Endgültig weg"})
        assert deleted.status_code == 200, deleted.text
        remaining = [item["document_id"] for item in client.get("/portal/admin/removals").json()["trash"]]
        assert normal not in remaining and held in remaining


def test_withdrawn_cases_leave_no_orphan_draft_in_the_document_list():
    """
    Wer einen Vorgang verwirft, erwartet, dass nichts zurueckbleibt. Der Entwurf
    stand danach weiter im Bestand und liess sich nur noch in den Papierkorb
    schieben.
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
            target_knowledgebase_id=kb.knowledgebase_id, title="Verworfen",
            original_filename="weg.md", original_file_id="weg",
            original_sha256="b" * 64, valid_workdays=30, confidentiality="internal",
        )
        module.DOCUMENT_LIFECYCLE.record_analysis(
            case_id=case.case_id, normalized_sha256="c" * 64, markdown_sha256="d" * 64,
            analysis=module.Analysis(),
        )
        titles = lambda: [item["title"] for item in client.get("/portal/documents").json()["documents"]]
        assert "Verworfen" in titles()

        module.DOCUMENT_LIFECYCLE.choose_action(
            case_id=case.case_id, actor_user_id="portal", action="discard",
        )
        assert "Verworfen" not in titles()


def test_trashed_documents_no_longer_count_as_similar_content():
    """
    Nach dem Loeschen aller Dokumente meldete der naechste Upload weiter eine
    sehr hohe Aehnlichkeit. move_to_thrash setzt die Version auf 'trash',
    pflegte aber den eigenen Status des Analysekorpus nicht nach.
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
        case = module.DOCUMENT_LIFECYCLE.submit(
            uploaded_by_user_id="portal", owner_user_id="portal",
            target_knowledgebase_id=kb.knowledgebase_id, title="Altbestand",
            original_filename="alt.md", original_file_id="alt",
            original_sha256="d" * 64, valid_workdays=30, confidentiality="internal",
        )
        module.GLOBAL_CORPUS.upsert(module.CorpusDocument(
            case.document_id, case.version_id, "Altbestand",
            "Die Richtlinie regelt den Einsatz von KI im Unternehmen.",
            (kb.knowledgebase_id,), "active",
        ))
        assert [doc.version_id for doc in module.GLOBAL_CORPUS.documents()] == [case.version_id]

        module.MAINTENANCE.move_to_trash(case.document_id, "portal", "Alles neu aufsetzen")
        assert module.GLOBAL_CORPUS.documents() == [], (
            "ein Dokument im Papierkorb darf keinen Aehnlichkeitstreffer mehr ausloesen"
        )


def test_corpus_entries_do_not_survive_their_version():
    """
    Nach der physischen Loeschung blieb der Korpuseintrag zurueck und meldete
    weiter eine sehr hohe Aehnlichkeit fuer ein Dokument, das es nicht mehr gab.
    """
    import tempfile
    from pathlib import Path
    from fastapi.testclient import TestClient
    from test_portal_api import identity, load_app

    with tempfile.TemporaryDirectory() as directory:
        module = load_app(Path(directory))
        current = {"user": identity("portal", "admin")}
        module.app.dependency_overrides[module.require_openwebui_user] = lambda: current["user"]
        assert TestClient(module.app).get("/portal/session").status_code == 200

        kb = module.PORTAL_GOVERNANCE.request_knowledgebase_change(
            "portal", "create", payload={"slug": "service", "label": "Service"},
        )
        case = module.DOCUMENT_LIFECYCLE.submit(
            uploaded_by_user_id="portal", owner_user_id="portal",
            target_knowledgebase_id=kb.knowledgebase_id, title="Vergaenglich",
            original_filename="v.md", original_file_id="v",
            original_sha256="9" * 64, valid_workdays=30, confidentiality="internal",
        )
        module.GLOBAL_CORPUS.upsert(module.CorpusDocument(
            case.document_id, case.version_id, "Vergaenglich", "Inhalt",
            (kb.knowledgebase_id,), "active",
        ))
        assert module.GLOBAL_CORPUS.documents()

        module.MAINTENANCE.move_to_trash(case.document_id, "portal", "Weg damit")
        module.MAINTENANCE.delete_now(case.document_id, "portal", "Endgültig weg")

        assert module.GLOBAL_CORPUS.documents() == [], (
            "ein physisch geloeschtes Dokument darf keinen Korpuseintrag hinterlassen"
        )

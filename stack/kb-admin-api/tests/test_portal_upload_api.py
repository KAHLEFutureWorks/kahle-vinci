from __future__ import annotations

import tempfile
import io
import zipfile
from types import SimpleNamespace
from pathlib import Path

from fastapi.testclient import TestClient

from test_portal_api import identity, load_app


def test_portal_upload_uses_account_owner_and_creates_quarantined_case():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        module = load_app(root)
        # load_app creates the module before this test overrides its storage adapter.
        module.SECURE_INGEST.storage.root = (root / "portal-files").resolve()
        current = {"user": identity("portal", "admin")}
        module.app.dependency_overrides[module.require_openwebui_user] = lambda: current["user"]
        client = TestClient(module.app)
        assert client.get("/portal/session").status_code == 200

        current["user"] = identity("employee")
        assert client.get("/portal/session").status_code == 200
        created = module.PORTAL_GOVERNANCE.request_knowledgebase_change("portal", "create", payload={"slug": "kahleallgemein", "label": "Allgemeines Wissen", "purpose": "Testwissen"})
        module.PORTAL_GOVERNANCE.grant_access(
            "portal", "employee", created.knowledgebase_id, can_read=True, can_upload=True
        )

        class Scanner:
            def scan(self, filename, data):
                assert filename == "wissen.md"

        class Converter:
            def convert(self, filename, data, title):
                return "# Wissen\n\nGepr?fter und vollst?ndig aufbereiteter fachlicher Inhalt.\n"


        module.SECURE_INGEST.scanner = Scanner()
        module.SECURE_INGEST.converter = Converter()
        response = client.post(
            "/portal/documents",
            data={
                "knowledgebase_id": created.knowledgebase_id,
                "title": "Wissen",
                "valid_workdays": "60",
                "confidentiality": "internal",
            },
            files={"file": ("wissen.md", b"Original", "text/markdown")},
        )
        assert response.status_code == 201, response.text
        payload = response.json()
        assert payload["owner_email"] == "employee@kahle.de"
        assert payload["status"] == "pending_employee_decision"
        assert payload["prompt_injection_risk"] == "none"




def test_docx_http_flow_activates_and_exposes_original_only_to_read_authorized_user():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); module = load_app(root)
        module.SECURE_INGEST.storage.root = (root / "portal-files").resolve()
        module.PORTAL_FILES_ROOT = module.SECURE_INGEST.storage.root
        module.RAG_METADATA.files_root = module.SECURE_INGEST.storage.root
        current = {"user": identity("portal", "admin")}
        module.app.dependency_overrides[module.require_openwebui_user] = lambda: current["user"]
        client = TestClient(module.app)
        assert client.get("/portal/session").status_code == 200
        module.PORTAL_GOVERNANCE.sync_identity(user_id="manager", email="manager@kahle.de", display_name="Leitung")
        module.PORTAL_GOVERNANCE.sync_identity(user_id="employee", email="employee@kahle.de", display_name="Mitarbeiter")
        module.PORTAL_GOVERNANCE.set_role("portal", "manager", "manager")
        module.PORTAL_GOVERNANCE.assign_manager("portal", "employee", "manager")
        kb = module.PORTAL_GOVERNANCE.request_knowledgebase_change(
            "portal", "create", payload={"slug": "service", "label": "Service"}
        )
        module.PORTAL_GOVERNANCE.grant_access("portal", "employee", kb.knowledgebase_id, can_read=True, can_upload=True)

        class Scanner:
            def scan(self, filename, data):
                return None
        class Converter:
            def convert(self, filename, data, title):
                return "# Serviceprozess\n\nVollständig geprüfter Inhalt für den Servicebereich.\n"
        module.SECURE_INGEST.scanner = Scanner(); module.SECURE_INGEST.converter = Converter()
        office = io.BytesIO()
        with zipfile.ZipFile(office, "w") as archive:
            archive.writestr("[Content_Types].xml", b"<Types/>")
            archive.writestr("word/document.xml", b"<w:document/>")

        current["user"] = identity("employee")
        uploaded = client.post(
            "/portal/documents",
            data={"knowledgebase_id": kb.knowledgebase_id, "title": "Serviceprozess",
                  "valid_workdays": "60", "confidentiality": "internal"},
            files={"file": ("service.docx", office.getvalue(),
                             "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        assert uploaded.status_code == 201, uploaded.text
        payload = uploaded.json()
        assert client.post(f"/portal/cases/{payload['case_id']}/action", json={"action": "create"}).status_code == 200
        current["user"] = identity("manager")
        assert client.post(f"/portal/cases/{payload['case_id']}/decision",
                           json={"decision": "approve", "reason": "Fachlich geprüft"}).status_code == 200
        module._trigger_hybrid_reindex = lambda: {"ok": True}
        current["user"] = identity("portal", "admin")
        activated = client.post(f"/portal/cases/{payload['case_id']}/decision",
                                json={"decision": "approve", "reason": "Final freigegeben"})
        assert activated.status_code == 200, activated.text
        assert activated.json()["case"]["status"] == "active"

        current["user"] = identity("employee")
        source = client.get(f"/portal/sources/{payload['version_id']}")
        assert source.status_code == 200
        assert source.content == office.getvalue()
        module.PORTAL_GOVERNANCE.grant_access("portal", "employee", kb.knowledgebase_id, can_read=False, can_upload=True)
        assert client.get(f"/portal/sources/{payload['version_id']}").status_code == 404


def test_http_replace_action_moves_uploaded_version_under_selected_canonical_document():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); module = load_app(root)
        files_root = (root / "portal-files").resolve()
        module.SECURE_INGEST.storage.root = files_root
        module.PORTAL_FILES_ROOT = files_root
        module.RAG_METADATA.files_root = files_root
        current = {"user": identity("portal", "admin")}
        module.app.dependency_overrides[module.require_openwebui_user] = lambda: current["user"]
        client = TestClient(module.app); assert client.get("/portal/session").status_code == 200
        module.PORTAL_GOVERNANCE.sync_identity(user_id="manager", email="manager@kahle.de", display_name="Leitung")
        module.PORTAL_GOVERNANCE.sync_identity(user_id="employee", email="employee@kahle.de", display_name="Mitarbeiter")
        module.PORTAL_GOVERNANCE.set_role("portal", "manager", "manager")
        module.PORTAL_GOVERNANCE.assign_manager("portal", "employee", "manager")
        kb = module.PORTAL_GOVERNANCE.request_knowledgebase_change(
            "portal", "create", payload={"slug": "service", "label": "Service"}
        )
        module.PORTAL_GOVERNANCE.grant_access("portal", "employee", kb.knowledgebase_id, can_read=True, can_upload=True)
        first = module.DOCUMENT_LIFECYCLE.submit(
            uploaded_by_user_id="employee", owner_user_id="employee", target_knowledgebase_id=kb.knowledgebase_id,
            title="Arbeitsanweisung", original_filename="alt.md", original_file_id="alt", original_sha256="a"*64,
            valid_workdays=60, confidentiality="internal",
        )
        with module.PORTAL_GOVERNANCE.store.connect() as db:
            db.execute("UPDATE document_versions SET status='active',valid_from='2026-08-01',valid_until='2026-10-01' WHERE version_id=?", (first.version_id,))
            db.execute("UPDATE canonical_documents SET active_version_id=? WHERE document_id=?", (first.version_id, first.document_id))
            db.execute("UPDATE document_publications SET status='active' WHERE document_id=?", (first.document_id,))

        class Scanner:
            def scan(self, filename, data): return None
        class Converter:
            def convert(self, filename, data, title): return "# Arbeitsanweisung\n\nNeue und vollst?ndig gepr?fte Fassung des Prozesses.\n"
        class Analyzer:
            def analyze(self, **kwargs):
                match = SimpleNamespace(
                    document_id=first.document_id, version_id=first.version_id, title="Arbeitsanweisung",
                    knowledgebase_ids=(kb.knowledgebase_id,), level="very_high", combined_score=.94,
                    lexical_score=.93, semantic_score=None, version_candidate=True, conflicting_passages=(),
                )
                return SimpleNamespace(normalized_sha256="b"*64, exact_document_id=None,
                                       matches=(match,), contradiction_document_ids=())
        module.SECURE_INGEST.scanner=Scanner(); module.SECURE_INGEST.converter=Converter(); module.GLOBAL_ANALYZER=Analyzer()
        current["user"] = identity("employee")
        uploaded = client.post(
            "/portal/documents", data={"knowledgebase_id":kb.knowledgebase_id,"title":"Arbeitsanweisung",
            "valid_workdays":"60","confidentiality":"internal"},
            files={"file":("neu.md",b"Neue Fassung","text/markdown")},
        )
        assert uploaded.status_code == 201, uploaded.text
        body=uploaded.json(); draft_document_id=body["document_id"]
        assert body["matches"][0]["version_candidate"] is True
        action=client.post(f"/portal/cases/{body['case_id']}/action",
                           json={"action":"replace","target_document_id":first.document_id})
        assert action.status_code == 200, action.text
        assert action.json()["case"]["document_id"] == first.document_id
        assert (files_root / first.document_id / body["version_id"] / "rag.md").exists()
        assert not (files_root / draft_document_id).exists()
        assert module.DOCUMENT_LIFECYCLE.version_record(body["version_id"])["previous_version_id"] == first.version_id


def test_required_scanner_outage_fails_closed_and_creates_admin_incident():
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory); module=load_app(root)
        module.SECURE_INGEST.storage.root=(root/"portal-files").resolve()
        current={"user":identity("portal","admin")}
        module.app.dependency_overrides[module.require_openwebui_user]=lambda:current["user"]
        client=TestClient(module.app); assert client.get("/portal/session").status_code==200
        module.PORTAL_GOVERNANCE.sync_identity(user_id="employee",email="employee@kahle.de",display_name="Mitarbeiter")
        kb=module.PORTAL_GOVERNANCE.request_knowledgebase_change("portal","create",payload={"slug":"service","label":"Service"})
        module.PORTAL_GOVERNANCE.grant_access("portal","employee",kb.knowledgebase_id,can_read=True,can_upload=True)
        class UnavailableScanner:
            def scan(self,filename,data): raise module.IngestError("malware_scanner_unavailable")
        module.SECURE_INGEST.scanner=UnavailableScanner()
        current["user"]=identity("employee")
        response=client.post("/portal/documents",data={"knowledgebase_id":kb.knowledgebase_id,
            "title":"Pr?fung","valid_workdays":"60","confidentiality":"internal"},
            files={"file":("test.md",b"sicherer Inhalt","text/markdown")})
        assert response.status_code==503
        assert response.json()["detail"].startswith("required_check_unavailable:")
        assert module.QUALITY_CASES.open_cases()["incidents"][0]["step"]=="required_ingest_check"


def _upload_ready_client(directory):
    """Portal client with an employee who may upload into one knowledgebase."""
    root = Path(directory)
    module = load_app(root)
    module.SECURE_INGEST.storage.root = (root / "portal-files").resolve()
    current = {"user": identity("portal", "admin")}
    module.app.dependency_overrides[module.require_openwebui_user] = lambda: current["user"]
    client = TestClient(module.app)
    assert client.get("/portal/session").status_code == 200
    current["user"] = identity("employee")
    assert client.get("/portal/session").status_code == 200
    created = module.PORTAL_GOVERNANCE.request_knowledgebase_change(
        "portal", "create",
        payload={"slug": "kahleallgemein", "label": "Allgemeines Wissen", "purpose": "Testwissen"},
    )
    module.PORTAL_GOVERNANCE.grant_access(
        "portal", "employee", created.knowledgebase_id, can_read=True, can_upload=True
    )

    class Scanner:
        def scan(self, filename, data):
            return None

    class Converter:
        def convert(self, filename, data, title):
            return "# Wissen\n\nGeprueter und vollstaendig aufbereiteter fachlicher Inhalt.\n"

    module.SECURE_INGEST.scanner = Scanner()
    module.SECURE_INGEST.converter = Converter()
    return module, client, created.knowledgebase_id


def test_upload_accepts_a_checked_date_instead_of_workdays():
    from datetime import date

    from document_lifecycle import add_workdays

    with tempfile.TemporaryDirectory() as directory:
        _, client, knowledgebase_id = _upload_ready_client(directory)
        valid_until = add_workdays(date.today(), 20)
        response = client.post(
            "/portal/documents",
            data={
                "knowledgebase_id": knowledgebase_id, "title": "Wissen",
                "valid_until": valid_until.isoformat(), "confidentiality": "internal",
            },
            files={"file": ("wissen.md", b"Original", "text/markdown")},
        )
        assert response.status_code == 201, response.text


def test_upload_requires_exactly_one_of_workdays_or_date():
    with tempfile.TemporaryDirectory() as directory:
        module, client, knowledgebase_id = _upload_ready_client(directory)
        for data in (
            {"knowledgebase_id": knowledgebase_id, "title": "Wissen", "confidentiality": "internal"},
            {"knowledgebase_id": knowledgebase_id, "title": "Wissen", "confidentiality": "internal",
             "valid_workdays": "20", "valid_until": "2099-01-01"},
        ):
            response = client.post(
                "/portal/documents", data=data,
                files={"file": ("wissen.md", b"Original", "text/markdown")},
            )
            assert response.status_code == 422, response.text
            assert response.json()["detail"] == "valid_workdays_or_valid_until_required"


def test_upload_rejects_a_date_beyond_sixty_workdays():
    from datetime import date, timedelta

    with tempfile.TemporaryDirectory() as directory:
        module, client, knowledgebase_id = _upload_ready_client(directory)
        from document_lifecycle import add_workdays
        too_far = add_workdays(date.today(), 60) + timedelta(days=7)
        response = client.post(
            "/portal/documents",
            data={
                "knowledgebase_id": knowledgebase_id, "title": "Wissen",
                "valid_until": too_far.isoformat(), "confidentiality": "internal",
            },
            files={"file": ("wissen.md", b"Original", "text/markdown")},
        )
        assert response.status_code == 422, response.text
        assert response.json()["detail"] == "valid_workdays_out_of_range"

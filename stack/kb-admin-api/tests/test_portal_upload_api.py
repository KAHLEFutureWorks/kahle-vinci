from __future__ import annotations

import tempfile
import io
import zipfile
from types import SimpleNamespace
from pathlib import Path

from fastapi.testclient import TestClient

from test_portal_api import identity, load_app


def test_clean_general_upload_uses_account_owner_and_is_activated_by_manager():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        module = load_app(root)
        # load_app creates the module before this test overrides its storage adapter.
        module.SECURE_INGEST.storage.root = (root / "portal-files").resolve()
        module.PORTAL_FILES_ROOT = module.SECURE_INGEST.storage.root
        module.RAG_METADATA.files_root = module.SECURE_INGEST.storage.root
        current = {"user": identity("portal", "admin")}
        module.app.dependency_overrides[module.require_openwebui_user] = lambda: current["user"]
        client = TestClient(module.app)
        assert client.get("/portal/session").status_code == 200

        current["user"] = identity("employee")
        assert client.get("/portal/session").status_code == 200
        module.PORTAL_GOVERNANCE.sync_identity(
            user_id="manager", email="manager@kahle.de", display_name="Leitung",
        )
        module.PORTAL_GOVERNANCE.set_role("portal", "manager", "manager")
        module.PORTAL_GOVERNANCE.assign_manager("portal", "employee", "manager")
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
        assert payload["status"] == "pending_manager_approval"
        assert payload["prompt_injection_risk"] == "none"
        module._trigger_hybrid_reindex = lambda: {"ok": True}
        module._trigger_hybrid_document_sync = lambda _document_id: {"ok": True}
        module._trigger_hybrid_version_sync = lambda _version_id: {"ok": True}
        current["user"] = identity("manager")
        decided = client.post(
            f"/portal/cases/{payload['case_id']}/decision",
            json={"decision": "approve", "reason": ""},
        )
        assert decided.status_code == 202, decided.text
        completed = client.get(f"/portal/decision-jobs/{decided.json()['job_id']}")
        assert completed.status_code == 200, completed.text
        assert completed.json()["status"] == "completed"
        assert completed.json()["result"]["case"]["status"] == "active"


def test_restricted_term_upload_is_stopped_for_admin_review_with_visible_finding():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); module = load_app(root)
        module.SECURE_INGEST.storage.root = (root / "portal-files").resolve()
        current = {"user": identity("portal", "admin")}
        module.app.dependency_overrides[module.require_openwebui_user] = lambda: current["user"]
        client = TestClient(module.app)
        assert client.get("/portal/session").status_code == 200
        current["user"] = identity("employee")
        assert client.get("/portal/session").status_code == 200
        current["user"] = identity("portal", "admin")
        module.PORTAL_GOVERNANCE.sync_identity(
            user_id="manager", email="manager@kahle.de", display_name="Leitung",
        )
        module.PORTAL_GOVERNANCE.set_role("portal", "manager", "manager")
        module.PORTAL_GOVERNANCE.assign_manager("portal", "employee", "manager")
        current["user"] = identity("employee")
        kb = module.PORTAL_GOVERNANCE.request_knowledgebase_change(
            "portal", "create", payload={"slug": "service", "label": "Service"}
        )
        module.PORTAL_GOVERNANCE.grant_access(
            "portal", "employee", kb.knowledgebase_id, can_read=True, can_upload=True
        )
        module.SECURE_INGEST.scanner = SimpleNamespace(scan=lambda *_: None)
        module.SECURE_INGEST.converter = SimpleNamespace(
            convert=lambda *_: "# Interne Anleitung\n\nDiese TPI verweist auf einen Reparaturleitfaden.\n"
        )
        response = client.post(
            "/portal/documents",
            data={"knowledgebase_id":kb.knowledgebase_id,"title":"Interne Anleitung",
                  "valid_workdays":"60","confidentiality":"internal"},
            files={"file":("anleitung.md",b"Original","text/markdown")},
        )
        assert response.status_code == 201, response.text
        assert response.json()["status"] == "pending_manager_approval"
        assert response.json()["restricted_terms"] == ["Reparaturleitfaden", "TPI"]
        assert "Gesperrte Begriffe gefunden: Reparaturleitfaden, TPI" in response.json()["confidentiality_reason"]
        current["user"] = identity("manager")
        tasks = client.get("/portal/tasks").json()["tasks"]
        task = next(item for item in tasks if item["case_id"] == response.json()["case_id"])
        assert task["restricted_terms"] == ["Reparaturleitfaden", "TPI"]
        approved = client.post(
            f"/portal/cases/{task['case_id']}/decision",
            json={"decision":"approve","reason":"Fachlich geprüft"},
        )
        assert approved.status_code == 202
        completed = client.get(f"/portal/decision-jobs/{approved.json()['job_id']}").json()
        assert completed["status"] == "completed"
        assert completed["result"]["case"]["status"] == "pending_admin_approval"
        current["user"] = identity("portal", "admin")
        assert task["case_id"] in {
            item["case_id"] for item in client.get("/portal/tasks").json()["tasks"]
        }


def test_clean_area_upload_is_automatically_active_and_retrievable_when_switch_is_on():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); module = load_app(root)
        files_root = (root / "portal-files").resolve()
        module.SECURE_INGEST.storage.root = files_root
        module.PORTAL_FILES_ROOT = files_root
        module.RAG_METADATA.files_root = files_root
        module.DOCUMENT_LIFECYCLE.auto_activation_enabled = lambda: True
        module._trigger_hybrid_reindex = lambda: {"ok": True}
        module._trigger_hybrid_document_sync = lambda _document_id: {"ok": True}
        module._trigger_hybrid_version_sync = lambda _version_id: {"ok": True}
        current = {"user": identity("portal", "admin")}
        module.app.dependency_overrides[module.require_openwebui_user] = lambda: current["user"]
        client = TestClient(module.app); assert client.get("/portal/session").status_code == 200
        current["user"] = identity("employee")
        assert client.get("/portal/session").status_code == 200
        kb = module.PORTAL_GOVERNANCE.request_knowledgebase_change(
            "portal", "create", payload={"slug":"service","label":"Service"},
        )
        module.PORTAL_GOVERNANCE.grant_access(
            "portal", "employee", kb.knowledgebase_id, can_read=True, can_upload=True,
        )
        module.SECURE_INGEST.scanner = SimpleNamespace(scan=lambda *_: None)
        module.SECURE_INGEST.converter = SimpleNamespace(
            convert=lambda *_: "# Reifenwechsel\n\nRäder mit dem vorgeschriebenen Drehmoment montieren.\n",
        )
        response = client.post(
            "/portal/documents",
            data={"knowledgebase_id":kb.knowledgebase_id,"title":"Reifenwechsel",
                  "valid_workdays":"60","confidentiality":"internal"},
            files={"file":("reifenwechsel.md",b"Original","text/markdown")},
        )
        assert response.status_code == 201, response.text
        assert response.json()["status"] == "active"
        assert client.get(f"/portal/sources/{response.json()['version_id']}").status_code == 200
        notifications = client.get("/portal/notifications").json()["notifications"]
        assert notifications[0]["status"] == "active"
        assert notifications[0]["document_title"] == "Reifenwechsel"
        assert notifications[0]["read_at"] is None
        assert "veröffentlicht und in Vinci abrufbar" in notifications[0]["message"]
        assert client.post(
            f"/portal/notifications/{notifications[0]['notification_id']}/read"
        ).status_code == 200
        assert client.get("/portal/notifications").json()["notifications"][0]["read_at"]




def test_clean_area_docx_is_automatically_active_and_exposes_original_only_to_read_authorized_user():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); module = load_app(root)
        module.SECURE_INGEST.storage.root = (root / "portal-files").resolve()
        module.PORTAL_FILES_ROOT = module.SECURE_INGEST.storage.root
        module.RAG_METADATA.files_root = module.SECURE_INGEST.storage.root
        module.DOCUMENT_LIFECYCLE.auto_activation_enabled = lambda: True
        module._trigger_hybrid_reindex = lambda: {"ok": True}
        module._trigger_hybrid_document_sync = lambda _document_id: {"ok": True}
        module._trigger_hybrid_version_sync = lambda _version_id: {"ok": True}
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
        assert payload["status"] == "active"

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


def test_upload_job_accepts_workdays_alone():
    """
    Der Weg, den die Oberflaeche tatsaechlich nutzt.

    Der Statuscode allein genuegt nicht: Der Upload laeuft als Hintergrundjob,
    dessen Fehler still in upload_jobs landen statt die Antwort zu beeinflussen.
    Geprueft wird deshalb das Jobergebnis.
    """
    with tempfile.TemporaryDirectory() as directory:
        _, client, knowledgebase_id = _upload_ready_client(directory)
        response = client.post(
            "/portal/upload-jobs",
            data={
                "knowledgebase_id": knowledgebase_id, "title": "Wissen",
                "valid_workdays": "30", "confidentiality": "internal",
            },
            files={"file": ("wissen.md", b"Original", "text/markdown")},
        )
        assert response.status_code == 202, response.text
        job = client.get(f"/portal/upload-jobs/{response.json()['job_id']}").json()
        assert job["status"] == "completed", job.get("error_code")


def test_upload_job_accepts_a_date_alone():
    from datetime import date

    from document_lifecycle import add_workdays

    with tempfile.TemporaryDirectory() as directory:
        _, client, knowledgebase_id = _upload_ready_client(directory)
        response = client.post(
            "/portal/upload-jobs",
            data={
                "knowledgebase_id": knowledgebase_id, "title": "Wissen",
                "valid_until": add_workdays(date.today(), 30).isoformat(),
                "confidentiality": "internal",
            },
            files={"file": ("wissen.md", b"Original", "text/markdown")},
        )
        assert response.status_code == 202, response.text
        job = client.get(f"/portal/upload-jobs/{response.json()['job_id']}").json()
        assert job["status"] == "completed", job.get("error_code")


def test_background_job_passes_every_form_parameter_explicitly():
    """
    _run_portal_upload_job ruft portal_upload_document als gewoehnliche Funktion
    auf, nicht ueber HTTP. Nicht uebergebene Parameter erhalten dadurch FastAPIs
    Form()-Default, also ein FieldInfo-Objekt statt None. Eine Pruefung wie
    `value is None` schlaegt damit still fehl, und der Fehler landet nur im
    Jobstatus. Jeder Form-Parameter muss deshalb ausdruecklich gesetzt werden.
    """
    import inspect
    import re

    with tempfile.TemporaryDirectory() as directory:
        module = load_app(Path(directory))

    # Form(...) liefert fastapi.params.Form, das von FieldInfo erbt.
    form_parameters = {
        name for name, parameter in
        inspect.signature(module.portal_upload_document).parameters.items()
        if any(base.__name__ == "FieldInfo" for base in type(parameter.default).__mro__)
    }
    assert form_parameters, "expected portal_upload_document to declare Form parameters"

    source = inspect.getsource(module._run_portal_upload_job)
    call = re.search(r"portal_upload_document\((.*?)\n\s*\)\)", source, re.S)
    assert call, "could not locate the portal_upload_document call"
    passed = set(re.findall(r"(\w+)\s*=", call.group(1)))

    missing = sorted(form_parameters - passed)
    assert not missing, (
        "background job must pass these explicitly, otherwise they arrive as "
        f"FieldInfo instead of their value: {missing}"
    )

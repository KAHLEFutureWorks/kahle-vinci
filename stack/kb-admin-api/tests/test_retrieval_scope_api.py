import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from test_portal_api import identity, load_app


def test_internal_scope_is_authenticated_and_derived_from_persisted_read_rights():
    with tempfile.TemporaryDirectory() as directory:
        module = load_app(Path(directory))
        module.MAINTENANCE_API_KEY = "internal-secret"
        current = {"user": identity("portal", "admin")}
        module.app.dependency_overrides[module.require_openwebui_user] = lambda: current["user"]
        client = TestClient(module.app)
        assert client.get("/portal/session").status_code == 200
        current["user"] = identity("employee")
        assert client.get("/portal/session").status_code == 200
        kb = module.PORTAL_GOVERNANCE.request_knowledgebase_change(
            "portal", "create", payload={"slug": "service", "label": "Service", "purpose": "Servicewissen"}
        )
        module.PORTAL_GOVERNANCE.grant_access(
            "portal", "employee", kb.knowledgebase_id, can_read=True, can_upload=True
        )
        case = module.DOCUMENT_LIFECYCLE.submit(
            uploaded_by_user_id="employee", owner_user_id="employee", target_knowledgebase_id=kb.knowledgebase_id,
            title="Aktives Wissen", original_filename="wissen.md", original_file_id="test",
            original_sha256="a" * 64, valid_workdays=60, confidentiality="internal",
        )
        module.DOCUMENT_LIFECYCLE.record_analysis(
            case_id=case.case_id, normalized_sha256="b" * 64, markdown_sha256="c" * 64,
            analysis=module.Analysis(cross_kb_matches=("admin-review",)),
        )
        module.DOCUMENT_LIFECYCLE.choose_action(case_id=case.case_id, actor_user_id="employee", action="create")
        module.DOCUMENT_LIFECYCLE.decide(
            case_id=case.case_id, actor_user_id="portal", decision="approve", reason="Freigabe",
        )
        active = module.DOCUMENT_LIFECYCLE.activate(case_id=case.case_id)

        assert client.post(
            "/portal/internal/retrieval-scope", json={"user_id": "employee"}
        ).status_code == 401
        response = client.post(
            "/portal/internal/retrieval-scope",
            headers={"X-API-Key": "internal-secret"}, json={"user_id": "employee"},
        )
        assert response.status_code == 200
        assert response.json() == {"user_id": "employee", "knowledgebase_ids": [kb.knowledgebase_id],
                                   "active_version_ids": [active.version_id]}


def test_scope_fails_closed_for_unknown_inactive_or_unassigned_user():
    with tempfile.TemporaryDirectory() as directory:
        module = load_app(Path(directory))
        module.MAINTENANCE_API_KEY = "internal-secret"
        current = {"user": identity("portal", "admin")}
        module.app.dependency_overrides[module.require_openwebui_user] = lambda: current["user"]
        client = TestClient(module.app)
        assert client.get("/portal/session").status_code == 200
        headers = {"X-API-Key": "internal-secret"}
        assert client.post(
            "/portal/internal/retrieval-scope", headers=headers, json={"user_id": "missing"}
        ).status_code == 403
        current["user"] = identity("employee")
        assert client.get("/portal/session").status_code == 200
        assert client.post(
            "/portal/internal/retrieval-scope", headers=headers, json={"user_id": "employee"}
        ).status_code == 403

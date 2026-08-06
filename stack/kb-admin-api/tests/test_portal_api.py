from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient


def load_app(root: Path):
    kb_root = root / "knowledgebases"
    for name in ("kahleallgemein", "kahlekontext", "kahlerichtlinien"):
        (kb_root / name).mkdir(parents=True)
    os.environ["KB_ROOT"] = str(kb_root)
    os.environ["KB_STATE_PATH"] = str(root / "state.json")
    os.environ["KB_PORTAL_DB_PATH"] = str(root / "portal.sqlite3")
    os.environ["KB_ADMIN_DEV_AUTH_BYPASS"] = "false"
    app_dir = Path(__file__).resolve().parents[1] / "app"
    sys.path.insert(0, str(app_dir))
    path = app_dir / "main.py"
    spec = importlib.util.spec_from_file_location("kb_portal_api_test", path)
    loaded = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def identity(user_id: str, role: str = "user") -> dict[str, str]:
    return {
        "id": user_id,
        "email": f"{user_id}@kahle.de",
        "name": user_id.title(),
        "role": role,
    }


def test_portal_http_contract_bootstraps_identity_and_enforces_roles():
    with tempfile.TemporaryDirectory() as directory:
        module = load_app(Path(directory))
        current = {"user": identity("portal", "admin")}
        module.app.dependency_overrides[module.require_openwebui_user] = lambda: current["user"]
        client = TestClient(module.app)

        response = client.get("/portal/session")
        assert response.status_code == 200
        assert response.json()["role"] == "portal_admin"

        current["user"] = identity("employee")
        response = client.get("/portal/session")
        assert response.status_code == 200
        assert response.json()["role"] == "employee"
        assert client.get("/portal/admin/users").status_code == 403

        current["user"] = identity("portal", "admin")
        module.DEV_AUTH_BYPASS = True  # local-only test adapter for an already verified step-up
        response = client.patch(
            "/portal/admin/users/employee/role", json={"role": "manager"}
        )
        assert response.status_code == 200
        assert response.json()["user"]["role"] == "manager"

        users = client.get("/portal/admin/users")
        assert users.status_code == 200
        assert {item["user_id"] for item in users.json()["users"]} == {"portal", "employee"}


def test_portal_admin_knowledgebase_mutation_requires_fresh_microsoft_authentication():
    with tempfile.TemporaryDirectory() as directory:
        module = load_app(Path(directory))
        current = {"user": identity("portal", "admin")}
        module.app.dependency_overrides[module.require_openwebui_user] = lambda: current["user"]
        client = TestClient(module.app)
        assert client.get("/portal/session").status_code == 200

        unavailable = client.post(
            "/portal/admin/knowledgebase-changes",
            json={
                "kind": "create",
                "payload": {"slug": "service", "label": "Service"},
            },
        )
        assert unavailable.status_code == 503
        assert unavailable.json()["detail"] == "microsoft_step_up_not_configured"

        class ConfiguredStepUpWithoutProof:
            def verify(self, proof, *, user_id):
                raise module.StepUpError("step_up_proof_invalid")

        module.STEP_UP_AUTHORITY = ConfiguredStepUpWithoutProof()
        blocked = client.post(
            "/portal/admin/knowledgebase-changes",
            json={
                "kind": "create",
                "payload": {"slug": "service", "label": "Service"},
            },
        )
        assert blocked.status_code == 428
        assert blocked.json()["detail"] == "fresh_microsoft_authentication_required"


if __name__ == "__main__":
    test_portal_http_contract_bootstraps_identity_and_enforces_roles()
    test_portal_admin_knowledgebase_mutation_requires_fresh_microsoft_authentication()
    print("portal api tests passed")


def test_openwebui_directory_sync_imports_all_accounts(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        module = load_app(Path(directory))
        module.DEV_AUTH_BYPASS = False

        class Response:
            def raise_for_status(self):
                return None
            def json(self):
                return {"users": [
                    {"id": "employee-2", "email": "employee2@kahle.de", "name": "Zweite Person"},
                    {"id": "employee-3", "email": "employee3@kahle.de", "name": "Dritte Person"},
                ]}

        monkeypatch.setattr(module.requests, "get", lambda *args, **kwargs: Response())
        request = type("Request", (), {"headers": {"Cookie": "session=safe"}})()
        module._sync_openwebui_user_directory(request)
        assert module.PORTAL_GOVERNANCE.identity("employee-2").email == "employee2@kahle.de"
        assert module.PORTAL_GOVERNANCE.identity("employee-3").display_name == "Dritte Person"


def test_non_kahle_identity_is_rejected_even_if_openwebui_knows_it():
    with tempfile.TemporaryDirectory() as directory:
        module = load_app(Path(directory))
        module.app.dependency_overrides[module.require_openwebui_user] = lambda: {
            "id": "external", "email": "external@example.org", "name": "Extern", "role": "user"
        }
        response = TestClient(module.app).get("/portal/session")
        assert response.status_code == 403
        assert response.json()["detail"] == "kahle_microsoft_tenant_required"

def test_migration_metadata_endpoint_uses_initialized_legacy_migration_service():
    with tempfile.TemporaryDirectory() as directory:
        module = load_app(Path(directory))
        current = {"user": identity("portal", "admin")}
        module.app.dependency_overrides[module.require_openwebui_user] = lambda: current["user"]
        client = TestClient(module.app)
        assert client.get("/portal/session").status_code == 200
        captured = {}

        class MigrationSpy:
            def resolve_metadata(self, path, actor_user_id, **metadata):
                captured.update(path=path, actor_user_id=actor_user_id, **metadata)

        module.LEGACY_MIGRATION = MigrationSpy()
        response = client.put("/portal/admin/migration/metadata", json={
            "path": "kahleallgemein/alt.md",
            "owner_email": "portal@kahle.de",
            "confidentiality": "internal",
            "authority_type": "information_or_training",
            "authority_level": 6,
            "scope": {"knowledgebase_ids": ["kahleallgemein"]},
        })
        assert response.status_code == 200
        assert response.json() == {"status": "metadata_resolved"}
        assert captured["actor_user_id"] == "portal"
        assert captured["path"] == "kahleallgemein/alt.md"

from __future__ import annotations

import tempfile
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
                return "# Wissen\n\nGeprÃ¼fter Inhalt.\n"

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



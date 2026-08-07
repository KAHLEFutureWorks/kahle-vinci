from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient


def load_app(root: Path, env: dict[str, str] | None = None):
    kb_root = root / "knowledgebases"
    for name in ("kahleallgemein", "kahlekontext", "kahlerichtlinien"):
        (kb_root / name).mkdir(parents=True)
    os.environ["KB_ROOT"] = str(kb_root)
    os.environ["KB_STATE_PATH"] = str(root / "state.json")
    os.environ["KB_PORTAL_DB_PATH"] = str(root / "portal.sqlite3")
    os.environ["KB_ADMIN_DEV_AUTH_BYPASS"] = "false"
    # Zusaetzliche Variablen gelten nur fuer diesen Import und werden danach
    # zurueckgesetzt, damit sie nicht in andere Tests durchschlagen.
    previous = {name: os.environ.get(name) for name in (env or {})}
    os.environ.update(env or {})
    app_dir = Path(__file__).resolve().parents[1] / "app"
    sys.path.insert(0, str(app_dir))
    path = app_dir / "main.py"
    spec = importlib.util.spec_from_file_location("kb_portal_api_test", path)
    loaded = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = loaded
    try:
        spec.loader.exec_module(loaded)
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
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


def _step_up_env(**overrides):
    """Vollstaendige Step-up-Umgebung, einzelne Werte gezielt ueberschreibbar."""
    env = {
        "KB_PORTAL_STEP_UP_SECRET": "s" * 43,
        "KB_PORTAL_ENTRA_TENANT_ID": "",
        "KB_PORTAL_ENTRA_CLIENT_ID": "",
        "KB_PORTAL_ENTRA_CLIENT_SECRET": "",
        "KB_PORTAL_ENTRA_REDIRECT_URI": "",
        "KB_PORTAL_LOCAL_STEP_UP": "false",
    }
    env.update(overrides)
    return env


def test_local_step_up_never_replaces_a_configured_microsoft_login():
    """
    Der lokale Ersatz ist ausschliesslich fuer die Abnahme gedacht. Sobald auch
    nur eine Entra-Angabe existiert, ist die Umgebung nicht mehr rein lokal und
    Microsoft muss gewinnen, selbst wenn das lokale Flag gesetzt wurde.
    """
    entra_fields = (
        "KB_PORTAL_ENTRA_TENANT_ID", "KB_PORTAL_ENTRA_CLIENT_ID",
        "KB_PORTAL_ENTRA_CLIENT_SECRET", "KB_PORTAL_ENTRA_REDIRECT_URI",
    )
    for field in entra_fields:
        with tempfile.TemporaryDirectory() as directory:
            module = load_app(
                Path(directory),
                env=_step_up_env(**{"KB_PORTAL_LOCAL_STEP_UP": "true", field: "gesetzt"}),
            )
            adapter = getattr(module.STEP_UP_AUTHORITY, "oidc", None)
            assert not isinstance(adapter, module.LocalStepUpAdapter), (
                f"local step-up must not activate when {field} is set"
            )


def test_local_step_up_requires_the_explicit_flag_and_a_secret():
    for env in (
        _step_up_env(),                                      # Flag fehlt
        _step_up_env(KB_PORTAL_LOCAL_STEP_UP="true",
                     KB_PORTAL_STEP_UP_SECRET=""),           # Secret fehlt
    ):
        with tempfile.TemporaryDirectory() as directory:
            module = load_app(Path(directory), env=env)
            assert module.STEP_UP_AUTHORITY is None


def test_local_step_up_activates_only_in_a_purely_local_environment():
    with tempfile.TemporaryDirectory() as directory:
        module = load_app(
            Path(directory), env=_step_up_env(KB_PORTAL_LOCAL_STEP_UP="true"),
        )
        assert isinstance(module.STEP_UP_AUTHORITY.oidc, module.LocalStepUpAdapter)


def test_knowledgebase_overview_is_admin_only_and_ignores_read_rights():
    """
    Die Verwaltungssicht muss auch Bereiche zeigen, in die der Admin selbst
    nicht hineinlesen darf; /portal/documents filtert dafuer zu streng. Sie
    liefert deshalb ausschliesslich Metadaten.
    """
    with tempfile.TemporaryDirectory() as directory:
        module = load_app(Path(directory))
        current = {"user": identity("portal", "admin")}
        module.app.dependency_overrides[module.require_openwebui_user] = lambda: current["user"]
        client = TestClient(module.app)
        assert client.get("/portal/session").status_code == 200

        base = module.PORTAL_GOVERNANCE.request_knowledgebase_change(
            "portal", "create", payload={"slug": "service", "label": "Service"},
        )
        module.PORTAL_GOVERNANCE.sync_identity(
            user_id="employee", email="employee@kahle.de", display_name="Mitarbeiter",
        )

        payload = client.get("/portal/admin/knowledgebase-overview").json()
        entry = next(
            item for item in payload["knowledgebases"]
            if item["knowledgebase_id"] == base.knowledgebase_id
        )
        assert entry["label"] == "Service"
        assert entry["document_count"] == 0
        # Kein Feld darf Dokumentinhalte transportieren.
        assert not any("content" in key or "markdown" in key for key in entry)

        current["user"] = identity("employee")
        assert client.get("/portal/session").status_code == 200
        forbidden = client.get("/portal/admin/knowledgebase-overview")
        assert forbidden.status_code == 403
        assert forbidden.json()["detail"] == "admin_required"


def test_feedback_screenshot_is_checked_and_only_admins_may_fetch_it():
    """
    Der Anhang durchlaeuft dieselbe Kette wie ein Dokument. Abrufen darf ihn
    nur ein Admin: Ein Screenshot zeigt genau die Antwort, die der Meldende
    fuer falsch haelt, und damit potenziell fremde Inhalte.
    """
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        module = load_app(root)
        module.PORTAL_FILES_ROOT = (root / "portal-files").resolve()
        current = {"user": identity("portal", "admin")}
        module.app.dependency_overrides[module.require_openwebui_user] = lambda: current["user"]
        client = TestClient(module.app)
        assert client.get("/portal/session").status_code == 200

        module.PORTAL_GOVERNANCE.sync_identity(
            user_id="employee", email="employee@kahle.de", display_name="Mitarbeiter",
        )
        module.SECURE_INGEST.scanner = type("Scanner", (), {"scan": lambda self, n, d: None})()

        current["user"] = identity("employee")
        assert client.get("/portal/session").status_code == 200
        feedback_id = client.post("/portal/feedback/rag", json={
            "reason": "incorrect", "comment": "Stimmt nicht.",
            "question": "Wie lange gilt das?", "answer": "Unbegrenzt.",
            "request_id": "req-1",
        }).json()["feedback_id"]

        png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
        assert client.post(
            f"/portal/feedback/{feedback_id}/screenshot",
            files={"file": ("beweis.png", png, "image/png")},
        ).status_code == 201

        # Ein als PNG benanntes Skript wird am Inhalt erkannt.
        rejected = client.post(
            f"/portal/feedback/{feedback_id}/screenshot",
            files={"file": ("angriff.png", b"<script>alert(1)</script>", "image/png")},
        )
        assert rejected.status_code == 422
        assert rejected.json()["detail"] == "screenshot_type_not_allowed"

        # Mitarbeitende duerfen den Anhang nicht wieder abrufen.
        assert client.get(f"/portal/admin/feedback/{feedback_id}/screenshot").status_code == 403

        current["user"] = identity("portal", "admin")
        served = client.get(f"/portal/admin/feedback/{feedback_id}/screenshot")
        assert served.status_code == 200
        assert served.content == png


def test_overview_hides_deleted_knowledgebases_but_keeps_archived_ones():
    """
    Ein endgueltig entfernter Wissensbereich darf nicht weiter in der
    Verwaltung stehen. Archivierte bleiben sichtbar: Nur ueber sie fuehrt der
    Weg zum endgueltigen Entfernen.
    """
    with tempfile.TemporaryDirectory() as directory:
        module = load_app(Path(directory))
        current = {"user": identity("portal", "admin")}
        module.app.dependency_overrides[module.require_openwebui_user] = lambda: current["user"]
        client = TestClient(module.app)
        assert client.get("/portal/session").status_code == 200

        labels = {}
        for slug, label in (("aktiv", "Aktiv"), ("archiv", "Archiviert"), ("weg", "Geloescht")):
            created = module.PORTAL_GOVERNANCE.request_knowledgebase_change(
                "portal", "create", payload={"slug": slug, "label": label},
            )
            labels[label] = created.knowledgebase_id
        module.PORTAL_GOVERNANCE.request_knowledgebase_change(
            "portal", "archive", knowledgebase_id=labels["Archiviert"],
        )
        module.PORTAL_GOVERNANCE.request_knowledgebase_change(
            "portal", "archive", knowledgebase_id=labels["Geloescht"],
        )
        module.PORTAL_GOVERNANCE.request_knowledgebase_change(
            "portal", "delete", knowledgebase_id=labels["Geloescht"],
        )

        shown = {
            item["label"]: item["status"]
            for item in client.get("/portal/admin/knowledgebase-overview").json()["knowledgebases"]
        }
        assert shown.get("Aktiv") == "active"
        assert shown.get("Archiviert") == "archived"
        assert "Geloescht" not in shown


def test_admins_can_reassign_a_document_to_another_knowledgebase():
    """
    PRD 9.3: Ein Dokument kann in mehreren Wissensbereichen veroeffentlicht
    sein, ohne dupliziert zu werden. Bisher entstand eine Zuordnung nur aus
    einem Uploadfall; ein Dokument ohne Bereich liess sich nicht mehr zuordnen.
    """
    with tempfile.TemporaryDirectory() as directory:
        module = load_app(Path(directory))
        module._trigger_hybrid_reindex = lambda: {"ok": True}
        current = {"user": identity("portal", "admin")}
        module.app.dependency_overrides[module.require_openwebui_user] = lambda: current["user"]
        client = TestClient(module.app)
        assert client.get("/portal/session").status_code == 200

        first = module.PORTAL_GOVERNANCE.request_knowledgebase_change(
            "portal", "create", payload={"slug": "eins", "label": "Eins"})
        second = module.PORTAL_GOVERNANCE.request_knowledgebase_change(
            "portal", "create", payload={"slug": "zwei", "label": "Zwei"})
        case = module.DOCUMENT_LIFECYCLE.submit(
            uploaded_by_user_id="portal", owner_user_id="portal",
            target_knowledgebase_id=first.knowledgebase_id, title="Wanderndes Dokument",
            original_filename="w.md", original_file_id="w", original_sha256="e" * 64,
            valid_workdays=30, confidentiality="internal",
        )
        # Nur aktive Dokumente duerfen veroeffentlicht werden.
        blocked = client.put(f"/portal/admin/documents/{case.document_id}/publications",
                             json={"knowledgebase_id": second.knowledgebase_id, "reason": "Passt besser"})
        assert blocked.status_code == 409
        assert blocked.json()["detail"] == "only_active_documents_can_be_published"

        with module.PORTAL_GOVERNANCE.store.connect() as db:
            db.execute("UPDATE document_versions SET status='active' WHERE version_id=?", (case.version_id,))
            db.execute("UPDATE canonical_documents SET active_version_id=? WHERE document_id=?",
                       (case.version_id, case.document_id))

        added = client.put(f"/portal/admin/documents/{case.document_id}/publications",
                           json={"knowledgebase_id": second.knowledgebase_id, "reason": "Passt besser"})
        assert added.status_code == 200, added.text
        active = {p["knowledgebase_id"] for p in added.json()["publications"] if p["status"] == "active"}
        assert second.knowledgebase_id in active

        removed = client.put(f"/portal/admin/documents/{case.document_id}/publications",
                             json={"knowledgebase_id": second.knowledgebase_id, "active": False,
                                   "reason": "Doch nicht passend"})
        assert removed.status_code == 200
        still_active = {p["knowledgebase_id"] for p in removed.json()["publications"] if p["status"] == "active"}
        assert second.knowledgebase_id not in still_active

        current["user"] = identity("employee")
        assert client.get("/portal/session").status_code == 200
        assert client.put(f"/portal/admin/documents/{case.document_id}/publications",
                          json={"knowledgebase_id": first.knowledgebase_id, "reason": "Nicht erlaubt"}).status_code == 403

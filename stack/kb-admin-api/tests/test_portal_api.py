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
    os.environ["KB_PORTAL_FILES_ROOT"] = str(root / "portal-files")
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


def test_load_app_keeps_upload_spool_inside_the_test_storage_root(tmp_path):
    module = load_app(tmp_path)

    assert module.UPLOAD_SPOOL.root == (tmp_path / "portal-files" / ".upload-spool").resolve()


def test_retrieval_metadata_review_is_admin_only_and_contains_no_document_text(tmp_path):
    module = load_app(tmp_path)
    current = {"user": identity("portal", "admin")}
    module.app.dependency_overrides[module.require_openwebui_user] = lambda: current["user"]
    client = TestClient(module.app)
    assert client.get("/portal/session").status_code == 200
    module.RETRIEVAL_METADATA.classify_version(
        document_id="doc-1",
        version_id="v-1",
        title="Hinweise",
        markdown="Geheimer Dokumentinhalt, der nicht in der Aufgabenliste erscheinen darf.",
    )

    response = client.get("/portal/admin/retrieval-metadata/review")

    assert response.status_code == 200
    body = response.json()
    assert [item["version_id"] for item in body["items"]] == ["v-1"]
    assert "Geheimer Dokumentinhalt" not in response.text

    current["user"] = identity("employee")
    assert client.get("/portal/admin/retrieval-metadata/review").status_code == 403


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
        response = client.patch(
            "/portal/admin/users/employee/role",
            json={"role": "manager", "confirmed": True},
        )
        assert response.status_code == 200
        assert response.json()["user"]["role"] == "manager"

        module.DEV_AUTH_BYPASS = True
        users = client.get("/portal/admin/users")
        assert users.status_code == 200
        assert {item["user_id"] for item in users.json()["users"]} == {"portal", "employee"}


def test_every_role_change_requires_explicit_confirmation():
    with tempfile.TemporaryDirectory() as directory:
        module = load_app(Path(directory))
        current = {"user": identity("portal", "admin")}
        module.app.dependency_overrides[module.require_openwebui_user] = lambda: current["user"]
        client = TestClient(module.app)
        assert client.get("/portal/session").status_code == 200

        module.PORTAL_GOVERNANCE.sync_identity(
            user_id="target-admin",
            email="target-admin@kahle.de",
            display_name="Target Admin",
        )
        module.PORTAL_GOVERNANCE.sync_identity(
            user_id="employee",
            email="employee@kahle.de",
            display_name="Employee",
        )
        module.PORTAL_GOVERNANCE.set_role("portal", "target-admin", "admin")

        blocked = client.patch(
            "/portal/admin/users/target-admin/role", json={"role": "manager"}
        )
        assert blocked.status_code == 409
        assert blocked.json()["detail"] == "confirmation_required"

        ordinary = client.patch(
            "/portal/admin/users/employee/role",
            json={"role": "manager", "confirmed": True},
        )
        assert ordinary.status_code == 200
        assert ordinary.json()["user"]["role"] == "manager"


def test_portal_admin_knowledgebase_mutation_requires_explicit_confirmation():
    with tempfile.TemporaryDirectory() as directory:
        module = load_app(Path(directory))
        current = {"user": identity("portal", "admin")}
        module.app.dependency_overrides[module.require_openwebui_user] = lambda: current["user"]
        client = TestClient(module.app)
        assert client.get("/portal/session").status_code == 200

        blocked = client.post(
            "/portal/admin/knowledgebase-changes",
            json={
                "kind": "create",
                "payload": {"slug": "service", "label": "Service"},
            },
        )
        assert blocked.status_code == 409
        assert blocked.json()["detail"] == "confirmation_required"

        confirmed = client.post(
            "/portal/admin/knowledgebase-changes",
            json={
                "kind": "create",
                "payload": {"slug": "service", "label": "Service"},
                "confirmed": True,
            },
        )
        assert confirmed.status_code == 201
        assert confirmed.json()["change"]["status"] == "approved"


if __name__ == "__main__":
    test_portal_http_contract_bootstraps_identity_and_enforces_roles()
    test_portal_admin_knowledgebase_mutation_requires_explicit_confirmation()
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
            "knowledgebase_id": "kahleallgemein",
            "scope": {"knowledgebase_ids": ["kahleallgemein"]},
        })
        assert response.status_code == 200
        assert response.json() == {"status": "metadata_resolved"}
        assert captured["actor_user_id"] == "portal"
        assert captured["path"] == "kahleallgemein/alt.md"
        assert captured["knowledgebase_id"] == "kahleallgemein"


def test_migration_review_endpoint_serves_only_service_resolved_file():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        module = load_app(root)
        module.app.dependency_overrides[module.require_openwebui_user] = lambda: identity("portal", "admin")
        review = root / "review.md"
        review.write_text("# Geprüfte Fassung", encoding="utf-8")
        captured = {}

        class MigrationSpy:
            def review_file(self, knowledge_root, path, kind):
                captured.update(root=knowledge_root, path=path, kind=kind)
                return review

        module.LEGACY_MIGRATION = MigrationSpy()
        response = TestClient(module.app).get(
            "/portal/admin/migration/file",
            params={"path": "service/ablauf.md", "kind": "markdown"},
        )

        assert response.status_code == 200
        assert response.text == "# Geprüfte Fassung"
        assert response.headers["content-disposition"].startswith("inline;")
        assert captured["path"] == "service/ablauf.md"
        assert captured["kind"] == "markdown"


def test_migration_disposition_endpoints_exclude_and_restore_with_reason():
    with tempfile.TemporaryDirectory() as directory:
        module = load_app(Path(directory))
        module.app.dependency_overrides[module.require_openwebui_user] = lambda: identity("portal", "admin")
        calls = []

        class MigrationSpy:
            def exclude(self, path, actor_user_id, reason):
                calls.append(("exclude", path, actor_user_id, reason))

            def restore_excluded(self, path, actor_user_id, reason):
                calls.append(("restore", path, actor_user_id, reason))

        module.LEGACY_MIGRATION = MigrationSpy()
        client = TestClient(module.app)
        payload = {"path": "service/alt.md", "reason": "Derzeit nicht benötigt"}
        assert client.post("/portal/admin/migration/exclude", json=payload).json() == {"status": "excluded"}
        assert client.post("/portal/admin/migration/restore", json=payload).json() == {"status": "restored"}
        assert calls == [
            ("exclude", "service/alt.md", "portal", "Derzeit nicht benötigt"),
            ("restore", "service/alt.md", "portal", "Derzeit nicht benötigt"),
        ]


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


def test_document_list_returns_one_primary_group_and_additional_publications():
    with tempfile.TemporaryDirectory() as directory:
        module = load_app(Path(directory))
        current = {"user": identity("portal", "admin")}
        module.app.dependency_overrides[module.require_openwebui_user] = lambda: current["user"]
        client = TestClient(module.app)
        assert client.get("/portal/session").status_code == 200
        module.PORTAL_GOVERNANCE.sync_identity(
            user_id="employee", email="employee@kahle.de", display_name="Mitarbeiter",
        )
        primary = module.PORTAL_GOVERNANCE.request_knowledgebase_change(
            "portal", "create", payload={"slug":"service","label":"Service"},
        )
        additional = module.PORTAL_GOVERNANCE.request_knowledgebase_change(
            "portal", "create", payload={"slug":"verkauf","label":"Verkauf"},
        )
        for base in (primary, additional):
            module.PORTAL_GOVERNANCE.grant_access(
                "portal", "employee", base.knowledgebase_id, can_read=True, can_upload=True,
            )
        case = module.DOCUMENT_LIFECYCLE.submit(
            uploaded_by_user_id="employee", owner_user_id="employee",
            target_knowledgebase_id=primary.knowledgebase_id, title="Bereichsübergreifende Anleitung",
            original_filename="anleitung.md", original_file_id="file-1",
            original_sha256="a"*64, valid_workdays=60, confidentiality="internal",
        )
        module.DOCUMENT_LIFECYCLE.auto_activation_enabled = lambda: True
        case = module.DOCUMENT_LIFECYCLE.record_analysis(
            case_id=case.case_id, normalized_sha256="b"*64, markdown_sha256="c"*64,
            analysis=module.Analysis(),
        )
        module.DOCUMENT_LIFECYCLE.activate(case_id=case.case_id)
        linked = client.put(
            f"/portal/admin/documents/{case.document_id}/publications",
            json={"knowledgebase_id":additional.knowledgebase_id,"active":True,
                  "reason":"Auch für Verkauf relevant"},
        )
        assert linked.status_code == 200, linked.text

        current["user"] = identity("employee")
        payload = client.get("/portal/documents").json()["documents"]
        assert len(payload) == 1
        assert payload[0]["original_url"] == f"/wissen/api/portal/sources/{case.version_id}"
        assert payload[0]["primary_knowledgebase"] == {
            "knowledgebase_id": primary.knowledgebase_id, "label": "Service",
        }
        assert payload[0]["additional_knowledgebases"] == [
            {"knowledgebase_id": additional.knowledgebase_id, "label": "Verkauf"},
        ]


def test_admin_can_manage_restricted_document_terms_over_http():
    with tempfile.TemporaryDirectory() as directory:
        module = load_app(Path(directory))
        current = {"user": identity("portal", "admin")}
        module.app.dependency_overrides[module.require_openwebui_user] = lambda: current["user"]
        client = TestClient(module.app)
        assert client.get("/portal/session").status_code == 200

        initial = client.get("/portal/admin/restricted-terms")
        assert initial.status_code == 200
        assert {item["term"] for item in initial.json()["terms"]} == {"TPI", "Reparaturleitfaden"}
        created = client.post("/portal/admin/restricted-terms", json={"term":"Interne Geheimliste"})
        assert created.status_code == 201
        rule_id = created.json()["term"]["rule_id"]
        assert client.delete(f"/portal/admin/restricted-terms/{rule_id}").json() == {"removed": True}

        current["user"] = identity("employee")
        assert client.get("/portal/session").status_code == 200
        assert client.get("/portal/admin/restricted-terms").status_code == 403


def test_portal_admin_controls_automatic_activation_switch_over_http():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); module = load_app(root)
        current = {"user": identity("portal", "admin")}
        module.app.dependency_overrides[module.require_openwebui_user] = lambda: current["user"]
        client = TestClient(module.app); assert client.get("/portal/session").status_code == 200
        initial = client.get("/portal/admin/settings/auto-activation")
        assert initial.status_code == 200
        assert initial.json() == {"enabled": False}
        changed = client.put(
            "/portal/admin/settings/auto-activation", json={"enabled": True, "reason":"Lokale Abnahme"},
        )
        assert changed.status_code == 200
        assert changed.json() == {"enabled": True}
        current["user"] = identity("admin", "admin")
        assert client.put(
            "/portal/admin/settings/auto-activation", json={"enabled": False, "reason":"Nicht erlaubt"},
        ).status_code == 403


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


def test_deleted_knowledgebase_notifies_all_users_who_had_read_access():
    with tempfile.TemporaryDirectory() as directory:
        module = load_app(Path(directory))
        module.DEV_AUTH_BYPASS = True
        current = {"user": identity("portal", "admin")}
        module.app.dependency_overrides[module.require_openwebui_user] = lambda: current["user"]
        client = TestClient(module.app)
        assert client.get("/portal/session").status_code == 200
        module.PORTAL_GOVERNANCE.sync_identity(
            user_id="reader", email="reader@kahle.de", display_name="Leserin",
        )
        kb = module.PORTAL_GOVERNANCE.request_knowledgebase_change(
            "portal", "create", payload={"slug": "alt", "label": "Altes Wissen"},
        )
        module.PORTAL_GOVERNANCE.grant_access(
            "portal", "reader", kb.knowledgebase_id, can_read=True, can_upload=False,
        )
        module.PORTAL_GOVERNANCE.request_knowledgebase_change(
            "portal", "archive", knowledgebase_id=kb.knowledgebase_id,
        )

        deleted = client.post("/portal/admin/knowledgebase-changes", json={
            "kind": "delete", "knowledgebase_id": kb.knowledgebase_id,
            "payload": {"reason": "Altbestand wird entfernt"},
            "confirmed": True,
        })
        assert deleted.status_code == 201, deleted.text

        current["user"] = identity("reader")
        assert client.get("/portal/session").status_code == 200
        notifications = client.get("/portal/notifications").json()["notifications"]
        assert notifications[0]["document_title"] == "Altes Wissen"
        assert notifications[0]["status"] == "knowledgebase_delete"
        assert "nicht mehr abrufbar" in notifications[0]["message"]


def test_reviewer_can_ask_involved_people_and_question_is_sent_in_app_and_by_mail():
    with tempfile.TemporaryDirectory() as directory:
        module = load_app(Path(directory))
        current = {"user": identity("portal", "admin")}
        module.app.dependency_overrides[module.require_openwebui_user] = lambda: current["user"]
        client = TestClient(module.app)
        assert client.get("/portal/session").status_code == 200

        module.PORTAL_GOVERNANCE.sync_identity(
            user_id="manager", email="manager@kahle.de", display_name="Frau Führung",
        )
        module.PORTAL_GOVERNANCE.set_role("portal", "manager", "manager")
        module.PORTAL_GOVERNANCE.sync_identity(
            user_id="employee", email="employee@kahle.de", display_name="Herr Upload",
        )
        module.PORTAL_GOVERNANCE.assign_manager("portal", "employee", "manager")
        kb = module.PORTAL_GOVERNANCE.request_knowledgebase_change(
            "portal", "create", payload={"slug": "service", "label": "Service"},
        )
        alternate_kb = module.PORTAL_GOVERNANCE.request_knowledgebase_change(
            "portal", "create", payload={"slug": "werkstatt", "label": "Werkstatt"},
        )
        module.PORTAL_GOVERNANCE.grant_access(
            "portal", "employee", kb.knowledgebase_id, can_read=True, can_upload=True,
        )
        case = module.DOCUMENT_LIFECYCLE.submit(
            uploaded_by_user_id="employee", owner_user_id="employee",
            target_knowledgebase_id=kb.knowledgebase_id, title="Arbeitsanweisung",
            original_filename="anweisung.pdf", original_file_id="file",
            original_sha256="f" * 64, valid_workdays=30, confidentiality="internal",
        )
        case = module.DOCUMENT_LIFECYCLE.record_analysis(
            case_id=case.case_id, normalized_sha256="e" * 64,
            markdown_sha256="d" * 64, analysis=module.Analysis(),
        )
        current["user"] = {
            **identity("manager"), "name": "Frau Führung",
        }
        tasks = client.get("/portal/tasks").json()["tasks"]
        assert tasks[0]["contact_name"] == "Herr Upload"
        assert tasks[0]["target_knowledgebase_label"] == "Service"
        changed = client.patch(
            f"/portal/cases/{case.case_id}/target-knowledgebase",
            json={"knowledgebase_id": alternate_kb.knowledgebase_id},
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["case"]["target_knowledgebase_id"] == alternate_kb.knowledgebase_id
        tasks_after_change = client.get("/portal/tasks").json()["tasks"]
        assert tasks_after_change[0]["target_knowledgebase_label"] == "Werkstatt"
        history = tasks_after_change[0]["target_knowledgebase_history"]
        assert [(item["knowledgebase_label"], item["selected_by_name"]) for item in history] == [
            ("Service", "Herr Upload"),
            ("Werkstatt", "Frau Führung"),
        ]
        with module.PORTAL_GOVERNANCE.store.connect() as db:
            event = db.execute(
                "SELECT event_type FROM document_events WHERE case_id=? ORDER BY sequence DESC",
                (case.case_id,),
            ).fetchone()
        assert event["event_type"] == "target_knowledgebases_changed"
        participants = client.get(
            f"/portal/cases/{case.case_id}/inquiry-participants"
        ).json()["participants"]
        assert [item["user_id"] for item in participants] == ["employee"]

        sent = client.post(f"/portal/cases/{case.case_id}/inquiries", json={
            "recipient_user_id": "employee",
            "question": "Welche Filiale betrifft diese Arbeitsanweisung?",
        })
        assert sent.status_code == 201, sent.text

        with module.PORTAL_GOVERNANCE.store.connect() as db:
            db.execute(
                "UPDATE document_cases SET requires_admin=1 WHERE case_id=?", (case.case_id,)
            )
        module.DOCUMENT_LIFECYCLE.decide(
            case_id=case.case_id, actor_user_id="manager", decision="approve", reason="",
        )
        current["user"] = identity("portal", "admin")
        admin_participants = client.get(
            f"/portal/cases/{case.case_id}/inquiry-participants"
        ).json()["participants"]
        assert {item["user_id"] for item in admin_participants} == {"employee", "manager"}
        admin_task = client.get("/portal/tasks").json()["tasks"][0]
        assert [item["knowledgebase_label"] for item in admin_task["target_knowledgebase_history"]] == [
            "Service", "Werkstatt",
        ]

        current["user"] = identity("employee")
        notification = client.get("/portal/notifications").json()["notifications"][0]
        assert notification["status"] == "clarification_requested"
        assert "Frau Führung" in notification["message"]
        assert notification["reason"] == "Welche Filiale betrifft diese Arbeitsanweisung?"
        assert notification["can_reply"] is True
        assert notification["sender_user_id"] == "manager"

        answered = client.post(
            f"/portal/notifications/{notification['notification_id']}/reply",
            json={"message": "Die Arbeitsanweisung betrifft die Filiale Hannover."},
        )
        assert answered.status_code == 201, answered.text

        current["user"] = {**identity("manager"), "name": "Frau Führung"}
        reply = client.get("/portal/notifications").json()["notifications"][0]
        assert reply["status"] == "clarification_reply"
        assert reply["sender_user_id"] == "employee"
        assert reply["reason"] == "Die Arbeitsanweisung betrifft die Filiale Hannover."
        assert reply["can_reply"] is True

        replied_again = client.post(
            f"/portal/notifications/{reply['notification_id']}/reply",
            json={"message": "Danke, damit kann ich die Prüfung abschließen."},
        )
        assert replied_again.status_code == 201, replied_again.text

        current["user"] = identity("employee")
        follow_up = client.get("/portal/notifications").json()["notifications"][0]
        assert follow_up["status"] == "clarification_reply"
        assert follow_up["sender_user_id"] == "manager"
        assert follow_up["reason"] == "Danke, damit kann ich die Prüfung abschließen."
        thread = client.get(
            f"/portal/notifications/{follow_up['notification_id']}/thread"
        )
        assert thread.status_code == 200, thread.text
        assert [item["sender_name"] for item in thread.json()["messages"]] == [
            "Frau Führung", "Employee", "Frau Führung",
        ]
        assert [item["message"] for item in thread.json()["messages"]] == [
            "Welche Filiale betrifft diese Arbeitsanweisung?",
            "Die Arbeitsanweisung betrifft die Filiale Hannover.",
            "Danke, damit kann ich die Prüfung abschließen.",
        ]
        with module.PORTAL_GOVERNANCE.store.connect() as db:
            db.execute(
                "INSERT INTO portal_notifications "
                "(notification_id,recipient_user_id,subject_type,subject_id,subject_title,"
                "status,message,reason,created_at,read_at) VALUES (?,?,?,?,?,?,?,?,?,NULL)",
                (
                    "employee-general", "employee", "knowledgebase", "kb-service",
                    "Servicewissen", "active", "Neues Wissen ist verfügbar.", "",
                    "2026-08-24T12:00:00+02:00",
                ),
            )

        marked = client.post("/portal/notifications/read-all")
        assert marked.status_code == 200, marked.text
        assert marked.json()["marked_read"] >= 2
        assert all(
            item["read_at"] for item in client.get("/portal/notifications").json()["notifications"]
        )

        current["user"] = {**identity("manager"), "name": "Frau Führung"}
        assert any(
            item["read_at"] is None
            for item in client.get("/portal/notifications").json()["notifications"]
        )
        with module.PORTAL_GOVERNANCE.store.connect() as db:
            mail = db.execute(
                "SELECT recipient,subject,body FROM notification_outbox WHERE kind='case_inquiry'"
            ).fetchone()
        assert mail["recipient"] == "employee@kahle.de"
        assert "Rückfrage zu Arbeitsanweisung" in mail["subject"]
        assert "Welche Filiale" in mail["body"]


def test_admins_can_reassign_a_document_to_another_knowledgebase():
    """
    PRD 9.3: Ein Dokument kann in mehreren Wissensbereichen veroeffentlicht
    sein, ohne dupliziert zu werden. Bisher entstand eine Zuordnung nur aus
    einem Uploadfall; ein Dokument ohne Bereich liess sich nicht mehr zuordnen.
    """
    with tempfile.TemporaryDirectory() as directory:
        module = load_app(Path(directory))
        module._trigger_hybrid_reindex = lambda: {"ok": True}
        module._trigger_hybrid_document_sync = lambda _document_id: {"ok": True}
        module._trigger_hybrid_version_sync = lambda _version_id: {"ok": True}
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

        overview = client.get("/portal/admin/knowledgebase-overview").json()["knowledgebases"]
        second_overview = next(
            item for item in overview if item["knowledgebase_id"] == second.knowledgebase_id
        )
        assert not any(
            item["document_id"] == case.document_id for item in second_overview["documents"]
        ), "inaktive Veröffentlichungen dürfen nicht mehr in der Knowledgebase erscheinen"

        current["user"] = identity("employee")
        assert client.get("/portal/session").status_code == 200
        assert client.put(f"/portal/admin/documents/{case.document_id}/publications",
                          json={"knowledgebase_id": first.knowledgebase_id, "reason": "Nicht erlaubt"}).status_code == 403


def test_admin_archive_lists_and_restores_a_retained_document_version():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        module = load_app(root)
        module._trigger_hybrid_version_sync = lambda _version_id: {"ok": True}
        current = {"user": identity("portal", "admin")}
        module.app.dependency_overrides[module.require_openwebui_user] = lambda: current["user"]
        client = TestClient(module.app)
        assert client.get("/portal/session").status_code == 200
        kb = module.PORTAL_GOVERNANCE.request_knowledgebase_change(
            "portal", "create", payload={"slug": "service", "label": "Service"},
        )
        first = module.DOCUMENT_LIFECYCLE.submit(
            uploaded_by_user_id="portal", owner_user_id="portal", target_knowledgebase_id=kb.knowledgebase_id,
            title="Arbeitsanweisung", original_filename="anweisung.md", original_file_id="first",
            original_sha256="a" * 64, valid_workdays=30, confidentiality="internal",
        )
        module.DOCUMENT_LIFECYCLE.record_analysis(
            case_id=first.case_id, normalized_sha256="b" * 64, markdown_sha256="c" * 64,
            analysis=module.Analysis(),
        )
        module.DOCUMENT_LIFECYCLE.decide(
            case_id=first.case_id, actor_user_id="portal", decision="approve", reason="Erstfassung",
        )
        first = module.DOCUMENT_LIFECYCLE.activate(case_id=first.case_id)
        second = module.DOCUMENT_LIFECYCLE.submit(
            uploaded_by_user_id="portal", owner_user_id="portal", target_knowledgebase_id=kb.knowledgebase_id,
            document_id=first.document_id, title="Arbeitsanweisung", original_filename="anweisung-neu.md",
            original_file_id="second", original_sha256="d" * 64, valid_workdays=30, confidentiality="internal",
        )
        module.DOCUMENT_LIFECYCLE.record_analysis(
            case_id=second.case_id, normalized_sha256="e" * 64, markdown_sha256="f" * 64,
            analysis=module.Analysis(same_kb_similarity="very_high"),
        )
        module.DOCUMENT_LIFECYCLE.choose_action(
            case_id=second.case_id, actor_user_id="portal", action="replace",
        )
        module.DOCUMENT_LIFECYCLE.decide(
            case_id=second.case_id, actor_user_id="portal", decision="approve", reason="Neue Fassung",
        )
        second = module.DOCUMENT_LIFECYCLE.activate(case_id=second.case_id)
        third = module.DOCUMENT_LIFECYCLE.submit(
            uploaded_by_user_id="portal", owner_user_id="portal", target_knowledgebase_id=kb.knowledgebase_id,
            document_id=first.document_id, title="Arbeitsanweisung aktuell", original_filename="anweisung-aktuell.md",
            original_file_id="third", original_sha256="1" * 64, valid_workdays=30, confidentiality="internal",
        )
        module.DOCUMENT_LIFECYCLE.record_analysis(
            case_id=third.case_id, normalized_sha256="2" * 64, markdown_sha256="3" * 64,
            analysis=module.Analysis(same_kb_similarity="very_high"),
        )
        module.DOCUMENT_LIFECYCLE.choose_action(
            case_id=third.case_id, actor_user_id="portal", action="replace",
        )
        module.DOCUMENT_LIFECYCLE.decide(
            case_id=third.case_id, actor_user_id="portal", decision="approve", reason="Aktuelle Fassung",
        )
        third = module.DOCUMENT_LIFECYCLE.activate(case_id=third.case_id)
        for version, content in (
            (first, "# Frühere Fassung\n"), (second, "# Zweite Fassung\n"), (third, "# Aktuelle Fassung\n"),
        ):
            version_dir = root / "portal-files" / version.document_id / version.version_id
            version_dir.mkdir(parents=True)
            (version_dir / "original.md").write_text(content, encoding="utf-8")
            (version_dir / "rag.md").write_text(content, encoding="utf-8")

        current["user"] = identity("employee")
        assert client.get("/portal/session").status_code == 200
        assert client.get("/portal/admin/archive").status_code == 403

        current["user"] = identity("portal", "admin")
        archive = client.get("/portal/admin/archive")
        assert archive.status_code == 200
        archived_versions = archive.json()["versions"]
        same_document_history = [item for item in archived_versions if item["document_id"] == first.document_id]
        assert len(same_document_history) == 2
        entry = next(item for item in archived_versions if item["version_id"] == first.version_id)
        assert entry["has_original"] is True
        assert entry["can_restore"] is True
        assert entry["active_version_title"] == third.title
        assert entry["version_count"] == 3
        # Die abloesende Fassung ist die direkte Nachfolgerin, nicht die heute
        # gueltige. Sonst laesst sich eine Kette aus drei Fassungen nicht lesen.
        assert entry["superseded_by_original_filename"] == second.original_filename
        replaced_second = next(
            item for item in archived_versions if item["version_id"] == second.version_id
        )
        assert replaced_second["superseded_by_original_filename"] == third.original_filename
        assert replaced_second["active_version_title"] == third.title
        # Neueste Ablösung zuerst, damit der Verlauf von oben nach unten zurueckreicht.
        assert [item["version_id"] for item in same_document_history] == [
            second.version_id, first.version_id,
        ]
        assert client.get(f"/portal/admin/archive/{first.version_id}/source").status_code == 200

        restored = client.post(
            f"/portal/admin/archive/{first.version_id}/restore", json={"reason": "Fachlich wieder gültig"},
        )
        assert restored.status_code == 200, restored.text
        assert module.DOCUMENT_LIFECYCLE.active_version(first.document_id) == first.version_id
        assert module.DOCUMENT_LIFECYCLE.version_record(second.version_id)["status"] == "superseded"
        assert module.DOCUMENT_LIFECYCLE.version_record(third.version_id)["status"] == "superseded"

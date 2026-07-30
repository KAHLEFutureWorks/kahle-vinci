from __future__ import annotations

import base64
import hashlib
import importlib.util
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path


def load_module(root: Path):
    kb_root = root / "knowledgebases"
    for name in ("kahleallgemein", "kahlekontext", "kahlerichtlinien"):
        (kb_root / name).mkdir(parents=True)
    os.environ["KB_ROOT"] = str(kb_root)
    os.environ["KB_STATE_PATH"] = str(root / "state.json")
    os.environ["KB_ADMIN_DEV_AUTH_BYPASS"] = "true"
    os.environ["KB_ADMIN_MAINTENANCE_API_KEY"] = "test-maintenance-key"
    os.environ["KB_ADMIN_TRASH_RETENTION_DAYS"] = "30"
    module_path = Path(__file__).resolve().parents[1] / "app" / "main.py"
    spec = importlib.util.spec_from_file_location("kb_admin_api", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_metadata_and_safe_paths():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        module = load_module(root)
        path = root / "knowledgebases" / "kahlekontext" / "test.md"
        path.write_text(
            "---\n"
            "title: Öffnungszeiten Hannover\n"
            "valid_until: 2099-12-31\n"
            "owner: AI Officer\n"
            "standorte: [Hannover, Neustadt]\n"
            "tags: [service, zeiten]\n"
            "---\n\n# Inhalt\n",
            encoding="utf-8",
        )
        metadata = module._metadata(path)
        assert metadata["title"] == "Öffnungszeiten Hannover"
        assert metadata["owner"] == "AI Officer"
        assert metadata["locations"] == ["Hannover", "Neustadt"]
        assert metadata["rag_index"] is True


def test_expiry_thresholds_and_dynamic_collection_discovery():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        module = load_module(root)
        dynamic = root / "knowledgebases" / "service-wissen"
        dynamic.mkdir()
        (dynamic / ".collection.json").write_text(
            '{"label":"Service Wissen"}', encoding="utf-8"
        )
        warning_date = (date.today() + timedelta(days=30)).isoformat()
        critical_date = (date.today() + timedelta(days=10)).isoformat()
        warning = dynamic / "warning.md"
        warning.write_text(
            f"---\nvalid_until: {warning_date}\nnotify_before_days: 14\n---\n",
            encoding="utf-8",
        )
        critical = dynamic / "critical.md"
        critical.write_text(
            f"---\nvalid_until: {critical_date}\nnotify_before_days: 14\n---\n",
            encoding="utf-8",
        )
        assert "service-wissen" in module._collection_names()
        assert module._collection_label("service-wissen") == "Service Wissen"
        assert module._metadata(warning)["expiry_status"] == "warning"
        assert module._metadata(critical)["expiry_status"] == "critical"
        assert module._metadata(critical)["notify_before_days"] == 14


def test_version_and_recoverable_delete_primitives():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        module = load_module(root)
        path = root / "knowledgebases" / "kahleallgemein" / "info.md"
        path.write_text("# Version 1\n", encoding="utf-8")
        version_id = module._create_version(
            path,
            "kahleallgemein",
            "info.md",
            {"email": "admin@kahle.de"},
            "save",
        )
        assert version_id
        versions = list((module.VERSIONS_ROOT / "kahleallgemein").rglob("*.json"))
        assert len(versions) == 1


def test_collection_update_and_recoverable_delete():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        module = load_module(root)
        qdrant_calls = []
        module._qdrant = lambda method, path, **kwargs: qdrant_calls.append((method, path)) or {"ok": True}
        admin = {"email": "admin@kahle.de", "role": "admin"}

        created = module.create_collection(
            module.CreateCollectionRequest(id="dashboard-test", label="Dashboard Test"),
            admin,
        )
        assert created["collection"]["deletable"] is True

        updated = module.update_collection(
            "dashboard-test",
            module.UpdateCollectionRequest(label="Neuer Anzeigename"),
            admin,
        )
        assert updated["collection"]["label"] == "Neuer Anzeigename"
        assert module._collection_label("dashboard-test") == "Neuer Anzeigename"

        deleted = module.delete_collection(
            "dashboard-test",
            module.DeleteCollectionRequest(confirm_id="dashboard-test"),
            admin,
        )
        assert deleted["ok"] is True
        assert deleted["retention_days"] == 30
        assert not (root / "knowledgebases" / "dashboard-test").exists()
        archive = root / "knowledgebases" / deleted["archived_path"]
        assert archive.exists()
        assert (archive / ".trash.json").exists()
        assert ("DELETE", "/collections/dashboard-test") in qdrant_calls

        trashed = module.list_trashed_collections(admin)
        assert len(trashed["collections"]) == 1
        assert trashed["collections"][0]["collection"] == "dashboard-test"

        module._trigger_reindex = lambda collection, relative_path="": {"ok": True}
        restored = module.restore_trashed_collection(archive.name, admin)
        assert restored["collection"]["id"] == "dashboard-test"
        assert (root / "knowledgebases" / "dashboard-test").exists()
        assert not archive.exists()
        assert ("PUT", "/collections/dashboard-test") in qdrant_calls

        deleted_again = module.delete_collection(
            "dashboard-test",
            module.DeleteCollectionRequest(confirm_id="dashboard-test"),
            admin,
        )
        archive_again = root / "knowledgebases" / deleted_again["archived_path"]
        manifest_path = archive_again / ".trash.json"
        manifest = __import__("json").loads(manifest_path.read_text(encoding="utf-8"))
        manifest["purge_at"] = "2000-01-01T00:00:00+00:00"
        manifest_path.write_text(__import__("json").dumps(manifest), encoding="utf-8")
        cleanup = module._purge_expired_collections(dry_run=False, actor=admin)
        assert archive_again.name in cleanup["purged"]
        assert not archive_again.exists()

        try:
            module.delete_collection(
                "kahleallgemein",
                module.DeleteCollectionRequest(confirm_id="kahleallgemein"),
                admin,
            )
            raise AssertionError("protected collection delete should fail")
        except module.HTTPException as exc:
            assert exc.status_code == 409
            assert exc.detail == "protected_collection"


def test_unlock_hash_and_signed_admin_session():
    with tempfile.TemporaryDirectory() as directory:
        module = load_module(Path(directory))
        module.DEV_AUTH_BYPASS = False
        salt = b"fixed-test-salt-123456789"
        code = "Sicherer-Testcode-2026"
        digest = hashlib.pbkdf2_hmac("sha256", code.encode(), salt, 600_000)
        encode = lambda value: base64.urlsafe_b64encode(value).decode().rstrip("=")
        module.UNLOCK_CODE_HASH = (
            f"pbkdf2_sha256.600000.{encode(salt)}.{encode(digest)}"
        )
        module.UNLOCK_SESSION_SECRET = "test-session-secret-with-sufficient-entropy"
        module.UNLOCK_ENABLED = True
        admin = {"id": "admin-1", "email": "admin@kahle.de", "role": "admin"}

        assert module._unlock_code_matches(code) is True
        assert module._unlock_code_matches("falsch") is False
        token = module._issue_unlock_token(admin)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/collections",
            "headers": [(b"cookie", f"{module.UNLOCK_COOKIE}={token}".encode())],
            "client": ("127.0.0.1", 12345),
        }
        request = module.Request(scope)
        assert module._has_valid_unlock(request, admin) is True
        assert module.require_unlocked_admin(request, admin)["id"] == "admin-1"
        assert module._has_valid_unlock(request, {**admin, "id": "other-admin"}) is False

        tampered_scope = {
            **scope,
            "headers": [(b"cookie", f"{module.UNLOCK_COOKIE}={token}x".encode())],
        }
        assert module._has_valid_unlock(module.Request(tampered_scope), admin) is False

if __name__ == "__main__":
    test_metadata_and_safe_paths()
    test_expiry_thresholds_and_dynamic_collection_discovery()
    test_version_and_recoverable_delete_primitives()
    test_collection_update_and_recoverable_delete()
    print("kb admin api contract tests passed")


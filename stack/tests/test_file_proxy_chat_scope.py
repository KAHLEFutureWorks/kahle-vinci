"""File tools resolve only files of the chat that calls them.

Open WebUI sends the chat and user of every tool-server call as connection
headers (X-Kahle-Chat-Id / X-Kahle-User-Id from {{CHAT_ID}} / {{USER_ID}}),
never from model arguments. The proxy derives the allowed files itself: the
chat's attachments from webui.db (chat_file) and the files it generated for
that chat (download-link manifests). Bare names, relative paths and download
links of other users' or other chats' files are not found, and an ambiguity
error lists only the chat's own files.
"""

import importlib.util
import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "owui-file-proxy" / "app"
SCOPE = APP / "chat_scope.py"
PROXY = APP / "main.py"
COMPOSE = ROOT / "docker-compose.yml"

CHAT = "chat-own"
OTHER_CHAT = "chat-foreign"
USER = "user-own"
OTHER_USER = "user-foreign"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_db(path: Path, upload_root: Path, rows: list[tuple[str, str, str, str]]) -> None:
    """rows: (chat_id, chat_owner, file_owner, stored filename)."""
    conn = sqlite3.connect(path)
    conn.execute("create table chat (id text primary key, user_id text)")
    conn.execute("create table file (id text primary key, user_id text, path text)")
    conn.execute("create table chat_file (id text primary key, user_id text, chat_id text, file_id text, message_id text)")
    for index, (chat_id, chat_owner, file_owner, name) in enumerate(rows):
        conn.execute("insert or ignore into chat values (?, ?)", (chat_id, chat_owner))
        file_id = f"file-{index}"
        conn.execute("insert into file values (?, ?, ?)", (file_id, file_owner, str(upload_root / name)))
        if not chat_id.startswith("local:"):
            conn.execute(
                "insert into chat_file values (?, ?, ?, ?, ?)",
                (f"cf-{index}", chat_owner, chat_id, file_id, "m1"),
            )
    conn.commit()
    conn.close()


def write_manifest(root: Path, download_id: str, rel: str, scope: dict, exp_offset: int = 600) -> None:
    links = root / ".download-links"
    links.mkdir(parents=True, exist_ok=True)
    manifest = {"rel": rel, "exp": int(time.time()) + exp_offset, "filename": Path(rel).name, **scope}
    (links / f"{download_id}.json").write_text(json.dumps(manifest), encoding="utf-8")


OWN_UPLOAD = "11111111-1111-4111-8111-111111111111_Bericht.pdf"
FOREIGN_UPLOAD = "22222222-2222-4222-8222-222222222222_Bericht.pdf"
FOREIGN_ONLY = "33333333-3333-4333-8333-333333333333_Gehaltsliste.xlsx"
OWN_GENERATED = "edited/20261015_113228_f49c942f_Zusammenfassung.pdf"
FOREIGN_GENERATED = "edited/20261015_113300_aaaaaaaa_Zusammenfassung.pdf"
OWN_LINK_ID = "0123456789abcdef0123456789abcdef"
FOREIGN_LINK_ID = "fedcba9876543210fedcba9876543210"


@pytest.fixture()
def uploads(tmp_path):
    root = tmp_path / "uploads"
    (root / "edited").mkdir(parents=True)
    for name in (OWN_UPLOAD, FOREIGN_UPLOAD, FOREIGN_ONLY, OWN_GENERATED, FOREIGN_GENERATED):
        (root / name).write_bytes(b"%PDF-1.4 test")
    db = tmp_path / "webui.db"
    make_db(
        db,
        root,
        [
            (CHAT, USER, USER, OWN_UPLOAD),
            (OTHER_CHAT, OTHER_USER, OTHER_USER, FOREIGN_UPLOAD),
            (OTHER_CHAT, OTHER_USER, OTHER_USER, FOREIGN_ONLY),
        ],
    )
    write_manifest(root, OWN_LINK_ID, OWN_GENERATED, {"chat_id": CHAT, "user_id": USER})
    write_manifest(root, FOREIGN_LINK_ID, FOREIGN_GENERATED, {"chat_id": OTHER_CHAT, "user_id": OTHER_USER})
    return root, db


# --- chat_scope: which files belong to the calling chat -----------------------


def test_scope_needs_both_headers_and_rejects_uninterpolated_templates():
    scope = load("chat_scope", SCOPE)

    assert scope.scope_from_headers(CHAT, USER) == scope.ChatScope(CHAT, USER)
    assert scope.scope_from_headers(f" {CHAT} ", USER) == scope.ChatScope(CHAT, USER)
    for chat_id, user_id in ((None, USER), (CHAT, None), ("", USER), ("{{CHAT_ID}}", USER), (CHAT, "{{USER_ID}}")):
        assert scope.scope_from_headers(chat_id, user_id) is None


def test_allowed_files_are_the_chats_attachments_and_its_generated_files(uploads):
    scope = load("chat_scope", SCOPE)
    root, db = uploads

    allowed = scope.allowed_rel_paths(root, db, scope.ChatScope(CHAT, USER), "edited")

    assert allowed == {OWN_UPLOAD, OWN_GENERATED}


def test_a_foreign_chat_id_with_the_wrong_user_sees_nothing(uploads):
    scope = load("chat_scope", SCOPE)
    root, db = uploads

    assert scope.allowed_rel_paths(root, db, scope.ChatScope(OTHER_CHAT, USER), "edited") == set()


def test_expired_or_unscoped_manifests_do_not_grant_access(uploads):
    scope = load("chat_scope", SCOPE)
    root, db = uploads
    write_manifest(root, "a" * 32, "edited/20261015_000000_bbbbbbbb_alt.pdf", {"chat_id": CHAT, "user_id": USER}, -1)
    write_manifest(root, "b" * 32, "edited/20261015_000000_cccccccc_ohne_chat.pdf", {})
    write_manifest(root, "c" * 32, FOREIGN_UPLOAD, {"chat_id": CHAT, "user_id": USER})

    assert scope.allowed_rel_paths(root, db, scope.ChatScope(CHAT, USER), "edited") == {OWN_UPLOAD, OWN_GENERATED}


def test_temporary_chats_fall_back_to_the_users_own_uploads(uploads, tmp_path):
    scope = load("chat_scope", SCOPE)
    root, _ = uploads
    db = tmp_path / "temp.db"
    make_db(db, root, [("local:abc", USER, USER, OWN_UPLOAD), ("local:xyz", OTHER_USER, OTHER_USER, FOREIGN_UPLOAD)])

    assert scope.allowed_rel_paths(root, db, scope.ChatScope("local:abc", USER), "edited") == {OWN_UPLOAD}


def test_missing_database_fails_closed(uploads, tmp_path):
    scope = load("chat_scope", SCOPE)
    root, _ = uploads

    assert scope.allowed_rel_paths(root, tmp_path / "missing.db", scope.ChatScope(CHAT, USER), "edited") == {OWN_GENERATED}


# --- owui-file-proxy endpoints ---------------------------------------------------


@pytest.fixture()
def proxy(uploads, monkeypatch):
    root, db = uploads
    monkeypatch.setenv("OWUI_UPLOAD_DIR", str(root))
    monkeypatch.setenv("OWUI_DB_PATH", str(db))
    monkeypatch.setenv("TOOL_API_KEY", "test-key")
    monkeypatch.setenv("REQUIRE_EXACT_FILE_PATH", "true")
    monkeypatch.setenv("FILE_LINK_SECRET", "test-secret")
    monkeypatch.setenv("OWUI_OUTPUT_SUBDIR", "edited")
    monkeypatch.syspath_prepend(str(APP))
    module = load("owui_file_proxy_main_chat_scope", PROXY)

    seen: list[str] = []

    class WorkerResponse:
        status_code = 200
        content = b"# Inhalt\n"

        def json(self):
            return {"files": [{"text": "Inhalt", "ext": "pdf"} for _ in seen]}

    def fake_post(url, files=None, **kwargs):
        seen[:] = [item[1][0] for item in files or []]
        return WorkerResponse()

    monkeypatch.setattr(module.requests, "post", fake_post)
    from fastapi.testclient import TestClient

    return TestClient(module.app), seen, root


def headers(chat_id: str = CHAT, user_id: str = USER) -> dict:
    return {"Authorization": "Bearer test-key", "X-Kahle-Chat-Id": chat_id, "X-Kahle-User-Id": user_id}


def extract(client, file_path: str, request_headers: dict):
    return client.post("/files/extract_text", json={"file_paths": [file_path]}, headers=request_headers)


def test_bare_filename_resolves_only_the_chats_own_upload(proxy):
    client, seen, _ = proxy

    response = extract(client, "Bericht.pdf", headers())

    assert response.status_code == 200, response.text
    assert seen == ["Bericht.pdf"]


@pytest.mark.parametrize(
    "file_path",
    [
        "Gehaltsliste.xlsx",
        FOREIGN_ONLY,
        FOREIGN_UPLOAD,
        FOREIGN_GENERATED,
        f"uploads/{FOREIGN_GENERATED}",
        f"http://localhost:8091/files/d/{FOREIGN_LINK_ID}",
    ],
)
def test_other_users_files_are_not_found_by_any_reference(proxy, file_path):
    client, seen, root = proxy

    response = extract(client, file_path, headers())

    assert response.status_code in (400, 404)
    assert seen == []
    body = response.text
    for foreign_marker in ("22222222-", "33333333-", "aaaaaaaa"):
        assert foreign_marker not in body or foreign_marker in file_path
    assert str(root) not in body


def test_absolute_path_of_a_foreign_file_is_not_found(proxy):
    client, seen, root = proxy

    response = extract(client, str(root / FOREIGN_UPLOAD), headers())

    assert response.status_code in (400, 404)
    assert seen == []


def test_generated_file_of_this_chat_resolves_by_link_and_by_relative_path(proxy):
    client, seen, _ = proxy

    for reference in (f"http://localhost:8091/files/d/{OWN_LINK_ID}", OWN_GENERATED):
        response = extract(client, reference, headers())
        assert response.status_code == 200, response.text
        assert seen == ["Zusammenfassung.pdf"]


def test_ambiguity_lists_only_the_chats_own_files(proxy, uploads):
    client, _, root = proxy
    _, db = uploads
    second = "44444444-4444-4444-8444-444444444444_Bericht.pdf"
    (root / second).write_bytes(b"%PDF-1.4 zweite")
    conn = sqlite3.connect(db)
    conn.execute("insert into file values ('file-x', ?, ?)", (USER, str(root / second)))
    conn.execute("insert into chat_file values ('cf-x', ?, ?, 'file-x', 'm2')", (USER, CHAT))
    conn.commit()
    conn.close()
    old = time.time() - 3600
    import os

    os.utime(root / second, (old, old))
    os.utime(root / OWN_UPLOAD, (old, old))

    response = extract(client, "Bericht.pdf", headers())

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error"] == "ambiguous_filename_use_exact_relative_path"
    assert sorted(detail["matches"]) == sorted([OWN_UPLOAD, second])


def test_missing_chat_headers_fail_closed(proxy):
    client, seen, _ = proxy

    response = extract(client, "Bericht.pdf", {"Authorization": "Bearer test-key"})

    assert response.status_code == 403
    assert response.json()["detail"] == "chat_scope_required"
    assert seen == []


def test_input_validation_still_runs_before_the_scope(proxy):
    client, _, _ = proxy

    for file_path, code in (("*.pdf", "wildcards_not_allowed"), ("your_file.pdf", "placeholder_filename_not_allowed")):
        response = extract(client, file_path, {"Authorization": "Bearer test-key"})
        assert response.status_code == 400
        assert code in response.text


def test_generated_files_record_the_chat_that_created_them(proxy):
    client, _, root = proxy

    response = client.post(
        "/text/create_save",
        json={"filename": "notiz.md", "content": "# Notiz"},
        headers=headers(),
    )

    assert response.status_code == 200, response.text
    download_id = response.json()["download_url"].rstrip("/").rsplit("/", 1)[-1]
    manifest = json.loads((root / ".download-links" / f"{download_id}.json").read_text(encoding="utf-8"))
    assert manifest["chat_id"] == CHAT
    assert manifest["user_id"] == USER

    follow_up = extract(client, response.json()["download_url"], headers())
    assert follow_up.status_code == 200, follow_up.text
    assert extract(client, response.json()["download_url"], headers(OTHER_CHAT, OTHER_USER)).status_code in (400, 404)


# --- Open WebUI connection sends the trusted headers ---------------------------


def test_tool_server_connection_forwards_chat_and_user_headers():
    compose = COMPOSE.read_text(encoding="utf-8")
    start = compose.index("TOOL_SERVER_CONNECTIONS: >-")
    connection = json.loads(compose[start:].split("\n", 2)[1].strip().replace("${OWUI_FILE_PROXY_API_KEY}", "k"))

    proxy_connection = next(item for item in connection if item["url"] == "http://owui-file-proxy:8091")
    assert proxy_connection["headers"] == {"X-Kahle-Chat-Id": "{{CHAT_ID}}", "X-Kahle-User-Id": "{{USER_ID}}"}


# --- Vinci's workflow tool creates files for its own chat ---------------------


WORKFLOW = ROOT / "open-webui-tools" / "kahle_workflow_orchestrator.py"


def test_workflow_tool_sends_its_chat_when_it_creates_files(monkeypatch):
    import requests

    workflow = load("workflow_chat_scope", WORKFLOW)
    monkeypatch.setenv("OWUI_FILE_PROXY_API_KEY", "test-key")
    sent: list[dict] = []

    class Created:
        status_code = 200

        def json(self):
            return {"download_url": "/files/d/" + "0" * 32, "filename": "x.pdf"}

    def fake_post(url, json=None, headers=None, **kwargs):
        sent.append(dict(headers or {}))
        return Created()

    monkeypatch.setattr(requests, "post", fake_post)

    token = workflow.bind_file_proxy_chat(CHAT, {"id": USER})
    try:
        workflow.create_downloadable_file("# Inhalt", "pdf", "x.pdf")
        workflow.create_ki_policy_quiz("quiz.pdf", "pdf")
    finally:
        workflow.unbind_file_proxy_chat(token)
    workflow.create_downloadable_file("# Inhalt", "md", "y.md")

    assert [h.get("X-Kahle-Chat-Id") for h in sent] == [CHAT, CHAT, None]
    assert [h.get("X-Kahle-User-Id") for h in sent] == [USER, USER, None]
    assert all(h["Authorization"] == "Bearer test-key" for h in sent)


def test_workflow_tool_binds_the_chat_for_the_whole_run():
    source = WORKFLOW.read_text(encoding="utf-8")
    run = source[source.index("async def kahle_workflow_execute("):source.index("async def _tasks_create(")]

    assert "bind_file_proxy_chat(__chat_id__, __user__)" in run
    assert "unbind_file_proxy_chat(" in run
    assert source.count('headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}') == 1
    assert source.count("headers=_file_proxy_headers(api_key)") == 4


# --- the tool-call guard also creates files for its own chat -------------------


GUARD = ROOT / "open-webui-functions" / "kahle_toolcall_guard.py"


def test_guard_sends_its_chat_when_it_creates_files(monkeypatch):
    guard = load("guard_chat_scope", GUARD)
    monkeypatch.setenv("OWUI_FILE_PROXY_API_KEY", "test-key")
    sent: list[dict] = []

    class Created:
        status_code = 200

        def json(self):
            return {"download_url": "/files/d/" + "0" * 32, "filename": "x.pdf"}

    def fake_post(url, json=None, headers=None, **kwargs):
        sent.append(dict(headers or {}))
        return Created()

    monkeypatch.setattr(guard.requests, "post", fake_post)

    token = guard.bind_file_proxy_chat(CHAT, {"id": USER})
    try:
        guard._create_file("# Bericht\n\nInhalt des Berichts mit genug Text.", "pdf", "x.pdf")
        guard._create_ki_policy_quiz("quiz.pdf", "pdf")
    finally:
        guard.unbind_file_proxy_chat(token)
    guard._create_file("# Bericht\n\nInhalt des Berichts mit genug Text.", "md", "y.md")

    assert [h.get("X-Kahle-Chat-Id") for h in sent] == [CHAT, CHAT, None]
    assert [h.get("X-Kahle-User-Id") for h in sent] == [USER, USER, None]


def test_guard_binds_the_chat_for_the_whole_outlet():
    source = GUARD.read_text(encoding="utf-8")
    outlet = source[source.index("    def outlet("):source.index("    def _outlet(")]

    assert "bind_file_proxy_chat(" in outlet and "unbind_file_proxy_chat(" in outlet
    assert "chat_id" in outlet
    assert source.count('headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}') == 0
    # file creation (4x) and the guard's own file tool calls
    assert source.count("headers=_file_proxy_headers(api_key)") == 5

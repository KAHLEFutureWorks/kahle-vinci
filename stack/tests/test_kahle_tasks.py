from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "open-webui-tools" / "kahle_tasks.py"


def load_module(tmp_path: Path):
    os.environ["KAHLE_TASKS_DB_PATH"] = str(tmp_path / "tasks.db")
    spec = importlib.util.spec_from_file_location("kahle_tasks", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def run(coro):
    return asyncio.run(coro)


def test_create_list_complete_task(tmp_path):
    module = load_module(tmp_path)
    tools = module.Tools()
    user = {"id": "user-1", "email": "u@example.invalid"}

    created = json.loads(
        run(
            tools.kv_task_create(
                title="KI-Richtlinie pruefen",
                description="Abschnitt Datenschutz pruefen",
                due_date="2026-05-10",
                priority="high",
                __user__=user,
            )
        )
    )

    assert created["ok"] is True
    task_id = created["task"]["id"]
    assert created["task"]["status"] == "open"
    assert created["task"]["priority"] == "high"

    listed = json.loads(run(tools.kv_tasks_list(__user__=user)))
    assert listed["count"] == 1
    assert listed["tasks"][0]["id"] == task_id

    completed = json.loads(run(tools.kv_task_complete(task_id=task_id, __user__=user)))
    assert completed["ok"] is True
    assert completed["task"]["status"] == "completed"
    assert completed["task"]["completed_at"]

    open_tasks = json.loads(run(tools.kv_tasks_list(__user__=user)))
    assert open_tasks["count"] == 0

    all_tasks = json.loads(run(tools.kv_tasks_list(include_completed=True, __user__=user)))
    assert all_tasks["count"] == 1


def test_update_and_complete_can_resolve_unique_task_by_title(tmp_path):
    module = load_module(tmp_path)
    tools = module.Tools()
    user = {"id": "user-1"}

    created = json.loads(run(tools.kv_task_create(title="Rueckruf Kunde Mueller wegen Reifenangebot", __user__=user)))
    assert created["ok"] is True

    updated = json.loads(
        run(
            tools.kv_task_update(
                title="Rueckruf Kunde Mueller wegen Reifenangebot",
                priority="urgent",
                description="Kunde moechte Rueckmeldung bis 15 Uhr.",
                __user__=user,
            )
        )
    )

    assert updated["ok"] is True
    assert updated["task"]["id"] == created["task"]["id"]
    assert updated["task"]["priority"] == "urgent"
    assert "15 Uhr" in updated["task"]["description"]

    completed = json.loads(run(tools.kv_task_complete(title="Rueckruf Kunde Mueller wegen Reifenangebot", __user__=user)))

    assert completed["ok"] is True
    assert completed["task"]["id"] == created["task"]["id"]
    assert completed["task"]["status"] == "completed"


def test_update_recovers_empty_params_from_latest_user_message(tmp_path):
    module = load_module(tmp_path)
    tools = module.Tools()
    user = {"id": "user-1"}

    created = json.loads(run(tools.kv_task_create(title="Rueckruf Kunde Mueller wegen Reifenangebot", __user__=user)))
    assert created["ok"] is True

    webui_db = tmp_path / "webui.db"
    con = sqlite3.connect(webui_db)
    con.execute("create table chat_message (chat_id text, role text, content text, created_at integer, updated_at integer)")
    con.execute(
        "insert into chat_message values (?, 'user', ?, 10, 10)",
        (
            "chat-update",
            'Aendere die Aufgabe "Rueckruf Kunde Mueller wegen Reifenangebot" auf Prioritaet dringend '
            "und ergaenze: Kunde moechte Rueckmeldung bis 15 Uhr.",
        ),
    )
    con.commit()
    con.close()

    old_webui = os.environ.get("OWUI_DB_PATH")
    os.environ["OWUI_DB_PATH"] = str(webui_db)
    try:
        updated = json.loads(run(tools.kv_task_update(__chat_id__="chat-update", __user__=user)))
    finally:
        if old_webui is None:
            os.environ.pop("OWUI_DB_PATH", None)
        else:
            os.environ["OWUI_DB_PATH"] = old_webui

    assert updated["ok"] is True
    assert updated["task"]["id"] == created["task"]["id"]
    assert updated["task"]["priority"] == "urgent"
    assert "15 Uhr" in updated["task"]["description"]


def test_update_resolves_title_with_umlaut_or_ascii_variants(tmp_path):
    module = load_module(tmp_path)
    tools = module.Tools()
    user = {"id": "user-1"}

    created = json.loads(run(tools.kv_task_create(title="Rueckruf Kunde Mueller wegen Reifenangebot", __user__=user)))
    assert created["ok"] is True

    updated = json.loads(
        run(
            tools.kv_task_update(
                title="Rückruf Kunde Müller wegen Reifenangebot",
                priority="urgent",
                __user__=user,
            )
        )
    )

    assert updated["ok"] is True
    assert updated["task"]["id"] == created["task"]["id"]
    assert updated["task"]["priority"] == "urgent"

    corrupted = json.loads(
        run(
            tools.kv_task_update(
                title="R?ckruf Kunde M?ller wegen Reifenangebot",
                priority="high",
                __user__=user,
            )
        )
    )

    assert corrupted["ok"] is True
    assert corrupted["task"]["id"] == created["task"]["id"]
    assert corrupted["task"]["priority"] == "high"


def test_complete_recovers_empty_params_from_latest_user_message(tmp_path):
    module = load_module(tmp_path)
    tools = module.Tools()
    user = {"id": "user-1"}

    created = json.loads(run(tools.kv_task_create(title="Rueckruf Kunde Mueller wegen Reifenangebot", __user__=user)))
    assert created["ok"] is True

    webui_db = tmp_path / "webui.db"
    con = sqlite3.connect(webui_db)
    con.execute("create table chat_message (chat_id text, role text, content text, created_at integer, updated_at integer)")
    con.execute(
        "insert into chat_message values (?, 'user', ?, 10, 10)",
        ("chat-complete", 'Markiere die Aufgabe "Rueckruf Kunde Mueller wegen Reifenangebot" als erledigt.'),
    )
    con.commit()
    con.close()

    old_webui = os.environ.get("OWUI_DB_PATH")
    os.environ["OWUI_DB_PATH"] = str(webui_db)
    try:
        completed = json.loads(run(tools.kv_task_complete(__chat_id__="chat-complete", __user__=user)))
    finally:
        if old_webui is None:
            os.environ.pop("OWUI_DB_PATH", None)
        else:
            os.environ["OWUI_DB_PATH"] = old_webui

    assert completed["ok"] is True
    assert completed["task"]["id"] == created["task"]["id"]
    assert completed["task"]["status"] == "completed"


def test_complete_decodes_json_encoded_latest_user_message(tmp_path):
    module = load_module(tmp_path)
    tools = module.Tools()
    user = {"id": "user-1"}

    created = json.loads(run(tools.kv_task_create(title="Rueckruf Kunde Mueller wegen Reifenangebot", __user__=user)))
    assert created["ok"] is True

    webui_db = tmp_path / "webui.db"
    con = sqlite3.connect(webui_db)
    con.execute("create table chat_message (chat_id text, role text, content text, created_at integer, updated_at integer)")
    con.execute(
        "insert into chat_message values (?, 'user', ?, 10, 10)",
        (
            "chat-complete-json",
            json.dumps('Bitte markiere die Aufgabe “Rückruf Kunde Müller” als abgeschlossen'),
        ),
    )
    con.commit()
    con.close()

    old_webui = os.environ.get("OWUI_DB_PATH")
    os.environ["OWUI_DB_PATH"] = str(webui_db)
    try:
        completed = json.loads(run(tools.kv_task_complete(__chat_id__="chat-complete-json", __user__=user)))
    finally:
        if old_webui is None:
            os.environ.pop("OWUI_DB_PATH", None)
        else:
            os.environ["OWUI_DB_PATH"] = old_webui

    assert completed["ok"] is True
    assert completed["task"]["id"] == created["task"]["id"]
    assert completed["task"]["status"] == "completed"


def test_due_date_morgen_is_resolved_from_latest_user_message(tmp_path):
    module = load_module(tmp_path)
    tools = module.Tools()
    user = {"id": "user-1"}

    webui_db = tmp_path / "webui.db"
    con = sqlite3.connect(webui_db)
    con.execute("create table chat_message (chat_id text, role text, content text, created_at integer, updated_at integer)")
    con.execute(
        "insert into chat_message values (?, 'user', ?, 10, 10)",
        ("chat-1", "Erstelle mir eine Aufgabe: Rueckruf Kunde Mueller, faellig morgen, Prioritaet hoch."),
    )
    con.commit()
    con.close()

    old_webui = os.environ.get("OWUI_DB_PATH")
    old_today = os.environ.get("KAHLE_TASKS_TODAY")
    os.environ["OWUI_DB_PATH"] = str(webui_db)
    os.environ["KAHLE_TASKS_TODAY"] = "2026-05-11"
    try:
        created = json.loads(
            run(
                tools.kv_task_create(
                    title="Rueckruf Kunde Mueller",
                    due_date="2026-05-07",
                    priority="high",
                    __chat_id__="chat-1",
                    __user__=user,
                )
            )
        )
    finally:
        if old_webui is None:
            os.environ.pop("OWUI_DB_PATH", None)
        else:
            os.environ["OWUI_DB_PATH"] = old_webui
        if old_today is None:
            os.environ.pop("KAHLE_TASKS_TODAY", None)
        else:
            os.environ["KAHLE_TASKS_TODAY"] = old_today

    assert created["ok"] is True
    assert created["task"]["due_date"] == "2026-05-12"
    assert created["task"]["created_at_display"]


def test_tasks_are_user_scoped(tmp_path):
    module = load_module(tmp_path)
    tools = module.Tools()

    result = json.loads(run(tools.kv_task_create(title="Nur Nutzer A", __user__={"id": "a"})))
    assert result["ok"] is True

    user_a = json.loads(run(tools.kv_tasks_list(__user__={"id": "a"})))
    user_b = json.loads(run(tools.kv_tasks_list(__user__={"id": "b"})))

    assert user_a["count"] == 1
    assert user_b["count"] == 0


def test_tasks_reject_missing_openwebui_user_id(tmp_path):
    module = load_module(tmp_path)
    tools = module.Tools()

    missing = json.loads(run(tools.kv_task_create(title="Keine Zuordnung", __user__={})))
    fallback_email = json.loads(run(tools.kv_task_create(title="Keine Email-Fallbacks", __user__={"email": "a@example.invalid"})))
    listed = json.loads(run(tools.kv_tasks_list(__user__={})))

    assert missing["ok"] is False
    assert "user_id fehlt" in missing["error"]
    assert fallback_email["ok"] is False
    assert listed["ok"] is False


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        test_create_list_complete_task(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_update_and_complete_can_resolve_unique_task_by_title(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_update_recovers_empty_params_from_latest_user_message(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_update_resolves_title_with_umlaut_or_ascii_variants(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_complete_recovers_empty_params_from_latest_user_message(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_complete_decodes_json_encoded_latest_user_message(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_due_date_morgen_is_resolved_from_latest_user_message(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_tasks_are_user_scoped(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_tasks_reject_missing_openwebui_user_id(Path(tmp))
    print("kahle task tests passed")

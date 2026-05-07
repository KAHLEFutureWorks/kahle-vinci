from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TASK_TOOL_PATH = ROOT / "open-webui-tools" / "kahle_tasks.py"
ADMIN_TOOL_PATH = ROOT / "open-webui-tools" / "kahle_tasks_admin.py"


def load_module(path: Path, name: str, tmp_path: Path):
    os.environ["KAHLE_TASKS_DB_PATH"] = str(tmp_path / "tasks.db")
    os.environ["OWUI_DB_PATH"] = str(tmp_path / "webui.db")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def run(coro):
    return asyncio.run(coro)


def create_webui_users_db(tmp_path: Path):
    import sqlite3

    con = sqlite3.connect(tmp_path / "webui.db")
    con.execute("create table if not exists user (id text primary key, name text, email text, role text)")
    con.execute("delete from user")
    con.executemany(
        "insert into user (id, name, email, role) values (?, ?, ?, ?)",
        [
            ("admin-1", "Admin User", "admin@example.test", "admin"),
            ("user-1", "Max Mustermann", "max@example.test", "user"),
            ("user-2", "Test Nutzer", "test@example.test", "user"),
        ],
    )
    con.commit()
    con.close()


def test_task_admin_status_requires_admin_and_reports_counts(tmp_path):
    create_webui_users_db(tmp_path)
    task_module = load_module(TASK_TOOL_PATH, "kahle_tasks_for_admin_test", tmp_path)
    admin_module = load_module(ADMIN_TOOL_PATH, "kahle_tasks_admin_test", tmp_path)
    tasks = task_module.Tools()
    admin = admin_module.Tools()

    created = json.loads(run(tasks.kv_task_create(title="Admin Smoke", __user__={"id": "user-1"})))
    assert created["ok"] is True

    forbidden = json.loads(run(admin.task_admin_status(__user__={"id": "user-1", "role": "user"})))
    assert forbidden["ok"] is False
    assert "Admins" in forbidden["error"]

    status = json.loads(run(admin.task_admin_status(include_user_breakdown=True, __user__={"id": "admin-1", "role": "admin"})))
    assert status["ok"] is True
    assert status["tasks_total"] == 1
    assert status["users_with_tasks"] == 1
    assert status["by_status"]["open"] == 1
    assert status["by_user"][0]["user_id"] == "user-1"
    assert status["by_user"][0]["user_name"] == "Max Mustermann"


def test_task_admin_lists_real_tasks_by_user_name_or_id(tmp_path):
    create_webui_users_db(tmp_path)
    task_module = load_module(TASK_TOOL_PATH, "kahle_tasks_for_admin_list_test", tmp_path)
    admin_module = load_module(ADMIN_TOOL_PATH, "kahle_tasks_admin_list_test", tmp_path)
    tasks = task_module.Tools()
    admin = admin_module.Tools()

    run(tasks.kv_tasks_create_many(
        tasks_json='[{"title":"Aufgabe 1","description":"Beschreibung 1","priority":"high"},'
                   '{"title":"Aufgabe 2","description":"Beschreibung 2","priority":"normal"},'
                   '{"title":"Aufgabe 3","description":"Beschreibung 3","priority":"low"}]',
        __user__={"id": "user-1"},
    ))
    run(tasks.kv_task_create(title="Andere Aufgabe", __user__={"id": "user-2"}))

    by_name = json.loads(run(admin.task_admin_list_user_tasks(user="Max Mustermann", __user__={"id": "admin-1", "role": "admin"})))
    assert by_name["ok"] is True
    assert by_name["user"]["id"] == "user-1"
    assert by_name["user"]["name"] == "Max Mustermann"
    assert [task["title"] for task in by_name["tasks"]] == ["Aufgabe 1", "Aufgabe 2", "Aufgabe 3"]

    by_id = json.loads(run(admin.task_admin_list_user_tasks(user="user-2", __user__={"id": "admin-1", "role": "admin"})))
    assert by_id["ok"] is True
    assert by_id["user"]["name"] == "Test Nutzer"
    assert [task["title"] for task in by_id["tasks"]] == ["Andere Aufgabe"]


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "status").mkdir()
        (root / "list").mkdir()
        test_task_admin_status_requires_admin_and_reports_counts(root / "status")
        test_task_admin_lists_real_tasks_by_user_name_or_id(root / "list")
    print("kahle task admin tests passed")

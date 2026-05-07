from __future__ import annotations

import asyncio
import importlib.util
import json
import os
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
        test_tasks_are_user_scoped(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_tasks_reject_missing_openwebui_user_id(Path(tmp))
    print("kahle task tests passed")

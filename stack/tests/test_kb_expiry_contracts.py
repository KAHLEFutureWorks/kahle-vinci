from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "docker-compose.yml"
PROXY_MAIN_PATH = ROOT / "owui-file-proxy" / "app" / "main.py"
WORKFLOW_PATH = ROOT.parent / "n8n" / "workflows" / "knowledgebase" / "kb-validity-reminders.json"


def test_file_proxy_has_read_only_knowledgebase_access():
    text = COMPOSE_PATH.read_text(encoding="utf-8")

    assert "KB_ROOT: /knowledgebases" in text
    assert "KAHLE_TASKS_DB_PATH: /app/backend/data/kahle_vinci_tasks.db" in text
    assert "/knowledgebases:/knowledgebases:ro" in text


def test_expiry_endpoint_does_not_replace_file_save_route():
    text = PROXY_MAIN_PATH.read_text(encoding="utf-8")

    assert '@app.post("/maintenance/kb_expiry_sync"' in text
    assert '@app.post("/files/save_b64"' in text
    assert text.index('@app.post("/maintenance/kb_expiry_sync"') < text.index(
        '@app.post("/files/save_b64"'
    )


def test_n8n_workflow_is_safe_template():
    payload = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    workflow = payload[0]

    assert workflow["id"] == "KbExpiryReminder"
    assert workflow["active"] is False
    schedule = next(node for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.scheduleTrigger")
    interval = schedule["parameters"]["rule"]["interval"][0]
    assert interval["triggerAtHour"] == 10
    assert interval["triggerAtMinute"] == 30
    assert workflow["settings"]["timezone"] == "Europe/Berlin"
    nodes = {node["name"]: node for node in workflow["nodes"]}
    request = nodes["Wissenspflege-Aufgaben synchronisieren"]
    assert request["parameters"]["url"] == "http://owui-file-proxy:8091/maintenance/kb_expiry_sync"
    assert "OWUI_FILE_PROXY_API_KEY" in json.dumps(request)
    cleanup = nodes["Papierkorb nach 30 Tagen bereinigen"]
    assert cleanup["parameters"]["url"] == "http://kb-admin-api:8092/maintenance/trash-cleanup?dry_run=false"
    assert "OWUI_FILE_PROXY_API_KEY" in json.dumps(cleanup)
    assert workflow["connections"]["Wissenspflege-Aufgaben synchronisieren"]["main"][0][0]["node"] == cleanup["name"]

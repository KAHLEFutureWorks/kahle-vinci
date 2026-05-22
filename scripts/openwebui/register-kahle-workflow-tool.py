#!/usr/bin/env python3
"""Register local KAHLE OpenWebUI tools and model bindings in SQLite."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
ROOT = SCRIPT_PATH.parents[2] if len(SCRIPT_PATH.parents) > 2 else Path.cwd()
DB_PATH = Path(os.environ["OWUI_DB_PATH"]) if "OWUI_DB_PATH" in os.environ else ROOT / "stack" / "openwebui_data" / "webui.db"
TOOLS_DIR = ROOT / "stack" / "open-webui-tools"
FUNCTIONS_DIR = ROOT / "stack" / "open-webui-functions"
PROMPTS_DIR = ROOT / "stack" / "open-webui-prompts"

KAHLE_VINCI_MODEL_IDS = ["vinci-2-clone-clone-clone", "kahle-vinci-thinking"]
KAHLE_VINCI_BASE_MODEL_IDS = ["mistralai/Mistral-Small-24B-Instruct", "openai/gpt-oss-120b"]
PUBLIC_MODEL_IDS = KAHLE_VINCI_MODEL_IDS + KAHLE_VINCI_BASE_MODEL_IDS
PUBLIC_TOOL_IDS = [
    "kahle_tasks",
    "kahle_workflow",
    "owui_productivity",
    "rag_chat",
    "safe_webcaller",
    "zeit_berechnung",
]
ADMIN_MODEL_ID = "kahle-vinci-admin"
ADMIN_BASE_MODEL_ID = os.environ.get("KAHLE_ADMIN_BASE_MODEL_ID", "mistralai/Mistral-Small-24B-Instruct")

TOOLS_FUNCTION_CALLING_PROMPT = """Available Tools: {{TOOLS}}

Return ONLY valid JSON, with no markdown, no prose and no visible pseudo tool syntax:
{"tool_calls":[{"name":"<tool>","parameters":{...}}]}

Hard rules:
- Never output "[TOOL_CALLS]" or a raw tool name in the chat. If a tool is needed, return the JSON object above only.
- Use exact tool names from Available Tools. Do not invent aliases.
- If no tool is needed or required information is missing, return exactly {"tool_calls":[]}.

Routing:
- Generated research/analysis/chat result -> downloadable PDF/DOCX/MD: use kahle_workflow_execute.
- Research/Web search AND downloadable PDF/DOCX/MD in one request: use kahle_workflow_execute once, with auftrag as the full user request and output_format set to pdf/docx/md.
- PowerPoint/PPTX output is disabled. If the user asks for PowerPoint/PPTX, do not call a document creation tool; offer PDF, DOCX or Markdown instead.
- "aus dem Ergebnis", "daraus", "aus der vorherigen Antwort" or similar -> use kahle_workflow_execute with auftrag as the full user request and output_format set to the requested file type.
- Do not use pdf_create_save/docx_create_save/text_create_save for generated content when kahle_workflow_execute is available.
- For uploaded file editing/conversion only: use the matching *_save file proxy tool and exact attached filename(s). Never guess upload filenames.
- For external/current web research without file output: use safe_websearch with a search-engine style query.
- For KAHLE-internal knowledge without web/file output: use RAG_Chat/rag_chat where available.
- For listing, updating, completing or deleting personal tasks: always use kahle_tasks tools. Never answer task lists from memory.

Parameter rules:
- kahle_workflow_execute: include auftrag whenever possible. Set output_format to pdf/docx/md when the user asks for a downloadable file.
- safe_websearch query should be concise and search-ready: main entity + aspect + region/language + date/year if present. Remove chat filler like "bitte recherchiere".
- kv_task_update/kv_task_complete: if the user gives a clear task title but no ID, pass that title in title/task_title instead of asking for task_id.
- For file proxy upload tools, file_path/file_paths must be exact uploaded filenames from current message context. No wildcards, placeholders, uploads/ prefix, absolute paths, "latest".
- If a tool result contains download_url, the assistant response must only show download_url and metadata.

If no tool: {"tool_calls":[]}"""


KAHLE_WORKFLOW_SPECS = [
    {
        "name": "kahle_workflow_execute",
        "description": (
            "Fuehrt komplexe KAHLE-Mehrschrittaufgaben in einem stabilen Toolcall aus: "
            "Tasks anlegen/aktualisieren, interne KAHLE-RAG-Recherche oder externe Webrecherche ausfuehren "
            "und strukturierte Ergebnisse fuer Briefings oder direkt herunterladbare PDF/DOCX/MD-Dateien liefern. "
            "Nutze dieses Tool bevorzugt, wenn der Nutzer sagt: Tasks erstellen UND abarbeiten, "
            "Aufgabe aufteilen UND ausfuehren, interne Informationen holen UND daraus eine Praesentation/Gliederung/Briefing erstellen. "
            "Nutze dieses Tool auch bevorzugt, wenn der Nutzer Recherche/Websuche UND Ausgabe als PDF/DOCX/Markdown in einer Anfrage verlangt. PPTX/PowerPoint ist deaktiviert."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "auftrag": {"type": "string", "description": "Die vollstaendige Nutzeraufgabe wortnah."},
                "modus": {
                    "type": "string",
                    "enum": ["auto", "internal", "external", "mixed"],
                    "default": "auto",
                    "description": "internal fuer KAHLE-Wissen, external fuer Web/News, mixed fuer beides.",
                },
                "ziel": {
                    "type": "string",
                    "enum": ["auto", "research_brief", "presentation_outline", "docx_brief"],
                    "default": "auto",
                    "description": "Gewuenschtes Ergebnisformat.",
                },
                "output_format": {
                    "type": "string",
                    "enum": ["auto", "none", "pdf", "docx", "md"],
                    "default": "auto",
                    "description": "Optional direkt eine neue Ergebnisdatei erzeugen. auto erkennt PDF/DOCX/Markdown-Wuensche aus dem Auftrag. PPTX ist deaktiviert.",
                },
                "filename": {
                    "type": "string",
                    "default": "",
                    "description": "Optionaler Ausgabedateiname fuer neu erzeugte Dateien, z. B. recherche.pdf. Leer = automatisch.",
                },
                "max_web_results": {"type": "integer", "default": 5, "description": "Maximale Webtrefferzahl."},
            },
        },
    }
]


SAFE_WEBCALLER_SPECS = [
    {
        "name": "safe_websearch",
        "description": (
            "Sichere Websuche ueber den lokalen n8n/SearXNG-Workflow. "
            "Verwende dieses Tool fuer aktuelle externe Web-Recherche. "
            "Die query soll suchmaschinengeeignet sein: kurz, konkret, mit Hauptentitaet, Aspekt, Region/Sprache und Zeitraum, sofern aus der Nutzerfrage erkennbar. "
            "Keine Chat-Floskeln wie 'bitte recherchiere'. Bei aktuellen/News-Anfragen darf 2026 ergaenzt werden."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Suchmaschinenoptimierte Anfrage, z. B. 'Claude AI Anthropic Modelle Funktionen Preise Enterprise Vergleich' "
                        "oder 'aktuelle KI News Mai 2026 OpenAI Anthropic Google Meta EU AI Act'."
                    ),
                },
                "lang": {"type": "string", "default": "de-DE", "description": "Sprache/Locale der Suche."},
                "maxResults": {"type": "integer", "default": 5, "description": "Maximale Anzahl Suchtreffer."},
                "userName": {"type": "string", "default": "", "description": "Optionaler Nutzername. Leer lassen, wenn unbekannt."},
            },
        },
    }
]


KAHLE_TASK_SPECS = [
    {
        "name": "kv_task_create",
        "description": "Erstellt eine persistente persoenliche Aufgabe fuer den aktuellen Nutzer.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Kurzer, eindeutiger Aufgabentitel."},
                "description": {"type": "string", "default": "", "description": "Optionaler Kontext oder naechster Schritt."},
                "due_date": {"type": "string", "default": "", "description": "Optionales Faelligkeitsdatum, bevorzugt YYYY-MM-DD."},
                "priority": {"type": "string", "default": "normal", "enum": ["low", "normal", "high", "urgent"]},
            },
            "required": ["title"],
        },
    },
    {
        "name": "kv_tasks_create_many",
        "description": "Erstellt mehrere persistente persoenliche Aufgaben in einem Aufruf.",
        "parameters": {
            "type": "object",
            "properties": {
                "tasks_json": {
                    "type": "string",
                    "description": 'JSON-Liste, z. B. [{"title":"Recherche","description":"...","due_date":"2026-05-08","priority":"high"}].',
                }
            },
            "required": ["tasks_json"],
        },
    },
    {
        "name": "kv_tasks_list",
        "description": "Listet die persistenten Aufgaben des aktuellen Nutzers.",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "default": "", "description": "Optional open, in_progress, completed oder cancelled."},
                "include_completed": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "default": 25},
            },
        },
    },
    {
        "name": "kv_task_update",
        "description": "Aktualisiert eine bestehende persistente Aufgabe. Kann per task_id oder eindeutigem Titel aufloesen.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "default": "", "description": "ID der Aufgabe, z. B. task_ab12cd34ef56. Optional, wenn title/task_title eindeutig ist."},
                "title": {"type": "string", "default": "", "description": "Aktueller eindeutiger Aufgabentitel, wenn keine task_id bekannt ist."},
                "task_title": {"type": "string", "default": "", "description": "Alias fuer aktueller eindeutiger Aufgabentitel."},
                "lookup_title": {"type": "string", "default": "", "description": "Alias fuer aktueller eindeutiger Aufgabentitel."},
                "new_title": {"type": "string", "default": "", "description": "Optional neuer Titel der Aufgabe."},
                "description": {"type": "string", "default": ""},
                "due_date": {"type": "string", "default": ""},
                "priority": {"type": "string", "default": "", "enum": ["", "low", "normal", "high", "urgent"]},
                "status": {"type": "string", "default": "", "enum": ["", "open", "in_progress", "completed", "cancelled"]},
            },
        },
    },
    {
        "name": "kv_task_complete",
        "description": "Markiert eine persistente Aufgabe als erledigt. Kann per task_id oder eindeutigem Titel aufloesen.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "default": "", "description": "ID der Aufgabe. Optional, wenn title/task_title eindeutig ist."},
                "title": {"type": "string", "default": "", "description": "Aktueller eindeutiger Aufgabentitel, wenn keine task_id bekannt ist."},
                "task_title": {"type": "string", "default": "", "description": "Alias fuer aktueller eindeutiger Aufgabentitel."},
                "lookup_title": {"type": "string", "default": "", "description": "Alias fuer aktueller eindeutiger Aufgabentitel."},
            },
        },
    },
    {
        "name": "kv_task_delete",
        "description": "Loescht eine persistente Aufgabe des aktuellen Nutzers.",
        "parameters": {
            "type": "object",
            "properties": {"task_id": {"type": "string", "description": "ID der Aufgabe."}},
            "required": ["task_id"],
        },
    },
]


KB_DIAGNOSTICS_SPECS = [
    {
        "name": "kb_status",
        "description": "Admin-Statusbericht fuer eine oder alle KAHLE Knowledgebase-Collections.",
        "parameters": {
            "type": "object",
            "properties": {
                "collection": {
                    "type": "string",
                    "default": "",
                    "description": "Optional kahleallgemein, kahlekontext oder kahlerichtlinien. Leer = alle.",
                }
            },
        },
    },
    {
        "name": "kb_file_status",
        "description": "Prueft eine konkrete Datei oder einen Dateinamen-Ausschnitt in einer Knowledgebase.",
        "parameters": {
            "type": "object",
            "properties": {
                "collection": {"type": "string", "description": "Collection-Name, z. B. kahleallgemein."},
                "filename_contains": {"type": "string", "description": "Teil des Dateinamens oder Pfads."},
            },
            "required": ["collection", "filename_contains"],
        },
    },
    {
        "name": "kb_reindex_hint",
        "description": "Gibt sichere Hinweise zum Reindex. Fuehrt keinen Reindex aus.",
        "parameters": {
            "type": "object",
            "properties": {"collection": {"type": "string", "default": "", "description": "Optional Collection-Name."}},
        },
    },
]


KAHLE_TASK_ADMIN_SPECS = [
    {
        "name": "task_admin_status",
        "description": "Admin-Kennzahlen zur zentralen KAHLE-Vinci Aufgaben-Datenbank. Nur fuer OpenWebUI-Admins.",
        "parameters": {
            "type": "object",
            "properties": {
                "include_user_breakdown": {"type": "boolean", "default": False},
                "completed_older_than_days": {"type": "integer", "default": 180},
            },
        },
    },
    {
        "name": "task_admin_list_user_tasks",
        "description": (
            "Listet die echten Aufgaben eines bestimmten Nutzers anhand von user_id, Name, E-Mail "
            "oder user_index aus task_admin_status. Nur fuer OpenWebUI-Admins."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "user": {
                    "type": "string",
                    "default": "",
                    "description": 'user_id, Name, E-Mail oder "Nutzer 1"/"Nutzer 2" aus task_admin_status.',
                },
                "user_index": {
                    "type": "integer",
                    "default": 0,
                    "description": "Optionaler user_index aus task_admin_status. 0 = nicht nutzen.",
                },
                "status": {
                    "type": "string",
                    "default": "open",
                    "description": "Optional open, in_progress, completed, cancelled oder leer fuer alle.",
                },
                "limit": {"type": "integer", "default": 50},
            },
        },
    },
    {
        "name": "task_admin_cleanup_completed",
        "description": "Bereinigt alte erledigte Aufgaben. Standard ist Dry-Run. Nur fuer OpenWebUI-Admins.",
        "parameters": {
            "type": "object",
            "properties": {
                "older_than_days": {"type": "integer", "default": 180},
                "dry_run": {"type": "boolean", "default": True},
                "max_delete": {"type": "integer", "default": 1000},
            },
        },
    },
]


TOOL_DEFINITIONS = {
    "safe_webcaller": {
        "name": "Safe Webcaller",
        "path": TOOLS_DIR / "safe_webcaller.py",
        "specs": SAFE_WEBCALLER_SPECS,
        "description": "Sichere Websuche mit Query-Optimierung ueber n8n/SearXNG.",
        "version": "0.2.0",
    },
    "kahle_workflow": {
        "name": "KAHLE Workflow",
        "path": TOOLS_DIR / "kahle_workflow_orchestrator.py",
        "specs": KAHLE_WORKFLOW_SPECS,
        "description": "Deterministischer KAHLE Workflow-Orchestrator fuer Tasks, RAG/Web und strukturierte Ausgaben.",
        "version": "0.1.0",
    },
    "kahle_tasks": {
        "name": "KAHLE Tasks",
        "path": TOOLS_DIR / "kahle_tasks.py",
        "specs": KAHLE_TASK_SPECS,
        "description": "Persistente persoenliche Aufgaben fuer KAHLE-Vinci.",
        "version": "0.1.0",
    },
    "kb_diagnostics": {
        "name": "KAHLE Knowledgebase Diagnose",
        "path": TOOLS_DIR / "kb_diagnostics.py",
        "specs": KB_DIAGNOSTICS_SPECS,
        "description": "Admin-Tool zur Diagnose von kb-sync, Qdrant Collections und Knowledgebase-Dateien.",
        "version": "0.1.0",
    },
    "kahle_tasks_admin": {
        "name": "KAHLE Tasks Admin",
        "path": TOOLS_DIR / "kahle_tasks_admin.py",
        "specs": KAHLE_TASK_ADMIN_SPECS,
        "description": "Admin-Diagnose fuer die zentrale KAHLE-Vinci Aufgaben-Datenbank.",
        "version": "0.1.0",
    },
}

FUNCTION_DEFINITIONS = {
    "kahle_toolcall_guard": {
        "name": "KAHLE Toolcall Guard",
        "path": FUNCTIONS_DIR / "kahle_toolcall_guard.py",
        "type": "filter",
        "description": "Outlet-Filter gegen sichtbare Pseudo-Toolcalls bei Datei-Erstellung.",
        "version": "0.1.0",
        "is_global": 1,
    },
}


def load_json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def register_tool(con: sqlite3.Connection, tool_id: str, definition: dict[str, Any], now: int) -> None:
    path = definition["path"]
    if not path.exists():
        raise FileNotFoundError(f"tool file not found: {path}")
    content = path.read_text(encoding="utf-8")
    existing = con.execute("select created_at from tool where id = ?", (tool_id,)).fetchone()
    created_at = int(existing["created_at"]) if existing else now
    meta = {
        "description": definition["description"],
        "manifest": {
            "title": definition["name"],
            "author": "local",
            "version": definition["version"],
            "description": definition["description"],
        },
    }
    con.execute(
        """
        insert into tool (id, user_id, name, content, specs, meta, created_at, updated_at, valves)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(id) do update set
            name = excluded.name,
            content = excluded.content,
            specs = excluded.specs,
            meta = excluded.meta,
            updated_at = excluded.updated_at
        """,
        (
            tool_id,
            "system",
            definition["name"],
            content,
            json.dumps(definition["specs"], ensure_ascii=False),
            json.dumps(meta, ensure_ascii=False),
            created_at,
            now,
            "{}",
        ),
    )


def register_function(con: sqlite3.Connection, function_id: str, definition: dict[str, Any], now: int) -> None:
    path = definition["path"]
    if not path.exists():
        raise FileNotFoundError(f"function file not found: {path}")
    content = path.read_text(encoding="utf-8")
    existing = con.execute("select created_at from function where id = ?", (function_id,)).fetchone()
    created_at = int(existing["created_at"]) if existing else now
    meta = {
        "description": definition["description"],
        "manifest": {
            "title": definition["name"],
            "author": "local",
            "version": definition["version"],
            "description": definition["description"],
        },
    }
    con.execute(
        """
        insert into function (id, user_id, name, type, content, meta, created_at, updated_at, valves, is_active, is_global)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        on conflict(id) do update set
            name = excluded.name,
            type = excluded.type,
            content = excluded.content,
            meta = excluded.meta,
            updated_at = excluded.updated_at,
            is_active = 1,
            is_global = excluded.is_global
        """,
        (
            function_id,
            "system",
            definition["name"],
            definition["type"],
            content,
            json.dumps(meta, ensure_ascii=False),
            created_at,
            now,
            "{}",
            int(definition.get("is_global", 0)),
        ),
    )


def table_exists(con: sqlite3.Connection, table_name: str) -> bool:
    return con.execute(
        "select 1 from sqlite_master where type = 'table' and name = ?",
        (table_name,),
    ).fetchone() is not None


def grant_public_read(con: sqlite3.Connection, resource_type: str, resource_id: str, now: int) -> None:
    if not table_exists(con, "access_grant"):
        return
    con.execute(
        """
        insert or ignore into access_grant
            (id, resource_type, resource_id, principal_type, principal_id, permission, created_at)
        values (?, ?, ?, 'user', '*', 'read', ?)
        """,
        (str(uuid.uuid4()), resource_type, resource_id, now),
    )


def set_model_tools(con: sqlite3.Connection, model_id: str, tool_ids: list[str], now: int, prompt_path: Path | None = None) -> bool:
    row = con.execute("select meta, params from model where id = ?", (model_id,)).fetchone()
    if not row:
        return False
    meta = load_json(row["meta"], {})
    existing_tool_ids = [item for item in list(meta.get("toolIds") or []) if item not in tool_ids]
    meta["toolIds"] = tool_ids + existing_tool_ids
    params = load_json(row["params"], {})
    if prompt_path and prompt_path.exists():
        params["system"] = prompt_path.read_text(encoding="utf-8")
    params.pop("function_calling", None)
    con.execute(
        "update model set meta = ?, params = ?, updated_at = ? where id = ?",
        (json.dumps(meta, ensure_ascii=False), json.dumps(params, ensure_ascii=False), now, model_id),
    )
    return True


def ensure_admin_model(con: sqlite3.Connection, now: int) -> None:
    existing = con.execute("select id from model where id = ?", (ADMIN_MODEL_ID,)).fetchone()
    prompt_path = PROMPTS_DIR / "kahle-vinci-admin-systemprompt.md"
    prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
    if existing:
        row = con.execute("select meta, params from model where id = ?", (ADMIN_MODEL_ID,)).fetchone()
        meta = load_json(row["meta"], {})
        params = load_json(row["params"], {})
    else:
        base = con.execute("select meta, params from model where id = ?", ("vinci-2-clone-clone-clone",)).fetchone()
        meta = load_json(base["meta"], {}) if base else {}
        params = load_json(base["params"], {}) if base else {}

    meta["description"] = "Admin-Modell fuer Knowledgebase-, Qdrant- und kb-sync-Diagnose."
    meta["toolIds"] = ["kb_diagnostics", "kahle_tasks_admin"]
    meta["capabilities"] = {
        "vision": False,
        "file_upload": False,
        "web_search": False,
        "image_generation": False,
        "code_interpreter": False,
    }
    meta["hidden"] = False
    params["system"] = prompt
    params.pop("function_calling", None)

    if existing:
        con.execute(
            "update model set name = ?, base_model_id = ?, meta = ?, params = ?, updated_at = ?, is_active = 1 where id = ?",
            (
                "KAHLE-Vinci Admin",
                ADMIN_BASE_MODEL_ID,
                json.dumps(meta, ensure_ascii=False),
                json.dumps(params, ensure_ascii=False),
                now,
                ADMIN_MODEL_ID,
            ),
        )
    else:
        con.execute(
            """
            insert into model (id, user_id, base_model_id, name, meta, params, created_at, updated_at, is_active)
            values (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                ADMIN_MODEL_ID,
                "system",
                ADMIN_BASE_MODEL_ID,
                "KAHLE-Vinci Admin",
                json.dumps(meta, ensure_ascii=False),
                json.dumps(params, ensure_ascii=False),
                now,
                now,
            ),
        )


def update_tools_function_calling_prompt(con: sqlite3.Connection) -> bool:
    row = con.execute("select data from config where id = 1").fetchone()
    if not row:
        return False
    data = load_json(row["data"], {})
    if not isinstance(data, dict):
        return False

    task = data.setdefault("task", {})
    if not isinstance(task, dict):
        data["task"] = task = {}
    tools = task.setdefault("tools", {})
    if not isinstance(tools, dict):
        task["tools"] = tools = {}

    tools["prompt_template"] = TOOLS_FUNCTION_CALLING_PROMPT
    con.execute("update config set data = ?, updated_at = ? where id = 1", (json.dumps(data, ensure_ascii=False), time.strftime("%Y-%m-%dT%H:%M:%S")))
    return True


def main() -> int:
    if not DB_PATH.exists():
        print(f"ERROR: OpenWebUI DB not found: {DB_PATH}", file=sys.stderr)
        return 2

    now = int(time.time())
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    has_access_grant = False
    tools_prompt_updated = False
    try:
        has_access_grant = table_exists(con, "access_grant")
        for tool_id, definition in TOOL_DEFINITIONS.items():
            register_tool(con, tool_id, definition, now)
        for function_id, definition in FUNCTION_DEFINITIONS.items():
            register_function(con, function_id, definition, now)

        prompts = {
            "vinci-2-clone-clone-clone": PROMPTS_DIR / "kahle-vinci-systemprompt.md",
            "kahle-vinci-thinking": PROMPTS_DIR / "kahle-vinci-thinking-systemprompt.md",
        }
        for model_id in KAHLE_VINCI_MODEL_IDS:
            if not set_model_tools(con, model_id, ["kahle_tasks", "kahle_workflow"], now, prompts.get(model_id)):
                print(f"WARN: model not found: {model_id}")

        ensure_admin_model(con, now)
        tools_prompt_updated = update_tools_function_calling_prompt(con)

        for model_id in PUBLIC_MODEL_IDS:
            if con.execute("select 1 from model where id = ?", (model_id,)).fetchone():
                grant_public_read(con, "model", model_id, now)
            else:
                print(f"WARN: public model grant skipped, model not found: {model_id}")

        for tool_id in PUBLIC_TOOL_IDS:
            if con.execute("select 1 from tool where id = ?", (tool_id,)).fetchone():
                grant_public_read(con, "tool", tool_id, now)
            else:
                print(f"WARN: public tool grant skipped, tool not found: {tool_id}")

        con.commit()
    finally:
        con.close()

    print("Registered KAHLE tools: " + ", ".join(TOOL_DEFINITIONS))
    print("Registered KAHLE functions: " + ", ".join(FUNCTION_DEFINITIONS))
    print(f"Attached kahle_tasks/kahle_workflow to {', '.join(KAHLE_VINCI_MODEL_IDS)}")
    print(f"Ensured admin model: {ADMIN_MODEL_ID}")
    if tools_prompt_updated:
        print("Updated global tools function-calling prompt")
    if has_access_grant:
        print("Ensured public read grants for KAHLE user models, base models and standard tools")
    else:
        print("Skipped public read grants because access_grant table is not present in this OpenWebUI schema")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Register KAHLE Welle-1 Vinci models in the OpenWebUI SQLite database.

Run inside the OpenWebUI container. The script reads prompt files from
PROMPTS_DIR and upserts model rows plus group access grants.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path


DB_PATH = Path(os.getenv("OWUI_DB_PATH", "/app/backend/data/webui.db"))
PROMPTS_DIR = Path(os.getenv("PROMPTS_DIR", "/tmp/kahle-vinci-prompts"))
OWNER_USER_ID = os.getenv("VINCI_OWNER_USER_ID", "4f4b8ca2-8fc8-412c-a369-25f771e92aeb")
BASE_MODEL_ID = os.getenv("VINCI_BASE_MODEL_ID", "mistralai/Mistral-Small-24B-Instruct")


GROUP = {
    "verkauf": "Verkauf",
    "service_werkstatt": "Service & Werkstatt",
    "teiledienst": "Teiledienst",
    "dispo_buchhaltung": "Dispo/Buchhaltung",
    "marketing": "Marketing",
    "hr": "Personalwesen (HR)",
    "gl": "Gesch\u00e4ftsleitung",
    "ai_pilot": "AI-Pilot",
}


ALL_ACTIVE_GROUP_KEYS = [
    "verkauf",
    "service_werkstatt",
    "teiledienst",
    "dispo_buchhaltung",
    "marketing",
    "hr",
    "gl",
    "ai_pilot",
]


def suggestions(*items: tuple[str, str, str]) -> list[dict]:
    return [{"title": [title, subtitle], "content": content} for title, subtitle, content in items]


MODELS = [
    {
        "id": "kahle-email-vinci",
        "name": "KAHLE-Mailer",
        "file": "kahle-email-vinci-systemprompt.md",
        "description": "Spezialisierter Vinci fuer KAHLE-Mailentwuerfe aus Kundenmails, Stichpunkten und internen Notizen.",
        "groups": ALL_ACTIVE_GROUP_KEYS,
        "tool_ids": ["rag_chat", "zeit_berechnung", "server:doc-worker"],
        "knowledge_collections": ["kahleallgemein", "kahlekontext", "kahlerichtlinien"],
        "temperature": 0.2,
        "tags": ["KAHLE", "Vinci", "E-Mail"],
        "suggestions": suggestions(
            ("Kundenmail beantworten", "Sie-Form, KAHLE-Stil", "Ich moechte eine Kundenmail beantworten. Bitte frage mich jetzt nach der Kundenmail und erstelle noch keinen Entwurf."),
            ("Mail aus Stichpunkten", "klar und verbindlich", "Ich moechte aus Stichpunkten eine E-Mail erstellen. Bitte frage mich jetzt nach den Stichpunkten und erstelle noch keinen Entwurf."),
            ("Entwurf verbessern", "kuerzer und klarer", "Ich moechte einen Mailentwurf verbessern. Bitte frage mich jetzt nach dem Entwurf und erstelle noch keinen neuen Text."),
        ),
    },
    {
        "id": "kahle-newsletter-vinci",
        "name": "KAHLE Newsletter Vinci",
        "file": "kahle-newsletter-vinci-systemprompt.md",
        "description": "Spezialisierter Vinci fuer Newsletter-Struktur, Betreff, Preheader und KAHLE-konforme Marketingtexte.",
        "groups": ["marketing", "verkauf", "gl", "ai_pilot"],
        "tool_ids": ["rag_chat", "safe_webcaller", "server:doc-worker"],
        "knowledge_collections": ["kahleallgemein", "kahlekontext"],
        "temperature": 0.35,
        "tags": ["KAHLE", "Vinci", "Newsletter", "Marketing"],
        "suggestions": suggestions(
            ("Newsletter erstellen", "Zielgruppe und CTA", "Ich moechte einen Newsletter erstellen. Bitte frage mich jetzt nach Thema, Zielgruppe, Ziel und CTA und erstelle noch keinen Entwurf."),
            ("Angebot strukturieren", "Betreff bis CTA", "Ich moechte ein Angebot als Newsletter strukturieren. Bitte frage mich jetzt nach dem Angebot und erstelle noch keinen Entwurf."),
            ("Betreff verbessern", "klar und klickstark", "Ich moechte Newsletter-Betreff und Preheader verbessern. Bitte frage mich jetzt nach Betreff, Preheader und Kontext."),
        ),
    },
    {
        "id": "kahle-serviceberater-vinci",
        "name": "KAHLE Serviceberater Vinci",
        "file": "kahle-serviceberater-vinci-systemprompt.md",
        "description": "Spezialisierter Vinci fuer kundenverstaendliche Service-, Reparatur- und Wartungserklaerungen.",
        "groups": ["service_werkstatt", "gl", "ai_pilot"],
        "tool_ids": ["rag_chat", "zeit_berechnung", "server:doc-worker"],
        "knowledge_collections": ["kahleallgemein", "kahlekontext", "kahlerichtlinien"],
        "temperature": 0.15,
        "tags": ["KAHLE", "Vinci", "Service"],
        "suggestions": suggestions(
            ("Reparatur erklaeren", "kundenverstaendlich", "Ich moechte eine Reparaturposition kundenverstaendlich erklaeren. Bitte frage mich jetzt nach der Reparaturposition und erstelle noch keinen Entwurf."),
            ("Serviceantwort", "ruhig und klar", "Ich moechte eine Servicefrage beantworten. Bitte frage mich jetzt nach der Servicefrage und erstelle noch keinen Entwurf."),
            ("Freigabe anfragen", "naechster Schritt", "Ich moechte eine Reparaturfreigabe anfragen. Bitte frage mich jetzt nach den Freigabeinfos und erstelle noch keinen Entwurf."),
        ),
    },
    {
        "id": "kahle-angebotsmail-vinci",
        "name": "KAHLE Angebotsmail Vinci",
        "file": "kahle-angebotsmail-vinci-systemprompt.md",
        "description": "Spezialisierter Vinci fuer vertriebliche Angebotsmails aus Fahrzeugdaten und Kundensituation.",
        "groups": ["verkauf", "gl", "ai_pilot"],
        "tool_ids": ["rag_chat", "zeit_berechnung", "server:doc-worker"],
        "knowledge_collections": ["kahleallgemein", "kahlekontext"],
        "temperature": 0.25,
        "tags": ["KAHLE", "Vinci", "Vertrieb", "Angebot"],
        "suggestions": suggestions(
            ("Angebotsmail", "Fahrzeug und CTA", "Ich moechte eine Angebotsmail erstellen. Bitte frage mich jetzt nach Fahrzeug, Angebotsdaten, Kundensituation und CTA und erstelle noch keinen Entwurf."),
            ("Probefahrt anbieten", "naechster Schritt", "Ich moechte eine Angebotsmail mit Probefahrt-CTA erstellen. Bitte frage mich jetzt nach Fahrzeug, Angebot und Terminwunsch."),
            ("Einwand aufnehmen", "sachlich verkaufen", "Ich moechte eine Angebotsmail mit Kundeneinwand erstellen. Bitte frage mich jetzt nach Angebot, Einwand und gewuenschtem naechsten Schritt."),
        ),
    },
    {
        "id": "kahle-beschwerde-vinci",
        "name": "KAHLE Beschwerde Vinci",
        "file": "kahle-beschwerde-vinci-systemprompt.md",
        "description": "Spezialisierter Vinci fuer empathische und rechtlich vorsichtige Beschwerdeantworten.",
        "groups": ["verkauf", "service_werkstatt", "gl", "ai_pilot"],
        "tool_ids": ["rag_chat", "server:doc-worker"],
        "knowledge_collections": ["kahleallgemein", "kahlekontext", "kahlerichtlinien"],
        "temperature": 0.15,
        "tags": ["KAHLE", "Vinci", "Beschwerde"],
        "suggestions": suggestions(
            ("Beschwerde beantworten", "vorsichtig und empathisch", "Ich moechte eine Beschwerde beantworten. Bitte frage mich jetzt nach Beschwerdetext und bekanntem Sachverhalt und erstelle noch keinen Entwurf."),
            ("Eskalation einordnen", "Risiko und Antwort", "Ich moechte eine Beschwerde einordnen. Bitte frage mich jetzt nach Beschwerde, Sachstand und Eskalationshinweisen."),
            ("Antwort entschaerfen", "ohne Schuldanerkenntnis", "Ich moechte einen Beschwerdeentwurf vorsichtiger formulieren. Bitte frage mich jetzt nach dem Entwurf."),
        ),
    },
    {
        "id": "kahle-onboarding-vinci",
        "name": "KAHLE Onboarding Vinci",
        "file": "kahle-onboarding-vinci-systemprompt.md",
        "description": "Spezialisierter Vinci fuer Onboarding-Checklisten, Begruessungstexte und Aufgabenplaene.",
        "groups": ["hr", "gl", "ai_pilot"],
        "tool_ids": ["rag_chat", "zeit_berechnung", "kahle_tasks", "server:doc-worker"],
        "knowledge_collections": ["kahleallgemein", "kahlekontext", "kahlerichtlinien"],
        "temperature": 0.15,
        "tags": ["KAHLE", "Vinci", "HR", "Onboarding"],
        "suggestions": suggestions(
            ("Checkliste erstellen", "Rolle, Standort, Start", "Ich moechte eine Onboarding-Checkliste erstellen. Bitte frage mich jetzt nach Rolle, Standort und Startdatum."),
            ("Begruessungsmail", "intern und freundlich", "Ich moechte eine Begruessungsmail fuer neue Mitarbeitende schreiben. Bitte frage mich jetzt nach Rolle, Standort, Startdatum und Empfaenger."),
            ("Aufgabenplan", "HR, IT, Empfang", "Ich moechte einen Aufgabenplan fuer ein Onboarding erstellen. Bitte frage mich jetzt nach Rolle, Standort, Startdatum und beteiligten Bereichen."),
        ),
    },
    {
        "id": "kahle-werkstatt-tagesbriefing-vinci",
        "name": "KAHLE Werkstatt Tagesbriefing Vinci",
        "file": "kahle-werkstatt-tagesbriefing-vinci-systemprompt.md",
        "description": "Spezialisierter Vinci fuer interne Werkstatt-Tagesbriefings aus Terminen, Notizen und Engpaessen.",
        "groups": ["service_werkstatt", "teiledienst", "dispo_buchhaltung", "gl", "ai_pilot"],
        "tool_ids": ["rag_chat", "zeit_berechnung", "server:doc-worker"],
        "knowledge_collections": ["kahleallgemein", "kahlekontext"],
        "temperature": 0.1,
        "tags": ["KAHLE", "Vinci", "Werkstatt", "Tagesbriefing"],
        "suggestions": suggestions(
            ("Tagesbriefing", "Termine und Risiken", "Ich moechte ein Werkstatt-Tagesbriefing erstellen. Bitte frage mich jetzt nach Datum, Standort, Terminliste und Risiken."),
            ("Engpaesse sortieren", "Prioritaeten", "Ich moechte Werkstatt- und Teilethemen priorisieren. Bitte frage mich jetzt nach den Themen, Engpaessen und Dringlichkeiten."),
            ("Servicehinweise", "fuer Empfang/Service", "Ich moechte Hinweise fuer Service und Empfang formulieren. Bitte frage mich jetzt nach der Lage und den betroffenen Faellen."),
        ),
    },
    {
        "id": "kahle-richtlinien-vinci",
        "name": "KAHLE Richtlinien Vinci",
        "file": "kahle-richtlinien-vinci-systemprompt.md",
        "description": "Streng quellengebundener Vinci fuer interne KAHLE-Richtlinien, Arbeitsanweisungen und KI-/Datenschutzregeln.",
        "groups": ALL_ACTIVE_GROUP_KEYS,
        "tool_ids": ["rag_chat", "server:doc-worker"],
        "knowledge_collections": ["kahlerichtlinien"],
        "temperature": 0.0,
        "tags": ["KAHLE", "Vinci", "Richtlinien"],
        "suggestions": suggestions(
            ("Richtlinie pruefen", "nur internes Wissen", "Ich moechte eine interne KAHLE-Richtlinie pruefen. Bitte frage mich jetzt nach dem konkreten Richtlinien- oder Prozessthema."),
            ("Prozessfrage", "Quelle nennen", "Ich moechte wissen, wie ein Prozess bei KAHLE geregelt ist. Bitte frage mich jetzt nach dem konkreten Prozess."),
            ("KI-Regel", "Compliance", "Ich moechte eine interne KI-Regel pruefen. Bitte frage mich jetzt nach dem konkreten KI- oder Compliance-Thema."),
        ),
    },
]


def now_ts() -> int:
    return int(time.time())


def read_prompt(file_name: str) -> str:
    path = PROMPTS_DIR / file_name
    if not path.exists():
        raise FileNotFoundError(f"Prompt file missing: {path}")
    return path.read_text(encoding="utf-8")


def load_group_ids(con: sqlite3.Connection) -> dict[str, str]:
    rows = con.execute('select id, name from "group"').fetchall()
    by_name = {row["name"]: row["id"] for row in rows}
    result: dict[str, str] = {}
    for key, name in GROUP.items():
        if name not in by_name:
            raise RuntimeError(f"OpenWebUI group not found: {name}")
        result[key] = by_name[name]
    return result


def make_meta(model: dict) -> dict:
    web_search = "safe_webcaller" in model["tool_ids"]
    return {
        "profile_image_url": "/static/favicon.png",
        "description": model["description"],
        "capabilities": {
            "file_context": True,
            "vision": False,
            "file_upload": True,
            "web_search": web_search,
            "image_generation": False,
            "code_interpreter": False,
            "terminal": False,
            "citations": True,
            "status_updates": True,
            "builtin_tools": True,
        },
        "suggestion_prompts": model["suggestions"],
        "tags": model["tags"],
        "toolIds": model["tool_ids"],
        "knowledge": [
            {
                "name": f"KAHLE RAG: {', '.join(model['knowledge_collections'])}",
                "type": "collection",
                "collection_names": model["knowledge_collections"],
                "legacy": True,
            }
        ],
        "kahleKnowledgeNote": "Primaere Wissensnutzung ueber RAG_Chat/kb-sync/Qdrant; OpenWebUI file context ist global deaktiviert.",
        "defaultFeatureIds": [],
        "builtinTools": {
            "memory": False,
            "notes": False,
            "knowledge": False,
            "channels": False,
            "web_search": False,
            "tasks": False,
            "automations": False,
            "calendar": False,
            "chats": False,
        },
        "hidden": False,
    }


def make_params(model: dict, system_prompt: str) -> dict:
    return {
        "system": system_prompt,
        "temperature": model["temperature"],
        "top_p": 0.85,
        "frequency_penalty": 0.2,
        "presence_penalty": 0.0,
        "max_tokens": 4096,
        "stream_delta_chunk_size": 4,
    }


def backup_db(con: sqlite3.Connection) -> Path:
    backup_path = DB_PATH.with_name(f"webui.db.before_vinci_models_{time.strftime('%Y%m%d_%H%M%S')}")
    dest = sqlite3.connect(str(backup_path))
    try:
        con.backup(dest)
    finally:
        dest.close()
    return backup_path


def upsert_model(con: sqlite3.Connection, model: dict) -> None:
    timestamp = now_ts()
    system_prompt = read_prompt(model["file"])
    meta = make_meta(model)
    params = make_params(model, system_prompt)
    con.execute(
        """
        insert into model (id, user_id, base_model_id, name, meta, params, created_at, updated_at, is_active)
        values (?, ?, ?, ?, ?, ?, ?, ?, 1)
        on conflict(id) do update set
            user_id=excluded.user_id,
            base_model_id=excluded.base_model_id,
            name=excluded.name,
            meta=excluded.meta,
            params=excluded.params,
            updated_at=excluded.updated_at,
            is_active=1
        """,
        (
            model["id"],
            OWNER_USER_ID,
            BASE_MODEL_ID,
            model["name"],
            json.dumps(meta, ensure_ascii=False),
            json.dumps(params, ensure_ascii=False),
            timestamp,
            timestamp,
        ),
    )


def replace_model_grants(con: sqlite3.Connection, model: dict, group_ids: dict[str, str]) -> None:
    con.execute(
        "delete from access_grant where resource_type='model' and resource_id=?",
        (model["id"],),
    )
    timestamp = now_ts()
    for group_key in model["groups"]:
        con.execute(
            """
            insert into access_grant
              (id, resource_type, resource_id, principal_type, principal_id, permission, created_at)
            values (?, 'model', ?, 'group', ?, 'read', ?)
            """,
            (str(uuid.uuid4()), model["id"], group_ids[group_key], timestamp),
        )


def main() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(DB_PATH)
    if not PROMPTS_DIR.exists():
        raise FileNotFoundError(PROMPTS_DIR)

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        backup_path = backup_db(con)
        group_ids = load_group_ids(con)
        for model in MODELS:
            upsert_model(con, model)
            replace_model_grants(con, model, group_ids)
        con.commit()
        print(json.dumps({"ok": True, "backup": str(backup_path), "models": [m["id"] for m in MODELS]}, ensure_ascii=False))
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == "__main__":
    main()

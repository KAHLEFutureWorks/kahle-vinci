#!/usr/bin/env python3
"""Unit checks for the KAHLE outlet guard filter."""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FILTER_PATH = ROOT / "open-webui-functions" / "kahle_toolcall_guard.py"


def load_module():
    spec = importlib.util.spec_from_file_location("kahle_toolcall_guard", FILTER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_visible_workflow_pseudo_call_is_replaced_with_download_metadata():
    module = load_module()
    original_create = module._create_file
    try:
        captured = {}

        def fake_create(content, output_format, filename):
            captured["content"] = content
            captured["output_format"] = output_format
            captured["filename"] = filename
            return {
                "download_url": "http://localhost:8091/files/download?token=test",
                "filename": "recherche.pdf",
                "sha256": "abc",
                "size_bytes": 123,
            }

        module._create_file = fake_create
        body = {
            "messages": [
                {"role": "user", "content": "Recherchiere zum Iran Krieg"},
                {"role": "assistant", "content": "# Recherche\n\nIran-Kontext."},
                {"role": "user", "content": "Bitte gib mir das Ergebnis als PDF aus"},
                {
                    "role": "assistant",
                    "content": '[TOOL_CALLS]kahle_workflow_execute{"output_format":"pdf","content":"ignored"}',
                },
            ]
        }

        result = module.Filter().outlet(body)
        content = result["messages"][-1]["content"]

        assert "Download-Link: [Datei herunterladen]" in content
        assert "SHA256: abc" in content
        assert captured["content"] == "# Recherche\n\nIran-Kontext."
        assert captured["output_format"] == "pdf"
        assert captured["filename"].endswith(".pdf")
    finally:
        module._create_file = original_create


def test_download_replacement_updates_output_text_as_well_as_content():
    module = load_module()
    original_create = module._create_file
    try:
        module._create_file = lambda content, output_format, filename: {
            "download_url": "http://localhost:8091/files/download?token=test",
            "filename": filename,
            "sha256": "abc",
            "size_bytes": 123,
        }
        body = {
            "messages": [
                {"role": "user", "content": "Recherchiere Prof4Net"},
                {"role": "assistant", "content": "# Recherche\n\nProf4Net Kontext."},
                {"role": "user", "content": "Bitte gib mir das Ergebnis einmal strukturiert als Word aus"},
                {
                    "role": "assistant",
                    "content": '[TOOL_CALLS]kahle_workflow_execute{"output_format":"docx","content":"ignored"}',
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": '[TOOL_CALLS]kahle_workflow_execute{"output_format":"docx","content":"ignored"}',
                                }
                            ],
                        }
                    ],
                },
            ]
        }

        result = module.Filter().outlet(body)
        message = result["messages"][-1]
        output_text = message["output"][0]["content"][0]["text"]

        assert "Download-Link: [Datei herunterladen]" in message["content"]
        assert output_text == message["content"]
        assert "[TOOL_CALLS]" not in output_text
    finally:
        module._create_file = original_create


def test_pseudo_call_with_prefix_still_uses_previous_assistant_result():
    module = load_module()
    original_create = module._create_file
    try:
        captured = {}

        def fake_create(content, output_format, filename):
            captured["content"] = content
            return {
                "download_url": "http://localhost:8091/files/download?token=test",
                "filename": "recherche.pdf",
                "sha256": "abc",
                "size_bytes": 123,
            }

        module._create_file = fake_create
        body = {
            "messages": [
                {"role": "user", "content": "Recherchiere zum Iran Krieg"},
                {"role": "assistant", "content": "# Recherche\n\nVollstaendiger Recherchetext."},
                {"role": "user", "content": "Bitte gib mir das Ergebnis als PDF aus"},
                {
                    "role": "assistant",
                    "content": 'Ich werde das Ergebnis als PDF speichern.[TOOL_CALLS]kahle_workflow_execute{"output_format":"pdf","content":"Nur Kurzsatz"}',
                },
            ]
        }

        module.Filter().outlet(body)

        assert captured["content"] == "# Recherche\n\nVollstaendiger Recherchetext."
    finally:
        module._create_file = original_create


def test_pseudo_call_without_previous_result_uses_embedded_content():
    module = load_module()
    original_create = module._create_file
    try:
        captured = {}

        def fake_create(content, output_format, filename):
            captured["content"] = content
            return {
                "download_url": "http://localhost:8091/files/download?token=test",
                "filename": "recherche.pdf",
                "sha256": "abc",
                "size_bytes": 123,
            }

        module._create_file = fake_create
        body = {
            "messages": [
                {"role": "user", "content": "Recherchiere und gib PDF aus"},
                {
                    "role": "assistant",
                    "content": '[TOOL_CALLS]kahle_workflow_execute{"output_format":"pdf","content":"# Recherche\\n\\nEingebetteter Inhalt"}',
                },
            ]
        }

        module.Filter().outlet(body)

        assert "Eingebetteter Inhalt" in captured["content"]
    finally:
        module._create_file = original_create


def test_file_request_without_toolcall_creates_requested_docx_from_answer():
    module = load_module()
    original_create = module._create_file
    try:
        captured = {}

        def fake_create(content, output_format, filename):
            captured["content"] = content
            captured["output_format"] = output_format
            captured["filename"] = filename
            return {
                "download_url": "http://localhost:8091/files/download?token=test",
                "filename": filename,
                "sha256": "abc",
                "size_bytes": 123,
            }

        module._create_file = fake_create
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": "Bitte recherchiere, welche Sorten es von Pesto von Barilla gibt. Gib das Ganze als Worddatei aus.",
                },
                {
                    "role": "assistant",
                    "content": (
                        "Hier ist die Liste der Pesto-Sorten von Barilla:\n\n"
                        "- Pesto Rosso\n"
                        "- Pesto alla Genovese\n"
                        "- Pesto Calabrese\n\n"
                        "Ich werde nun eine Word-Datei mit dieser Liste erstellen. Bitte einen Moment Geduld."
                    ),
                },
            ]
        }

        result = module.Filter().outlet(body)

        assert "Download-Link: [Datei herunterladen]" in result["messages"][-1]["content"]
        assert captured["output_format"] == "docx"
        assert captured["filename"].endswith(".docx")
        assert "Pesto Rosso" in captured["content"]
        assert "Ich werde nun" not in captured["content"]
    finally:
        module._create_file = original_create


def test_generic_pseudo_toolcall_creates_requested_docx_from_previous_answer():
    module = load_module()
    original_create = module._create_file
    try:
        captured = {}

        def fake_create(content, output_format, filename):
            captured["content"] = content
            captured["output_format"] = output_format
            captured["filename"] = filename
            return {
                "download_url": "http://localhost:8091/files/download?token=test",
                "filename": filename,
                "sha256": "abc",
                "size_bytes": 123,
            }

        module._create_file = fake_create
        body = {
            "messages": [
                {"role": "user", "content": "Bitte recherchiere Barilla Pesto Sorten und gib es als Worddatei aus."},
                {"role": "assistant", "content": "# Pesto Barilla Sorten\n\n- Pesto Rosso\n- Pesto Basilico"},
                {"role": "user", "content": "Bitte jetzt als Worddatei zum Download."},
                {"role": "assistant", "content": "Ich werde die Informationen in eine Worddatei umwandeln.[TOOL_CALLS]pptx"},
            ]
        }

        result = module.Filter().outlet(body)

        assert "Download-Link: [Datei herunterladen]" in result["messages"][-1]["content"]
        assert captured["output_format"] == "docx"
        assert "Pesto Barilla Sorten" in captured["content"]
    finally:
        module._create_file = original_create


def test_hallucinated_file_link_metadata_creates_real_docx_from_previous_result():
    module = load_module()
    original_create = module._create_file
    try:
        captured = {}

        def fake_create(content, output_format, filename):
            captured["content"] = content
            captured["output_format"] = output_format
            captured["filename"] = filename
            return {
                "download_url": "http://localhost:8091/files/download?token=real",
                "filename": filename,
                "sha256": "real-sha",
                "size_bytes": 456,
            }

        module._create_file = fake_create
        body = {
            "messages": [
                {"role": "user", "content": "Bitte recherchiere einmal zu der Firma mobilapp"},
                {"role": "assistant", "content": "# mobilApp GmbH\n\nmobilApp entwickelt digitale Autohaus-Loesungen."},
                {
                    "role": "user",
                    "content": "Bitte strukturiere einmal das Ergebnis passend fuer eine Word Datei und gib mir das dann als Word zum download",
                },
                {
                    "role": "assistant",
                    "content": (
                        "Ich habe die Informationen als Word-Dokument gespeichert.\n\n"
                        "[Datei herunterladen](file=tmp_download_mobilapp_gmbh.docx)\n"
                        "Datei: mobilapp_gmbh.docx\n"
                        "SHA256: 4a1d55df490362772956354f01b19f82708865dca1aa6e1551ad45d402f6439a\n"
                        "Groesse: 12345 Bytes"
                    ),
                },
            ]
        }

        result = module.Filter().outlet(body)
        content = result["messages"][-1]["content"]

        assert "http://localhost:8091/files/download?token=real" in content
        assert "file=tmp_download_mobilapp_gmbh.docx" not in content
        assert captured["output_format"] == "docx"
        assert captured["filename"].endswith(".docx")
        assert "mobilApp entwickelt digitale Autohaus-Loesungen" in captured["content"]
    finally:
        module._create_file = original_create


def test_hallucinated_sandbox_download_link_creates_real_docx_from_previous_result():
    module = load_module()
    original_create = module._create_file
    try:
        captured = {}

        def fake_create(content, output_format, filename):
            captured["content"] = content
            captured["output_format"] = output_format
            captured["filename"] = filename
            return {
                "download_url": "http://localhost:8091/files/download?token=real-sandbox-replacement",
                "filename": filename,
                "sha256": "real-sha",
                "size_bytes": 456,
            }

        module._create_file = fake_create
        body = {
            "messages": [
                {"role": "user", "content": "Bitte recherchiere einmal ueber die Firma Prof4net"},
                {"role": "assistant", "content": "# Prof4Net GmbH\n\nProf4Net ist ein IT-Dienstleister."},
                {
                    "role": "user",
                    "content": "Bitte strukturiere einmal das Ergebnis passend fuer eine Word Datei und gib mir das dann als Word zum download",
                },
                {
                    "role": "assistant",
                    "content": (
                        "**Download-Link**: [prof4net_unternehmensprofil.docx]"
                        "(sandbox:/files/download?token=01c755a7-98a4-4622-8772-52606831983a)\n"
                        "**Datei**: prof4net_unternehmensprofil.docx\n"
                        "**SHA256**: 5d41402abc4b2a76b9719d911017c592\n"
                        "**Groesse**: 12345 Bytes"
                    ),
                },
            ]
        }

        result = module.Filter().outlet(body)
        content = result["messages"][-1]["content"]

        assert "http://localhost:8091/files/download?token=real-sandbox-replacement" in content
        assert "sandbox:/files/download" not in content
        assert captured["output_format"] == "docx"
        assert captured["filename"].endswith(".docx")
        assert "Prof4Net ist ein IT-Dienstleister" in captured["content"]
    finally:
        module._create_file = original_create


def test_filename_from_unicode_escape_request_is_readable_ascii():
    module = load_module()

    filename = module._filename_from_request(
        r"Bitte einmal wie Spaghetti hergestellt werden, dann sortieren einer Art Erkl\u00e4rung Recherche als PDF",
        "pdf",
    )

    assert filename.endswith(".pdf")
    assert "u00" not in filename
    assert "erklaerung" in filename

    double_escaped = module._filename_from_request(
        r"Bitte erstelle eine Pesto_Erkl\\u00e4rung als Worddatei",
        "docx",
    )
    assert double_escaped.endswith(".docx")
    assert "u00" not in double_escaped
    assert "pesto_erklaerung" in double_escaped


def test_visible_workflow_pseudo_call_with_powerpoint_request_does_not_create_pptx():
    module = load_module()
    original_create = module._create_file
    try:
        captured = {}

        def fake_create(content, output_format, filename):
            captured["content"] = content
            captured["output_format"] = output_format
            captured["filename"] = filename
            return {
                "download_url": "http://localhost:8091/files/download?token=test",
                "filename": filename,
                "sha256": "abc",
                "size_bytes": 123,
            }

        module._create_file = fake_create
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": "Bitte recherchiere die wichtigsten Trends zu Elektromobilitaet 2026 in Deutschland und erstelle daraus eine kurze PowerPoint-Praesentation mit 5 Folien.",
                },
                {
                    "role": "assistant",
                    "content": '[TOOL_CALLS]kahle_workflow_execute{"modus":"external","ziel":"presentation_outline","output_format":"pptx","content":"# Elektromobilitaet 2026\\n\\n## Ladeinfrastruktur\\n\\n- Ausbau der Ladepunkte"}',
                },
            ]
        }

        result = module.Filter().outlet(body)

        assert "PowerPoint" in result["messages"][-1]["content"] or "PPTX" in result["messages"][-1]["content"]
        assert captured == {}
    finally:
        module._create_file = original_create


def test_task_list_request_is_replaced_with_exact_open_tasks_from_db():
    module = load_module()

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "tasks.db"
        con = sqlite3.connect(db_path)
        con.execute(
            """
            create table tasks (
                id text primary key,
                user_id text not null,
                title text not null,
                description text not null default '',
                status text not null default 'open',
                priority text not null default 'normal',
                due_date text not null default '',
                source_chat_id text not null default '',
                source_message_id text not null default '',
                created_at integer not null,
                updated_at integer not null,
                completed_at integer
            )
            """
        )
        con.execute(
            "insert into tasks values (?, ?, ?, '', 'open', 'high', '2026-05-12', '', '', 1778495659, 1778495659, null)",
            ("task_real", "user-1", "Rueckruf Kunde Mueller wegen Reifenangebot"),
        )
        con.commit()
        con.close()

        old = os.environ.get("KAHLE_TASKS_DB_PATH")
        os.environ["KAHLE_TASKS_DB_PATH"] = str(db_path)
        try:
            body = {
                "messages": [
                    {"role": "user", "content": "Liste einmal meine offenen Aufgaben auf"},
                    {
                        "role": "assistant",
                        "content": "Hier sind deine Aufgaben: 1. Rueckruf Kunde Mueller 2. Erfundene Aufgabe",
                    },
                ]
            }
            result = module.Filter().outlet(body, __user__={"id": "user-1"})
        finally:
            if old is None:
                os.environ.pop("KAHLE_TASKS_DB_PATH", None)
            else:
                os.environ["KAHLE_TASKS_DB_PATH"] = old

    content = result["messages"][-1]["content"]
    assert "task_real" in content
    assert "Rueckruf Kunde Mueller wegen Reifenangebot" in content
    assert "Erfundene Aufgabe" not in content


def test_safe_webcaller_pseudo_call_with_pdf_request_creates_file():
    module = load_module()
    original_create = module._create_file
    original_websearch = module._run_websearch
    try:
        captured = {}

        def fake_websearch(query, user_name=""):
            captured["query"] = query
            return {
                "ok": True,
                "summary": "KI bezeichnet Systeme, die Aufgaben ausfuehren, die sonst menschliche Intelligenz erfordern.",
                "sources": [{"title": "Quelle", "url": "https://example.test/ki", "snippet": "KI Grundlagen"}],
            }

        def fake_create(content, output_format, filename):
            captured["content"] = content
            captured["output_format"] = output_format
            captured["filename"] = filename
            return {
                "download_url": "http://localhost:8091/files/download?token=test",
                "filename": filename,
                "sha256": "abc",
                "size_bytes": 123,
            }

        module._run_websearch = fake_websearch
        module._create_file = fake_create
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": 'Bitte recherchiere einmal zu dem Thema KI und baue daraus einen Infotext mit dem Titel "Einfuehrung in die KI" und gib mir diesen Infotext als PDF aus',
                },
                {
                    "role": "assistant",
                    "content": '[TOOL_CALLS]safe_webcaller{"query":"KI Einfuehrung Grundlagen Anwendungen Ethik 2026"}',
                },
            ]
        }

        result = module.Filter().outlet(body)

        assert "Download-Link: [Datei herunterladen]" in result["messages"][-1]["content"]
        assert captured["output_format"] == "pdf"
        assert "# Einfuehrung in die KI" in captured["content"]
        assert "KI bezeichnet Systeme" in captured["content"]
    finally:
        module._create_file = original_create
        module._run_websearch = original_websearch


def test_safe_websearch_alias_pseudo_call_with_pdf_request_creates_file():
    module = load_module()
    original_create = module._create_file
    original_websearch = module._run_websearch
    try:
        captured = {}

        module._run_websearch = lambda query, user_name="": {
            "ok": True,
            "summary": "Alias-Websuche erfolgreich.",
            "sources": [],
        }

        def fake_create(content, output_format, filename):
            captured["output_format"] = output_format
            captured["content"] = content
            return {
                "download_url": "http://localhost:8091/files/download?token=test",
                "filename": filename,
                "sha256": "abc",
                "size_bytes": 123,
            }

        module._create_file = fake_create
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": "Bitte recherchiere zu KI und gib mir das Ergebnis als PDF aus.",
                },
                {
                    "role": "assistant",
                    "content": '[TOOL_CALLS]safe_websearch{"query":"KI Grundlagen 2026"}',
                },
            ]
        }

        result = module.Filter().outlet(body)

        assert "Download-Link: [Datei herunterladen]" in result["messages"][-1]["content"]
        assert captured["output_format"] == "pdf"
        assert "Alias-Websuche erfolgreich" in captured["content"]
    finally:
        module._create_file = original_create
        module._run_websearch = original_websearch


def test_workflow_pseudo_call_with_empty_embedded_content_runs_research_instead_of_blank_file():
    module = load_module()
    original_create = module._create_file
    original_websearch = module._run_websearch
    try:
        captured = {}

        module._run_websearch = lambda query, user_name="": {
            "ok": True,
            "summary": "Aktuelle KI-News fuer Autohaeuser: CRM-Automation, Service-Prozesse und EU-AI-Act bleiben relevant.",
            "sources": [{"title": "KI News", "url": "https://example.test/news", "snippet": "CRM und Service"}],
        }

        def fake_create(content, output_format, filename):
            captured["output_format"] = output_format
            captured["content"] = content
            return {
                "download_url": "http://localhost:8091/files/download?token=test",
                "filename": filename,
                "sha256": "abc",
                "size_bytes": 123,
            }

        module._create_file = fake_create
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": "Recherchiere aktuelle KI News fuer Autohaeuser in Deutschland und gib mir das Ergebnis als PDF aus.",
                },
                {
                    "role": "assistant",
                    "content": '[TOOL_CALLS]kahle_workflow_execute{"output_format":"pdf","content":"\\"\\""}',
                },
            ]
        }

        result = module.Filter().outlet(body)

        assert "Download-Link: [Datei herunterladen]" in result["messages"][-1]["content"]
        assert captured["output_format"] == "pdf"
        assert "Aktuelle KI-News fuer Autohaeuser" in captured["content"]
        assert captured["content"].strip() != '""'
    finally:
        module._create_file = original_create
        module._run_websearch = original_websearch


def test_invalid_download_token_is_recreated_from_previous_assistant_result():
    module = load_module()
    original_create = module._create_file
    try:
        captured = {}

        def fake_create(content, output_format, filename):
            captured["content"] = content
            captured["output_format"] = output_format
            return {
                "download_url": "http://localhost:8091/files/download?token=fixed",
                "filename": filename,
                "sha256": "abc",
                "size_bytes": 123,
            }

        module._create_file = fake_create
        body = {
            "messages": [
                {"role": "user", "content": "Bitte recherchiere einmal zur Firma Prof4Net"},
                {
                    "role": "assistant",
                    "content": "# Recherche\n\nProf4Net bietet CRM-Loesungen fuer Autohaeuser.",
                },
                {"role": "user", "content": "Bitte gib mir das Ergebnis einmal als Word aus"},
                {
                    "role": "assistant",
                    "content": (
                        "Hier ist das Ergebnis als Word-Dokument:\n\n"
                        "Download-Link: [Datei herunterladen](http://localhost:8091/files/download?token=abc)\n"
                        "Datei: einmal_aus.docx\nSHA256: broken\nGroesse: 28859 Bytes"
                    ),
                },
            ]
        }

        result = module.Filter().outlet(body)

        content = result["messages"][-1]["content"]
        assert "token=fixed" in content
        assert "token=abc" not in content
        assert captured["output_format"] == "docx"
        assert "Prof4Net bietet CRM-Loesungen" in captured["content"]
    finally:
        module._create_file = original_create


def test_bare_json_file_tool_call_is_replaced_with_download_metadata():
    module = load_module()
    original_call = module._call_file_proxy_tool
    try:
        captured = {}

        def fake_call(tool_name, params):
            captured["tool_name"] = tool_name
            captured["params"] = params
            return {
                "download_url": "http://localhost:8091/files/download?token=converted",
                "filename": "KAHLE_KI-Compliance_v1.2.docx",
                "sha256": "def",
                "size_bytes": 456,
            }

        module._call_file_proxy_tool = fake_call
        body = {
            "messages": [
                {"role": "user", "content": "Kannst du mir die angehaengte PDF bitte zu Markdown umwandeln?"},
                {
                    "role": "assistant",
                    "content": '{\n"tool": "file_to_md_save",\n"params": {"file_path": "KAHLE_KI-Compliance_v1.2.pdf"}\n}',
                },
            ]
        }

        result = module.Filter().outlet(body)

        assert "Download-Link: [Datei herunterladen]" in result["messages"][-1]["content"]
        assert captured["tool_name"] == "file_to_md_save"
        assert captured["params"]["file_path"] == "KAHLE_KI-Compliance_v1.2.pdf"
    finally:
        module._call_file_proxy_tool = original_call


def test_safe_webcaller_pseudo_call_without_file_request_returns_formatted_text():
    module = load_module()
    original_websearch = module._run_websearch
    try:
        module._run_websearch = lambda query, user_name="": {
            "ok": True,
            "summary": "KI Grundlagen Zusammenfassung.",
            "sources": [],
        }
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": 'Bitte recherchiere einmal zu dem Thema KI und baue daraus einen Infotext mit dem Titel "Einfuehrung in die KI"',
                },
                {
                    "role": "assistant",
                    "content": '[TOOL_CALLS]safe_webcaller{"query":"KI Einfuehrung Grundlagen Anwendungen Ethik 2026"}',
                },
            ]
        }

        result = module.Filter().outlet(body)

        assert "# Einfuehrung in die KI" in result["messages"][-1]["content"]
        assert "KI Grundlagen Zusammenfassung" in result["messages"][-1]["content"]
    finally:
        module._run_websearch = original_websearch


def test_kb_list_files_pseudo_call_is_replaced_with_file_inventory():
    module = load_module()
    original_call = module._call_kb_diagnostics_tool
    try:
        captured = {}

        def fake_call(tool_name, params):
            captured["tool_name"] = tool_name
            captured["params"] = params
            return {
                "ok": True,
                "collection": "kahlerichtlinien",
                "count": 2,
                "files": [
                    {"source_path": "Arbeitsanweisung_Datenpflege_VaudisX.md", "indexed": True},
                    {"source_path": "README_Dokumentation.md", "indexed": True},
                ],
                "collections": [
                    {
                        "collection": "kahlerichtlinien",
                        "count": 2,
                        "last_reconcile_at": "2026-05-20T10:00:03Z",
                        "issue_counts": {
                            "missing_in_qdrant": 0,
                            "orphan_in_qdrant": 0,
                            "missing_in_state": 0,
                            "state_without_file": 0,
                        },
                        "files": [
                            {"source_path": "Arbeitsanweisung_Datenpflege_VaudisX.md", "indexed": True},
                            {"source_path": "README_Dokumentation.md", "indexed": True},
                        ],
                    }
                ],
            }

        module._call_kb_diagnostics_tool = fake_call
        body = {
            "messages": [
                {"role": "user", "content": "welche Dateien liegen aktuell in der KB kahlerichtlinien?"},
                {"role": "assistant", "content": '[TOOL_CALLS]kb_list_files{"collection":"kahlerichtlinien"}'},
            ]
        }

        result = module.Filter().outlet(body)
        content = result["messages"][-1]["content"]

        assert captured["tool_name"] == "kb_list_files"
        assert captured["params"]["collection"] == "kahlerichtlinien"
        assert "In `kahlerichtlinien` liegen aktuell 2 Dateien" in content
        assert "Arbeitsanweisung_Datenpflege_VaudisX.md" in content
        assert "[TOOL_CALLS]" not in content
        assert "Tool-Fehler" not in content
    finally:
        module._call_kb_diagnostics_tool = original_call


def test_kb_list_files_pseudo_call_accepts_collection_name_alias():
    module = load_module()
    original_call = module._call_kb_diagnostics_tool
    try:
        captured = {}

        def fake_call(tool_name, params):
            captured["tool_name"] = tool_name
            captured["params"] = params
            return {
                "ok": True,
                "collection": "kahlerichtlinien",
                "count": 1,
                "files": [{"source_path": "README_Dokumentation.md", "indexed": True}],
                "collections": [
                    {
                        "collection": "kahlerichtlinien",
                        "count": 1,
                        "last_reconcile_at": "2026-05-20T10:00:03Z",
                        "issue_counts": {},
                        "files": [{"source_path": "README_Dokumentation.md", "indexed": True}],
                    }
                ],
            }

        module._call_kb_diagnostics_tool = fake_call
        body = {
            "messages": [
                {"role": "user", "content": "welche Dateien liegen aktuell in der KB kahlerichtlinien?"},
                {"role": "assistant", "content": '[TOOL_CALLS]kb_list_files{"collection_name":"kahlerichtlinien"}'},
            ]
        }

        result = module.Filter().outlet(body)
        content = result["messages"][-1]["content"]

        assert captured["tool_name"] == "kb_list_files"
        assert captured["params"]["collection"] == "kahlerichtlinien"
        assert "README_Dokumentation.md" in content
        assert "collection_name" not in captured["params"]
        assert "Tool-Fehler" not in content
    finally:
        module._call_kb_diagnostics_tool = original_call


def test_reasoning_leak_for_research_request_is_replaced_with_formatted_text():
    module = load_module()
    original_websearch = module._run_websearch
    try:
        module._run_websearch = lambda query, user_name="": {
            "ok": True,
            "summary": "Recherche wurde nachtraeglich ausgefuehrt.",
            "sources": [],
        }
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": 'Bitte recherchiere einmal zu dem Thema KI und baue daraus einen Infotext mit dem Titel "Einfuehrung in die KI"',
                },
                {
                    "role": "assistant",
                    "content": 'The user asks: "Bitte recherchiere..." According to policy, we should use safe_webcaller. We must not include tool syntax.',
                },
            ]
        }

        result = module.Filter().outlet(body)

        assert "The user asks" not in result["messages"][-1]["content"]
        assert "Recherche wurde nachtraeglich ausgefuehrt" in result["messages"][-1]["content"]
    finally:
        module._run_websearch = original_websearch


if __name__ == "__main__":
    test_visible_workflow_pseudo_call_is_replaced_with_download_metadata()
    test_download_replacement_updates_output_text_as_well_as_content()
    test_pseudo_call_with_prefix_still_uses_previous_assistant_result()
    test_pseudo_call_without_previous_result_uses_embedded_content()
    test_file_request_without_toolcall_creates_requested_docx_from_answer()
    test_generic_pseudo_toolcall_creates_requested_docx_from_previous_answer()
    test_hallucinated_file_link_metadata_creates_real_docx_from_previous_result()
    test_hallucinated_sandbox_download_link_creates_real_docx_from_previous_result()
    test_filename_from_unicode_escape_request_is_readable_ascii()
    test_visible_workflow_pseudo_call_with_powerpoint_request_does_not_create_pptx()
    test_task_list_request_is_replaced_with_exact_open_tasks_from_db()
    test_safe_webcaller_pseudo_call_with_pdf_request_creates_file()
    test_safe_websearch_alias_pseudo_call_with_pdf_request_creates_file()
    test_workflow_pseudo_call_with_empty_embedded_content_runs_research_instead_of_blank_file()
    test_bare_json_file_tool_call_is_replaced_with_download_metadata()
    test_safe_webcaller_pseudo_call_without_file_request_returns_formatted_text()
    test_kb_list_files_pseudo_call_is_replaced_with_file_inventory()
    test_kb_list_files_pseudo_call_accepts_collection_name_alias()
    test_reasoning_leak_for_research_request_is_replaced_with_formatted_text()
    print("kahle toolcall guard tests passed")

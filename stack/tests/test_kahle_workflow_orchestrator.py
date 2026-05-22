#!/usr/bin/env python3
"""Unit checks for the KAHLE workflow orchestrator helper logic."""

from __future__ import annotations

import importlib.util
import asyncio
import json
import os
import sqlite3
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "open-webui-tools" / "kahle_workflow_orchestrator.py"


def load_module():
    spec = importlib.util.spec_from_file_location("kahle_workflow_orchestrator", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_internal_kahle_policy_task_routes_to_internal_rag():
    module = load_module()

    intent = module.classify_workflow_intent(
        "Hole dir Infos zu unserer KI Richtlinie und erstelle eine Praesentationsgliederung.",
        "auto",
    )

    assert intent == "internal"


def test_external_news_task_routes_to_external_search():
    module = load_module()

    intent = module.classify_workflow_intent("Recherchiere aktuelle KI News aus Mai 2026.", "auto")

    assert intent == "external"


def test_external_employee_instruction_research_does_not_route_to_internal_rag():
    module = load_module()

    intent = module.classify_workflow_intent(
        "Bitte recherchiere einmal, wie Spaghetti hergestellt werden. "
        "Dann sortiere mir das zu einer Schritt-fuer-Schritt-Anleitung, die ich direkt an Mitarbeiter geben kann.",
        "auto",
    )

    assert intent == "external"


def test_internal_plus_internet_policy_task_routes_to_mixed():
    module = load_module()

    intent = module.classify_workflow_intent(
        "Hole dir Infos zu unserer KI-Richtlinie. Hole dir aktuelle Infos aus dem Internet zu typischen KI Richtlinien.",
        "auto",
    )

    assert intent == "mixed"


def test_task_plan_for_internal_presentation_uses_rag_before_output():
    module = load_module()

    tasks = module.build_task_plan("internal", "presentation_outline")
    contents = [task["content"] for task in tasks]

    assert contents[0] == "Interne KAHLE-Informationen abrufen"
    assert "Praesentationsgliederung erstellen" in contents[-1]


def test_rag_result_parser_extracts_found_context():
    module = load_module()
    raw = (
        "KAHLE_RAG_RESULT\n"
        "FOUND: true\n"
        "QUERY: KI Richtlinie\n"
        "META: top1_score=0.812 threshold=0.45\n\n"
        "KONTEXT (zitierbar mit [#]):\n"
        "[#1 | kahlerichtlinien | KI.md | chunk 0 | score 0.812]\n"
        "KI darf nur datenschutzkonform genutzt werden."
    )

    parsed = module.parse_rag_result(raw)

    assert parsed["found"] is True
    assert parsed["top1_score"] == 0.812
    assert "datenschutzkonform" in parsed["context"]


def test_web_result_without_ok_is_usable_when_summary_and_sources_exist():
    module = load_module()
    raw = '{"summary":"Kurz-Zusammenfassung","sources":[{"title":"Quelle"}]}'

    parsed = module.parse_web_result(raw)

    assert parsed["ok"] is True
    assert parsed["summary"] == "Kurz-Zusammenfassung"
    assert len(parsed["sources"]) == 1


def test_output_format_is_inferred_from_pdf_request():
    module = load_module()

    fmt = module.infer_download_format("Recherchiere zum CUPRA Tindaya und gib mir das Ergebnis als PDF aus.", "auto")

    assert fmt == "pdf"


def test_previous_result_request_is_detected_for_common_pdf_followup():
    module = load_module()

    assert module._looks_like_previous_result_request("Bitte gib mir das Ergebnis als PDF aus") is True
    assert module._looks_like_previous_result_request("Danke, gib mir das Ergebnis jetzt bitte zusaetzlich als PDF aus.") is True
    assert module._looks_like_previous_result_request("Kannst du die Recherche als PDF speichern?") is True


def test_powerpoint_output_is_not_offered_as_document_generation_format():
    module = load_module()

    fmt = module.infer_download_format("Erstelle daraus eine PowerPoint Praesentation.", "auto")

    assert fmt == "none"


def test_output_format_is_inferred_from_word_output_request():
    module = load_module()

    fmt = module.infer_download_format("Kannst du mir die Datei bitte als Word ausgeben?", "auto")

    assert fmt == "docx"


def test_suggest_output_filename_decodes_literal_unicode_escapes():
    module = load_module()

    filename = module.suggest_output_filename(
        r"Einmal wie Spaghetti hergestellt werden, dann sortieren einer Art Erkl\u00e4rung Recherche",
        "pdf",
    )

    assert filename.endswith(".pdf")
    assert "u00" not in filename
    assert "erklaerung" in filename

    double_escaped = module.suggest_output_filename(r"Pesto_Erkl\\u00e4rung Worddatei", "docx")
    assert double_escaped.endswith(".docx")
    assert "u00" not in double_escaped
    assert "pesto_erklaerung" in double_escaped


def test_same_turn_research_with_daraus_is_not_previous_result_followup():
    module = load_module()

    assert (
        module._looks_like_previous_result_request(
            'Bitte recherchiere zum Thema KI und baue daraus einen Infotext als PDF.'
        )
        is False
    )


def test_workflow_web_query_is_optimized_for_cupra_tindaya_pdf_request():
    module = load_module()

    query = module.build_web_search_query("Recherchiere zum CUPRA Tindaya und gib mir das Ergebnis als PDF aus.")

    assert "CUPRA Tindaya" in query
    assert "Konzeptfahrzeug" in query
    assert "PDF" not in query


def test_workflow_web_query_is_optimized_for_barilla_pesto_docx_request():
    module = load_module()

    query = module.build_web_search_query(
        'Bitte recherchiere, welche Pesto-Sorten es aktuell von Barilla gibt. '
        'Erstelle daraus eine Liste mit der Überschrift "Pesto Barilla Sorten" und gib mir das Ganze als Worddatei aus.'
    )

    assert query == "Barilla Pesto Sorten Deutschland aktuell 2026"


def test_workflow_web_query_is_optimized_for_spaghetti_instructions():
    module = load_module()

    query = module.build_web_search_query(
        "Bitte recherchiere einmal, wie Spaghetti hergestellt werden, und sortiere das als Schritt-für-Schritt-Erklärung für Mitarbeiter."
    )

    assert "Spaghetti" in query
    assert "Herstellung" in query
    assert "Hartweizen" in query
    assert "Schritt-für-Schritt" not in query
    assert "Mitarbeiter" not in query


def test_report_markdown_contains_web_summary_and_sources():
    module = load_module()
    payload = module.build_final_payload(
        "Recherchiere zum CUPRA Tindaya.",
        "external",
        "research_brief",
        [{"id": "1", "content": "Externe Recherche durchfuehren", "status": "completed"}],
        web={
            "ok": True,
            "summary": "CUPRA Tindaya ist ein Konzeptfahrzeug.",
            "sources": [{"title": "CUPRA Newsroom", "url": "https://example.test/cupra"}],
            "topLinks": [],
        },
    )

    markdown = module.build_report_markdown(payload)

    assert "CUPRA Tindaya ist ein Konzeptfahrzeug" in markdown
    assert "CUPRA Newsroom" in markdown
    assert "https://example.test/cupra" in markdown


def test_report_markdown_turns_barilla_research_into_requested_list():
    module = load_module()
    payload = module.build_final_payload(
        'Bitte recherchiere, welche Pesto-Sorten es aktuell von Barilla gibt. Erstelle daraus eine Liste mit der Überschrift "Pesto Barilla Sorten" und gib mir das Ganze als Worddatei aus.',
        "external",
        "docx_brief",
        [{"id": "1", "content": "Externe Recherche durchfuehren", "status": "completed"}],
        web={
            "ok": True,
            "summary": (
                "**Recherchekontext (aus abgerufenen Webseiten, untrusted):**\n"
                "Pesto Rosso, Basilikum-Pesto, Gemuesepesto oder Pesto Rustico. "
                "Barilla Pesto Set: Genovese, Basilico Pistacchio, Ricotta e Noci, Rucola, Calabrese, Basilico Limone, Genovese ohne Knoblauch."
            ),
            "sources": [{"title": "Barilla Pesto", "url": "https://example.test/barilla", "snippet": "Pesto Rosso und Pesto Ricotta e Noci"}],
            "topLinks": [],
        },
    )

    markdown = module.build_report_markdown(payload)

    assert "# Pesto Barilla Sorten" in markdown
    assert "- Pesto Rosso" in markdown
    assert "- Pesto Ricotta e Noci" in markdown
    assert "Recherchekontext" not in markdown
    assert "**Auftrag:**" not in markdown


def test_report_markdown_turns_spaghetti_research_into_step_by_step_guide():
    module = load_module()
    payload = module.build_final_payload(
        "Bitte recherchiere einmal, wie Spaghetti hergestellt werden. Dann sortiere mir das zu einer Schritt-fuer-Schritt-Anleitung, die ich direkt an Mitarbeiter geben kann, und gib mir das dann als PDF aus.",
        "external",
        "research_brief",
        [{"id": "1", "content": "Externe Recherche durchfuehren", "status": "completed"}],
        web={
            "ok": True,
            "summary": "Spaghetti werden aus Hartweizengriess und Wasser hergestellt, der Teig wird gemischt, durch Matrizen gepresst, getrocknet und verpackt.",
            "sources": [{"title": "Pasta Herstellung", "url": "https://example.test/pasta", "snippet": "Hartweizengriess, Extrusion und Trocknung"}],
            "topLinks": [],
        },
    )

    markdown = module.build_report_markdown(payload)

    assert "# Schritt-fuer-Schritt-Anleitung: Spaghetti-Herstellung" in markdown
    assert "## Schritt-fuer-Schritt-Anleitung" in markdown
    assert "1. Rohstoffe vorbereiten" in markdown
    assert "8. Verpacken" in markdown
    assert "Suchergebnisse" not in markdown
    assert "Recherchekontext" not in markdown


def test_workflow_creates_generated_file_payload_for_research_pdf_request():
    module = load_module()

    original_create = module.create_downloadable_file
    try:
        module.create_downloadable_file = lambda content, output_format, filename, title="": {
            "output_kind": "file_saved",
            "filename": filename,
            "download_url": "http://localhost:8091/files/download?rel=edited/test.pdf",
            "sha256": "abc",
            "size_bytes": 123,
        }
        tools = module.Tools()
        tools._run_external_websearch = lambda query, max_results, user: json.dumps(
            {"ok": True, "summary": "CUPRA Tindaya Recherche", "sources": []},
            ensure_ascii=False,
        )

        raw = asyncio.run(
            tools.kahle_workflow_execute(
                "Recherchiere zum CUPRA Tindaya und gib mir das Ergebnis als PDF aus.",
                modus="external",
                output_format="pdf",
            )
        )
        payload = json.loads(raw)

        assert payload["generated_file"]["output_kind"] == "file_saved"
        assert payload["download_url"].startswith("http://localhost:8091/files/download")
        assert payload["filename"].endswith(".pdf")
    finally:
        module.create_downloadable_file = original_create


def test_workflow_recovers_empty_auftrag_from_chat_history():
    module = load_module()

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "webui.db"
        con = sqlite3.connect(db_path)
        con.execute(
            "create table chat_message (chat_id text, role text, content text, created_at integer, updated_at integer)"
        )
        con.execute(
            "insert into chat_message values (?, 'user', ?, 10, 10)",
            ("chat-1", "Recherchiere zum CUPRA Tindaya und gib mir das Ergebnis als PDF aus."),
        )
        con.commit()
        con.close()

        old = os.environ.get("OWUI_DB_PATH")
        os.environ["OWUI_DB_PATH"] = str(db_path)
        original_create = module.create_downloadable_file
        try:
            module.create_downloadable_file = lambda content, output_format, filename, title="": {
                "output_kind": "file_saved",
                "filename": filename,
                "download_url": "http://localhost:8091/files/download?token=test",
                "sha256": "abc",
                "size_bytes": 123,
            }
            tools = module.Tools()
            tools._run_external_websearch = lambda query, max_results, user: json.dumps(
                {"ok": True, "summary": "CUPRA Tindaya Recherche", "sources": []},
                ensure_ascii=False,
            )
            raw = asyncio.run(
                tools.kahle_workflow_execute(
                    "",
                    modus="external",
                    output_format="pdf",
                    __chat_id__="chat-1",
                )
            )
            payload = json.loads(raw)
            assert payload["auftrag"].startswith("Recherchiere zum CUPRA Tindaya")
            assert payload["generated_file"]["filename"].endswith(".pdf")
        finally:
            module.create_downloadable_file = original_create
            if old is None:
                os.environ.pop("OWUI_DB_PATH", None)
            else:
                os.environ["OWUI_DB_PATH"] = old


def test_workflow_creates_pdf_from_previous_assistant_result_followup():
    module = load_module()

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "webui.db"
        con = sqlite3.connect(db_path)
        con.execute(
            "create table chat_message (chat_id text, role text, content text, created_at integer, updated_at integer)"
        )
        con.execute(
            "insert into chat_message values (?, 'user', ?, 20, 20)",
            ("chat-2", "Bitte gib mir das Ergebnis als PDF aus."),
        )
        con.execute(
            "insert into chat_message values (?, 'assistant', ?, 10, 10)",
            ("chat-2", "# Recherche\n\nCUPRA Tindaya ist ein Konzeptfahrzeug."),
        )
        con.commit()
        con.close()

        old = os.environ.get("OWUI_DB_PATH")
        os.environ["OWUI_DB_PATH"] = str(db_path)
        original_create = module.create_downloadable_file
        try:
            captured = {}

            def fake_create(content, output_format, filename, title=""):
                captured["content"] = content
                captured["output_format"] = output_format
                return {
                    "output_kind": "file_saved",
                    "filename": filename,
                    "download_url": "http://localhost:8091/files/download?token=test",
                    "sha256": "abc",
                    "size_bytes": 123,
                }

            module.create_downloadable_file = fake_create
            raw = asyncio.run(
                module.Tools().kahle_workflow_execute(
                    "",
                    output_format="pdf",
                    __chat_id__="chat-2",
                )
            )
            payload = json.loads(raw)
            assert payload["intent"] == "previous_result_file"
            assert "CUPRA Tindaya ist ein Konzeptfahrzeug" in captured["content"]
            assert payload["download_url"].endswith("token=test")
        finally:
            module.create_downloadable_file = original_create
            if old is None:
                os.environ.pop("OWUI_DB_PATH", None)
            else:
                os.environ["OWUI_DB_PATH"] = old


def test_workflow_skips_current_empty_assistant_when_creating_previous_result_docx():
    module = load_module()

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "webui.db"
        con = sqlite3.connect(db_path)
        con.execute(
            "create table chat_message (chat_id text, role text, content text, created_at integer, updated_at integer)"
        )
        con.execute(
            "insert into chat_message values (?, 'assistant', ?, 30, 30)",
            ("chat-3", '""'),
        )
        con.execute(
            "insert into chat_message values (?, 'user', ?, 20, 20)",
            ("chat-3", "Bitte gib mir das Ergebnis als Word aus."),
        )
        con.execute(
            "insert into chat_message values (?, 'assistant', ?, 10, 10)",
            ("chat-3", "# Recherche\n\nProf4Net bietet CRM-Loesungen fuer Autohaeuser."),
        )
        con.commit()
        con.close()

        old = os.environ.get("OWUI_DB_PATH")
        os.environ["OWUI_DB_PATH"] = str(db_path)
        original_create = module.create_downloadable_file
        try:
            captured = {}

            def fake_create(content, output_format, filename, title=""):
                captured["content"] = content
                captured["output_format"] = output_format
                return {
                    "output_kind": "file_saved",
                    "filename": filename,
                    "download_url": "http://localhost:8091/files/download?token=test",
                    "sha256": "abc",
                    "size_bytes": 123,
                }

            module.create_downloadable_file = fake_create
            raw = asyncio.run(
                module.Tools().kahle_workflow_execute(
                    "",
                    output_format="docx",
                    __chat_id__="chat-3",
                )
            )
            payload = json.loads(raw)
            assert payload["intent"] == "previous_result_file"
            assert captured["output_format"] == "docx"
            assert "Prof4Net bietet CRM-Loesungen" in captured["content"]
            assert captured["content"].strip() != '""'
        finally:
            module.create_downloadable_file = original_create
            if old is None:
                os.environ.pop("OWUI_DB_PATH", None)
            else:
                os.environ["OWUI_DB_PATH"] = old


def test_workflow_does_not_create_previous_result_file_from_clarification_only():
    module = load_module()

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "webui.db"
        con = sqlite3.connect(db_path)
        con.execute(
            "create table chat_message (chat_id text, role text, content text, created_at integer, updated_at integer)"
        )
        con.execute(
            "insert into chat_message values (?, 'assistant', ?, 10, 10)",
            (
                "chat-4",
                "Um eine praezise Recherche durchzufuehren, benoetige ich weitere Details. Bitte praezisiere deine Anfrage.",
            ),
        )
        con.execute(
            "insert into chat_message values (?, 'user', ?, 20, 20)",
            ("chat-4", "Bitte gib mir das Ergebnis als Word aus."),
        )
        con.commit()
        con.close()

        old = os.environ.get("OWUI_DB_PATH")
        os.environ["OWUI_DB_PATH"] = str(db_path)
        original_create = module.create_downloadable_file
        try:
            module.create_downloadable_file = lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("should not create a file without a previous result")
            )
            raw = asyncio.run(
                module.Tools().kahle_workflow_execute(
                    "",
                    output_format="docx",
                    __chat_id__="chat-4",
                )
            )
            payload = json.loads(raw)
            assert payload["intent"] != "previous_result_file"
            assert payload.get("download_url") is None
        finally:
            module.create_downloadable_file = original_create
            if old is None:
                os.environ.pop("OWUI_DB_PATH", None)
            else:
                os.environ["OWUI_DB_PATH"] = old


def test_workflow_cancels_internal_research_task_when_rag_errors():
    module = load_module()

    updates = []
    tools = module.Tools()

    async def fake_create(*args, **kwargs):
        return None

    async def fake_update(task_id, status, *args, **kwargs):
        updates.append((task_id, status))

    tools._tasks_create = fake_create
    tools._task_update = fake_update
    tools._run_internal_rag = lambda query: "KAHLE_RAG_RESULT\nFOUND: false\nERROR: IONOS API Key fehlt."

    raw = asyncio.run(
        tools.kahle_workflow_execute(
            "Hole dir Infos zu unserer KI Richtlinie.",
            modus="internal",
            output_format="none",
            __chat_id__="chat-rag-error",
        )
    )
    payload = json.loads(raw)

    assert ("1", "completed") not in updates
    assert ("1", "cancelled") in updates
    assert payload["tasks"][0]["status"] == "cancelled"
    assert payload["status"] == "blocked"


def test_workflow_cancels_external_research_task_when_web_errors():
    module = load_module()

    updates = []
    tools = module.Tools()

    async def fake_create(*args, **kwargs):
        return None

    async def fake_update(task_id, status, *args, **kwargs):
        updates.append((task_id, status))

    tools._tasks_create = fake_create
    tools._task_update = fake_update
    tools._run_external_websearch = lambda query, max_results, user: json.dumps(
        {"ok": False, "error": "n8n returned HTTP 500"},
        ensure_ascii=False,
    )

    raw = asyncio.run(
        tools.kahle_workflow_execute(
            "Recherchiere aktuelle KI News.",
            modus="external",
            output_format="none",
            __chat_id__="chat-web-error",
        )
    )
    payload = json.loads(raw)

    assert ("1", "completed") not in updates
    assert ("1", "cancelled") in updates
    assert payload["tasks"][0]["status"] == "cancelled"
    assert payload["status"] == "blocked"


def test_workflow_cancels_output_task_when_file_creation_errors():
    module = load_module()

    updates = []
    original_create = module.create_downloadable_file
    try:
        module.create_downloadable_file = lambda content, output_format, filename, title="": {
            "ok": False,
            "error": "file_proxy_http_500",
        }

        tools = module.Tools()

        async def fake_create(*args, **kwargs):
            return None

        async def fake_update(task_id, status, *args, **kwargs):
            updates.append((task_id, status))

        tools._tasks_create = fake_create
        tools._task_update = fake_update
        tools._run_external_websearch = lambda query, max_results, user: json.dumps(
            {"ok": True, "summary": "KI News Zusammenfassung", "sources": []},
            ensure_ascii=False,
        )

        raw = asyncio.run(
            tools.kahle_workflow_execute(
                "Recherchiere aktuelle KI News und gib mir das Ergebnis als PDF aus.",
                modus="external",
                output_format="pdf",
                __chat_id__="chat-file-error",
            )
        )
        payload = json.loads(raw)

        assert ("3", "completed") not in updates
        assert ("3", "cancelled") in updates
        assert payload["tasks"][2]["status"] == "cancelled"
        assert payload["status"] == "blocked"
    finally:
        module.create_downloadable_file = original_create


if __name__ == "__main__":
    test_internal_kahle_policy_task_routes_to_internal_rag()
    test_external_news_task_routes_to_external_search()
    test_external_employee_instruction_research_does_not_route_to_internal_rag()
    test_internal_plus_internet_policy_task_routes_to_mixed()
    test_task_plan_for_internal_presentation_uses_rag_before_output()
    test_rag_result_parser_extracts_found_context()
    test_web_result_without_ok_is_usable_when_summary_and_sources_exist()
    test_output_format_is_inferred_from_pdf_request()
    test_previous_result_request_is_detected_for_common_pdf_followup()
    test_powerpoint_output_is_not_offered_as_document_generation_format()
    test_output_format_is_inferred_from_word_output_request()
    test_suggest_output_filename_decodes_literal_unicode_escapes()
    test_same_turn_research_with_daraus_is_not_previous_result_followup()
    test_workflow_web_query_is_optimized_for_cupra_tindaya_pdf_request()
    test_workflow_web_query_is_optimized_for_barilla_pesto_docx_request()
    test_workflow_web_query_is_optimized_for_spaghetti_instructions()
    test_report_markdown_contains_web_summary_and_sources()
    test_report_markdown_turns_barilla_research_into_requested_list()
    test_report_markdown_turns_spaghetti_research_into_step_by_step_guide()
    test_workflow_creates_generated_file_payload_for_research_pdf_request()
    test_workflow_recovers_empty_auftrag_from_chat_history()
    test_workflow_creates_pdf_from_previous_assistant_result_followup()
    test_workflow_cancels_internal_research_task_when_rag_errors()
    test_workflow_cancels_external_research_task_when_web_errors()
    test_workflow_cancels_output_task_when_file_creation_errors()
    print("kahle workflow orchestrator tests passed")

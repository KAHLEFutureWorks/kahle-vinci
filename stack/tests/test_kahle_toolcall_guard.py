#!/usr/bin/env python3
"""Unit checks for the KAHLE outlet guard filter."""

from __future__ import annotations

import importlib.util
import json
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


def test_guard_expands_short_marketing_reply_from_customer_lock_clarification():
    module = load_module()
    messages = [
        {"role": "user", "content": "Wie sperre ich einen Kunden in Vaudis?"},
        {
            "role": "assistant",
            "content": (
                "Geht es darum, Werbung und Befragungen für den Kunden zu sperren, "
                "oder um eine allgemeine Kundensperre in Vaudis?"
            ),
        },
    ]

    assert module._expand_customer_lock_followup("Werbung", messages) == (
        "Wie sperre ich Werbung und automatisierte Befragungen für einen Kunden "
        "in Vaudis über die DSE-Kontaktfreigaben?"
    )


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


def test_visible_json_workflow_call_uses_embedded_content_for_docx():
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
        visible = json.dumps(
            {
                "tool": "kahle_workflow_execute",
                "parameters": {
                    "content": (
                        "# KAHLE-Vinci Migrationstest\n\n"
                        "Der Servermigrationstest wurde erfolgreich durchgefuehrt."
                    ),
                    "output_format": "docx",
                    "filename": "KAHLE_Vinci_Migrationstest.docx",
                },
            },
            ensure_ascii=False,
        )
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Erstelle eine Word-Datei mit der Ueberschrift KAHLE-Vinci Migrationstest "
                        "und einem kurzen Absatz zum erfolgreichen Servermigrationstest."
                    ),
                },
                {"role": "assistant", "content": visible},
            ]
        }

        result = module.Filter().outlet(body)

        assert "Download-Link: [Datei herunterladen]" in result["messages"][-1]["content"]
        assert captured["output_format"] == "docx"
        assert captured["filename"] == "KAHLE_Vinci_Migrationstest.docx"
        assert "Servermigrationstest wurde erfolgreich" in captured["content"]
    finally:
        module._create_file = original_create


def test_direct_file_promise_synthesizes_and_creates_docx():
    module = load_module()
    original_create = module._create_file
    original_synthesize = module._synthesize_requested_file_content
    try:
        captured = {}

        module._synthesize_requested_file_content = lambda request_text: (
            "# KAHLE-Vinci Migrationstest\n\n"
            "Die Servermigration wurde erfolgreich geprueft."
        )

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
                    "content": (
                        "Erstelle eine Word-Datei mit der Ueberschrift KAHLE-Vinci Migrationstest "
                        "und einem kurzen Absatz, dass die Servermigration erfolgreich geprueft wurde."
                    ),
                },
                {
                    "role": "assistant",
                    "content": (
                        "Ich werde eine Word-Datei mit dem gewuenschten Inhalt erstellen. "
                        "Bitte einen Moment Geduld."
                    ),
                },
            ]
        }

        result = module.Filter().outlet(body)

        assert "Download-Link: [Datei herunterladen]" in result["messages"][-1]["content"]
        assert captured["output_format"] == "docx"
        assert "Servermigration wurde erfolgreich" in captured["content"]
    finally:
        module._create_file = original_create
        module._synthesize_requested_file_content = original_synthesize


def test_fillable_ki_permission_request_never_uses_generic_docx_export():
    module = load_module()
    original_form = module._create_fillable_ki_permission_form
    original_create = module._create_file
    try:
        captured = {}
        def fake_form(filename, output_format="docx"):
            captured["filename"] = filename
            return {"download_url":"http://localhost:8091/files/d/form","filename":filename,"sha256":"abc","size_bytes":456,"fillable":True}
        module._create_fillable_ki_permission_form = fake_form
        module._create_file = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("generic DOCX export used"))
        body = {"messages":[
            {"role":"user","content":"Bitte erstelle eine ausfüllbare/aktive Word Datei, die wir als Vorlage nehmen können, um diese Erlaubnisse schriftlich festzuhalten"},
            {"role":"assistant","content":json.dumps({"tool":"kahle_workflow_execute","parameters":{"output_format":"docx","content":"# Statischer Platzhalter"}})},
        ]}
        result = module.Filter().outlet(body)
        assert captured["filename"] == "KI-Nutzungs-und-Freigabeantrag.docx"
        assert "KI-Nutzungs-und-Freigabeantrag.docx" in result["messages"][-1]["content"]
    finally:
        module._create_fillable_ki_permission_form = original_form
        module._create_file = original_create


def test_successful_rag_source_replaces_false_no_internal_knowledge_answer():
    module = load_module()
    original_synthesize = module._synthesize_rag_answer
    try:
        module._synthesize_rag_answer = lambda request_text, rag_text, user_name="": (
            "Der KAHLE-Standort Nienburg fuehrt Volkswagen und Audi Service [#1]."
        )
        rag_text = (
            "KAHLE_RAG_RESULT\n"
            "FOUND: true\n"
            "QUERY: KAHLE Standort Nienburg\n"
            "INSTRUCTION: Nutze ausschliesslich den Kontext.\n"
            "META: top1_score=0.717 threshold=0.45 model=BAAI/bge-m3\n\n"
            "KONTEXT (zitierbar mit [#]):\n"
            "[#1 | kahleallgemein | KB_KAHLE_Nienburg.md | chunk 0 | score 0.717]\n"
            "Der Standort Nienburg fuehrt Volkswagen und Audi Service."
        )
        body = {
            "messages": [
                {"role": "user", "content": "Was weisst du ueber unseren Standort Nienburg?"},
                {
                    "role": "assistant",
                    "content": (
                        "Ich habe keine Informationen ueber den Standort Nienburg. "
                        "Bitte waehle einen anderen Standort aus."
                    ),
                },
            ]
        }

        metadata = {
            "kahle_tool_sources": [
                {
                    "source": {"name": "rag_chat/rag_chat"},
                    "document": [rag_text],
                    "tool_result": True,
                }
            ]
        }
        result = module.Filter().outlet(body, __metadata__=metadata)

        assert "Volkswagen und Audi Service [#1]" in result["messages"][-1]["content"]
        assert "keine Informationen" not in result["messages"][-1]["content"]
    finally:
        module._synthesize_rag_answer = original_synthesize


def test_negative_rag_source_replaces_thinking_model_hallucination():
    module = load_module()
    rag_text = (
        "KAHLE_RAG_RESULT\n"
        "FOUND: false\n"
        "ANSWER: Dazu habe ich keine verlässliche freigegebene Information."
    )
    body = {
        "messages": [
            {"role": "user", "content": "Wie plane ich einen Termin im WPS?"},
            {
                "role": "assistant",
                "content": (
                    "Öffne im WPS den Werkstatt-Kalender, wähle Ressourcen aus "
                    "und versende anschließend automatisch eine SMS."
                ),
                "sources": [
                    {
                        "source": {"name": "rag_chat/rag_chat"},
                        "document": [rag_text],
                        "tool_result": True,
                    }
                ],
            },
        ]
    }

    result = module.Filter().outlet(body)

    assert result["messages"][-1]["content"] == "Dazu habe ich kein internes Wissen."


def test_successful_but_unanswerable_rag_context_stays_fail_closed():
    module = load_module()
    original_synthesize = module._synthesize_rag_answer
    try:
        module._synthesize_rag_answer = lambda *_args, **_kwargs: (
            "Dazu habe ich kein internes Wissen."
        )
        rag_text = (
            "KAHLE_RAG_RESULT\nFOUND: true\n"
            "KONTEXT (zitierbar mit [#]):\n"
            "[#1 | allgemein | Standortregeln.md | chunk 1 | score 0.71]\n"
            "Bei zeitkritischen Informationen muss der Stand genannt werden."
        )

        answer = module._rag_answer_text(
            "Wie sind unsere Öffnungszeiten?", rag_text
        )

        assert answer == "Dazu habe ich kein internes Wissen."
        assert "Standortregeln" not in answer
    finally:
        module._synthesize_rag_answer = original_synthesize


def test_current_raw_rag_context_is_parsed_and_always_regrounded():
    module = load_module()
    original_synthesize = module._synthesize_rag_answer
    try:
        module._synthesize_rag_answer = lambda *_args, **_kwargs: (
            "Dazu habe ich kein internes Wissen."
        )
        rag_text = (
            "KAHLE_RAG_RESULT\nFOUND: true\n"
            "INSTRUCTION: Antworte nur aus CONTEXT.\n"
            "CONTEXT:\n"
            "[Quelle 1] KAHLE Systemlandkarte | System-Landkarte\n"
            "WPS/DA ist ein Werkstatt- und Termin-System.\n"
            "SOURCES_JSON: []\n"
            "FEEDBACK_LINK: [Wissensfehler melden](/wissen/)"
        )
        body = {
            "messages": [
                {"role": "user", "content": "Wie plane ich einen Termin im WPS?"},
                {
                    "role": "assistant",
                    "content": "Öffne den Kalender und aktiviere automatische SMS.",
                    "sources": [{
                        "source": {"name": "rag_chat/rag_chat"},
                        "document": [rag_text],
                        "tool_result": True,
                    }],
                },
            ]
        }

        assert "WPS/DA ist" in module._rag_context_text(rag_text)
        result = module.Filter().outlet(body)
        assert result["messages"][-1]["content"] == "Dazu habe ich kein internes Wissen."
    finally:
        module._synthesize_rag_answer = original_synthesize


def test_synthesized_internal_answer_without_source_marks_is_rejected():
    module = load_module()
    original_synthesize = module._synthesize_rag_answer
    try:
        module._synthesize_rag_answer = lambda *_args, **_kwargs: (
            "Öffne das WPS, klicke in den Kalender und sende anschließend eine SMS."
        )
        rag_text = (
            "KAHLE_RAG_RESULT\nFOUND: true\nCONTEXT:\n"
            "[Quelle 1] Systemlandkarte | Überblick\n"
            "WPS ist ein Terminplanungssystem.\nSOURCES_JSON: []"
        )

        assert module._rag_answer_text("Wie plane ich einen Termin?", rag_text) == (
            "Dazu habe ich kein internes Wissen."
        )
    finally:
        module._synthesize_rag_answer = original_synthesize


def test_valid_rag_answer_accepts_quelle_mark_and_keeps_feedback_link():
    module = load_module()
    original_synthesize = module._synthesize_rag_answer
    try:
        module._synthesize_rag_answer = lambda *_args, **_kwargs: (
            "Der Teiledienst in Nienburg ist Montag bis Freitag von "
            "07:30 bis 17:00 Uhr geöffnet. [Quelle 1]"
        )
        rag_text = (
            "KAHLE_RAG_RESULT\nFOUND: true\n"
            "CONTEXT:\n"
            "[Quelle 1] Standort Nienburg > Öffnungszeiten\n"
            "Teiledienst: Mo-Fr 07:30-17:00.\n"
            "SOURCES_JSON: []\n"
            "FEEDBACK_LINK: [Wissensfehler melden]"
            "(/wissen/?feedback=1&chat_id=chat-1&message_id=message-1)"
        )

        answer = module._rag_answer_text(
            "Wie sind die TD Öffnungszeiten in NIE?", rag_text,
        )

        assert "Mo-Fr 07:30-17:00" in answer
        assert "[#1]" in answer
        assert "[Quelle 1]" not in answer
        assert answer.endswith(
            "[Wissensfehler melden]"
            "(/wissen/?feedback=1&chat_id=chat-1&message_id=message-1)"
        )
    finally:
        module._synthesize_rag_answer = original_synthesize


def test_opening_hours_answer_is_deterministic_and_skips_second_model_call():
    module = load_module()
    original_synthesize = module._synthesize_rag_answer
    try:
        module._synthesize_rag_answer = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("opening hours must not use a second model call")
        )
        rag_text = (
            "KAHLE_RAG_RESULT\nFOUND: true\nCONTEXT:\n"
            "[Quelle 1] MasterKontext KAHLE v1.6 > Standort Nienburg\n"
            "- **Öffnungszeiten:** Service: Mo-Fr 07:30-18:00 · Sa 09:00-13:00 | "
            "Teiledienst: Mo-Fr 07:30-17:00 · Samstag nicht eindeutig ausgewiesen | "
            "Verkauf: Mo-Fr 09:00-18:00 · Sa 09:00-13:00\n"
            "SOURCES_JSON: []\n"
            "FEEDBACK_LINK: [Wissensfehler melden]"
            "(/wissen/?feedback=1&chat_id=chat-1&message_id=message-1)"
        )

        answer = module._rag_answer_text(
            "Wie sind unsere TD Öffnungszeiten in NIE?", rag_text,
        )

        assert answer.startswith(
            "Teiledienst in Nienburg: Mo-Fr 07:30-17:00 · "
            "Samstag nicht eindeutig ausgewiesen [#1]"
        )
        assert "Wissensfehler melden" in answer
    finally:
        module._synthesize_rag_answer = original_synthesize


def test_opening_hours_supports_vk_shg_and_location_without_department():
    module = load_module()
    context = (
        "[Quelle 2] Standort Stadthagen > Öffnungszeiten\n"
        "Öffnungszeiten: Service: Mo-Fr 07:00-18:00 | "
        "Teiledienst: Mo-Fr 07:30-17:30 | Verkauf: Mo-Fr 09:00-18:00"
    )

    sales = module._deterministic_opening_hours_answer(
        "Wie sind unsere VK Öffnungszeiten in SHG?", context,
    )
    all_departments = module._deterministic_opening_hours_answer(
        "Wie sind unsere Stadthagener Öffnungszeiten?", context,
    )

    assert sales == "Verkauf in Stadthagen: Mo-Fr 09:00-18:00 [#2]"
    assert "Service: Mo-Fr 07:00-18:00 [#2]" in all_departments
    assert "Teiledienst: Mo-Fr 07:30-17:30 [#2]" in all_departments
    assert "Verkauf: Mo-Fr 09:00-18:00 [#2]" in all_departments


def test_existing_grounded_rag_answer_is_kept_without_second_synthesis():
    module = load_module()
    original_synthesize = module._synthesize_rag_answer
    try:
        module._synthesize_rag_answer = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("an already grounded answer must not be synthesized again")
        )
        rag_text = (
            "KAHLE_RAG_RESULT\nFOUND: true\nCONTEXT:\n"
            "[Quelle 1] Prozesshandbuch\nServiceprozesse reichen von der Terminierung "
            "bis zur Zufriedenheitsabfrage.\n"
            "[Quelle 2] Auditregel\nInterne Audits werden dokumentiert.\n"
            "SOURCES_JSON: []\n"
            "FEEDBACK_LINK: [Wissensfehler melden]"
            "(/wissen/?feedback=1&chat_id=chat-3&message_id=message-3)"
        )
        candidate = (
            "Ich kenne folgende Prozesse bei der KAHLE Gruppe:\n\n"
            "1. Serviceprozesse von der Terminierung bis zur "
            "Zufriedenheitsabfrage.\n"
            "2. Interne Audits und deren Dokumentation."
        )

        answer = module._rag_answer_text(
            "Welche Prozesse bei uns kennst du?", rag_text,
            candidate_answer=candidate,
        )

        assert "Serviceprozesse" in answer
        assert "Interne Audits" in answer
        assert "Dazu habe ich kein internes Wissen" not in answer
        assert "[#1]" in answer and "[#2]" in answer
    finally:
        module._synthesize_rag_answer = original_synthesize


def test_partially_grounded_answer_keeps_cited_lines_and_removes_uncited_claims():
    module = load_module()
    answer = (
        "Ich kenne folgende Prozesse:\n\n"
        "1. Serviceprozesse reichen bis zur Zufriedenheitsabfrage [#1].\n"
        "2. Im WPS werden Kunden automatisch per SMS informiert.\n"
        "3. Interne Audits werden dokumentiert [#2]."
    )

    retained = module._retain_grounded_answer(answer)

    assert "Serviceprozesse" in retained
    assert "Interne Audits" in retained
    assert "automatisch per SMS" not in retained


def test_answer_without_any_source_mark_is_not_treated_as_grounded():
    module = load_module()

    assert module._retain_grounded_answer(
        "Serviceprozesse umfassen Terminierung und Werkstattplanung."
    ) == ""


def test_source_chip_answer_is_grounded_against_context_line_by_line():
    module = load_module()
    context = (
        "[Quelle 3] Service-Prozesskette\n"
        "Terminierung, Werkstattplanung, Fahrzeugannahme, Diagnose und "
        "Zufriedenheitsabfrage.\n"
        "[Quelle 4] Auditregeln\nInterne Audits werden dokumentiert."
    )
    candidate = (
        "Ich kenne folgende Prozesse:\n"
        "- Terminierung und Werkstattplanung.\n"
        "- Interne Audits werden dokumentiert.\n"
        "- Kunden erhalten automatisch eine SMS nach jedem Arbeitsschritt."
    )

    retained = module._retain_context_supported_answer(candidate, context)

    assert "Terminierung und Werkstattplanung [#3]" in retained
    assert "Interne Audits werden dokumentiert [#4]" in retained
    assert "automatisch eine SMS" not in retained


def test_negative_rag_result_keeps_feedback_link_after_guard_replacement():
    module = load_module()
    rag_text = (
        "KAHLE_RAG_RESULT\nFOUND: false\n"
        "ANSWER: Dazu habe ich keine verlässliche freigegebene Information.\n"
        "FEEDBACK_LINK: [Wissensfehler melden]"
        "(/wissen/?feedback=1&chat_id=chat-2&message_id=message-2)"
    )
    body = {
        "messages": [
            {"role": "user", "content": "Wie läuft der unbekannte Prozess?"},
            {
                "role": "assistant",
                "content": "Eine unbelegte Antwort.",
                "sources": [{
                    "source": {"name": "rag_chat/rag_chat"},
                    "document": [rag_text],
                    "tool_result": True,
                }],
            },
        ],
    }

    answer = module.Filter().outlet(body)["messages"][-1]["content"]

    assert answer.startswith("Dazu habe ich kein internes Wissen.")
    assert answer.endswith(
        "[Wissensfehler melden]"
        "(/wissen/?feedback=1&chat_id=chat-2&message_id=message-2)"
    )


def test_wps_system_overview_does_not_answer_procedural_question():
    module = load_module()
    context = (
        "[#1] KAHLE Systemlandkarte\n"
        "WPS/DA ist ein Werkstatt- und Terminplanungssystem. "
        "Catch ist ein CRM-System."
    )

    assert module._rag_context_supports_request(
        "Wie plane ich einen Termin im WPS?", context
    ) is False


def test_real_wps_instructions_answer_procedural_question():
    module = load_module()
    context = (
        "[#1] WPS Anleitung\n"
        "Öffne im WPS die Terminplanung. Wähle den gewünschten Zeitraum aus. "
        "Gib Kunde und Fahrzeug ein und speichere anschließend den Termin."
    )

    assert module._rag_context_supports_request(
        "Wie plane ich einen Termin im WPS?", context
    ) is True


def test_every_procedural_answer_step_needs_a_source_mark():
    module = load_module()
    partially_cited = (
        "1. Öffne die Terminplanung [#1].\n"
        "2. Wähle den Kunden aus.\n"
        "3. Speichere den Termin [#1]."
    )
    fully_cited = (
        "1. Öffne die Terminplanung [#1].\n"
        "2. Wähle den Kunden aus [#1].\n"
        "3. Speichere den Termin [#1]."
    )

    assert module._grounded_answer_has_source_marks(partially_cited) is False
    assert module._grounded_answer_has_source_marks(fully_cited) is True


def test_rag_clarification_replaces_model_answer():
    module = load_module()
    rag_text = (
        "KAHLE_RAG_RESULT\nFOUND: false\n"
        "CLARIFICATION_REQUIRED: true\n"
        "ANSWER: Für welchen Standort und welchen Bereich brauchst du die Öffnungszeiten?"
    )
    body = {
        "messages": [
            {"role": "user", "content": "Wie sind unsere Öffnungszeiten?"},
            {
                "role": "assistant",
                "content": "Hier ist die vollständige Liste aller Standorte.",
                "sources": [{
                    "source": {"name": "rag_chat/rag_chat"},
                    "document": [rag_text],
                    "tool_result": True,
                }],
            },
        ]
    }

    result = module.Filter().outlet(body)
    assert result["messages"][-1]["content"] == (
        "Für welchen Standort und welchen Bereich brauchst du die Öffnungszeiten?"
    )


def test_rag_guided_response_replaces_model_answer():
    module = load_module()
    guided_answer = (
        "Bitte wende dich mit der Kundennummer und dem Grund der gewünschten Sperre "
        "an [datenschutz@kahle.de](mailto:datenschutz@kahle.de)."
    )
    rag_text = (
        "KAHLE_RAG_RESULT\nFOUND: true\n"
        "GUIDED_RESPONSE: true\n"
        f"ANSWER: {guided_answer}"
    )
    body = {
        "messages": [
            {"role": "user", "content": "Wie sperre ich einen Kunden allgemein in Vaudis?"},
            {
                "role": "assistant",
                "content": "Öffne die Kundenverwaltung und ändere den Status.",
                "sources": [{
                    "source": {"name": "rag_chat/rag_chat"},
                    "document": [rag_text],
                    "tool_result": True,
                }],
            },
        ]
    }

    result = module.Filter().outlet(body)
    assert result["messages"][-1]["content"] == guided_answer


def test_active_harness_keeps_completed_rag_answer_unchanged():
    module = load_module()
    answer = (
        "WPS ist als Terminplanungssystem dokumentiert [#1].\n\n"
        "Eine belastbare Schritt-für-Schritt-Anleitung ist in den Quellen nicht enthalten."
    )
    rag_text = (
        "KAHLE_RAG_RESULT\nFOUND: true\n"
        "EVIDENCE_BUNDLE_JSON: {\"schema_version\":\"kahle.evidence-bundle.v1\","
        "\"status\":\"partially_supported\",\"supported_claims\":[],"
        "\"missing_information\":[\"Anleitung fehlt.\"],\"conflicts\":[],"
        "\"sources\":[{\"number\":1}]}\n"
        "CONTEXT:\n[Quelle 1] Systemlandkarte\n"
        "WPS ist ein Terminplanungssystem."
    )
    body = {
        "messages": [
            {"role": "user", "content": "Wie plane ich einen Termin im WPS?"},
            {
                "role": "assistant",
                "content": answer,
                "sources": [{
                    "source": {"name": "rag_chat/rag_chat"},
                    "document": [rag_text],
                    "tool_result": True,
                }],
            },
        ]
    }

    result = module.Filter().outlet(
        body,
        __metadata__={"kahle_knowledge_harness_active": True},
    )

    assert result["messages"][-1]["content"] == answer


def test_active_harness_does_not_disable_technical_pseudo_toolcall_guard():
    module = load_module()
    rag_text = (
        "KAHLE_RAG_RESULT\nFOUND: true\n"
        "EVIDENCE_BUNDLE_JSON: {\"schema_version\":\"kahle.evidence-bundle.v1\","
        "\"status\":\"supported\",\"supported_claims\":[],"
        "\"missing_information\":[],\"conflicts\":[],\"sources\":[]}\n"
        "CONTEXT:\n[Quelle 1] Prozess\nEin belegter interner Prozess."
    )
    body = {
        "messages": [
            {"role": "user", "content": "Erkläre den internen Prozess."},
            {
                "role": "assistant",
                "content": (
                    '[TOOL_CALLS]time_and_calculation'
                    '{"action":"get_current_date_and_time","timezone":"Europe/Berlin"}'
                ),
                "sources": [{
                    "source": {"name": "rag_chat/rag_chat"},
                    "document": [rag_text],
                    "tool_result": True,
                }],
            },
        ]
    }

    result = module.Filter().outlet(
        body,
        __metadata__={"kahle_knowledge_harness_active": True},
    )

    assert result["messages"][-1]["content"].startswith("Tool-Fehler:")


def test_guard_rag_refresh_calls_current_tool_signature_with_user():
    module = load_module()
    with tempfile.TemporaryDirectory() as directory:
        db_path = Path(directory) / "webui.db"
        db = sqlite3.connect(db_path)
        db.execute("CREATE TABLE tool (id TEXT PRIMARY KEY, content TEXT)")
        db.execute(
            "INSERT INTO tool VALUES (?, ?)",
            (
                "rag_chat",
                """
class Tools:
    async def rag_chat(self, query='', __user__=None, __chat_id__='', __message_id__=''):
        return f'{query}|{(__user__ or {}).get("id", "")}'
""",
            ),
        )
        db.commit()
        db.close()
        previous = os.environ.get("WEBUI_DB_PATH")
        os.environ["WEBUI_DB_PATH"] = str(db_path)
        try:
            assert module._call_rag_chat_tool(
                "Wer ist Thomas Keller?", [], {"id": "user-1"}
            ) == "Wer ist Thomas Keller?|user-1"
        finally:
            if previous is None:
                os.environ.pop("WEBUI_DB_PATH", None)
            else:
                os.environ["WEBUI_DB_PATH"] = previous




def test_internal_followup_without_toolcall_is_refreshed_from_rag():
    module = load_module()
    original_call = module._call_rag_chat_tool
    original_synthesize = module._synthesize_rag_answer
    captured = {}
    rag_text = (
        "KAHLE_RAG_RESULT\n"
        "FOUND: true\n"
        "QUERY: Was sind die 5 Dimensionen, die im A1a bewertet werden?\n"
        "META: top1_score=0.801 threshold=0.45 routing=exact_source\n\n"
        "KONTEXT (zitierbar mit [#]):\n"
        "[#1 | testkb | A1a_ki_safety_readiness_check.md | chunk 4 | score 0.801]\n"
        "1. Governance & Verantwortlichkeiten\n"
        "2. Tool-Landschaft & Freigaben\n"
        "3. Datenpraktiken & Klassifizierung\n"
        "4. Prozesse & Human-in-the-Loop\n"
        "5. Dokumentation & Incident"
    )
    try:
        def fake_call(query, messages, user=None):
            captured["query"] = query
            captured["messages"] = messages
            captured["user"] = user
            return rag_text

        module._call_rag_chat_tool = fake_call
        module._synthesize_rag_answer = lambda request_text, source, user_name="": (
            "Die fünf Dimensionen sind Governance & Verantwortlichkeiten, "
            "Tool-Landschaft & Freigaben, Datenpraktiken & Klassifizierung, "
            "Prozesse & Human-in-the-Loop sowie Dokumentation & Incident [#1]."
        )
        previous_rag = (
            "KAHLE_RAG_RESULT\nFOUND: true\n"
            "KONTEXT (zitierbar mit [#]):\n"
            "[#1 | testkb | A1a_ki_safety_readiness_check.md | chunk 0 | score 0.700]\n"
            "A1a ist der KI Safety-Readiness-Check."
        )
        body = {
            "messages": [
                {"role": "user", "content": "Was weißt du intern über A1a?"},
                {
                    "role": "assistant",
                    "content": "A1a ist der KI Safety-Readiness-Check [#1].",
                    "sources": [
                        {
                            "source": {"name": "rag_chat/rag_chat"},
                            "document": [previous_rag],
                            "tool_result": True,
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": "Was sind die 5 Dimensionen, die im A1a bewertet werden?",
                },
                {
                    "role": "assistant",
                    "content": (
                        "Governance, Mitarbeitende, Datenmanagement, "
                        "Technische Infrastruktur und Compliance."
                    ),
                },
            ]
        }

        result = module.Filter().outlet(body)
        answer = result["messages"][-1]

        assert captured["query"] == "Was sind die 5 Dimensionen, die im A1a bewertet werden?"
        assert len(captured["messages"]) == 3
        assert "Governance & Verantwortlichkeiten" in answer["content"]
        assert "Technische Infrastruktur" not in answer["content"]
        assert answer["sources"][-1]["source"]["name"] == "rag_chat/rag_chat"
        assert answer["sources"][-1]["document"] == [rag_text]
    finally:
        module._call_rag_chat_tool = original_call
        module._synthesize_rag_answer = original_synthesize




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


def test_generic_pseudo_toolcall_error_updates_output_text_as_well_as_content():
    module = load_module()
    raw_toolcall = '[TOOL_CALLS]time_and_calculation{"action":"get_current_date_and_time","timezone":"Europe/Berlin"}'
    body = {
        "messages": [
            {"role": "user", "content": "Hey bitte recherchiere einmal zum Volkswagen Passat"},
            {
                "role": "assistant",
                "content": raw_toolcall,
                "originalContent": raw_toolcall,
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": raw_toolcall}],
                    }
                ],
            },
        ]
    }

    result = module.Filter().outlet(body)
    message = result["messages"][-1]

    assert message["content"] == (
        "Tool-Fehler: Das Modell hat einen sichtbaren Pseudo-Toolcall erzeugt. "
        "Bitte stelle die Anfrage in einem neuen Chat erneut."
    )
    assert message["output"][0]["content"][0]["text"] == message["content"]
    assert message["originalContent"] == message["content"]
    assert "[TOOL_CALLS]" not in message["content"]
    assert "[TOOL_CALLS]" not in message["output"][0]["content"][0]["text"]
    assert "[TOOL_CALLS]" not in message["originalContent"]


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


def test_file_saved_source_payload_overrides_mutated_model_download_token():
    module = load_module()
    good_url = "http://localhost:8091/files/download?token=good_2026_token"
    bad_url = "http://localhost:8091/files/download?token=bad_2066_token"
    body = {
        "messages": [
            {"role": "user", "content": "Bitte wandle die PDF in Markdown um."},
            {
                "role": "assistant",
                "content": (
                    f"Download-Link: [Datei herunterladen]({bad_url})\n"
                    "Datei: DE_2.5_KI__KAHLE_Stand_03.2026.md\n"
                    "SHA256: wrong\n"
                    "Groesse: 24664 Bytes"
                ),
                "sources": [
                    {
                        "source": {"name": "server:doc-worker/file_to_md_save"},
                        "document": [
                            '{"output_kind":"file_saved",'
                            f'"download_url":"{good_url}",'
                            '"filename":"DE_2.5_KI__KAHLE_Stand_03.2026.md",'
                            '"sha256":"real-sha",'
                            '"size_bytes":24664}'
                        ],
                        "tool_result": True,
                    }
                ],
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": f"Download-Link: [Datei herunterladen]({bad_url})"}],
                    },
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": f"Debug details {bad_url}"}],
                    }
                ],
            },
        ]
    }

    result = module.Filter().outlet(body)
    message = result["messages"][-1]

    assert good_url in message["content"]
    assert bad_url not in message["content"]
    assert "real-sha" in message["content"]
    assert message["output"][0]["content"][0]["text"] == message["content"]
    assert message["output"][1]["content"][0]["text"] == message["content"]


def test_file_saved_source_payload_syncs_json_encoded_output():
    module = load_module()
    good_url = "http://localhost:8091/files/download?token=good_token"
    bad_url = "http://localhost:8091/files/download?token=bad_token"
    encoded_output = json.dumps(
        [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": f"Download-Link: [Datei herunterladen]({bad_url})",
                    }
                ],
            }
        ]
    )
    body = {
        "messages": [
            {"role": "user", "content": "Erstelle eine Word-Datei."},
            {
                "role": "assistant",
                "content": f"Download-Link: [Datei herunterladen]({bad_url})",
                "sources": [
                    {
                        "source": {"name": "kahle_workflow/kahle_workflow_execute"},
                        "document": [
                            json.dumps(
                                {
                                    "download_url": good_url,
                                    "filename": "test.docx",
                                    "sha256": "real-sha",
                                    "size_bytes": 123,
                                }
                            )
                        ],
                        "tool_result": True,
                    }
                ],
                "output": encoded_output,
            },
        ]
    }

    result = module.Filter().outlet(body)
    message = result["messages"][-1]
    decoded_output = json.loads(message["output"])

    assert good_url in message["content"]
    assert bad_url not in message["content"]
    assert decoded_output[0]["content"][0]["text"] == message["content"]
    assert bad_url not in message["output"]

def test_file_saved_source_payload_syncs_unknown_stream_delta_field():
    module = load_module()
    good_url = "http://localhost:8091/files/download?token=good_migrationstest_token"
    bad_url = "http://localhost:8091/files/download?token=bad_nigrationstest_token"
    body = {
        "messages": [
            {"role": "user", "content": "Erstelle eine Word-Datei."},
            {
                "role": "assistant",
                "content": f"Download-Link: [Datei herunterladen]({bad_url})",
                "sources": [
                    {
                        "source": {"name": "kahle_workflow/kahle_workflow_execute"},
                        "document": [
                            json.dumps(
                                {
                                    "download_url": good_url,
                                    "filename": "migrationstest.docx",
                                    "sha256": "real-sha",
                                    "size_bytes": 123,
                                }
                            )
                        ],
                        "tool_result": True,
                    }
                ],
                "output": json.dumps(
                    [
                        {
                            "type": "response.output_text.delta",
                            "delta": f"Download-Link: [Datei herunterladen]({bad_url})",
                        }
                    ]
                ),
            },
        ]
    }

    result = module.Filter().outlet(body)
    message = result["messages"][-1]
    decoded_output = json.loads(message["output"])

    assert good_url in message["content"]
    assert decoded_output[0]["delta"].endswith(f"({good_url})")
    assert bad_url not in message["output"]

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


def test_successful_safe_webcaller_source_overrides_rag_template_pseudo_call():
    module = load_module()
    raw_toolcall = (
        "[TOOL_CALLS]rag_template>Ich habe keine Moeglichkeit, im Internet zu recherchieren. "
        "Ich kann Ihnen jedoch helfen, eine Praesentation zum Volkswagen Passat zu erstellen."
    )
    safe_result = {
        "ok": True,
        "decision": "proceed",
        "blocked": False,
        "searchQuery": "Volkswagen Passat 2026",
        "summary": "Volkswagen Passat 2026 Recherche Ergebnis mit Variant, Motoren, Ausstattung und Kofferraum.",
        "sources": [
            {
                "title": "Volkswagen Passat Test",
                "url": "https://example.test/passat",
                "snippet": "Passat Variant mit aktuellen Ausstattungsdetails.",
            }
        ],
    }
    body = {
        "messages": [
            {"role": "user", "content": "Hey bitte recherchiere einmal zum Volkswagen Passat"},
            {
                "role": "assistant",
                "content": raw_toolcall,
                "originalContent": raw_toolcall,
                "sources": [
                    {
                        "source": {"name": "safe_webcaller/safe_websearch"},
                        "document": [json.dumps(safe_result)],
                        "tool_result": True,
                    }
                ],
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": raw_toolcall}],
                    }
                ],
            },
        ]
    }

    result = module.Filter().outlet(body)
    message = result["messages"][-1]

    assert "Volkswagen Passat 2026 Recherche Ergebnis" in message["content"]
    assert "Volkswagen Passat Test" in message["content"]
    assert "[TOOL_CALLS]" not in message["content"]
    assert message["output"][0]["content"][0]["text"] == message["content"]
    assert message["originalContent"] == message["content"]


def test_successful_safe_webcaller_source_recovers_existing_pseudo_toolcall_error():
    module = load_module()
    raw_toolcall = (
        "[TOOL_CALLS]rag_template>Ich habe keine Moeglichkeit, im Internet zu recherchieren."
    )
    safe_result = {
        "ok": True,
        "decision": "proceed",
        "blocked": False,
        "summary": "Volkswagen Passat Recherche aus bereits vorhandenem Toolresultat.",
        "sources": [],
    }
    body = {
        "messages": [
            {"role": "user", "content": "Hey bitte recherchiere einmal zum Volkswagen Passat"},
            {
                "role": "assistant",
                "content": (
                    "Tool-Fehler: Das Modell hat einen sichtbaren Pseudo-Toolcall erzeugt. "
                    "Bitte stelle die Anfrage in einem neuen Chat erneut."
                ),
                "originalContent": raw_toolcall,
                "sources": [
                    {
                        "source": {"name": "safe_webcaller/safe_websearch"},
                        "document": [json.dumps(safe_result)],
                        "tool_result": True,
                    }
                ],
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": raw_toolcall}],
                    }
                ],
            },
        ]
    }

    result = module.Filter().outlet(body)
    message = result["messages"][-1]

    assert "Volkswagen Passat Recherche aus bereits vorhandenem Toolresultat" in message["content"]
    assert "Tool-Fehler" not in message["content"]
    assert "[TOOL_CALLS]" not in json.dumps(message, ensure_ascii=False)


def test_visible_json_toolcall_with_safe_web_source_is_recovered():
    module = load_module()
    visible = (
        '{\n  "tool": "safe_webcaller",\n  "parameters": {\n'
        '    "query": "Elektroauto Foerderung 2026 Deutschland aktuelle News",\n'
        '    "lang": "de-DE",\n    "maxResults": 5\n  }\n}'
    )
    safe_result = {
        "ok": True,
        "decision": "proceed",
        "blocked": False,
        "searchQuery": "Elektroauto Foerderung 2026",
        "summary": "Elektroauto-Foerderung 2026: Hoechstfoerderung 6000 Euro fuer Familien mit niedrigem Einkommen.",
        "sources": [
            {
                "title": "Foerderung 2026",
                "url": "https://example.test/ev",
                "snippet": "Details zur Elektroauto-Foerderung 2026.",
            }
        ],
    }
    body = {
        "messages": [
            {"role": "user", "content": "Recherchiere aktuelle Neuigkeiten zur Elektroauto-Foerderung 2026"},
            {
                "role": "assistant",
                "content": visible,
                "originalContent": visible,
                "sources": [
                    {
                        "source": {"name": "safe_webcaller/safe_websearch"},
                        "document": [json.dumps(safe_result)],
                        "tool_result": True,
                    }
                ],
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": visible}]},
                ],
            },
        ]
    }

    result = module.Filter().outlet(body)
    message = result["messages"][-1]

    assert "Hoechstfoerderung 6000 Euro" in message["content"]
    assert '"tool": "safe_webcaller"' not in message["content"]
    assert '"parameters"' not in message["content"]
    assert message["output"][0]["content"][0]["text"] == message["content"]


def test_search_in_progress_meta_answer_is_synthesized_by_llm():
    module = load_module()
    original = module._synthesize_web_answer
    try:
        module._synthesize_web_answer = lambda request_text, result, user_name="": (
            "## E-Auto-Foerderung 2026\n\n"
            "Ab Mai 2026 gibt es eine sozial gestaffelte Foerderung mit Kinderbonus.\n\n"
            "Quellen:\n- ADAC"
        )
        safe_result = {
            "ok": True,
            "decision": "proceed",
            "blocked": False,
            "summary": "E-Auto-Foerderung 2026 sozial gestaffelt, Antraege voraussichtlich ab Mai 2026.",
            "sources": [{"title": "ADAC", "url": "https://example.test/adac", "snippet": "Details"}],
        }
        body = {
            "messages": [
                {"role": "user", "content": "Recherchiere aktuelle Neuigkeiten zur Elektroauto-Foerderung 2026"},
                {
                    "role": "assistant",
                    "content": "Websuche wird durchgefuehrt, um aktuelle Neuigkeiten zur Elektroauto-Foerderung 2026 zu ermitteln.",
                    "sources": [
                        {
                            "source": {"name": "safe_webcaller/safe_websearch"},
                            "document": [json.dumps(safe_result)],
                            "tool_result": True,
                        }
                    ],
                },
            ]
        }
        result = module.Filter().outlet(body)
        content = result["messages"][-1]["content"]
        assert "sozial gestaffelte Foerderung mit Kinderbonus" in content
        assert "Websuche wird durchgefuehrt" not in content
    finally:
        module._synthesize_web_answer = original


def test_web_answer_falls_back_to_deterministic_format_without_llm():
    module = load_module()
    original = module._synthesize_web_answer
    try:
        module._synthesize_web_answer = lambda request_text, result, user_name="": ""
        safe_result = {
            "ok": True,
            "decision": "proceed",
            "blocked": False,
            "summary": "Deterministischer Fallback-Inhalt zur Foerderung.",
            "sources": [{"title": "Quelle", "url": "https://example.test/q", "snippet": "x"}],
        }
        body = {
            "messages": [
                {"role": "user", "content": "Recherchiere zur Foerderung"},
                {
                    "role": "assistant",
                    "content": "",
                    "sources": [
                        {
                            "source": {"name": "safe_webcaller/safe_websearch"},
                            "document": [json.dumps(safe_result)],
                            "tool_result": True,
                        }
                    ],
                },
            ]
        }
        result = module.Filter().outlet(body)
        content = result["messages"][-1]["content"]
        assert "Deterministischer Fallback-Inhalt" in content
        assert "Kurzueberblick" in content
    finally:
        module._synthesize_web_answer = original


def test_failed_research_answer_runs_safe_websearch_fallback():
    module = load_module()
    original_websearch = module._run_websearch
    try:
        captured = {}

        def fake_websearch(query, user_name=""):
            captured["query"] = query
            return {
                "ok": True,
                "summary": "Passat aus Websuche: aktuelle Informationen zu Motoren, Ausstattung und Variant.",
                "sources": [],
            }

        module._run_websearch = fake_websearch
        raw_answer = (
            "Ich kann leider keine externen Recherchen durchfuehren. "
            "Aber ich kann dir helfen, wenn du spezifische Fragen zum Volkswagen Passat hast."
        )
        body = {
            "messages": [
                {"role": "user", "content": "Hey bitte recherchiere einmal zum Volkswagen Passat"},
                {
                    "role": "assistant",
                    "content": raw_answer,
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": raw_answer}],
                        }
                    ],
                },
            ]
        }

        result = module.Filter().outlet(body)
        message = result["messages"][-1]

        assert "Volkswagen Passat" in captured["query"]
        assert "Passat aus Websuche" in message["content"]
        assert "keine externen Recherchen" not in message["content"]
        assert message["output"][0]["content"][0]["text"] == message["content"]
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


def test_blocked_safe_webcaller_source_overrides_model_answer():
    module = load_module()
    notice = "Ich kann die Websuche nicht ausfuehren, weil sensible Daten/Identifier erkannt wurden."
    body = {
        "messages": [
            {"role": "user", "content": "Bitte suche Details zum EU AI Act"},
            {
                "role": "assistant",
                "content": "Hier sind trotzdem Details aus dem vorherigen Kontext.",
                "sources": [
                    {
                        "source": {"name": "safe_webcaller/safe_websearch"},
                        "document": [module.FINAL_NOTICE_PREFIX + notice + module.FINAL_NOTICE_SUFFIX],
                        "metadata": [{"source": "safe_webcaller/safe_websearch"}],
                        "tool_result": True,
                    }
                ],
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "Hier sind trotzdem Details."}],
                    }
                ],
            },
        ]
    }

    result = module.Filter().outlet(body)
    message = result["messages"][-1]

    assert message["content"] == notice
    assert message["output"][0]["content"][0]["text"] == notice


def test_admin_gets_kb_expiry_notice_once_per_day():
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "tasks.db"
        con = sqlite3.connect(db_path)
        con.execute(
            """
            create table tasks (
                id text primary key,
                user_id text,
                title text,
                status text,
                priority text,
                due_date text,
                source_chat_id text
            )
            """
        )
        con.execute(
            "insert into tasks values (?, ?, ?, ?, ?, ?, ?)",
            (
                "kbexp_test",
                "admin-1",
                "Wissensdatei pr\u00fcfen",
                "open",
                "urgent",
                "2026-07-01",
                "system:kb-expiry",
            ),
        )
        con.commit()
        con.close()
        old_path = os.environ.get("KAHLE_TASKS_DB_PATH")
        os.environ["KAHLE_TASKS_DB_PATH"] = str(db_path)
        try:
            first_body = {
                "messages": [
                    {"role": "user", "content": "Hallo"},
                    {"role": "assistant", "content": "Hallo Jan!"},
                ]
            }
            first = module.Filter().outlet(
                first_body,
                __user__={"id": "admin-1", "role": "admin"},
            )
            assert "Wissenspflege" in first["messages"][-1]["content"]

            second_body = {
                "messages": [
                    {"role": "user", "content": "Noch eine Frage"},
                    {"role": "assistant", "content": "Gerne."},
                ]
            }
            second = module.Filter().outlet(
                second_body,
                __user__={"id": "admin-1", "role": "admin"},
            )
            assert "Wissenspflege" not in second["messages"][-1]["content"]
        finally:
            if old_path is None:
                os.environ.pop("KAHLE_TASKS_DB_PATH", None)
            else:
                os.environ["KAHLE_TASKS_DB_PATH"] = old_path


def test_short_download_id_is_valid_and_not_saved_as_wrapper_file():
    module = load_module()
    url = "http://localhost:8091/files/d/efdbf4b281114461a1573e228e3a2235"
    manifest = (
        f"Download-Link: [Datei herunterladen]({url})\n"
        "Datei: Digitales_Autohaus_Teiledienst.md\n"
        "SHA256: abc\nGroesse: 3636 Bytes"
    )
    assert module._has_download_metadata(manifest)
    assert module._has_valid_download_metadata(manifest)

    original_create = module._create_file
    try:
        module._create_file = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("wrapper file created"))
        body = {
            "messages": [
                {"role": "user", "content": "Bitte gib mir die PDF als Markdown aus."},
                {"role": "assistant", "content": manifest},
            ]
        }
        result = module.Filter().outlet(body)
        assert result["messages"][-1]["content"] == manifest
    finally:
        module._create_file = original_create

def test_download_host_is_normalized_to_configured_vinci_host():
    module = load_module()
    original = os.environ.get("PUBLIC_FILE_BASE_URL")
    try:
        os.environ["PUBLIC_FILE_BASE_URL"] = "https://vinci.kahle.de"
        stale = "https://openwebui-dev.kahle.de/files/d/efdbf4b281114461a1573e228e3a2235"
        normalized = module._canonicalize_download_links(f"Download-Link: {stale}")
        assert "https://vinci.kahle.de/files/d/efdbf4b281114461a1573e228e3a2235" in normalized
        assert "openwebui-dev.kahle.de" not in normalized
    finally:
        if original is None:
            os.environ.pop("PUBLIC_FILE_BASE_URL", None)
        else:
            os.environ["PUBLIC_FILE_BASE_URL"] = original
if __name__ == "__main__":
    test_visible_workflow_pseudo_call_is_replaced_with_download_metadata()
    test_fillable_ki_permission_request_never_uses_generic_docx_export()
    test_successful_rag_source_replaces_false_no_internal_knowledge_answer()
    test_internal_followup_without_toolcall_is_refreshed_from_rag()
    test_download_replacement_updates_output_text_as_well_as_content()
    test_generic_pseudo_toolcall_error_updates_output_text_as_well_as_content()
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
    test_successful_safe_webcaller_source_overrides_rag_template_pseudo_call()
    test_successful_safe_webcaller_source_recovers_existing_pseudo_toolcall_error()
    test_failed_research_answer_runs_safe_websearch_fallback()
    test_kb_list_files_pseudo_call_is_replaced_with_file_inventory()
    test_kb_list_files_pseudo_call_accepts_collection_name_alias()
    test_reasoning_leak_for_research_request_is_replaced_with_formatted_text()
    test_blocked_safe_webcaller_source_overrides_model_answer()
    test_admin_gets_kb_expiry_notice_once_per_day()
    test_file_saved_source_payload_overrides_mutated_model_download_token()
    test_download_host_is_normalized_to_configured_vinci_host()
    print("kahle toolcall guard tests passed")

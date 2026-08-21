from __future__ import annotations

import asyncio
import ast
import copy
import re
import unicodedata
from typing import Any, Optional
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIDDLEWARE = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "middleware.py"


def load_rag_routing_helpers():
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    wanted = {
        "_ascii_fold",
        "_contains_token",
        "_looks_like_raw_email_text",
        "_has_explicit_internal_lookup_intent",
        "_looks_like_named_person_question",
        "_looks_like_internal_rag_request",
    }
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"re": re, "unicodedata": unicodedata}
    exec(compile(module, str(MIDDLEWARE), "exec"), namespace)
    return namespace["_looks_like_internal_rag_request"]


def load_native_rag_fallback():
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    wanted = {
        "_ascii_fold",
        "_contains_token",
        "_looks_like_raw_email_text",
        "_has_explicit_internal_lookup_intent",
        "_looks_like_named_person_question",
        "_looks_like_internal_rag_request",
        "_build_native_rag_fallback",
    }
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "Any": Any,
        "asyncio": asyncio,
        "re": re,
        "unicodedata": unicodedata,
        "uuid4": lambda: type("FixedUuid", (), {"hex": "a" * 32})(),
        "json": __import__("json"),
    }
    exec(compile(module, str(MIDDLEWARE), "exec"), namespace)
    return namespace["_build_native_rag_fallback"]


def load_function_from_middleware(name: str):
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    nodes = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    aliases = {
        "TD": "Teiledienst",
        "VK": "Verkauf",
        "NIE": "Nienburg",
        "HAN": "Hannover",
        "SHG": "Stadthagen",
    }
    namespace = {
        "Any": Any,
        "asyncio": asyncio,
        "re": re,
        "resolve_query_aliases": lambda query: __import__("functools").reduce(
            lambda value, item: re.sub(
                rf"(?<!\w){re.escape(item[0])}(?!\w)",
                item[1],
                value,
                flags=re.IGNORECASE,
            ),
            aliases.items(),
            str(query or ""),
        ),
    }
    exec(compile(module, str(MIDDLEWARE), "exec"), namespace)
    return namespace[name]


def load_canonical_rag_source_helpers():
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    wanted = {
        "_extract_kahle_rag_sources",
        "_canonical_kahle_rag_source_events",
        "_append_canonical_rag_source_links",
    }
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"Any": Any, "re": re, "json": __import__("json")}
    exec(compile(module, str(MIDDLEWARE), "exec"), namespace)
    return namespace


def load_canonical_rag_feedback_helpers():
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    wanted = {"_extract_kahle_rag_feedback_link", "_append_canonical_rag_feedback_link"}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"Any": Any, "re": re}
    exec(compile(module, str(MIDDLEWARE), "exec"), namespace)
    return namespace


def test_stream_strip_hides_json_toolcall():
    strip = load_function_from_middleware("_strip_pseudo_toolcall_stream_text")
    assert strip('{\n  "tool": "safe_webcaller",\n  "parameters": {"query": "x"}\n}') == ""
    assert strip('{"tool_calls": [{"name": "safe_websearch"}]}') == ""
    assert strip('  {"name": "rag_chat", "parameters": {}}') == ""


def test_stream_strip_keeps_normal_answer_and_legacy_marker():
    strip = load_function_from_middleware("_strip_pseudo_toolcall_stream_text")
    assert strip("Zusammenfassung: Die Foerderung betraegt 6000 Euro.") == "Zusammenfassung: Die Foerderung betraegt 6000 Euro."
    assert strip("Hier ist die Antwort.[TOOL_CALLS]safe_websearch{}") == "Hier ist die Antwort."
    # A normal JSON snippet that is not a tool call must be preserved.
    assert strip('{"foerderung": 6000}') == '{"foerderung": 6000}'


def test_stream_strip_hides_partial_json_toolcall_while_streaming():
    """The thinking model (Responses API) pretty-prints a JSON tool call as the
    visible answer; it streams in incrementally. Every partial prefix the stream
    emits must already be blanked, otherwise the raw '{ "tool" ...' fragment
    flashes in the UI before the outlet guard replaces it."""
    strip = load_function_from_middleware("_strip_pseudo_toolcall_stream_text")
    # Real captured shape from kahle-vinci-thinking (leading newline, multi-line).
    full = '\n{\n  "tool": "safe_webcaller",\n  "parameters": {"query": "Elektroauto 2026"}\n}'
    for i in range(1, len(full) + 1):
        out = strip(full[:i])
        assert "{" not in out and "tool" not in out and "safe_webcaller" not in out, (
            f"leaked raw tool-call fragment at prefix length {i}: {out!r}"
        )
    assert strip(full) == ""


def test_stream_strip_reveals_legit_json_once_first_key_known():
    """A legit JSON answer whose first key is not a tool-call key must survive,
    even though its opening brace is briefly held back while streaming."""
    strip = load_function_from_middleware("_strip_pseudo_toolcall_stream_text")
    assert strip('{"foerderung": 6000, "jahr": 2026}') == '{"foerderung": 6000, "jahr": 2026}'
    # While the first key is still incomplete, the partial brace is held back
    # (returns empty) so nothing flashes; this is acceptable for a JSON answer.
    assert strip('{"foer') == ""
    assert strip('{"foer"') == ""
    # Content that merely starts with '{' but is not a string-keyed object
    # (e.g. a template) must not be over-suppressed.
    assert strip('{{kunde.name}}, willkommen!') == '{{kunde.name}}, willkommen!'
    assert strip('{}') == '{}'


def test_internal_rag_routing_detects_recovery_gutschein():
    looks_internal = load_rag_routing_helpers()

    assert looks_internal("Ich habe einen Kunden mit Recovery Gutschein, was muss ich machen?") is True


def test_internal_rag_routing_detects_wps_appointment_process():
    looks_internal = load_rag_routing_helpers()

    assert looks_internal("Wie plane ich einen Termin im WPS?") is True


def test_internal_rag_routing_detects_internal_person_question_without_company_keyword():
    looks_internal = load_rag_routing_helpers()

    assert looks_internal("Wer ist Engin Bayir?") is True


def test_prerouted_generic_opening_hours_keeps_clarification_answer():
    outcome = load_function_from_middleware("_internal_rag_source_outcome")
    clarification = load_function_from_middleware("_internal_rag_clarification")
    sources = [{
        "source": {"name": "rag_chat/rag_chat"},
        "document": [
            "KAHLE_RAG_RESULT\nFOUND: false\n"
            "CLARIFICATION_REQUIRED: true\n"
            "ANSWER: Für welchen Standort brauchst du die Öffnungszeiten?"
        ],
    }]

    assert outcome(sources) == "clarification"
    assert clarification(sources) == (
        "Für welchen Standort brauchst du die Öffnungszeiten?"
    )


def test_opening_hours_clarification_followup_is_internal_rag_request():
    helper = load_function_from_middleware("_is_internal_clarification_followup")
    messages = [
        {"role": "user", "content": "Wie sind unsere Öffnungszeiten?"},
        {
            "role": "assistant",
            "content": (
                "Für welchen Standort und welchen Bereich (Verkauf, Service oder "
                "Teiledienst) brauchst du die Öffnungszeiten?"
            ),
        },
        {"role": "user", "content": "allgemein alles"},
    ]

    assert helper(messages, "allgemein alles") is True


def test_opening_hours_followup_expands_to_one_complete_rag_query():
    helper = load_function_from_middleware("_expanded_internal_rag_query")
    messages = [
        {"role": "user", "content": "Wie sind unsere Öffnungszeiten?"},
        {
            "role": "assistant",
            "content": (
                "Für welchen Standort und welchen Bereich (Verkauf, Service oder "
                "Teiledienst) brauchst du die Öffnungszeiten?"
            ),
        },
        {"role": "user", "content": "allgemein alles"},
    ]

    expanded = helper(messages, "allgemein alles")

    assert expanded.startswith("Öffnungszeiten Verkauf Service Teiledienst")
    for location in (
        "Hannover", "Wunstorf", "Wedemark", "Walsrode",
        "Neustadt am Rübenberge", "Nienburg", "Stadthagen",
    ):
        assert location in expanded


def test_opening_hours_abbreviation_followup_expands_before_routing():
    expand = load_function_from_middleware("_expanded_internal_rag_query")
    is_followup = load_function_from_middleware("_is_internal_clarification_followup")
    messages = [
        {"role": "user", "content": "Wie sind unsere Öffnungszeiten?"},
        {
            "role": "assistant",
            "content": (
                "Für welchen Standort und welchen Bereich (Verkauf, Service oder "
                "Teiledienst) brauchst du die Öffnungszeiten?"
            ),
        },
        {"role": "user", "content": "TD in NIE"},
    ]

    expanded = expand(messages, "TD in NIE")

    assert expanded == "Teiledienst in Nienburg"
    assert is_followup(messages, expanded) is True


def test_customer_lock_marketing_followup_keeps_clarification_context():
    helper = load_function_from_middleware("_expanded_internal_rag_query")
    messages = [
        {"role": "user", "content": "Wie sperre ich einen Kunden in Vaudis?"},
        {
            "role": "assistant",
            "content": (
                "Geht es darum, Werbung und Befragungen für den Kunden zu sperren, "
                "oder um eine allgemeine Kundensperre in Vaudis?"
            ),
        },
        {"role": "user", "content": "Werbung"},
    ]

    assert helper(messages, "Werbung") == (
        "Wie sperre ich Werbung und automatisierte Befragungen für einen Kunden "
        "in Vaudis über die DSE-Kontaktfreigaben?"
    )


def test_customer_lock_general_followup_keeps_clarification_context():
    helper = load_function_from_middleware("_expanded_internal_rag_query")
    messages = [
        {"role": "user", "content": "Wie sperre ich einen Kunden in Vaudis?"},
        {
            "role": "assistant",
            "content": (
                "Geht es darum, Werbung und Befragungen für den Kunden zu sperren, "
                "oder um eine allgemeine Kundensperre in Vaudis?"
            ),
        },
        {"role": "user", "content": "allgemeine Sperre"},
    ]

    assert helper(messages, "allgemeine Sperre") == (
        "Wie veranlasse ich eine allgemeine Kundensperre in Vaudis?"
    )


def test_internal_answer_stream_is_suppressed_even_when_preroute_found_context():
    source = MIDDLEWARE.read_text(encoding="utf-8")
    block = source[source.index("suppress_initial_rag_response = (") :]
    block = block[: block.index("\n            )")]

    assert "kahle_internal_rag_prerouted') != 'found'" not in block


def test_internal_rag_routing_does_not_treat_internet_as_intern():
    looks_internal = load_rag_routing_helpers()

    assert looks_internal("Bitte recherchiere wie Spaghetti hergestellt werden im Internet") is False


def test_internal_rag_routing_does_not_auto_route_raw_mail_drafts():
    looks_internal = load_rag_routing_helpers()

    raw_mail = """Hallo Herr Langhorst,

ich habe die beiden weiteren DA-Center soweit vorbereitet mit den Daten, die ich habe.
Ich benoetige letztlich noch jeweils die Dokumenten-ID fuer die CSV-Datei.

Fuer Walsrode finde ich aber keinen einzigen Termin in CATCH.

Viele Gruesse
Jan"""

    assert looks_internal(raw_mail) is False


def test_internal_rag_routing_does_not_auto_route_raw_mail_without_signoff():
    looks_internal = load_rag_routing_helpers()

    raw_mail = """Hallo Herr Langhorst,
ich habe die beiden weiteren DA-Center soweit vorbereitet mit den Daten, die ich habe.
Ich benoetige letztlich noch jeweils die Dokumenten-ID fuer die CSV-Datei,
die fuer das jeweilige Center abgerufen werden soll aus dem GUDAT-System.
Fuer Walsrode finde ich aber keinen einzigen Termin in CATCH.
Das liegt vermutlich daran, dass die abgerufene Quelldatei gudat_4357.csv 12 Spalte hat."""

    assert looks_internal(raw_mail) is False


def test_internal_rag_routing_does_not_auto_route_answer_mail_command_with_raw_mail():
    looks_internal = load_rag_routing_helpers()

    raw_mail = """Beantworte die Mail:
Hallo Herr Langhorst,
ich habe die beiden weiteren DA-Center soweit vorbereitet mit den Daten, die ich habe.
Ich benoetige letztlich noch jeweils die Dokumenten-ID fuer die CSV-Datei.
Fuer Walsrode finde ich aber keinen einzigen Termin in CATCH."""

    assert looks_internal(raw_mail) is False


def test_internal_rag_routing_still_detects_explicit_internal_policy_questions():
    looks_internal = load_rag_routing_helpers()

    assert looks_internal("Was sagt unsere interne Richtlinie zur Nutzung von Kundendaten in Mails?") is True


def test_native_function_calling_cannot_bypass_internal_rag():
    fallback = load_native_rag_fallback()

    calls = fallback(
        {"rag_chat": object()},
        "Was sagt unsere interne Richtlinie zur Nutzung von Kundendaten?",
        [],
        [{"type": "message", "content": [{"type": "output_text", "text": "Geraten"}]}],
    )

    assert calls[0][0]["function"]["name"] == "rag_chat"
    assert "interne Richtlinie" in calls[0][0]["function"]["arguments"]


def test_native_rag_fallback_does_not_repeat_after_tool_result():
    fallback = load_native_rag_fallback()

    assert fallback(
        {"rag_chat": object()},
        "Was sagt unsere interne Richtlinie?",
        [],
        [{"type": "function_call_output"}],
    ) == []


def test_canonical_source_link_replaces_model_invented_host():
    helpers = load_canonical_rag_source_helpers()
    tool_result = (
        'KAHLE_RAG_RESULT\nFOUND: true\nSOURCES_JSON: '
        '[{"title":"Policy","source_url":"/wissen/api/portal/sources/v1"}]\n'
        'FEEDBACK_LINK: x'
    )
    sources = helpers["_extract_kahle_rag_sources"](tool_result)
    output = [{
        "type": "message",
        "content": [{
            "type": "output_text",
            "text": "Details: [Policy](https://kahle.wissen/api/portal/sources/v1)",
        }],
    }]

    helpers["_append_canonical_rag_source_links"](output, sources)

    text = output[0]["content"][0]["text"]
    assert "https://kahle.wissen" not in text
    assert "[Policy](/wissen/api/portal/sources/v1)" in text


def test_canonical_source_link_replaces_existing_model_source_section_once():
    helpers = load_canonical_rag_source_helpers()
    sources = [{
        "title": "Policy",
        "source_url": "/wissen/api/portal/sources/v1",
    }]
    output = [{
        "type": "message",
        "content": [{
            "type": "output_text",
            "text": (
                "Die belegte Antwort [1].\n\n"
                "Quellen:\n- [Policy](/wissen/api/portal/sources/v1)"
            ),
        }],
    }]

    helpers["_append_canonical_rag_source_links"](output, sources)

    text = output[0]["content"][0]["text"]
    assert text.count("Quellen:") == 1
    assert text.count("[Policy](/wissen/api/portal/sources/v1)") == 1


def test_canonical_rag_source_event_names_the_document_instead_of_the_tool():
    helpers = load_canonical_rag_source_helpers()
    sources = [{
        "title": "WPS Bedienungsanleitung",
        "source_url": "/wissen/api/portal/sources/version-1",
        "document_id": "doc-1",
        "version_id": "version-1",
        "knowledgebase_ids": ["kb-service"],
        "evidence_text": "Terminmaske öffnen und Kunden auswählen.",
    }]

    events = helpers["_canonical_kahle_rag_source_events"](sources)

    assert events == [{
        "source": {
            "name": "WPS Bedienungsanleitung",
            "url": "/wissen/api/portal/sources/version-1",
        },
        "document": ["Terminmaske öffnen und Kunden auswählen."],
        "metadata": [{
            "document_id": "doc-1",
            "version_id": "version-1",
            "knowledgebase_ids": ["kb-service"],
            "source": "WPS Bedienungsanleitung",
            "url": "/wissen/api/portal/sources/version-1",
        }],
    }]


def test_canonical_feedback_link_replaces_plain_model_text_with_clickable_portal_link():
    helpers = load_canonical_rag_feedback_helpers()
    tool_result = (
        "KAHLE_RAG_RESULT\nFOUND: true\n"
        "FEEDBACK_LINK: [Wissensfehler melden](/wissen/?feedback=1&chat_id=chat-1&message_id=msg-1)"
    )
    link = helpers["_extract_kahle_rag_feedback_link"](tool_result)
    output = [{
        "type": "message",
        "content": [{"type": "output_text", "text": "Die Antwort.\n\nWissensfehler melden"}],
    }]

    helpers["_append_canonical_rag_feedback_link"](output, link)

    assert output[0]["content"][0]["text"] == (
        "Die Antwort.\n\n"
        "[Wissensfehler melden](/wissen/?feedback=1&chat_id=chat-1&message_id=msg-1)"
    )


def test_canonical_feedback_link_accepts_transition_links_with_source_references():
    helpers = load_canonical_rag_feedback_helpers()
    tool_result = (
        "KAHLE_RAG_RESULT\nFOUND: true\n"
        "FEEDBACK_LINK: [Wissensfehler melden]"
        "(/wissen/?feedback=1&chat_id=chat-1&message_id=msg-1"
        "&document_ids=doc-1%2Cdoc-2&knowledgebase_ids=kb-service)"
    )
    link = helpers["_extract_kahle_rag_feedback_link"](tool_result)
    assert link.endswith("&knowledgebase_ids=kb-service")


def test_last_kahle_answer_text_reads_only_the_final_message_output():
    helper = load_function_from_middleware("_last_kahle_answer_text")
    output = [
        {"type": "reasoning", "content": [{"type": "output_text", "text": "intern"}]},
        {"type": "message", "content": [{"type": "output_text", "text": "Antwort eins"}]},
        {"type": "message", "content": [{"type": "output_text", "text": "Antwort zwei "}]},
    ]

    assert helper(output) == "Antwort zwei"


def test_active_harness_validates_hidden_answer_and_retries_once_before_final_output():
    source = MIDDLEWARE.read_text(encoding="utf-8")

    assert "validate_knowledge_harness_answer(" in source
    assert "validation.retry_prompt()" in source
    assert "suppress_initial_rag_response = True" in source
    assert "retry_form_data.pop('tools', None)" in source
    assert "retry_form_data.pop('tool_choice', None)" in source
    assert "metadata['kahle_answer_validation']" in source
    assert "kahle_answer_validation_fallback" in source
    assert "'kahle_answer_validation': metadata['kahle_answer_validation']" in source


def test_realtime_chat_save_persists_harness_validation_and_metrics_server_side():
    source = MIDDLEWARE.read_text(encoding="utf-8")
    realtime_block = source[source.index("realtime_metadata = {") :]
    realtime_block = realtime_block[: realtime_block.index("# Send a webhook notification")]

    assert "'kahle_answer_validation': metadata['kahle_answer_validation']" in realtime_block
    assert "'kahle_harness_metrics': metadata['kahle_harness_metrics']" in realtime_block
    assert "{'done': True, **realtime_metadata}" in realtime_block


def test_active_harness_answer_stream_timeout_ends_a_never_finishing_stream():
    helper = load_function_from_middleware("_await_kahle_answer_stream")

    async def never_finishes():
        await asyncio.Event().wait()

    assert asyncio.run(helper(never_finishes(), timeout_seconds=0.01)) is True


def test_active_harness_timeout_is_wired_to_a_safe_visible_delivery_state():
    source = MIDDLEWARE.read_text(encoding="utf-8")

    assert "_knowledge_harness_answer_timeout_seconds()" in source
    assert source.count("_await_kahle_answer_stream(") >= 3
    assert "metadata['kahle_answer_stream_timed_out'] = True" in source
    assert "'safe_timeout_fallback'" in source


def load_fallback_tool_helpers():
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    wanted = {
        "_ascii_fold",
        "_infer_generated_file_output_format",
        "_looks_like_previous_result_file_request",
        "_infer_fallback_tool_calls",
    }
    nodes = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in wanted]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "Any": Any,
        "Optional": Optional,
        "re": re,
        "unicodedata": unicodedata,
        "tools": {"kahle_workflow_execute": object()},
        "attached_file_names": [],
        "attached_exact_paths": [],
        "_looks_like_internal_rag_request": lambda text: False,
    }
    exec(compile(module, str(MIDDLEWARE), "exec"), namespace)
    return namespace["_infer_fallback_tool_calls"]


def test_previous_result_word_request_routes_to_workflow_before_streaming():
    infer_fallback = load_fallback_tool_helpers()

    calls = infer_fallback(
        {},
        "Bitte gib mir das Ergebnis einmal strukturiert als WOrd aus",
    )

    assert calls == [
        {
            "name": "kahle_workflow_execute",
            "parameters": {
                "auftrag": "Bitte gib mir das Ergebnis einmal strukturiert als WOrd aus",
                "output_format": "docx",
            },
        }
    ]


def test_direct_word_creation_request_routes_to_workflow_before_streaming():
    infer_fallback = load_fallback_tool_helpers()

    calls = infer_fallback(
        {},
        (
            "Erstelle eine Word-Datei mit der Ueberschrift KAHLE-Vinci Migrationstest "
            "und einem kurzen Absatz, dass die Servermigration erfolgreich geprueft wurde."
        ),
    )

    assert calls == [
        {
            "name": "kahle_workflow_execute",
            "parameters": {
                "auftrag": (
                    "Erstelle eine Word-Datei mit der Ueberschrift KAHLE-Vinci Migrationstest "
                    "und einem kurzen Absatz, dass die Servermigration erfolgreich geprueft wurde."
                ),
                "output_format": "docx",
            },
        }
    ]


def load_stream_safe_output():
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    wanted = {"_strip_pseudo_toolcall_stream_text", "_stream_safe_output"}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"copy": copy, "re": re}
    exec(compile(module, str(MIDDLEWARE), "exec"), namespace)
    return namespace["_stream_safe_output"]


def test_stream_safe_output_hides_visible_pseudo_toolcall_text():
    stream_safe_output = load_stream_safe_output()
    output = [
        {
            "type": "message",
            "content": [
                {
                    "type": "output_text",
                    "text": 'Ich erstelle die Datei.[TOOL_CALLS]kahle_workflow_execute{"output_format":"docx"}',
                }
            ],
        }
    ]

    safe = stream_safe_output(output)

    assert safe[0]["content"][0]["text"] == "Ich erstelle die Datei."
    assert output[0]["content"][0]["text"].startswith("Ich erstelle die Datei.[TOOL_CALLS]")


def test_stream_safe_output_blanks_thinking_model_json_toolcall():
    """kahle-vinci-thinking (Responses API) emits a reasoning item followed by a
    message item whose text is a pretty-printed JSON tool call. The stream-safe
    view (used for both streaming and the final `done` emit) must blank that
    message text so the raw block never reaches the browser, while leaving the
    underlying output untouched so the outlet guard can still recover."""
    stream_safe_output = load_stream_safe_output()
    output = [
        {"type": "reasoning", "summary": [{"type": "summary_text", "text": "Thought"}]},
        {
            "type": "message",
            "content": [
                {
                    "type": "output_text",
                    "text": '\n{\n  "tool": "safe_webcaller",\n  "parameters": {"query": "Elektroauto 2026"}\n}',
                }
            ],
        },
    ]

    safe = stream_safe_output(output)

    assert safe[1]["content"][0]["text"] == ""
    # Original output is preserved (deepcopy) so the guard still sees the leak.
    assert "safe_webcaller" in output[1]["content"][0]["text"]


def test_stream_safe_output_hides_unsupported_initial_internal_answer():
    stream_safe_output = load_stream_safe_output()
    output = [
        {
            "type": "message",
            "content": [
                {
                    "type": "output_text",
                    "text": "Um einen Termin im WPS zu planen, folge diesen erfundenen Schritten.",
                }
            ],
        }
    ]

    safe = stream_safe_output(output, suppress_message_text=True)

    assert safe[0]["content"][0]["text"] == ""
    assert "erfundenen Schritten" in output[0]["content"][0]["text"]


def test_stream_safe_output_hides_thinking_reasoning_for_unsupported_internal_answer():
    stream_safe_output = load_stream_safe_output()
    output = [
        {
            "type": "reasoning",
            "summary": [
                {
                    "type": "summary_text",
                    "text": "No internal result, so I will answer from general knowledge.",
                }
            ],
        },
        {
            "type": "message",
            "content": [{"type": "output_text", "text": "Erfundene WPS-Anleitung"}],
        },
    ]

    safe = stream_safe_output(output, suppress_message_text=True)

    assert safe[0]["summary"][0]["text"] == ""
    assert safe[1]["content"][0]["text"] == ""


def test_native_internal_rag_suppression_is_wired_before_initial_stream():
    source = MIDDLEWARE.read_text(encoding="utf-8")

    assert "force_internal_rag = (" in source
    assert "if force_internal_rag:" in source
    assert "pre_route_tools = {'rag_chat': tools_dict['rag_chat']}" in source
    assert "form_data, flags = await chat_completion_tools_handler(" in source
    assert "suppress_initial_rag_response = (" in source
    assert "return _stream_safe_output(" in source
    assert "suppress_message_text=suppress_initial_rag_response" in source
    assert "suppress_initial_rag_response = False" in source


def test_prerouted_rag_is_not_exposed_to_native_model_for_a_second_call():
    source = MIDDLEWARE.read_text(encoding="utf-8")

    assert "native_tools_dict =" in source
    assert "if not (force_internal_rag and name == 'rag_chat' and pre_routed_internal_rag)" in source


def test_prerouted_rag_replaces_generic_tool_source_even_without_documents():
    source = MIDDLEWARE.read_text(encoding="utf-8")
    block = source[source.index("canonical_pre_route_events =") :]
    block = block[: block.index("if pre_routed_internal_rag:")]

    assert "sources[:] = [" in block
    assert "if 'rag_chat' not in str(" in block
    assert block.index("sources[:] = [") < block.index("if canonical_pre_route_events:")


if __name__ == "__main__":
    test_internal_rag_routing_detects_recovery_gutschein()
    test_internal_rag_routing_does_not_treat_internet_as_intern()
    test_internal_rag_routing_does_not_auto_route_raw_mail_drafts()
    test_internal_rag_routing_does_not_auto_route_raw_mail_without_signoff()
    test_internal_rag_routing_does_not_auto_route_answer_mail_command_with_raw_mail()
    test_internal_rag_routing_still_detects_explicit_internal_policy_questions()
    test_previous_result_word_request_routes_to_workflow_before_streaming()
    test_stream_safe_output_hides_visible_pseudo_toolcall_text()
    print("middleware internal rag routing tests passed")

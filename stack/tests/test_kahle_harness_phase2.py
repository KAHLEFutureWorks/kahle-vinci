import asyncio
import ast
import copy
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "kahle_knowledge_harness.py"
MIDDLEWARE = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "middleware.py"


def load_harness():
    spec = importlib.util.spec_from_file_location("kahle_harness_phase2", HARNESS)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def load_middleware_functions(*names, **extra_globals):
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    nodes = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
    ]
    assert {node.name for node in nodes} == set(names)
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    namespace = {"Any": Any, "asyncio": asyncio, "copy": copy, "json": json, "re": re,
                 "os": __import__("os"), **extra_globals}
    exec(compile(module, str(MIDDLEWARE), "exec"), namespace)
    return namespace


PERSONIO_MISS = {"status": "not_found", "claims": [], "sources": [], "sync_completed_at": None, "stale": False}


def test_contract_forbids_citations_without_an_existing_source():
    harness = load_harness()
    decision = harness.build_decision(
        query="Wer ist Zyx Nichtvorhandenmann?", resolved_query="Wer ist Zyx Nichtvorhandenmann?",
        messages=[], model_id="m", permission_scope={"user_id": "u"}, rag_result="",
        personio_result=PERSONIO_MISS,
    )

    prompt = decision.answer_prompt()
    assert "Zitiere ausschließlich Quellen-IDs aus evidence_bundle.source_ids" in prompt
    assert "Ist source_ids leer, setze kein Zitat" in prompt
    assert harness.validate_answer("Dazu gibt es keinen Eintrag [P1].", decision.to_dict()).retry_required


def test_retry_prompt_names_allowed_sources_and_concrete_fixes():
    harness = load_harness()
    validation = harness.AnswerValidation(
        schema_version="kahle.answer-validation.v1", status="retry_required",
        violations=(
            {"code": "unknown_source_id", "severity": "blocking", "message": "x", "source_ids": ["P1"]},
            {"code": "citation_missing", "severity": "blocking", "message": "y"},
            {"code": "unsupported_example", "severity": "advisory", "message": "z"},
        ),
    )

    prompt = validation.retry_prompt(source_ids=("1", "2"))

    assert prompt.startswith("KAHLE_KNOWLEDGE_ANSWER_RETRY\n")
    payload = json.loads(prompt.split("\n", 1)[1])
    assert payload["allowed_source_ids"] == ["[1]", "[2]"]
    assert [item["code"] for item in payload["violations"]] == ["unknown_source_id", "citation_missing"]
    assert "Entferne jedes Zitat, das nicht in allowed_source_ids steht." in payload["instructions"]
    assert "Belege jede interne Aussage mit einer Quellen-ID aus allowed_source_ids." in payload["instructions"]


def test_retry_prompt_without_sources_forbids_citations():
    harness = load_harness()
    validation = harness.AnswerValidation("kahle.answer-validation.v1", "retry_required",
        ({"code": "unknown_source_id", "severity": "blocking", "message": "x"},))

    payload = json.loads(validation.retry_prompt().split("\n", 1)[1])

    assert payload["allowed_source_ids"] == []
    assert "Setze kein Zitat." in payload["instructions"]


def test_abstention_answer_is_neutral_and_mentions_sources_only_if_present():
    harness = load_harness()

    assert harness.knowledge_abstention_answer(has_sources=False) == (
        "Dazu habe ich keine verlässliche freigegebene Information."
    )
    with_sources = harness.knowledge_abstention_answer(has_sources=True)
    assert with_sources.startswith("Dazu habe ich keine verlässliche freigegebene Information.")
    assert "Quellen" in with_sources
    assert "[" not in with_sources


def test_enforcement_mode_defaults_to_observe(monkeypatch):
    mode = load_middleware_functions("_answer_enforcement_mode")["_answer_enforcement_mode"]
    monkeypatch.delenv("KAHLE_ANSWER_ENFORCEMENT", raising=False)
    assert mode() == "observe"
    monkeypatch.setenv("KAHLE_ANSWER_ENFORCEMENT", "enforce")
    assert mode() == "enforce"
    monkeypatch.setenv("KAHLE_ANSWER_ENFORCEMENT", "kaputt")
    assert mode() == "observe"


def test_retry_timeout_depends_on_base_model(monkeypatch):
    namespace = load_middleware_functions("_answer_retry_timeout")
    namespace["_DEFAULT_ANSWER_RETRY_TIMEOUTS"] = {"default": 45, "Qwen/": 120}
    timeout = namespace["_answer_retry_timeout"]
    monkeypatch.delenv("KAHLE_ANSWER_RETRY_TIMEOUTS", raising=False)
    assert timeout("mistralai/Mistral-Small-24B-Instruct") == 45
    assert timeout("Qwen/Qwen3.5-397B-A17B") == 120
    monkeypatch.setenv("KAHLE_ANSWER_RETRY_TIMEOUTS", '{"default": 30, "openai/": 60}')
    assert timeout("openai/gpt-oss-120b") == 60
    assert timeout("Qwen/Qwen3.5-397B-A17B") == 30


def test_default_retry_timeouts_give_qwen_more_time():
    source = MIDDLEWARE.read_text(encoding="utf-8")

    assert "_DEFAULT_ANSWER_RETRY_TIMEOUTS = {'default': 45, 'Qwen/': 120}" in source


def test_retry_messages_keep_systems_first_and_flatten_tool_results():
    build = load_middleware_functions("_knowledge_retry_messages")["_knowledge_retry_messages"]
    messages = [
        {"role": "system", "content": "Systemprompt"},
        {"role": "system", "content": "KAHLE_KNOWLEDGE_ANSWER_CONTRACT\n{}"},
        {"role": "user", "content": "Frühere Frage"},
        {"role": "assistant", "content": "Frühere Antwort"},
        {"role": "user", "content": "Aktuelle Frage"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "fc_pre", "type": "function"}]},
        {"role": "tool", "tool_call_id": "fc_pre", "content": "KAHLE_RAG_RESULT\n[2] Vorab-Beleg"},
    ]
    output = [
        {"type": "function_call", "call_id": "call_1", "name": "rag_chat", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "call_1", "output": [{"type": "input_text", "text": "KAHLE_RAG_RESULT\n[1] Beleg"}]},
        {"type": "message", "content": [{"type": "output_text", "text": "Entwurf ohne Zitat."}]},
    ]

    result = build(messages, output, "KAHLE_KNOWLEDGE_ANSWER_RETRY\n{}")

    roles = [item["role"] for item in result]
    assert roles == ["system", "system", "user", "assistant", "user", "user", "assistant", "user"]
    assert "rag_chat" in result[5]["content"] and "[1] Beleg" in result[5]["content"]
    assert "[2] Vorab-Beleg" in result[5]["content"]
    assert result[6]["content"] == "Entwurf ohne Zitat."
    assert result[7]["content"].startswith("KAHLE_KNOWLEDGE_ANSWER_RETRY")
    assert all("tool_calls" not in item and item["role"] != "tool" for item in result)


@pytest.mark.parametrize(
    "response, expected",
    [
        ({"choices": [{"message": {"content": "<think>x</think>\n\nAntwort [1]."}}]}, "Antwort [1]."),
        ({"choices": [{"message": {"content": "\n\nAntwort [1]."}}]}, "Antwort [1]."),
        ({"choices": []}, ""),
    ],
)
def test_completion_text_strips_reasoning(response, expected):
    extract = load_middleware_functions("_completion_text")["_completion_text"]
    assert extract(response) == expected


def test_replace_last_answer_text_only_touches_the_final_message():
    replace_text = load_middleware_functions("_replace_last_answer_text")["_replace_last_answer_text"]
    output = [
        {"type": "message", "content": [{"type": "output_text", "text": "alt 1"}]},
        {"type": "function_call", "name": "rag_chat"},
        {"type": "message", "content": [{"type": "output_text", "text": "alt 2"}]},
    ]

    replace_text(output, "neu")

    assert output[0]["content"][0]["text"] == "alt 1"
    assert output[2]["content"][0]["text"] == "neu"


def _enforce_namespace():
    harness = load_harness()
    namespace = load_middleware_functions(
        "_enforce_knowledge_answer", "_knowledge_retry_messages",
        "_replace_last_answer_text", "_last_kahle_answer_text",
        validate_knowledge_harness_answer=harness.validate_answer,
        knowledge_abstention_answer=harness.knowledge_abstention_answer,
    )
    return harness, namespace["_enforce_knowledge_answer"]


def _payload(harness):
    rag = "KAHLE_RAG_RESULT\nFOUND: true\nCONTEXT:\n[1] Handbuch | A\nÖffnen Sie die Maske.\n"
    return harness.build_decision(
        query="Wie öffne ich die Maske?", resolved_query="Wie öffne ich die Maske?", messages=[],
        model_id="m", permission_scope={"user_id": "u"}, rag_result=rag,
    ).to_dict()


def _output(text):
    return [{"type": "message", "content": [{"type": "output_text", "text": text}]}]


def _run(enforce, output, payload, replies, timeout=5):
    calls = []

    async def regenerate(messages):
        calls.append(messages)
        reply = replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    result = asyncio.run(enforce(
        output, payload, messages=[{"role": "user", "content": "Frage"}],
        reference_urls=(), regenerate=regenerate, timeout_seconds=timeout,
    ))
    return result, calls


def test_accepted_answer_is_delivered_without_retry():
    harness, enforce = _enforce_namespace()
    output = _output("Öffnen Sie die Maske [1].")

    result, calls = _run(enforce, output, _payload(harness), [])

    assert calls == []
    assert (result["delivery_status"], result["retry_count"], result["fallback_used"]) == ("accepted", 0, False)
    assert output[0]["content"][0]["text"] == "Öffnen Sie die Maske [1]."


def test_blocking_violation_is_corrected_once():
    harness, enforce = _enforce_namespace()
    output = _output("Öffnen Sie die Maske.")

    result, calls = _run(enforce, output, _payload(harness), ["Öffnen Sie die Maske [1]."])

    assert len(calls) == 1 and calls[0][-1]["content"].startswith("KAHLE_KNOWLEDGE_ANSWER_RETRY")
    assert '"allowed_source_ids":["[1]"]' in calls[0][-1]["content"]
    assert (result["delivery_status"], result["retry_count"], result["fallback_used"]) == ("corrected", 1, False)
    assert [attempt["status"] for attempt in result["attempts"]] == ["retry_required", "accepted"]
    assert output[0]["content"][0]["text"] == "Öffnen Sie die Maske [1]."


@pytest.mark.parametrize("reply", ["Immer noch ohne Zitat.", asyncio.TimeoutError(), RuntimeError("upstream")])
def test_failed_correction_falls_back_to_neutral_abstention(reply):
    harness, enforce = _enforce_namespace()
    output = _output("Öffnen Sie die Maske.")

    result, calls = _run(enforce, output, _payload(harness), [reply])

    assert len(calls) == 1
    assert (result["delivery_status"], result["retry_count"], result["fallback_used"]) == ("abstained", 1, True)
    assert output[0]["content"][0]["text"].startswith("Dazu habe ich keine verlässliche freigegebene Information.")


def test_slow_correction_is_cut_by_the_timeout():
    harness, enforce = _enforce_namespace()
    output = _output("Öffnen Sie die Maske.")

    async def slow(_messages):
        await asyncio.sleep(1)
        return "Öffnen Sie die Maske [1]."

    result = asyncio.run(enforce(
        output, _payload(harness), messages=[], reference_urls=(), regenerate=slow, timeout_seconds=0.05,
    ))

    assert result["delivery_status"] == "abstained"
    assert result["attempts"][-1]["error"] == "TimeoutError"


def test_advisory_findings_never_trigger_a_retry():
    harness, enforce = _enforce_namespace()
    output = _output("Öffnen Sie die Maske [1]. Das ist technisch möglich.")

    result, calls = _run(enforce, output, _payload(harness), [])

    assert calls == []
    assert result["delivery_status"] == "accepted"


def test_hold_hides_answer_text_but_keeps_reasoning():
    safe = load_middleware_functions(
        "_stream_safe_output", "_strip_pseudo_toolcall_stream_text",
    )["_stream_safe_output"]
    output = [
        {"type": "reasoning", "content": [{"type": "text", "text": "denke"}], "summary": []},
        {"type": "message", "content": [{"type": "output_text", "text": "Antwort"}]},
    ]

    held = safe(output, suppress_message_text=True, suppress_reasoning=False)

    assert held[0]["content"] == [{"type": "text", "text": "denke"}]
    assert held[1]["content"][0]["text"] == ""
    assert safe(output, suppress_message_text=True)[0]["content"] == []


def test_stream_holds_knowledge_answers_in_enforce_mode():
    source = MIDDLEWARE.read_text(encoding="utf-8")

    assert "hold_knowledge_answer = (" in source
    assert source.count(
        "suppress_message_text=suppress_initial_rag_response or hold_knowledge_answer"
    ) == 1
    assert source.count("suppress_reasoning=suppress_initial_rag_response") == 1
    assert re.search(
        r"if tool_function_name in \{'rag_chat', 'personio_directory'\}:\s+"
        r"hold_knowledge_answer = _answer_enforcement_mode\(\) == 'enforce'",
        source,
    )


def test_validation_point_enforces_in_enforce_mode_and_records_metrics():
    source = MIDDLEWARE.read_text(encoding="utf-8")
    block = source[source.index("validation_attempts = []"):source.index("if not shadow_validation:\n")]

    assert "_answer_enforcement_mode() == 'enforce'" in block
    assert "await _enforce_knowledge_answer(" in block
    assert "timeout_seconds=_answer_retry_timeout(" in block
    assert "'retry_count': enforcement['retry_count']" in block
    assert "'fallback_used': enforcement['fallback_used']" in block
    assert "enforcement['delivery_status']" in block
    assert "Antwort wird anhand der Quellen geprüft" in block


def test_compose_defaults_to_observe_and_local_edge_enforces():
    base = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    local = (ROOT / "docker-compose.local-edge.yml").read_text(encoding="utf-8")

    assert "KAHLE_ANSWER_ENFORCEMENT: ${KAHLE_ANSWER_ENFORCEMENT:-observe}" in base
    assert 'KAHLE_ANSWER_ENFORCEMENT: "enforce"' in local

"""Phase 4b: measure what the answer prompt is made of, then cut the largest parts."""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "kahle_knowledge_harness.py"


def load_harness():
    spec = importlib.util.spec_from_file_location("kahle_harness_phase4b", HARNESS)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PASSAGE = (
    "Reklamationen werden im Garantieportal erfasst. Die Werkstattleitung prüft "
    "den Antrag innerhalb von zwei Arbeitstagen und gibt ihn frei."
)
SPAN = "Die Werkstattleitung prüft den Antrag innerhalb von zwei Arbeitstagen"
BLUEPRINT = {"sections": [{"section_id": "s1", "heading": "Ablauf", "order": 1, "coverage": "supported",
                           "claims": [{"claim_id": "c1", "source_id": "1", "evidence_span": SPAN,
                                       "evidence_role": "editorial"}]}]}
CONTRACT = (
    "KAHLE_KNOWLEDGE_ANSWER_CONTRACT\n{\"schema_version\":\"kahle.answer-contract.v1\"}\n"
    "\nKAHLE_KNOWLEDGE_ANSWER_BLUEPRINT\n" + json.dumps(BLUEPRINT, ensure_ascii=False) + "\n"
    "Formuliere die sichtbare Antwort.\nAntworte nur aus der bereitgestellten Evidenz."
)
DUTIES = "KAHLE_KNOWLEDGE_ANSWER_DUTIES\n- Belege jede interne Aussage."


def test_composition_counts_each_part_once_and_finds_duplicate_spans():
    harness = load_harness()
    messages = [
        {"role": "system", "content": "Du bist Vinci."},
        {"role": "system", "content": CONTRACT},
        {"role": "user", "content": "Wie läuft eine Reklamation?\n\n" + DUTIES},
        {"role": "assistant", "content": ""},
        {"role": "tool", "content": "[1] Garantie\n" + PASSAGE},
    ]
    tools = [{"type": "function", "function": {"name": "rag_chat", "parameters": {}}}]

    result = harness.prompt_composition(messages, tools)

    blueprint_line = json.dumps(BLUEPRINT, ensure_ascii=False)
    assert result["system_chars"] == len("Du bist Vinci.")
    assert result["blueprint_chars"] == len(blueprint_line)
    assert result["contract_chars"] == len(CONTRACT) - len(blueprint_line)
    assert result["duties_chars"] == len(DUTIES)
    assert result["conversation_chars"] == len("Wie läuft eine Reklamation?\n\n")
    assert result["tool_result_chars"] == len("[1] Garantie\n" + PASSAGE)
    assert result["tool_spec_chars"] == len(json.dumps(tools, ensure_ascii=False))
    assert result["duplicate_span_chars"] == len(SPAN)
    assert result["total_chars"] == sum(
        value for key, value in result.items()
        if key.endswith("_chars") and key not in {"total_chars", "duplicate_span_chars"}
    )


def test_context_blocks_in_system_messages_count_as_tool_results():
    harness = load_harness()
    rag_system = "Regeln.\n<context>\n[1] Garantie\n" + PASSAGE + "\n</context>\nEnde."

    result = harness.prompt_composition([{"role": "system", "content": rag_system}], None)

    context = "<context>\n[1] Garantie\n" + PASSAGE + "\n</context>"
    assert result["tool_result_chars"] == len(context)
    assert result["system_chars"] == len(rag_system) - len(context)
    assert result["tool_spec_chars"] == 0


def test_composition_accepts_list_content_and_ignores_garbage():
    harness = load_harness()
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "Hallo"}, {"type": "image_url"}]},
        "kein dict",
        {"role": "system", "content": None},
    ]

    result = harness.prompt_composition(messages, [])

    assert result["conversation_chars"] == len("Hallo")
    assert result["total_chars"] == len("Hallo")


MIDDLEWARE = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "middleware.py"


def test_middleware_records_composition_before_each_answer_call_and_reports_it():
    source = MIDDLEWARE.read_text(encoding="utf-8")
    record = "metadata['_kahle_prompt_composition'] = prompt_composition(\n"
    assert source.count(record) == 2
    assert "'prompt_composition': metadata.get('_kahle_prompt_composition') or {}," in source
    assert "    prompt_composition,\n" in source

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


def test_composition_names_the_size_of_each_tool_spec():
    harness = load_harness()
    tools = [
        {"type": "function", "function": {"name": "rag_chat", "description": "Suche", "parameters": {}}},
        {"type": "function", "function": {"name": "search_web", "description": "Web" * 50, "parameters": {}}},
        {"type": "function"},
    ]

    result = harness.prompt_composition([], tools)

    sizes = result["tool_spec_chars_by_name"]
    assert sizes["rag_chat"] == len(json.dumps(tools[0], ensure_ascii=False))
    assert sizes["search_web"] == len(json.dumps(tools[1], ensure_ascii=False))
    assert sizes["?"] == len(json.dumps(tools[2], ensure_ascii=False))
    assert "tool_spec_chars_by_name" not in {k for k in result if k.endswith("_chars")}


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


OPENAI_ROUTER = ROOT / "open-webui-overrides" / "open_webui" / "routers" / "openai.py"


def test_composition_is_recorded_on_the_prompt_as_sent_and_reported():
    # The model system prompt is only added in the OpenAI router; measuring in the
    # middleware missed it (smoke run 15.10.: system_chars 0).
    router = OPENAI_ROUTER.read_text(encoding="utf-8")
    # utils/chat.py passes the router a merged copy of the metadata; only the
    # request-scoped dict reaches the middleware metrics (smoke run 15.10.).
    record = "request_metadata['_kahle_prompt_composition'] = prompt_composition(\n"
    assert router.count(record) == 1
    assert "request_metadata = getattr(request.state, 'metadata', None)" in router
    assert "not (metadata or {}).get('task')" in router
    assert router.index(record) > router.index("payload = await apply_system_prompt_to_body(")
    assert "from open_webui.utils.kahle_knowledge_harness import prompt_composition\n" in router
    middleware = MIDDLEWARE.read_text(encoding="utf-8")
    # The handler's metadata is not request.state.metadata (diagnosed 15.10. by object id).
    assert "(getattr(request.state, 'metadata', None) or {}).get('_kahle_prompt_composition')" in middleware


def test_document_tools_stay_whenever_the_conversation_has_a_file():
    harness = load_harness()
    needed = harness.document_tools_needed
    plain = [{"role": "user", "content": "Wer ist für Garantie zuständig?"}]

    assert needed(current_files=[], request_messages=plain, history_messages={}) is False
    assert needed(current_files=[{"id": "f1", "name": "vertrag.pdf"}], request_messages=plain, history_messages={})
    earlier = {"m1": {"role": "user", "content": "Lies das", "files": [{"id": "f1", "name": "liste.xlsx"}]}}
    assert needed(current_files=[], request_messages=plain, history_messages=earlier)
    in_request = [{"role": "user", "content": "x", "files": [{"name": "a.docx"}]}]
    assert needed(current_files=[], request_messages=in_request, history_messages={})


def test_document_tools_stay_after_vinci_generated_a_file():
    harness = load_harness()
    generated = [
        {"role": "user", "content": "Fasse das zusammen"},
        {"role": "assistant", "content": "Download: https://vinci.local/files/download?token=abc123"},
        {"role": "user", "content": "Mach daraus eine PDF"},
    ]

    assert harness.document_tools_needed(current_files=[], request_messages=generated, history_messages={})
    assert harness.document_tools_needed(
        current_files=[], request_messages=[],
        history_messages={"a": {"role": "assistant", "content": [{"type": "text", "text": "/files/download?token=x"}]}},
    )


def test_middleware_hides_document_tools_only_without_file_context_and_keeps_them_on_doubt():
    source = MIDDLEWARE.read_text(encoding="utf-8")
    gate = source.index("if 'server:doc-worker' in tool_ids:")
    assert gate < source.index("tools_dict = await get_tools(", gate)
    block = source[gate:source.index("tools_dict = await get_tools(", gate)]
    assert "document_tools_needed(" in block
    assert "Chats.get_messages_map_by_chat_id(" in block
    # An unreadable history keeps the tools (no lost capability on doubt).
    assert "history_messages = None" in block
    assert "history_messages is not None" in block

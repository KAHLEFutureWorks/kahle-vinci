"""Phase 4a: the contract is in the context once; only a duty list precedes the answer."""

import ast
import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "kahle_knowledge_harness.py"
MIDDLEWARE = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "middleware.py"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_kahle_harness_phase3c import _model_led_decision, _scoped_rag_result  # noqa: E402


def load_harness():
    spec = importlib.util.spec_from_file_location("kahle_harness_phase4a", HARNESS)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_duties_name_scope_and_citations_but_carry_no_evidence():
    harness = load_harness()
    decision = _model_led_decision(harness, _scoped_rag_result())

    duties = decision.answer_duties()

    assert duties.startswith("KAHLE_KNOWLEDGE_ANSWER_DUTIES\n")
    assert "Er gilt nur für Hannover, Wunstorf und Wedemark." in duties
    assert "Quellen-ID" in duties
    assert "Kunden in Vaudis anhand der gemeldeten Kundennummer aufrufen" not in duties
    assert "EVIDENCE" not in duties and "evidence_bundle" not in duties
    assert len(duties) < len(decision.answer_prompt()) / 3


def test_high_salience_prompt_is_the_duty_list():
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_high_salience_knowledge_answer_prompt")
    namespace: dict[str, Any] = {"Any": Any}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(MIDDLEWARE), "exec"), namespace)
    decision = _model_led_decision(load_harness(), _scoped_rag_result())

    assert namespace["_high_salience_knowledge_answer_prompt"](decision) == decision.answer_duties()


def test_final_prompt_goes_only_to_the_user_turn():
    source = MIDDLEWARE.read_text(encoding="utf-8")
    block = source[source.index("    final_answer_prompt = metadata.pop('_kahle_final_answer_prompt', '')"):]
    block = block[: block.index("    # If there are citations")]

    assert "add_or_update_user_message(" in block
    assert "add_or_update_system_message(" not in block


def test_pre_route_installs_the_replaceable_contract_message():
    source = MIDDLEWARE.read_text(encoding="utf-8")
    start = source.index("metadata['kahle_answer_contract'] = harness_payload[")
    block = source[start: start + 1200]

    assert "upsert_answer_contract_message(" in block
    assert "knowledge_answer_prompt,\n" not in block


def test_refresh_after_pre_route_leaves_exactly_one_contract():
    sys.path.insert(0, str(ROOT / "open-webui-overrides"))
    try:
        spec = importlib.util.spec_from_file_location(
            "kahle_internal_phase4a", ROOT / "open-webui-overrides" / "open_webui" / "utils" / "kahle_internal_knowledge.py"
        )
        internal = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(internal)
    finally:
        sys.path.remove(str(ROOT / "open-webui-overrides"))
    harness = load_harness()
    first = _model_led_decision(harness, _scoped_rag_result())
    messages = [{"role": "system", "content": "Basis"}, {"role": "user", "content": "Frage"}]

    messages = internal.upsert_answer_contract_message(messages, first)
    messages = internal.upsert_answer_contract_message(messages, first)

    contracts = [m for m in messages if str(m.get("content") or "").startswith("KAHLE_KNOWLEDGE_ANSWER_CONTRACT\n")]
    assert len(contracts) == 1

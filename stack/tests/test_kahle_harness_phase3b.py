import ast
import importlib.util
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
UTILS = ROOT / "open-webui-overrides" / "open_webui" / "utils"
MIDDLEWARE = UTILS / "middleware.py"
HARNESS = UTILS / "kahle_knowledge_harness.py"


def load_harness():
    spec = importlib.util.spec_from_file_location("kahle_harness_phase3b", HARNESS)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_middleware_functions(*names, **extra):
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in nodes} == set(names)
    namespace = {"Any": Any, "replace": replace, **extra}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(MIDDLEWARE), "exec"), namespace)
    return namespace


def test_retrieval_plan_carries_an_evidence_probe_flag():
    harness = load_harness()
    plan = harness.RetrievalPlan(required_tools=("rag_chat",), queries=("q",), permission_scope={})

    assert plan.evidence_probe is False
    assert replace(plan, evidence_probe=True).evidence_probe is True


def _gate():
    harness = load_harness()
    return load_middleware_functions(
        "_plan_kahle_retrieval_gate",
        "_evidence_probe_kinds_match",
        plan_knowledge_retrieval=harness.plan_retrieval,
    )["_plan_kahle_retrieval_gate"]


def _run_gate(query, *, legacy, tools=("rag_chat",), harness_mode="active"):
    return _gate()(
        query=query,
        resolved_query=query,
        messages=[{"role": "user", "content": query}],
        model_id="test-model",
        permission_scope={"user_id": "user-1", "role": "user"},
        tools_dict={name: object() for name in tools},
        legacy_rag_request=legacy,
        harness_mode=harness_mode,
    )


@pytest.mark.parametrize(
    "query",
    [
        "Wie storniere ich eine Rechnung?",
        "Wie lautet das Funktionspostfach für Bewerbungen?",
        "Wie koche ich Nudeln?",
    ],
)
def test_specific_needs_without_keyword_hit_become_an_evidence_probe(query):
    plan = _run_gate(query, legacy=False)

    assert plan is not None
    assert plan.required_tools == ("rag_chat",)
    assert plan.evidence_probe is True


def test_keyword_hit_keeps_the_binding_pre_route():
    plan = _run_gate("Wie storniere ich eine Rechnung?", legacy=True)

    assert plan is not None
    assert plan.evidence_probe is False


def test_catch_all_internal_knowledge_stays_model_led():
    assert _run_gate("Was ist die Hauptstadt von Frankreich?", legacy=False) is None


def test_probe_requires_the_rag_tool():
    assert _run_gate("Wie storniere ich eine Rechnung?", legacy=False, tools=()) is None


def test_harness_off_is_unchanged():
    assert _run_gate("Wie storniere ich eine Rechnung?", legacy=False, harness_mode="off") is None


def test_directory_plans_never_become_probes():
    plan = _run_gate("Wo arbeitet Max Mustermann?", legacy=False)

    assert plan is not None
    assert plan.required_tools == ("personio_directory",)
    assert plan.evidence_probe is False


INTERNAL = UTILS / "kahle_internal_knowledge.py"
PROBE = replace(
    load_harness().RetrievalPlan(required_tools=("rag_chat",), queries=("q",), permission_scope={}),
    evidence_probe=True,
)
BINDING = replace(PROBE, evidence_probe=False)


@pytest.mark.parametrize(
    "plan, rag_outcome, expected",
    [
        (PROBE, "found", "bound"),
        (PROBE, "clarification", "bound"),
        (PROBE, "forbidden", "bound"),
        (PROBE, "missing", "released"),
        (PROBE, "", "released"),
        (BINDING, "missing", ""),
        (None, "missing", ""),
    ],
)
def test_probe_outcome_binds_only_on_evidence(plan, rag_outcome, expected):
    outcome = load_middleware_functions("_evidence_probe_outcome")["_evidence_probe_outcome"]

    assert outcome(plan, rag_outcome) == expected


def test_release_prompt_separates_internal_and_general_questions():
    prompt = load_middleware_functions("_evidence_probe_release_prompt")["_evidence_probe_release_prompt"]()

    assert "Die Suche in den freigegebenen KAHLE-Dokumenten hat zu dieser Frage nichts ergeben." in prompt
    assert "Betrifft die Frage einen KAHLE-internen Ablauf" in prompt
    assert "kennzeichne allgemeine Hinweise ausdrücklich als allgemein" in prompt
    assert "Andernfalls beantworte die Frage normal" in prompt


def test_probe_plans_do_not_announce_the_search_upfront():
    emit = load_middleware_functions("_should_emit_prerouted_rag_status")["_should_emit_prerouted_rag_status"]

    assert emit(BINDING) is True
    assert emit(PROBE) is False


def test_session_can_forget_a_released_probe():
    sys.path.insert(0, str(ROOT / "open-webui-overrides"))
    try:
        spec = importlib.util.spec_from_file_location("kahle_internal_phase3b", INTERNAL)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(ROOT / "open-webui-overrides"))
    session = module.KnowledgeEvidenceSession(messages=[{"role": "user", "content": "q"}])
    session.record("rag_chat", "FOUND: false")
    session.record("personio_directory", {"people": []})

    session.forget("rag_chat")

    assert session.called_tools() == ("personio_directory",)


def test_release_path_is_wired_into_the_pre_route():
    source = MIDDLEWARE.read_text(encoding="utf-8")

    for fragment in (
        "evidence_probe = _evidence_probe_outcome(retrieval_plan, pre_routed_internal_rag)",
        "metadata['kahle_evidence_probe'] = evidence_probe",
        "knowledge_evidence_session.forget('rag_chat')",
        "metadata['_kahle_final_answer_prompt'] = _evidence_probe_release_prompt()",
        "if harness_mode != 'off' and evidence_probe != 'released':",
    ):
        assert fragment in source


def test_routing_metrics_report_the_probe():
    fields = load_middleware_functions(
        "_knowledge_harness_routing_metric_fields",
        "_knowledge_harness_tool_called",
        "_model_led_routing_comparison",
    )["_knowledge_harness_routing_metric_fields"]

    assert fields({"kahle_evidence_probe": "released"})["evidence_probe"] == "released"
    assert "evidence_probe" not in fields({})


def test_release_clears_a_contract_the_pre_route_refresh_installed():
    from types import SimpleNamespace

    release = load_middleware_functions("_release_evidence_probe")["_release_evidence_probe"]
    request = SimpleNamespace(state=SimpleNamespace(_kahle_knowledge_harness_payload={"x": 1}))
    copied = {
        "kahle_knowledge_harness_active": True,
        "kahle_answer_contract": {"citation_required": True},
        "kahle_knowledge_harness_shadow": {},
        "_kahle_final_answer_prompt": "p",
        "kahle_retrieval_tools": ["rag_chat"],
    }
    metadata = dict(copied)
    form_data = {
        "metadata": dict(copied),
        "messages": [
            {"role": "system", "content": "Basis"},
            {"role": "system", "content": "KAHLE_KNOWLEDGE_ANSWER_CONTRACT\n{}"},
            {"role": "user", "content": "Wie koche ich Nudeln?"},
        ],
    }

    release(form_data, metadata, request)

    assert [m["content"] for m in form_data["messages"]] == ["Basis", "Wie koche ich Nudeln?"]
    for md in (metadata, form_data["metadata"]):
        assert "kahle_knowledge_harness_active" not in md
        assert "kahle_answer_contract" not in md
        assert "_kahle_final_answer_prompt" not in md
        assert md["kahle_retrieval_tools"] == []
    assert request.state._kahle_knowledge_harness_payload is None


def test_release_path_uses_the_cleanup():
    assert "_release_evidence_probe(form_data, metadata, request)" in MIDDLEWARE.read_text(encoding="utf-8")


def test_released_probe_still_writes_routing_metrics():
    source = MIDDLEWARE.read_text(encoding="utf-8")

    assert "elif metadata.get('kahle_evidence_probe'):" in source
    assert "'schema_version': 'kahle.harness-metrics.v1'," in source.split("elif metadata.get('kahle_evidence_probe'):", 1)[1][:400]


GUARD = ROOT / "open-webui-functions" / "kahle_toolcall_guard.py"


@pytest.mark.parametrize(
    "query",
    [
        "Wie sperre ich einen Kunden für Werbung am Standort Walsrode?",
        "Der Kunde will keine Werbung mehr bekommen, wie trage ich das ein?",
        "Wie deaktiviere ich die DSE-Kontaktfreigaben in Wunstorf?",
    ],
)
def test_opt_out_wording_is_no_longer_rewritten(query):
    harness = load_harness()

    assert harness.resolve_request(query, [{"role": "user", "content": query}]).retrieval_query == query


def test_customer_lock_choice_resolves_to_a_natural_question():
    harness = load_harness()
    prior_user = "Wie sperre ich einen Kunden?"
    prior_assistant = (
        "Meinst du Werbung und Befragungen oder eine allgemeine Kundensperre in Vaudis?"
    )

    def follow(reply):
        return harness.customer_lock_followup_query(reply, prior_user, prior_assistant)

    assert follow("Werbung") == "Wie hinterlege ich einen Werbewiderspruch in Vaudis?"
    assert follow("Werbung für Walsrode") == (
        "Wie hinterlege ich einen Werbewiderspruch in Vaudis am Standort Walsrode?"
    )
    # A bare location keeps the original question; retrieval decides the process.
    assert follow("Nienburg") == "Wie sperre ich einen Kunden? Standort Nienburg"
    assert follow("allgemein").startswith("Wie veranlasse ich eine allgemeine Kundensperre in Vaudis?")


def test_special_path_identifiers_are_gone():
    harness_source = HARNESS.read_text(encoding="utf-8")
    middleware_source = MIDDLEWARE.read_text(encoding="utf-8")
    guard_source = GUARD.read_text(encoding="utf-8")

    for name in (
        "_canonical_marketing_opt_out_query",
        "_marketing_opt_out_query",
        "_opt_out_contract_scope",
        "_SUPPORTED_OPT_OUT_LOCATIONS",
        "KAHLE_KNOWLEDGE_LOCATION_CONTEXT",
        "location_mode",
    ):
        assert name not in harness_source
    for name in (
        "temporary_survey_opt_out",
        "temporary_survey_without_location",
        "kahle_survey_location_mode",
        "_normalize_repeated_location_prompt_output",
        "location_mode",
    ):
        assert name not in middleware_source
    for source in (harness_source, middleware_source, guard_source):
        assert "herstellerseitige Zufriedenheitsbefragungen" not in source


TOOL_PATH = ROOT / "open-webui-tools" / "rag_chat_hybrid_tool.py"

OPT_OUT_STEPS = """## 5. Durchführung der Sperrung
1. Kunden in Vaudis anhand der gemeldeten Kundennummer aufrufen.
1. Die DSE-Einstellungen des Kunden öffnen.
1. Die für die Kontaktfreigaben gesetzten Haken entfernen.
1. Exakt dokumentieren, welche Haken entfernt wurden.
1. Den Kunden unmittelbar danach in die standortbezogene Sperrliste eintragen.
"""
PROSE_ONLY = "Im Servicebereich kann man den Kalender öffnen. Die Termine sind dort sichtbar."
NUMBERED_FACTS = """1. Hannover, Mo-Fr 7-18 Uhr
2. Wunstorf, Mo-Fr 7-17 Uhr
3. Wedemark, Mo-Fr 8-17 Uhr
"""
VERB_STEPS = "Öffne die Maske. Wähle den Kunden. Speichere die Änderung."


def _procedure_detectors():
    sys.path.insert(0, str(TOOL_PATH.parent))
    try:
        spec = importlib.util.spec_from_file_location("rag_tool_phase3b", TOOL_PATH)
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
    finally:
        sys.path.remove(str(TOOL_PATH.parent))
    return {"tool": tool._context_has_procedure, "harness": load_harness()._procedure_is_supported}


@pytest.mark.parametrize("detector", ["tool", "harness"])
@pytest.mark.parametrize(
    "context, expected",
    [
        (OPT_OUT_STEPS, True),
        (VERB_STEPS, True),
        (PROSE_ONLY, False),
        (NUMBERED_FACTS, False),
    ],
    ids=["numbered_steps", "verb_steps", "prose", "numbered_facts"],
)
def test_procedure_detection_recognises_numbered_steps(detector, context, expected):
    assert _procedure_detectors()[detector](context) is expected


def test_diagnostic_metrics_explain_the_evidence_status():
    from types import SimpleNamespace

    fields = load_middleware_functions(
        "_knowledge_harness_diagnostic_metric_fields"
    )["_knowledge_harness_diagnostic_metric_fields"]
    session = SimpleNamespace(called_tools=lambda: ("rag_chat", "personio_directory", "rag_chat"))
    metadata = {
        "kahle_contract_origin": "model_led_refresh",
        "kahle_internal_rag_prerouted": "found",
        "kahle_knowledge_evidence_session": session,
    }
    evidence = {"missing_information": ["a", "b", "c", "d"]}

    assert fields(metadata, evidence) == {
        "contract_origin": "model_led_refresh",
        "prerouted_rag": "found",
        "rag_call_count": 2,
        "evidence_missing": ["a", "b", "c"],
    }
    assert fields({}, {}) == {
        "contract_origin": "",
        "prerouted_rag": "",
        "rag_call_count": 0,
        "evidence_missing": [],
    }


def test_contract_origin_is_recorded_on_both_paths():
    source = MIDDLEWARE.read_text(encoding="utf-8")

    assert source.count("metadata['kahle_contract_origin'] = 'pre_route'") == 1
    assert source.count("metadata['kahle_contract_origin'] = 'model_led_refresh'") == 1
    assert "**_knowledge_harness_diagnostic_metric_fields(metadata, evidence_payload)," in source


def test_pre_route_handler_receives_the_flagged_metadata_copy():
    """The nested handler reads extra_params['__metadata__']; the flags live in the copy."""
    source = MIDDLEWARE.read_text(encoding="utf-8")
    block = source[
        source.index("async def retrieve_pre_route_rag()"):
        source.index("retrieval = await _execute_kahle_retrieval_plan(")
    ]

    assert "pre_route_extra_params = {**extra_params, '__metadata__': pre_route_metadata}" in block
    call = block[block.index("await chat_completion_tools_handler("):]
    assert call.index("pre_route_extra_params,") < call.index(")")

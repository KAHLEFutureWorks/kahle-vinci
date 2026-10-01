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

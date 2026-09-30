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

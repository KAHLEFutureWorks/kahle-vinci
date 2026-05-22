from __future__ import annotations

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
    wanted = {"_ascii_fold", "_contains_token", "_looks_like_internal_rag_request"}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"re": re, "unicodedata": unicodedata}
    exec(compile(module, str(MIDDLEWARE), "exec"), namespace)
    return namespace["_looks_like_internal_rag_request"]


def test_internal_rag_routing_detects_recovery_gutschein():
    looks_internal = load_rag_routing_helpers()

    assert looks_internal("Ich habe einen Kunden mit Recovery Gutschein, was muss ich machen?") is True


def test_internal_rag_routing_does_not_treat_internet_as_intern():
    looks_internal = load_rag_routing_helpers()

    assert looks_internal("Bitte recherchiere wie Spaghetti hergestellt werden im Internet") is False


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


def load_stream_safe_output():
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    wanted = {"_strip_pseudo_toolcall_stream_text", "_stream_safe_output"}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"copy": copy}
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


if __name__ == "__main__":
    test_internal_rag_routing_detects_recovery_gutschein()
    test_internal_rag_routing_does_not_treat_internet_as_intern()
    test_previous_result_word_request_routes_to_workflow_before_streaming()
    test_stream_safe_output_hides_visible_pseudo_toolcall_text()
    print("middleware internal rag routing tests passed")

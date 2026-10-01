import ast
import importlib.util
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
MIDDLEWARE = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "middleware.py"


def load_middleware_functions(*names):
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in nodes} == set(names)
    namespace = {"Any": Any, "os": __import__("os")}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(MIDDLEWARE), "exec"), namespace)
    return namespace


PLAN = object()


@pytest.mark.parametrize(
    "mode, off_models, model_id, expected",
    [
        ("model_led", "", "kahle-vinci-thinking", PLAN),
        ("model_led", "kahle-vinci-thinking", "kahle-vinci-thinking", None),
        ("model_led", "kahle-vinci-thinking, vinci-2-clone-clone-clone", "vinci-2-clone-clone-clone", None),
        ("model_led", "kahle-vinci-thinking", "kahle-vinci-max-thinking", PLAN),
        ("legacy", "kahle-vinci-thinking", "kahle-vinci-thinking", PLAN),
    ],
)
def test_preroute_can_be_disabled_per_model_only_in_model_led(monkeypatch, mode, off_models, model_id, expected):
    monkeypatch.setenv("KAHLE_MODEL_LED_PREROUTE_OFF_MODELS", off_models)
    select = load_middleware_functions(
        "_routing_plan_for_execution", "_model_led_preroute_disabled"
    )["_routing_plan_for_execution"]

    assert select(mode, PLAN, model_id) is expected


def test_call_site_passes_the_request_model():
    source = MIDDLEWARE.read_text(encoding="utf-8")

    assert re.search(
        r"retrieval_plan = _routing_plan_for_execution\(\s*routing_mode, legacy_retrieval_plan, "
        r"str\(form_data\.get\('model'\) or ''\)\s*\)",
        source,
    )


def test_local_edge_exposes_the_switch_with_an_empty_default():
    local = (ROOT / "docker-compose.local-edge.yml").read_text(encoding="utf-8")

    assert "KAHLE_MODEL_LED_PREROUTE_OFF_MODELS: ${KAHLE_MODEL_LED_PREROUTE_OFF_MODELS:-}" in local

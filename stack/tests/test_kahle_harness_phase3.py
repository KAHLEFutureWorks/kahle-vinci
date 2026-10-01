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


REGISTER = ROOT.parent / "scripts" / "openwebui" / "register-kahle-workflow-tool.py"
MODEL_REGISTER = ROOT.parent / "scripts" / "openwebui" / "register-vinci-models.py"
INTERNAL = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "kahle_internal_knowledge.py"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rag_description_covers_roles_locations_abbreviations_and_mixed_contacts():
    spec = _load(REGISTER, "reg_phase3").TOOL_DEFINITIONS["rag_chat"]["specs"][0]
    description = spec["description"]

    for phrase in (
        "Aufgaben von Rollen",
        "standortbezogene Abläufe",
        "Abkürzungen",
        "auch bei kurzen Begriffen, Abkürzungen und Folgefragen",
        "Nicht für aktuelle Personen, ihre Einzelkontakte oder Führungskräfte",
        "Bei Kontaktfragen zu einer Abteilung oder einem Bereich zusätzlich personio_directory aufrufen",
    ):
        assert phrase in description
    assert "Rollen, Teams, Abteilungen, Standorte" not in description
    assert "Bezug aus dem Verlauf" in spec["parameters"]["properties"]["query"]["description"]


def test_personio_description_is_german_and_names_the_mixed_case():
    tree = ast.parse(INTERNAL.read_text(encoding="utf-8"))
    source = " ".join(
        node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )

    assert "Durchsucht das aktuelle KAHLE-Mitarbeiterverzeichnis (Personio)" in source
    assert "Nicht für dokumentierte Prozesse, Zuständigkeiten oder Aufgabenbeschreibungen" in source
    assert "Bei Kontaktfragen zu einer Abteilung oder einem Bereich zusätzlich rag_chat aufrufen" in source
    assert "Search the current KAHLE employee directory" not in source


def test_model_note_matches_the_source_policy():
    models = _load(MODEL_REGISTER, "model_reg_phase3")
    note = models.make_meta(models.MODELS[0])["kahleKnowledgeNote"]

    assert "Abteilungs- und Bereichskontakte: beide Tools" in note


PROMPTS = (
    ROOT / "open-webui-prompts" / "kahle-vinci-systemprompt.md",
    ROOT / "open-webui-prompts" / "kahle-vinci-thinking-systemprompt.md",
)
RULES = (
    "Beantworte KAHLE-interne Fragen nie ohne Tool-Evidenz. Das gilt auch für Abkürzungen, Systeme, Öffnungszeiten und Folgefragen; rufe dafür das passende Tool erneut auf.",
    "Kontaktfragen zu einer Abteilung oder einem Bereich brauchen beide Quellen: rufe rag_chat und personio_directory im selben Schritt auf.",
)
MATRIX_ROWS = (
    "| aktuelle Personen, Profile, geschäftliche Einzelkontakte, Positionen, Teams, Abteilungs- und Standortzuordnung von Personen, Onboarding und Führungskräfte | `personio_directory` |",
    "| dokumentierte Prozesse, Zuständigkeiten und Aufgaben von Rollen, standortbezogene Abläufe, Abkürzungen, Funktionspostfächer, Ticketsysteme sowie Einreichungs- und Kontaktwege | `rag_chat` |",
    "| Kontakte einer Abteilung oder eines Bereichs sowie Fragen mit echtem Bedarf an beiden Evidenzarten | beide Tools |",
)


@pytest.mark.parametrize("prompt_path", PROMPTS, ids=lambda p: p.name)
def test_prompts_state_tool_duty_and_mixed_contacts(prompt_path):
    prompt = prompt_path.read_text(encoding="utf-8")
    for rule in RULES:
        assert rule in prompt


@pytest.mark.parametrize("prompt_path", PROMPTS, ids=lambda p: p.name)
def test_prompt_source_matrix_matches_the_tool_descriptions(prompt_path):
    prompt = prompt_path.read_text(encoding="utf-8")
    for row in MATRIX_ROWS:
        assert row in prompt
    assert "Rollen, Teams, Abteilungen, Standorte, Onboarding und Führungskräfte | `personio_directory`" not in prompt


def test_function_calling_prompt_matches_the_tool_descriptions():
    prompt = _load(REGISTER, "reg_phase3_fc").TOOLS_FUNCTION_CALLING_PROMPT

    for row in (
        "| current people, profiles, business contacts, positions, teams, department and location assignment of people, onboarding, and supervisors | personio_directory |",
        "| documented processes, responsibilities and duties of roles, location-specific workflows, abbreviations, shared mailboxes, ticket systems, submission, and contact paths | rag_chat |",
        "| contacts of a department or area, and questions that actually need both evidence types | personio_directory and rag_chat |",
        "- Never answer KAHLE-internal questions without tool evidence, including abbreviations, systems, opening hours, and follow-ups.",
    ):
        assert row in prompt
    assert "roles, teams, departments, locations" not in prompt

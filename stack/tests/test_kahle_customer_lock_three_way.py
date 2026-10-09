"""Customer-lock clarification with three paths (decision 2026-10-09, option A).

The opt-out document covers only a temporary block of manufacturer
satisfaction surveys in Hannover, Wunstorf and Wedemark. A permanent
objection to advertising goes to datenschutz@kahle.de at every location.
The clarification therefore offers three choices, and harness, middleware
and guard resolve each reply to the same follow-up query.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "kahle_knowledge_harness.py"
GUARD = ROOT / "open-webui-functions" / "kahle_toolcall_guard.py"
TOOLS = ROOT / "open-webui-tools"

QUESTION = "Wie sperre ich einen Kunden?"
CLARIFICATION = (
    "Geht es um eine befristete Sperre für Hersteller-Zufriedenheitsbefragungen, "
    "um einen dauerhaften Werbewiderspruch oder um eine allgemeine Kundensperre in Vaudis?"
)
OLD_CLARIFICATION = (
    "Geht es darum, Werbung und Befragungen für den Kunden zu sperren, "
    "oder um eine allgemeine Kundensperre in Vaudis?"
)
SURVEY = "Wie setze ich eine befristete Sperre für Hersteller-Zufriedenheitsbefragungen in Vaudis?"
PERMANENT = "An wen wende ich mich bei einem dauerhaften Werbewiderspruch eines Kunden?"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_tool_asks_for_the_three_paths():
    sys.path.insert(0, str(TOOLS))
    try:
        tool = _load("rag_tool_three_way", TOOLS / "rag_chat_hybrid_tool.py")
    finally:
        sys.path.remove(str(TOOLS))

    assert tool._clarification_for_query(QUESTION) == CLARIFICATION


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("befristet", SURVEY),
        ("Zufriedenheitsbefragung", SURVEY),
        ("die erste Option", SURVEY),
        ("Befragung für Walsrode", SURVEY.replace("in Vaudis?", "in Vaudis am Standort Walsrode?")),
        ("dauerhaft", PERMANENT),
        ("Werbewiderspruch", PERMANENT),
        ("Werbung", PERMANENT),
        ("zweite Option", PERMANENT),
        ("allgemein", None),
        ("die dritte", None),
    ],
)
@pytest.mark.parametrize("clarification", [CLARIFICATION, OLD_CLARIFICATION], ids=["new", "old"])
def test_every_reply_resolves_the_same_in_harness_and_guard(reply, expected, clarification):
    harness = _load("harness_three_way", HARNESS)
    guard = _load("guard_three_way", GUARD)
    history = [{"role": "user", "content": QUESTION}, {"role": "assistant", "content": clarification}]

    resolved = harness.customer_lock_followup_query(reply, QUESTION, clarification)

    if expected is None:
        assert resolved.startswith("Wie veranlasse ich eine allgemeine Kundensperre in Vaudis?")
    else:
        assert resolved == expected
    assert guard._expand_customer_lock_followup(reply, history) == resolved

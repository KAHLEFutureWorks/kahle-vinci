"""Answers after a released evidence probe (decision 2026-10-08, option A).

No KAHLE document matched. A general answer stays allowed, but its first
sentence says that there is no KAHLE document, and it never invents KAHLE
contact data: no KAHLE mailbox, link, phone number or postal address
without a source.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "kahle_knowledge_harness.py"


def load_harness():
    spec = importlib.util.spec_from_file_location("kahle_harness_released", HARNESS)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _codes(harness, answer):
    payload = harness.released_decision_payload("Wie erstelle ich eine Mahnung?", {"user_id": "user-1"})
    return {v["code"]: v["severity"] for v in harness.validate_answer(answer, payload).violations}


def test_released_payload_has_no_evidence_and_its_own_mode():
    payload = load_harness().released_decision_payload("Wie erstelle ich eine Mahnung?", {"user_id": "user-1"})

    assert payload["retrieval_plan"]["mode"] == "released"
    assert payload["evidence_bundle"]["status"] == "unsupported"
    assert payload["evidence_bundle"]["sources"] == []


@pytest.mark.parametrize("answer", [
    "Dazu gibt es kein KAHLE-Dokument. Allgemein gilt: Eine Mahnung nennt Betrag und Frist.",
    "**Allgemeine Hinweise (nicht als KAHLE-Vorgabe zu verstehen):** Eine Mahnung nennt Betrag und Frist.",
    "In den freigegebenen KAHLE-Dokumenten habe ich dazu nichts gefunden. Allgemein gilt …",
    "Dazu habe ich keine verlässliche freigegebene Information.",
])
def test_disclosed_general_answer_passes(answer):
    harness = load_harness()

    assert _codes(harness, answer) == {}


def test_general_answer_without_notice_must_be_corrected():
    harness = load_harness()

    codes = _codes(harness, "Die Erstellung einer Mahnung kann je nach Kontext variieren. Hier sind die Schritte …")

    assert codes == {"release_notice_missing": "blocking"}


@pytest.mark.parametrize("line", [
    "Absender: Autohaus KAHLE GmbH & Co. KG, Musterstraße 1, 12345 Hannover",
    "Absender: Autohaus KAHLE, Telefon +49 511 123 456",
    "E-Mail: info@kahle.de",
    "Mehr unter https://www.kahle.de/mahnung",
])
def test_invented_kahle_contact_data_is_blocked(line):
    harness = load_harness()

    codes = _codes(harness, f"Dazu gibt es kein KAHLE-Dokument. Allgemein gilt:\n{line}")

    assert codes == {"unbound_contact_literal": "blocking"}


def test_general_contacts_outside_kahle_stay_allowed():
    harness = load_harness()

    answer = (
        "Dazu gibt es kein KAHLE-Dokument. Allgemein: Verbraucherzentrale, "
        "info@verbraucherzentrale.example, Telefon 0800 123456."
    )

    assert _codes(harness, answer) == {}


def test_retry_prompt_asks_for_the_notice_first():
    harness = load_harness()
    payload = harness.released_decision_payload("Wie erstelle ich eine Mahnung?", {"user_id": "user-1"})

    prompt = harness.validate_answer("Schritte …", payload).retry_prompt(())

    assert "Beginne mit dem Satz: Dazu gibt es kein KAHLE-Dokument." in prompt


def test_eval_counts_the_new_code_as_blocking():
    sys.path.insert(0, str(ROOT.parent / "eval" / "harness"))
    try:
        import harness_eval
    finally:
        sys.path.pop(0)

    assert "release_notice_missing" in harness_eval.BLOCKING_VIOLATION_CODES
    assert "release_notice_missing" in load_harness().BLOCKING_VIOLATION_CODES

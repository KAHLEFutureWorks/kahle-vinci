import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = (
    ROOT / "open-webui-prompts" / "kahle-vinci-systemprompt.md",
    ROOT / "open-webui-prompts" / "kahle-vinci-thinking-systemprompt.md",
)
HARNESS = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "kahle_knowledge_harness.py"


def load_harness():
    spec = importlib.util.spec_from_file_location("kahle_harness_phase0b", HARNESS)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("prompt_path", PROMPTS, ids=lambda path: path.name)
def test_prompts_have_one_consistent_internal_source_policy(prompt_path):
    prompt = prompt_path.read_text(encoding="utf-8")

    assert "KAHLE-interne Fakten -> RAG_Chat" not in prompt
    assert "Bei KAHLE-internen Fakten bleibt RAG_Chat zuerst Pflicht" not in prompt
    assert "konkurriere nicht mit einer eigenen fachlichen Quellenentscheidung" not in prompt
    assert "Waehle interne Quellen nach der Quellenmatrix in Abschnitt 3.3" in prompt


@pytest.mark.parametrize("prompt_path", PROMPTS, ids=lambda path: path.name)
def test_prompts_have_one_priority_order_and_no_model_specific_section(prompt_path):
    prompt = prompt_path.read_text(encoding="utf-8")

    assert "HOECHSTE PRIORITAET" not in prompt
    assert "Mistral" not in prompt
    assert "0) ABSOLUTE PRIORITAETEN" in prompt


@pytest.mark.parametrize("prompt_path", PROMPTS, ids=lambda path: path.name)
def test_stable_facts_are_orientation_not_evidence(prompt_path):
    prompt = prompt_path.read_text(encoding="utf-8")

    assert (
        "Diese Fakten dienen nur der Orientierung. Fuer interne Tatsachenaussagen gilt "
        "ausschliesslich das aktuelle EvidenceBundle; bei Widerspruch gilt das EvidenceBundle."
    ) in prompt

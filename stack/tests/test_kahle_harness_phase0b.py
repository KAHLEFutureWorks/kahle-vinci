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


sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_rag_evidence_bundle_contract import (  # noqa: E402
    chunk,
    configured_tool,
    evidence_from_result,
    load_tool,
)


def _rag_result(module, monkeypatch, chunks):
    import asyncio

    tool = configured_tool(module, monkeypatch, chunks)
    return asyncio.run(tool.rag_chat(
        query="Wie plane ich einen Termin im WPS?",
        __user__={"id": "user-1"},
        __chat_id__="chat-1",
        __message_id__="message-1",
    ))


def test_rag_context_uses_native_gapless_markers(monkeypatch):
    module = load_tool()
    first = chunk("Öffnen Sie den Werkstattkalender.")
    empty = chunk("")
    second = chunk("Wählen Sie einen freien Termin.")
    second.document_id = "doc-2"
    second.title = "WPS Termine"

    result = _rag_result(module, monkeypatch, [first, empty, second])
    context = result.split("CONTEXT:\n", 1)[1].split("\nSOURCES_JSON:", 1)[0]
    sources = json.loads(result.split("SOURCES_JSON: ", 1)[1].splitlines()[0])

    assert "[Quelle" not in result
    assert context.startswith("[1] KAHLE Systemwissen | WPS\n")
    assert "\n[2] WPS Termine | WPS\n" in context
    assert [source["number"] for source in sources] == [1, 2]
    assert [source["number"] for source in evidence_from_result(result)["sources"]] == [1, 2]
    assert "[1]" in result.split("INSTRUCTION: ", 1)[1].splitlines()[0]

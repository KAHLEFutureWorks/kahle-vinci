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


NATIVE_RESULT = (
    "KAHLE_RAG_RESULT\nFOUND: true\nCONTEXT:\n"
    "[1] Dokument A | Abschnitt A\nErster Beleg.\n\n"
    "[2] Dokument B | Abschnitt B\nZweiter Beleg.\n"
    "FEEDBACK_LINK: /wissen/?feedback=1"
)


def test_harness_parses_native_numbered_context_blocks():
    evidence = load_harness()._evidence_bundle(NATIVE_RESULT, procedural=False)

    assert [source["source_id"] for source in evidence.sources] == ["#1", "#2"]
    assert evidence.supported_claims == ("Erster Beleg.", "Zweiter Beleg.")


def test_reconstructed_rag_result_uses_native_markers():
    text = load_harness().rag_result_from_sources([
        {"source": {"name": "Dokument A"}, "document": ["Erster Beleg."], "metadata": [{}]},
    ])

    assert "[1] Dokument A\nErster Beleg." in text
    assert "[Quelle" not in text


import re  # noqa: E402

from test_middleware_internal_rag_routing import (  # noqa: E402
    MIDDLEWARE,
    load_function_from_middleware,
)


def _frontend_source_ids(events):
    """Mirror OpenWebUI ContentRenderer.getSourceIds for citation lookup."""
    names = []
    for source in events:
        for index, _document in enumerate(source.get("document") or []):
            metadata = (source.get("metadata") or [{}])[index] or {}
            names.append(metadata.get("name") or source.get("source", {}).get("name"))
    return list(dict.fromkeys(names))


def test_every_passage_gets_its_own_citation_source_in_marker_order():
    events_for = load_function_from_middleware("_canonical_kahle_rag_source_events")
    sources = [
        {"number": 1, "title": "WPS", "section_heading": "1 Termine", "source_url": "/wissen/api/portal/sources/a", "evidence_text": "A"},
        {"number": 2, "title": "WPS", "section_heading": "1 Termine", "source_url": "/wissen/api/portal/sources/a", "evidence_text": "B"},
        {"number": 3, "title": "Vaudis", "source_url": "https://evil.example/x", "evidence_text": ""},
    ]

    events = events_for(sources)
    ids = _frontend_source_ids(events)

    assert len(events) == 3
    assert ids == ["WPS – 1 Termine", "WPS – 1 Termine (2)", "Vaudis"]
    assert events[2]["document"] == ["Vaudis"]
    assert "url" not in events[2]["metadata"][0]
    assert events[0]["metadata"][0]["url"] == "/wissen/api/portal/sources/a"


def test_citation_sources_keep_passages_without_trusted_links():
    extract = load_function_from_middleware("_extract_kahle_rag_citation_sources")
    result = 'SOURCES_JSON: [{"number": 2, "title": "B"}, {"number": 1, "title": "A", "source_url": "/wissen/api/portal/sources/a"}]\n'

    assert [source["number"] for source in extract(result)] == [1, 2]


def test_rag_citation_sources_come_first_and_are_emitted_in_the_native_tool_path():
    source = MIDDLEWARE.read_text(encoding="utf-8")

    assert "sources[:] = [*canonical_pre_route_events, *[" in source
    assert re.search(
        r"canonical_rag_sources\.extend\(_extract_kahle_rag_sources\(tool_result\)\)"
        r"[\s\S]{0,400}?tool_call_sources\.extend\([\s\S]{0,80}?"
        r"_canonical_kahle_rag_source_events\([\s\S]{0,80}?"
        r"_extract_kahle_rag_citation_sources\(tool_result\)",
        source,
    )


CITATION_RULE = (
    "Zitiere Dokumentbelege mit ihrer Nummer in eckigen Klammern, z. B. [1] oder [1, 2]; "
    "Personio-Belege als [P1]."
)


@pytest.mark.parametrize("prompt_path", PROMPTS, ids=lambda path: path.name)
def test_prompts_state_the_native_citation_rule(prompt_path):
    assert CITATION_RULE in prompt_path.read_text(encoding="utf-8")


def test_answer_contract_states_the_native_citation_rule():
    harness = load_harness()
    decision = harness.build_decision(
        query="Wie plane ich einen Termin im WPS?",
        resolved_query="Wie plane ich einen Termin im WPS?",
        messages=[],
        model_id="test-model",
        permission_scope={"user_id": "u"},
        rag_result=NATIVE_RESULT,
    )

    assert CITATION_RULE in decision.answer_prompt()


def test_middleware_continuation_hint_uses_native_markers():
    source = MIDDLEWARE.read_text(encoding="utf-8")

    assert "Quellenmarke [#]" not in source
    assert "passenden Quellennummer, z. B. [1]" in source


def _plain_decision():
    return {
        "evidence_bundle": {"status": "supported", "supported_claims": [], "sources": [{"number": 1}]},
        "answer_contract": {},
        "retrieval_plan": {"permission_scope": {"user_id": "u"}},
        "resolved_context": {"retrieval_query": "Frage"},
    }


@pytest.mark.parametrize("marker", ["[Quelle 1]", "[#1]", "[R1]"])
def test_legacy_citation_markers_are_advisory(marker):
    result = load_harness().validate_answer(f"Belegte Aussage {marker}.", _plain_decision())

    assert ("noncanonical_citation", "advisory") in [
        (item["code"], item["severity"]) for item in result.violations
    ]


def test_native_citation_marker_is_accepted_without_findings():
    result = load_harness().validate_answer("Belegte Aussage [1].", _plain_decision())

    assert result.violations == ()


def _bundle_result(numbers):
    sources = [{"number": n, "title": f"D{n}", "source_url": f"/wissen/api/portal/sources/d{n}"} for n in numbers]
    bundle = {
        "schema_version": "kahle.evidence-bundle.v1",
        "status": "supported",
        "supported_claims": [
            {"claim_id": f"R{n}C1", "source_id": f"#{n}", "text": f"Beleg {n}.", "evidence_span": f"Beleg {n}."}
            for n in numbers
        ],
        "missing_information": [],
        "conflicts": [],
        "sources": [{"number": n, "document_id": f"d{n}"} for n in numbers],
    }
    context = "\n\n".join(f"[{n}] D{n} | A\nBeleg {n}." for n in numbers)
    return (
        "KAHLE_RAG_RESULT\nFOUND: true\n"
        f"EVIDENCE_BUNDLE_JSON: {json.dumps(bundle)}\n"
        "INSTRUCTION: Belege mit [1].\n"
        f"CONTEXT:\n{context}\n"
        f"SOURCES_JSON: {json.dumps(sources)}\n"
        "FEEDBACK_LINK: /wissen/?feedback=1"
    )


def test_renumber_rag_result_shifts_markers_sources_and_claims():
    harness = load_harness()
    shifted = harness.renumber_rag_result(_bundle_result([1, 2]), 3)

    assert harness.rag_result_source_count(_bundle_result([1, 2])) == 2
    assert "[4] D1 | A" in shifted and "[5] D2 | A" in shifted
    assert "INSTRUCTION: Belege mit [1]." in shifted
    bundle = json.loads(shifted.split("EVIDENCE_BUNDLE_JSON: ", 1)[1].splitlines()[0])
    assert [s["number"] for s in bundle["sources"]] == [4, 5]
    assert [(c["claim_id"], c["source_id"]) for c in bundle["supported_claims"]] == [("R4C1", "#4"), ("R5C1", "#5")]
    sources = json.loads(shifted.split("SOURCES_JSON: ", 1)[1].splitlines()[0])
    assert [s["number"] for s in sources] == [4, 5]


def test_renumber_with_zero_offset_is_identity():
    result = _bundle_result([1])

    assert load_harness().renumber_rag_result(result, 0) == result

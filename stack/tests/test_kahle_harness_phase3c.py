"""Phase 3c: a restrictive document scope is an evidence obligation.

The scope and the path for everything outside it come from the evidence of
the current request: an editorial claim that limits validity to a strict
subset of KAHLE locations, and a typed functional contact whose scope
excludes exactly those locations. No process text or location list is
hard-coded for a single document.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "kahle_knowledge_harness.py"

SCOPE_ROW = (
    "| Geltungsbereich | Servicebereiche der Standorte Hannover (HAN), "
    "Wunstorf (WUN) und Wedemark (WED) |"
)
STEP = "Kunden in Vaudis anhand der gemeldeten Kundennummer aufrufen."
EXCEPTION_ROW = "| Datenschutz | E-Mail | datenschutz@kahle.de | Sperranfragen | Alle KAHLE-Standorte außer Hannover, Wunstorf und Wedemark |"


def load_harness():
    spec = importlib.util.spec_from_file_location("kahle_harness_phase3c", HARNESS)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _claim(text, number=1, index=1, role="editorial"):
    return {
        "claim_id": f"R{number}C{index}", "source_id": f"#{number}", "text": text,
        "evidence_span": text, "document_id": f"doc-{number}", "version_id": f"v-{number}",
        "evidence_role": role,
    }


def _contact_claim(row=EXCEPTION_ROW, scope="Alle KAHLE-Standorte außer Hannover, Wunstorf und Wedemark",
                   value="datenschutz@kahle.de", number=2):
    contact = {
        "schema_version": "kahle.functional-contact.v1", "function": "Datenschutz", "channel": "email",
        "value": value, "purpose": "Sperranfragen", "scope": scope, "row_number": 7, "evidence_span": row,
    }
    claim = {
        "claim_id": f"R{number}C1", "source_id": f"#{number}", "document_id": f"doc-{number}",
        "version_id": f"v-{number}", "text": row, "evidence_span": row,
        "claim_type": "functional_contact", "functional_contact": dict(contact),
    }
    source = {
        "number": number, "document_id": f"doc-{number}", "version_id": f"v-{number}",
        "chunk_kind": "functional_contact", "functional_contact": dict(contact),
    }
    return claim, source


def _bundle(harness, *claims, extra_sources=(), status="supported"):
    sources = [{"number": 1, "document_id": "doc-1", "version_id": "v-1", "title": "Prozess"}, *extra_sources]
    return harness.EvidenceBundle(status=status, supported_claims=tuple(claims), sources=tuple(sources))


def test_table_scope_and_excluding_contact_form_one_requirement():
    harness = load_harness()
    contact, source = _contact_claim()
    evidence = _bundle(harness, _claim(SCOPE_ROW), _claim(STEP, index=2), contact, extra_sources=(source,))

    assert harness._scope_requirements(evidence) == ({
        "source_id": "#1",
        "locations": ("Hannover", "Wunstorf", "Wedemark"),
        "exception_contacts": ("datenschutz@kahle.de",),
    },)


def test_sentence_scope_without_exception_path():
    harness = load_harness()
    evidence = _bundle(harness, _claim("Diese Anleitung gilt nur für Walsrode."))

    assert harness._scope_requirements(evidence) == ({
        "source_id": "#1", "locations": ("Walsrode",), "exception_contacts": (),
    },)


@pytest.mark.parametrize(
    "text",
    [
        "Geltungsbereich: alle KAHLE-Standorte",
        "| Geltungsbereich | Hannover, Wunstorf, Wedemark, Walsrode, Neustadt, Nienburg, Stadthagen |",
        "In Hannover und Wunstorf gibt es eine eigene Annahme.",
        "Die Annahme ist in Hannover besetzt; die Anleitung gilt für alle Standorte.",
    ],
    ids=["all_named_generically", "all_listed", "mere_mention", "not_restrictive"],
)
def test_non_restrictive_or_mere_mentions_create_no_requirement(text):
    harness = load_harness()

    assert harness._scope_requirements(_bundle(harness, _claim(text))) == ()


def test_contact_without_matching_exclusion_is_no_exception_path():
    harness = load_harness()
    contact, source = _contact_claim(
        row="| IT | E-Mail | it@kahle.de | Störungen | gruppenweit |", scope="gruppenweit", value="it@kahle.de",
    )
    evidence = _bundle(harness, _claim(SCOPE_ROW), contact, extra_sources=(source,))

    assert harness._scope_requirements(evidence)[0]["exception_contacts"] == ()


def test_exclusion_must_cover_exactly_the_scoped_locations():
    harness = load_harness()
    contact, source = _contact_claim(scope="Alle KAHLE-Standorte außer Hannover")
    evidence = _bundle(harness, _claim(SCOPE_ROW), contact, extra_sources=(source,))

    assert harness._scope_requirements(evidence)[0]["exception_contacts"] == ()


def test_non_editorial_or_unsupported_evidence_creates_no_requirement():
    harness = load_harness()

    assert harness._scope_requirements(_bundle(harness, _claim(SCOPE_ROW, role="auxiliary_ocr"))) == ()
    assert harness._scope_requirements(_bundle(harness, _claim(SCOPE_ROW), status="unsupported")) == ()


import ast
import json
from typing import Any

MIDDLEWARE = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "middleware.py"


def _rag_result(*claims, sources):
    bundle = {
        "schema_version": "kahle.evidence-bundle.v1", "status": "supported",
        "supported_claims": list(claims), "missing_information": [], "conflicts": [],
        "sources": list(sources),
    }
    return (
        "KAHLE_RAG_RESULT\nFOUND: true\n"
        f"EVIDENCE_BUNDLE_JSON: {json.dumps(bundle, ensure_ascii=False)}\n"
        "CONTEXT:\n[1] Prozess | A\n" + " ".join(c["text"] for c in claims) + "\n"
    )


def _scoped_rag_result():
    contact, source = _contact_claim()
    return _rag_result(
        _claim(SCOPE_ROW), _claim(STEP, index=2), contact,
        sources=[{"number": 1, "document_id": "doc-1", "version_id": "v-1", "title": "Prozess"}, source],
    )


# Neutral wording: the opt-out special path (until Task 4) rewrites opt-out questions.
QUESTION = "Wie läuft der dokumentierte Prozess ab?"
EXPECTED_SCOPE = ({
    "source_id": "#1",
    "locations": ("Hannover", "Wunstorf", "Wedemark"),
    "exception_contacts": ("datenschutz@kahle.de",),
},)


def _pre_route_decision(harness, rag):
    return harness.build_decision(
        query=QUESTION, resolved_query=QUESTION, messages=[], model_id="m",
        permission_scope={"user_id": "u"}, rag_result=rag,
    )


def _model_led_decision(harness, rag):
    return harness.build_result_driven_decision(
        called_tools=("rag_chat",), query=QUESTION, messages=[], model_id="m",
        permission_scope={"user_id": "u"}, rag_result=[rag],
    )


@pytest.mark.parametrize("build", [_pre_route_decision, _model_led_decision], ids=["pre_route", "model_led"])
def test_both_contract_paths_carry_the_scope(build):
    harness = load_harness()

    decision = build(harness, _scoped_rag_result())

    assert decision.answer_contract.required_scope == EXPECTED_SCOPE
    prompt = decision.answer_prompt()
    assert (
        "Die Quellen begrenzen ihren Geltungsbereich auf Hannover, Wunstorf und Wedemark [#1]. "
        "Nenne diesen Geltungsbereich und für alle anderen Fälle den dokumentierten Weg "
        "(datenschutz@kahle.de)."
    ) in prompt


@pytest.mark.parametrize("build", [_pre_route_decision, _model_led_decision], ids=["pre_route", "model_led"])
def test_no_scope_no_requirement_and_no_scope_sentence(build):
    harness = load_harness()
    rag = _rag_result(_claim(STEP), sources=[{"number": 1, "document_id": "doc-1", "version_id": "v-1", "title": "Prozess"}])

    decision = build(harness, rag)

    assert decision.answer_contract.required_scope == ()
    assert "begrenzen ihren Geltungsbereich" not in decision.answer_prompt()


def test_scope_without_exception_path_asks_only_for_the_scope():
    harness = load_harness()
    rag = _rag_result(
        _claim("Diese Anleitung gilt nur für Walsrode."),
        sources=[{"number": 1, "document_id": "doc-1", "version_id": "v-1", "title": "Prozess"}],
    )

    prompt = _model_led_decision(harness, rag).answer_prompt()

    assert "Die Quellen begrenzen ihren Geltungsbereich auf Walsrode [#1]. Nenne diesen Geltungsbereich." in prompt


def test_scope_contract_is_repeated_right_before_the_answer():
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_high_salience_knowledge_answer_prompt")
    namespace: dict[str, Any] = {"Any": Any}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(MIDDLEWARE), "exec"), namespace)
    harness = load_harness()

    decision = _model_led_decision(harness, _scoped_rag_result())

    assert namespace["_high_salience_knowledge_answer_prompt"](decision) == decision.answer_prompt()


FULL_ANSWER = (
    "Der Ablauf gilt nur für Hannover, Wunstorf und Wedemark [1]. Kunden in Vaudis aufrufen [1]. "
    "Für alle anderen Standorte wende dich an datenschutz@kahle.de [2]."
)


def _codes(result):
    return [item["code"] for item in result.violations]


@pytest.mark.parametrize("build", [_pre_route_decision, _model_led_decision], ids=["pre_route", "model_led"])
def test_complete_scope_passes(build):
    harness = load_harness()
    decision = build(harness, _scoped_rag_result())

    assert "required_scope_missing" not in _codes(harness.validate_answer(FULL_ANSWER, decision.to_dict()))


@pytest.mark.parametrize("build", [_pre_route_decision, _model_led_decision], ids=["pre_route", "model_led"])
def test_missing_location_or_contact_blocks_delivery(build):
    harness = load_harness()
    decision = build(harness, _scoped_rag_result())

    no_wedemark = harness.validate_answer(FULL_ANSWER.replace(" und Wedemark", ""), decision.to_dict())
    no_contact = harness.validate_answer(FULL_ANSWER.split(" Für alle anderen")[0], decision.to_dict())

    [violation] = [v for v in no_wedemark.violations if v["code"] == "required_scope_missing"]
    assert violation["severity"] == "blocking"
    assert violation["missing_locations"] == ["Wedemark"]
    assert violation["missing_contacts"] == []
    [violation] = [v for v in no_contact.violations if v["code"] == "required_scope_missing"]
    assert violation["missing_contacts"] == ["datenschutz@kahle.de"]


def test_abstention_is_exempt():
    harness = load_harness()
    decision = _model_led_decision(harness, _scoped_rag_result())

    result = harness.validate_answer(harness.knowledge_abstention_answer(has_sources=True), decision.to_dict())

    assert "required_scope_missing" not in _codes(result)


def test_serialized_scope_is_not_an_authority():
    harness = load_harness()
    decision = _model_led_decision(harness, _scoped_rag_result()).to_dict()
    decision["answer_contract"]["required_scope"] = []

    result = harness.validate_answer(FULL_ANSWER.replace(" und Wedemark", ""), decision)

    assert "required_scope_missing" in _codes(result)


def test_retry_prompt_names_the_missing_values():
    harness = load_harness()
    decision = _model_led_decision(harness, _scoped_rag_result())

    result = harness.validate_answer("Kunden in Vaudis aufrufen [1].", decision.to_dict())
    prompt = result.retry_prompt(("1", "2"))

    assert "Nenne den Geltungsbereich aus der Evidenz: Hannover, Wunstorf und Wedemark." in prompt
    assert "Nenne für alle anderen Fälle: datenschutz@kahle.de." in prompt


def test_eval_knows_the_new_blocking_code():
    sys.path.insert(0, str(ROOT.parent / "eval" / "harness"))
    try:
        import harness_eval
    finally:
        sys.path.remove(str(ROOT.parent / "eval" / "harness"))

    assert harness_eval.BLOCKING_VIOLATION_CODES == load_harness().BLOCKING_VIOLATION_CODES
    assert "required_scope_missing" in harness_eval.BLOCKING_VIOLATION_CODES


TOOL_PATH = ROOT / "open-webui-tools" / "rag_chat_hybrid_tool.py"


def load_tool():
    sys.path.insert(0, str(TOOL_PATH.parent))
    try:
        spec = importlib.util.spec_from_file_location("rag_tool_phase3c", TOOL_PATH)
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
    finally:
        sys.path.remove(str(TOOL_PATH.parent))
    return tool


def test_tool_and_harness_share_the_location_list():
    assert load_tool()._KAHLE_LOCATIONS == load_harness()._REQUEST_LOCATIONS


def test_scope_sentences_always_reach_the_claims():
    tool = load_tool()
    passage = (
        "| Geltungsbereich | Servicebereiche der Standorte Hannover (HAN), Wunstorf (WUN) und Wedemark (WED) |\n"
        "Die DSE-Einstellungen des Kunden öffnen.\n"
        "Die für die Kontaktfreigaben gesetzten Haken entfernen."
    )

    spans = tool._claim_evidence_spans("Wie deaktiviere ich die DSE-Kontaktfreigaben in Wunstorf?", passage)

    assert any(span.startswith("| Geltungsbereich |") for span in spans)


class _Chunk:
    def __init__(self, parent_content="", functional_contact=None, chunk_kind="text", document_id="d"):
        self.parent_content = parent_content
        self.content = parent_content
        self.functional_contact = functional_contact
        self.chunk_kind = chunk_kind
        self.document_id = document_id


def test_restrictive_scope_locations_come_from_scope_statements():
    tool = load_tool()
    chunks = [
        _Chunk("| Geltungsbereich | Standorte Hannover, Wunstorf und Wedemark |"),
        _Chunk("In Walsrode gibt es eine eigene Annahme."),
    ]

    assert tool._restrictive_scope_locations(chunks) == ("Hannover", "Wunstorf", "Wedemark")
    assert tool._restrictive_scope_locations([_Chunk("Geltungsbereich: alle KAHLE-Standorte")]) == ()


def test_exception_contacts_must_exclude_exactly_the_scoped_locations():
    tool = load_tool()
    exact = _Chunk(chunk_kind="functional_contact", functional_contact={
        "value": "datenschutz@kahle.de", "scope": "Alle KAHLE-Standorte außer Hannover, Wunstorf und Wedemark"})
    partial = _Chunk(chunk_kind="functional_contact", functional_contact={
        "value": "x@kahle.de", "scope": "Alle KAHLE-Standorte außer Hannover"})
    group = _Chunk(chunk_kind="functional_contact", functional_contact={
        "value": "it@kahle.de", "scope": "gruppenweit"})

    selected = tool._exception_contact_chunks([exact, partial, group], ("Hannover", "Wunstorf", "Wedemark"))

    assert selected == [exact]


def test_exception_query_names_only_the_scope_from_the_evidence():
    tool = load_tool()

    assert tool._scope_exception_query(("Hannover", "Wunstorf", "Wedemark")) == (
        "Kontakt für alle anderen Standorte außer Hannover, Wunstorf und Wedemark"
    )


def test_rag_chat_completes_the_exception_path():
    source = TOOL_PATH.read_text(encoding="utf-8")

    assert "scope_locations = _restrictive_scope_locations(chunks)" in source
    assert "_exception_contact_chunks(chunks, scope_locations)" in source
    assert "_scope_exception_query(scope_locations)" in source
    assert '{"kind": "functional_contact", "evidence_capabilities": ["functional_contact"]}' in source


RETRIEVAL_PATH = ROOT / "open-webui-tools" / "hybrid_retrieval.py"


def load_retrieval():
    spec = importlib.util.spec_from_file_location("hybrid_retrieval_phase3c", RETRIEVAL_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _point(point_id, document_id, text, heading=(), kind="text"):
    return {"id": point_id, "payload": {
        "document_id": document_id, "version_id": "v", "parent_id": point_id,
        "parent_content": text, "content": text, "heading_path": list(heading), "chunk_kind": kind,
        "title": "Prozess",
    }}


def test_retrieval_shares_the_location_list():
    assert load_retrieval().KAHLE_LOCATIONS == load_harness()._REQUEST_LOCATIONS


def test_restrictive_scope_of_a_selected_document_is_added_for_any_question():
    retrieval = load_retrieval()
    step = _point("p5", "doc", "Die DSE-Einstellungen öffnen.", ("5. Durchführung",))
    header = _point("p0", "doc", SCOPE_ROW, ("Datei",))
    general = _point("q0", "other", "| Geltungsbereich | alle KAHLE-Standorte |")
    unselected_doc = _point("x0", "elsewhere", SCOPE_ROW)
    hint = _point("p9", "doc", SCOPE_ROW, kind="retrieval_hint")

    companions = retrieval.restrictive_scope_companions(
        [step, _point("q1", "other", "Text")], [step, header, general, unselected_doc, hint],
    )

    assert companions == [header]


def test_no_companion_when_the_scope_is_already_selected():
    retrieval = load_retrieval()
    header = _point("p0", "doc", SCOPE_ROW)

    assert retrieval.restrictive_scope_companions([header], [header]) == []


def test_retriever_adds_restrictive_scope_companions():
    source = RETRIEVAL_PATH.read_text(encoding="utf-8")

    assert "for companion in restrictive_scope_companions(" in source


GUARD_PATH = ROOT / "open-webui-functions" / "kahle_toolcall_guard.py"
LOCK_QUESTION = "Wie sperre ich einen Kunden in Vaudis?"
LOCK_CLARIFICATION = (
    "Geht es darum, Werbung und Befragungen für den Kunden in Hannover, Wunstorf oder "
    "Wedemark zu sperren, oder um eine allgemeine Kundensperre in Vaudis für einen anderen Standort?"
)
LOCK_REPLIES = ("Werbung", "Werbung für Walsrode", "Nienburg", "allgemein")


def _middleware_expansion():
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_expanded_internal_rag_query")
    import re as _re
    namespace: dict[str, Any] = {
        "Any": Any, "re": _re,
        "customer_lock_followup_query": load_harness().customer_lock_followup_query,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(MIDDLEWARE), "exec"), namespace)
    return namespace["_expanded_internal_rag_query"]


def _guard_module():
    spec = importlib.util.spec_from_file_location("kahle_guard_phase3c", GUARD_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("reply", LOCK_REPLIES)
def test_customer_lock_follow_up_is_one_behaviour(reply):
    harness = load_harness()
    expected = harness.customer_lock_followup_query(reply, LOCK_QUESTION, LOCK_CLARIFICATION)
    history = [
        {"role": "user", "content": LOCK_QUESTION},
        {"role": "assistant", "content": LOCK_CLARIFICATION},
    ]

    assert expected
    assert _middleware_expansion()([*history, {"role": "user", "content": reply}], reply) == expected
    assert _guard_module()._expand_customer_lock_followup(reply, history) == expected


def test_middleware_has_no_own_customer_lock_branch():
    source = MIDDLEWARE.read_text(encoding="utf-8")

    assert "customer_lock_clarification = (" not in source
    assert "customer_lock_followup_query(" in source


@pytest.mark.parametrize("path", [TOOL_PATH, RETRIEVAL_PATH], ids=["rag_chat", "hybrid_retrieval"])
def test_tool_special_filters_are_gone(path):
    source = path.read_text(encoding="utf-8")

    for name in (
        "temporary_survey", "_marketing_opt_out_query", "_prioritize_marketing_opt_out_evidence",
        "kd-sperrprozess", "sperrliste", "datenschutz@kahle.de",
    ):
        assert name not in source.casefold(), name


def test_tool_texts_name_no_locations_or_contacts():
    tool = load_tool()

    instruction = tool._rag_final_response_instruction(
        "Wie sperre ich einen Kunden für Zufriedenheitsbefragungen in Hannover?"
    )
    clarification = tool._clarification_for_query("Wie sperre ich einen Kunden bei KAHLE?")

    for text in (instruction, clarification):
        assert not tool._named_kahle_locations(text)
    assert "Werbung und Befragungen" in clarification
    assert "allgemeine Kundensperre in Vaudis" in clarification


def test_full_procedure_only_follows_document_overviews():
    source = TOOL_PATH.read_text(encoding="utf-8")

    assert 'full_procedure = bool(source.get("document_overview"))\n' in source

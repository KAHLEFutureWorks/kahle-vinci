"""Person names from documents need a current Personio confirmation.

Review decision 2026-10-08: a process document may name the person who handles
a topic, but that person can have left or changed roles. Such a name reaches the
answer only when Personio confirms exactly one current person with that name in
the same request. Otherwise the statement is withheld from the evidence and an
answer naming the person is a blocking violation.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "kahle_knowledge_harness.py"
SCOPE = {"user_id": "user-1", "role": "user", "groups": []}
QUESTION = "Wer ist für Garantieanträge zuständig?"
NAMED = "Max Muster bearbeitet Garantieanträge."
PROCESS = "Garantieanträge werden im Herstellerportal gestellt."


def load_harness():
    spec = importlib.util.spec_from_file_location("kahle_harness_person_confirmation", HARNESS)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _rag(*claims):
    bundle = {
        "schema_version": "kahle.evidence-bundle.v1",
        "status": "supported",
        "supported_claims": [
            {"claim_id": f"R1C{index}", "source_id": "#1", "text": text, "evidence_span": text,
             "document_id": "process", "version_id": "v1", "evidence_role": "editorial"}
            for index, text in enumerate(claims, start=1)
        ],
        "missing_information": [],
        "conflicts": [],
        "sources": [{"number": 1, "document_id": "process"}],
    }
    return "KAHLE_RAG_RESULT\nFOUND: true\nEVIDENCE_BUNDLE_JSON: " + json.dumps(bundle, ensure_ascii=False)


def _personio(*people, stale=False):
    """people: (personio_id, display_name); an empty id omits the field."""
    claims = []
    for number, (personio_id, name) in enumerate(people, start=1):
        claim = {"display_name": name, "position": "Garantie", "source_id": f"P{number}"}
        if personio_id:
            claim["personio_id"] = personio_id
        claims.append(claim)
    return {
        "status": "ok" if claims else "not_found",
        "claims": claims,
        "sources": [{"id": f"P{n}", "kind": "personio_directory"} for n in range(1, len(claims) + 1)],
        "sync_completed_at": "2026-10-08T06:00:00Z",
        "stale": stale,
    }


def _pre_route(harness, rag, confirmations=(), query=QUESTION):
    return harness.build_decision(
        query=query, resolved_query=query, messages=[], model_id="kahle-vinci",
        permission_scope=SCOPE, rag_result=rag, person_confirmations=confirmations,
    )


def _texts(decision):
    return [c.get("text") for c in decision.evidence_bundle.supported_claims]


@pytest.mark.parametrize(
    ("text", "names"),
    [
        ("Max Muster bearbeitet Garantieanträge.", ("Max Muster",)),
        ("Für Garantieanträge ist Frau Erika Beispiel zuständig.", ("Erika Beispiel",)),
        ("Bei Fragen wende dich an das Serviceteam.", ()),
        ("Die Garantieabteilung bearbeitet Garantieanträge.", ()),
        ("Garantieanträge bearbeitet der Service Hannover.", ()),
        ("Ansprechpartner ist Herr Müller.", ()),
        ("Andere Standorte wenden sich an datenschutz@kahle.de.", ()),
        ("Dokumentierte Kontaktwege stehen im Intranet.", ()),
        ("Max Muster und Erika Beispiel bearbeiten Anträge.", ("Max Muster", "Erika Beispiel")),
        ("Bei Rückfragen wende dich an Anna Probe.", ("Anna Probe",)),
        ("Ihre Fragen beantwortet das Serviceteam.", ()),
        ("Verantwortliche Stelle ist die Geschäftsführung.", ()),
        ("Datenschutzrechtliche Fragen klärt die Rechtsabteilung.", ()),
        ("KAHLE Speak beantwortet Rückfragen.", ()),
        ("Anke Meyer betreut die Anträge.", ("Anke Meyer",)),
    ],
)
def test_person_names_are_recognised_without_prepositions_units_or_locations(text, names):
    assert load_harness()._person_name_mentions(text) == names


def test_unconfirmed_document_person_is_withheld_from_the_evidence():
    decision = _pre_route(load_harness(), _rag(NAMED))

    assert decision.evidence_bundle.status == "unsupported"
    assert _texts(decision) == []
    assert decision.answer_contract.withheld_person_names == ("Max Muster",)
    prompt = decision.answer_prompt()
    assert "Max Muster" not in prompt
    assert "withheld_person_names" not in prompt


def test_other_statements_of_the_document_stay_usable():
    decision = _pre_route(load_harness(), _rag(PROCESS, NAMED))

    assert decision.evidence_bundle.status == "supported"
    assert _texts(decision) == [PROCESS]
    assert any("Personio" in item for item in decision.evidence_bundle.missing_information)


def test_one_current_personio_match_confirms_the_name():
    decision = _pre_route(load_harness(), _rag(NAMED), (_personio(("p-1", "Max Muster")),))

    assert _texts(decision) == [NAMED]
    assert decision.answer_contract.withheld_person_names == ()


@pytest.mark.parametrize(
    "confirmation",
    [
        _personio(("p-1", "Max Muster"), ("p-2", "Max Muster")),
        _personio(("", "Max Muster")),
        _personio(("p-1", "Max Mustermann")),
        _personio(("p-1", "Max Muster"), stale=True),
        _personio(),
        {"status": "directory_unavailable", "claims": [], "sources": []},
    ],
    ids=["two_ids", "no_id", "other_name", "stale", "not_found", "unavailable"],
)
def test_ambiguous_or_outdated_directory_evidence_confirms_nothing(confirmation):
    decision = _pre_route(load_harness(), _rag(NAMED), (confirmation,))

    assert _texts(decision) == []
    assert decision.answer_contract.withheld_person_names == ("Max Muster",)


def test_confirmation_names_for_the_lookup_are_bounded():
    harness = load_harness()
    rag = _rag(NAMED, "Erika Beispiel ist zuständig.", "Anna Probe betreut Anträge.",
               "Otto Test bearbeitet Rückfragen.", PROCESS)

    assert harness.person_confirmation_names(rag) == ("Max Muster", "Erika Beispiel", "Anna Probe")
    assert harness.person_confirmation_names(_rag(PROCESS)) == ()


@pytest.mark.parametrize(
    ("tools", "personio", "kept"),
    [
        (("rag_chat",), None, []),
        (("rag_chat", "personio_directory"), _personio(("p-1", "Max Muster")), [NAMED]),
    ],
    ids=["rag_only", "with_personio"],
)
def test_model_led_path_applies_the_same_rule(tools, personio, kept):
    decision = load_harness().build_result_driven_decision(
        called_tools=tools, query=QUESTION, messages=[], model_id="kahle-vinci",
        permission_scope=SCOPE, rag_result=_rag(NAMED), personio_result=personio,
    )

    assert [c.get("text") for c in decision.evidence_bundle.supported_claims
            if not str(c.get("source_id", "")).startswith("P")] == kept


@pytest.mark.parametrize(
    ("answer", "violated"),
    [
        ("Garantieanträge bearbeitet Max Muster [1].", True),
        ("Zuständig ist Herr Muster [1].", True),
        ("Dazu habe ich keine verlässliche freigegebene Information.", False),
    ],
)
def test_naming_a_withheld_person_is_a_blocking_violation(answer, violated):
    harness = load_harness()
    decision = _pre_route(harness, _rag(PROCESS, NAMED))

    validation = harness.validate_answer(answer, decision.to_dict())
    codes = {v["code"]: v["severity"] for v in validation.violations}

    assert (codes.get("unconfirmed_person_name") == "blocking") is violated
    if violated:
        assert "Max Muster" not in json.dumps(validation.to_dict(), ensure_ascii=False)
        assert "Personio" in validation.retry_prompt(("1",))


def test_eval_counts_the_new_code_as_blocking():
    sys.path.insert(0, str(ROOT.parent / "eval" / "harness"))
    try:
        import harness_eval
    finally:
        sys.path.pop(0)

    assert "unconfirmed_person_name" in harness_eval.BLOCKING_VIOLATION_CODES
    assert "unconfirmed_person_name" in load_harness().BLOCKING_VIOLATION_CODES


@pytest.mark.parametrize(
    ("query", "tools"),
    [
        ("Wer ist der Ansprechpartner für Garantieanträge?", ("rag_chat",)),
        ("Wer ist der Ansprechpartner für Kundenbeschwerden?", ("rag_chat",)),
        ("Wer ist Ansprechpartner für Datenschutz?", ("personio_directory", "rag_chat")),
        ("Wer ist Ansprechpartner im Teiledienst in Hannover?", ("personio_directory", "rag_chat")),
        ("Wer ist der Ansprechpartner von Erika Beispiel?", ("personio_directory",)),
    ],
)
def test_contact_person_for_a_process_topic_is_answered_from_documents(query, tools):
    plan = load_harness().plan_retrieval(query, query, [], "kahle-vinci", SCOPE)

    assert plan.required_tools == tools


MIDDLEWARE = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "middleware.py"


def _middleware_helper(name):
    import ast
    import asyncio

    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
    namespace = {"asyncio": asyncio, "Any": object}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(MIDDLEWARE), "exec"), namespace)
    return namespace[name]


class _FakeDirectory:
    def __init__(self, failing=()):
        self.calls = []
        self.failing = set(failing)

    async def search(self, query, intent, user_id, user_role, *, candidate_query=""):
        self.calls.append((query, intent, user_id, user_role))
        if query in self.failing:
            raise RuntimeError("directory down")
        return _personio(("p-1", query))


def test_middleware_looks_up_each_document_name_as_a_person():
    import asyncio

    confirm = _middleware_helper("_confirm_rag_person_names")
    directory = _FakeDirectory(failing={"Erika Beispiel"})

    results = asyncio.run(confirm(("Max Muster", "Erika Beispiel"), personio_client=directory,
                                  user_id="user-1", user_role="user"))

    assert [call[:2] for call in directory.calls] == [("Max Muster", "person_lookup"),
                                                      ("Erika Beispiel", "person_lookup")]
    assert [r["claims"][0]["display_name"] for r in results] == ["Max Muster"]


@pytest.mark.parametrize(("names", "role"), [((), "user"), (("Max Muster",), "pending")])
def test_middleware_skips_the_lookup_without_names_or_access(names, role):
    import asyncio

    confirm = _middleware_helper("_confirm_rag_person_names")
    directory = _FakeDirectory()

    assert asyncio.run(confirm(names, personio_client=directory, user_id="u", user_role=role)) == ()
    assert directory.calls == []


def test_pre_route_passes_the_confirmations_to_the_harness():
    source = MIDDLEWARE.read_text(encoding="utf-8")

    assert "person_confirmation_names(pre_route_rag_result)" in source
    assert "person_confirmations=person_confirmations," in source


@pytest.mark.parametrize("text", [
    "Bei Fragen zu Kahle Vinci wende dich an das Digitale Autohaus.",
    "Mitarbeiter Service bearbeitet Rückfragen.",
    "Zentrale Ansprechpartner sind im Intranet hinterlegt.",
])
def test_company_product_and_common_words_are_no_names(text):
    assert load_harness()._person_name_mentions(text) == ()

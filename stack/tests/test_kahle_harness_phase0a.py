import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "kahle_knowledge_harness.py"


def load_harness():
    spec = importlib.util.spec_from_file_location("kahle_harness_phase0a", HARNESS)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "umlaut, ascii_form",
    [
        ("Wie ändere ich eine Kundenadresse in Vaudis?", "Wie aendere ich eine Kundenadresse in Vaudis?"),
        ("Wie öffne ich einen Werkstattauftrag in WPS?", "Wie oeffne ich einen Werkstattauftrag in WPS?"),
        ("Wie läuft die Dialogannahme?", "Wie laeuft die Dialogannahme?"),
        ("Wie führe ich eine HU-Anmeldung durch?", "Wie fuehre ich eine HU-Anmeldung durch?"),
        ("Wie wähle ich im WPS einen freien Termin?", "Wie waehle ich im WPS einen freien Termin?"),
        ("Wie bestätige ich den Auftrag?", "Wie bestaetige ich den Auftrag?"),
    ],
)
def test_procedural_detection_is_independent_of_umlaut_spelling(umlaut, ascii_form):
    harness = load_harness()

    assert harness._is_procedural(umlaut) is True
    assert harness._is_procedural(ascii_form) is True


@pytest.mark.parametrize(
    "context",
    [
        "Öffnen Sie die Maske. Wählen Sie den Kunden. Bestätigen Sie mit OK.",
        "Oeffnen Sie die Maske. Waehlen Sie den Kunden. Bestaetigen Sie mit OK.",
    ],
)
def test_procedure_support_counts_umlaut_and_ascii_action_verbs(context):
    assert load_harness()._procedure_is_supported(context) is True


@pytest.mark.parametrize(
    "query",
    [
        "Wie lege ich einen Neukunden in Vaudis an?",
        "Wie storniere ich eine Rechnung?",
        "Wie reserviere ich einen Leihwagen für einen Werkstattkunden?",
        "Wie hinterlege ich einen Werbewiderspruch in Vaudis?",
        "Wie macht man eine Garantieanfrage?",
    ],
)
def test_first_person_how_to_questions_are_procedural(query):
    assert load_harness()._is_procedural(query) is True


@pytest.mark.parametrize(
    "query",
    [
        "Wie heißt der Serviceleiter in Wunstorf?",
        "Wie viele Serviceberater gibt es in Nienburg?",
        "Wie bin ich bei KAHLE versichert?",
        "Wie ist das Wetter heute?",
        "Was bedeutet TD?",
    ],
)
def test_non_procedural_how_questions_stay_non_procedural(query):
    assert load_harness()._is_procedural(query) is False


def _tools(harness, query):
    return harness.plan_retrieval(query, query, [], "test-model", {"user_id": "u"}).required_tools


@pytest.mark.parametrize(
    "query",
    [
        "Wer ist für Garantieanträge zuständig?",
        "Welche Aufgaben hat ein Serviceberater?",
        "Wer kümmert sich um Leasingrückläufer?",
        "Wer ist für die Freigabe von Arbeitsanweisungen verantwortlich?",
    ],
)
def test_documented_responsibility_questions_use_rag_only(query):
    assert _tools(load_harness(), query) == ("rag_chat",)


@pytest.mark.parametrize(
    "query, tools",
    [
        ("Wer ist Max Mustermann?", ("personio_directory",)),
        ("Wer ist die Führungskraft von Anna Beispiel?", ("personio_directory",)),
        ("Wer sind die Serviceberater in Wunstorf?", ("personio_directory",)),
        (
            "Welche Rolle hat Anna Beispiel und welche Aufgaben gehören laut Arbeitsanweisung dazu?",
            ("personio_directory", "rag_chat"),
        ),
    ],
)
def test_person_questions_keep_their_directory_route(query, tools):
    assert _tools(load_harness(), query) == tools


@pytest.mark.parametrize(
    "query",
    [
        "Wer ist die Fürhungskraft von Anna Beispiel?",
        "Wer ist die Führungskrfat von Anna Beispiel?",
        "Wer ist die Führungskrft von Anna Beispiel?",
    ],
)
def test_supervisor_reference_tolerates_one_typo_or_transposition(query):
    assert load_harness()._has_supervisor_reference(query) is True


def test_unrelated_words_are_not_supervisor_references():
    harness = load_harness()

    assert harness._has_supervisor_reference("Wie funktioniert die Fahrzeugführung?") is False
    assert harness._has_supervisor_reference("Wer macht die Fuhrparkplanung?") is False


def _personio(*names):
    return {
        "status": "ok",
        "claims": [
            {"personio_id": f"p-{index}", "display_name": name, "position": "Leitung", "source_id": f"P{index}"}
            for index, name in enumerate(names, 1)
        ],
        "sources": [{"id": f"P{index}", "kind": "personio_directory"} for index in range(1, len(names) + 1)],
        "sync_completed_at": "2026-09-29T08:00:00Z",
        "stale": False,
    }


def _decide(harness, query, personio=None, rag=""):
    return harness.build_decision(
        query=query,
        resolved_query=query,
        messages=[{"role": "user", "content": query}],
        model_id="test-model",
        permission_scope={"user_id": "u", "role": "user", "groups": []},
        rag_result=rag,
        personio_result=personio,
    )


@pytest.mark.parametrize(
    "query",
    [
        # Both wordings are routed to Personio; the ranking must still stay unsupported.
        "Wer sind die wichtigsten Führungskräfte im Verkauf?",
        "Gib mir eine Rangliste der Führungskräfte im Service",
    ],
)
def test_leadership_ranking_has_no_supported_evidence(query):
    harness = load_harness()
    assert "personio_directory" in _tools(harness, query)

    decision = _decide(harness, query, _personio("Erika Beispiel"))

    assert decision.evidence_bundle.status == "unsupported"
    assert decision.evidence_bundle.supported_claims == ()
    assert "Erika Beispiel" not in decision.answer_prompt()


def test_named_supervisor_with_one_personio_claim_stays_supported():
    decision = _decide(load_harness(), "Wer ist die Führungskraft von Erika Beispiel?", _personio("Max Leitung"))

    assert decision.evidence_bundle.status == "supported"
    assert "Max Leitung" in decision.answer_prompt()


def test_ambiguous_supervisor_candidates_are_unsupported():
    decision = _decide(
        load_harness(), "Wer ist die Führungskraft von Erika Beispiel?", _personio("Max Leitung", "Mia Leitung")
    )

    assert decision.evidence_bundle.status == "unsupported"
    assert "Mia Leitung" not in decision.answer_prompt()


def test_supervisor_typo_without_personio_evidence_has_no_person_claim():
    decision = _decide(load_harness(), "Wer ist die Führungskrft von Erika Beispiel?")

    assert decision.evidence_bundle.status == "unsupported"
    assert decision.evidence_bundle.supported_claims == ()


MIDDLEWARE = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "middleware.py"


def test_harness_decision_has_no_direct_answer_renderer():
    harness = load_harness()

    assert not hasattr(harness.HarnessDecision, "direct_answer")
    assert not hasattr(harness, "_organization_contact_answer")


def test_middleware_never_sets_final_content_from_the_knowledge_harness():
    source = MIDDLEWARE.read_text(encoding="utf-8")

    assert "_knowledge_harness_direct_answer" not in source
    active_block = source[
        source.index("if harness_mode == 'active':"):
        source.index(
            "if harness_mode != 'active' and pre_routed_internal_rag",
            source.index("if harness_mode == 'active':"),
        )
    ]
    assert "kahle_direct_final_content" not in active_block


def _validation_decision():
    return {
        "evidence_bundle": {
            "status": "supported",
            "supported_claims": [{"text": "Die Rechnung liegt im Archiv.", "source_id": "#1"}],
            "sources": [{"number": 1}],
        },
        "answer_contract": {},
        "retrieval_plan": {"permission_scope": {"user_id": "u"}},
        "resolved_context": {"retrieval_query": "Wo liegt die Rechnung?"},
    }


@pytest.mark.parametrize(
    "answer",
    [
        "Die Rechnung liegt im Archiv [1]. Eine Suche ist dort möglich.",
        "Die Rechnung liegt im Archiv [1]. Ohne Freigabe darfst du sie nicht löschen.",
    ],
)
def test_ordinary_wording_is_not_flagged_as_an_approval(answer):
    result = load_harness().validate_answer(answer, _validation_decision())

    assert result.status == "accepted"
    assert result.violations == ()


@pytest.mark.parametrize(
    "answer, code",
    [
        ("Die Rechnung liegt im Archiv [1]. Das ist technisch möglich.", "unsupported_technical_approval"),
        ("Die Rechnung liegt im Archiv [1]. Eine Datenschutzprüfung ist nicht erforderlich.", "unsupported_privacy_approval"),
        ("Die Rechnung liegt im Archiv [1]. Es bestehen keine datenschutzrechtlichen Bedenken.", "unsupported_privacy_approval"),
    ],
)
def test_heuristic_findings_are_advisory_and_do_not_require_retry(answer, code):
    result = load_harness().validate_answer(answer, _validation_decision())

    assert result.status == "accepted"
    assert [(item["code"], item["severity"]) for item in result.violations] == [(code, "advisory")]


def test_unknown_source_is_blocking_and_requires_retry():
    result = load_harness().validate_answer("Die Rechnung liegt im Archiv [7].", _validation_decision())

    assert result.status == "retry_required"
    assert {"code": "unknown_source_id", "severity": "blocking"}.items() <= result.violations[0].items()

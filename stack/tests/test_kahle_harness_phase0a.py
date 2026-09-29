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

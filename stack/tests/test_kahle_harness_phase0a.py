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

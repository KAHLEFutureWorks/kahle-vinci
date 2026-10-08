"""Personio evidence is shown by name (decision 2026-10-08, option A).

"[P1]" has no citation chip in OpenWebUI. After validation the visible
answer says "(Personio)" and names the directory with its sync date.
"""

import ast
import re
from pathlib import Path
from typing import Any

import pytest

MIDDLEWARE = Path(__file__).resolve().parents[1] / "open-webui-overrides" / "open_webui" / "utils" / "middleware.py"


def _present():
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_present_personio_citations")
    namespace: dict[str, Any] = {"Any": Any, "re": re}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(MIDDLEWARE), "exec"), namespace)
    return namespace["_present_personio_citations"]


def _output(text):
    return [{"type": "message", "content": [{"type": "output_text", "text": text}]}]


def _text(output):
    return output[0]["content"][0]["text"]


PAYLOAD = {"evidence_bundle": {"sync_completed_at": "2026-10-08T14:40:40Z"}}


def test_personio_marker_becomes_a_named_source_line():
    output = _output("Max Beispiel ist Marketingleiter in Hannover [P1].\n\n[Wissensfehler melden](/wissen/?feedback=1)")

    _present()(output, PAYLOAD)

    assert _text(output) == (
        "Max Beispiel ist Marketingleiter in Hannover (Personio).\n\n"
        "Quelle: Personio-Mitarbeiterverzeichnis, Stand 08.10.2026\n\n"
        "[Wissensfehler melden](/wissen/?feedback=1)"
    )


def test_line_goes_before_the_document_sources_and_markers_merge():
    output = _output("A ist zuständig [P1][P2] und B [P3]. Prozess [1].\n\nQuellen:\n- [Doc](/wissen/api/portal/sources/x)")

    _present()(output, PAYLOAD)

    assert _text(output) == (
        "A ist zuständig (Personio) und B (Personio). Prozess [1].\n\n"
        "Quelle: Personio-Mitarbeiterverzeichnis, Stand 08.10.2026\n\n"
        "Quellen:\n- [Doc](/wissen/api/portal/sources/x)"
    )


@pytest.mark.parametrize("payload", [None, {}, {"evidence_bundle": {"sync_completed_at": "kaputt"}}])
def test_without_a_valid_sync_date_the_line_has_no_date(payload):
    output = _output("Rolle laut Verzeichnis [P1].")

    _present()(output, payload)

    assert _text(output) == "Rolle laut Verzeichnis (Personio).\n\nQuelle: Personio-Mitarbeiterverzeichnis"


def test_answers_without_personio_markers_stay_untouched():
    output = _output("Prozess [1].")

    _present()(output, PAYLOAD)

    assert _text(output) == "Prozess [1]."


def test_presentation_runs_after_every_validation():
    source = MIDDLEWARE.read_text(encoding="utf-8")
    call = source.index("_present_personio_citations(output, harness_payload)")

    assert call > source.rindex("validate_knowledge_harness_answer(")
    assert call > source.rindex("_observe_model_led_answer(")
    assert call > source.rindex("_enforce_knowledge_answer(")

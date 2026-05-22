#!/usr/bin/env python3
"""Regression checks for PDF/Office to Markdown cleanup in the document worker."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
WORKER_MAIN = ROOT / "document-worker" / "app" / "main.py"


def load_cleanup_helpers() -> dict[str, Any]:
    src = WORKER_MAIN.read_text(encoding="utf-8")
    start = src.index("_MOJIBAKE_MARKERS")
    end = src.index("def _extract_text_docx")
    ns: dict[str, Any] = {
        "re": __import__("re"),
        "os": __import__("os"),
        "tempfile": __import__("tempfile"),
        "Optional": Optional,
        "List": List,
        "Tuple": Tuple,
        "Dict": Dict,
        "Any": Any,
        "USE_MARKITDOWN": False,
        "_guess_ext": lambda filename: (filename.rsplit(".", 1)[-1].lower() if "." in filename else ""),
    }
    exec(src[start:end], ns)
    return ns


HELPERS = load_cleanup_helpers()


def test_repair_mojibake_for_german_pdf_text():
    raw = "DatenqualitÃ¤t fÃ¼r VerkÃ¤ufer â€¢ â€žStammkundenâ€œ"

    assert HELPERS["_repair_mojibake"](raw) == "Datenqualität für Verkäufer • „Stammkunden“"


def test_normalize_pdf_spacing_and_bullets():
    raw = """
Eure Auf  gaben:
â€¢ Bessere Vorbereitung:  Sie haben alle Informationen.
1.Le gt die gesammelten DSEs ein.
K AHLE kauft dein Auto und CRM -Manager
"""

    cleaned = HELPERS["_normalize_extracted_text"](raw, paragraphize=True)

    assert "Eure Aufgaben:" in cleaned
    assert "- Bessere Vorbereitung:" in cleaned
    assert "1. Legt die gesammelten DSEs ein." in cleaned
    assert "KAHLE kauft dein Auto und CRM-Manager" in cleaned
    assert "Ã" not in cleaned
    assert "â€¢" not in cleaned


def test_paragraphize_visual_line_wraps_but_preserves_lists():
    raw = """
Einführung:
Dies ist ein langer Satz
der im PDF nur visuell umgebrochen wurde.
- Erster Punkt
- Zweiter Punkt
"""

    cleaned = HELPERS["_normalize_extracted_text"](raw, paragraphize=True)

    assert "Dies ist ein langer Satz der im PDF nur visuell umgebrochen wurde." in cleaned
    assert "- Erster Punkt" in cleaned
    assert "- Zweiter Punkt" in cleaned


def test_paragraphize_merges_wrapped_list_items_across_blank_lines():
    raw = """
- Eure Arbeit erleichtert, indem zukünftige Anfragen schneller und reibungsloser bearbeitet

werden können.

- Die Kundenbindung stärkt, da die Kunden eine professionelle und effiziente Betreuung

erfahren.
"""

    cleaned = HELPERS["_normalize_extracted_text"](raw, paragraphize=True)

    assert "- Eure Arbeit erleichtert, indem zukünftige Anfragen schneller und reibungsloser bearbeitet werden können." in cleaned
    assert "- Die Kundenbindung stärkt, da die Kunden eine professionelle und effiziente Betreuung erfahren." in cleaned
    assert "bearbeitet\n\nwerden" not in cleaned


def test_paragraphize_does_not_swallow_paragraph_after_finished_list_item():
    raw = """
- Wenn der Kunde keine E-Mail-Adresse angeben möchte, lasst ihr das Feld frei.

Vielen Dank für eure Unterstützung.
"""

    cleaned = HELPERS["_normalize_extracted_text"](raw, paragraphize=True)

    assert "- Wenn der Kunde keine E-Mail-Adresse angeben möchte, lasst ihr das Feld frei." in cleaned
    assert "\nVielen Dank für eure Unterstützung." in cleaned
    assert "frei. Vielen Dank" not in cleaned


def test_paragraphize_merges_sentence_continuation_across_soft_blank():
    raw = """
Die Erfassung korrekter Daten ist wichtig für euch

als Servicemitarbeiter, da ihr:
"""

    cleaned = HELPERS["_normalize_extracted_text"](raw, paragraphize=True)

    assert "wichtig für euch als Servicemitarbeiter, da ihr:" in cleaned


if __name__ == "__main__":
    test_repair_mojibake_for_german_pdf_text()
    test_normalize_pdf_spacing_and_bullets()
    test_paragraphize_visual_line_wraps_but_preserves_lists()
    test_paragraphize_merges_wrapped_list_items_across_blank_lines()
    test_paragraphize_does_not_swallow_paragraph_after_finished_list_item()
    test_paragraphize_merges_sentence_continuation_across_soft_blank()
    print("document worker markdown cleanup tests passed")

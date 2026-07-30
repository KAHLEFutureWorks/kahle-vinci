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
        "Counter": __import__("collections").Counter,
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


def test_pdf_margin_cleanup_and_layout_preservation():
    pages = [
        f"VaudisX Dokumentation\n\n{n}.2 Inhalt\n\nFirma   Öffentlich   Seite {n} von 8\nVersion: 1.0 gültig ab: 15.01.2026"
        for n in range(1, 9)
    ]
    repeated = HELPERS["_detect_repeated_pdf_margin_lines"](pages)
    cleaned = HELPERS["_strip_pdf_margin_lines"](pages[3], repeated)
    assert "VaudisX Dokumentation" not in cleaned
    assert "Öffentlich" not in cleaned
    assert "4.2 Inhalt" in cleaned

    table = "Feld             Beschreibung\nKonto            Erlösbuchung\nNachlass         Sollkonto"
    markdown = HELPERS["_pdf_page_to_markdown"](f"2.6.3 Titel\n\n{table}", 100)
    assert "<!-- Seite 100 -->" in markdown
    assert "### 2.6.3 Titel" in markdown
    assert "```text" in markdown
    assert table in markdown


def test_ocr_deduplicates_page_text_and_redacts_sensitive_values():
    lines = [
        "Bestellung bearbeitet",
        "Zusätzlicher Status: Teile vollständig ausgeliefert",
        "Kontakt test@example.org",
        "Telefon 0511 1234567",
        "Zusätzlicher Status: Teile vollständig ausgeliefert",
    ]
    result = HELPERS["_dedupe_ocr_lines"]("Bestellung bearbeitet", lines)
    assert "Bestellung bearbeitet" not in result
    assert result.count("Zusätzlicher Status: Teile vollständig ausgeliefert") == 1
    assert any("[E-MAIL ENTFERNT]" in line for line in result)
    assert any("[TELEFON ENTFERNT]" in line for line in result)


def test_ocr_deduplicates_across_document_and_removes_dynamic_examples():
    document_seen: set[str] = set()
    first = HELPERS["_dedupe_ocr_lines"](
        "",
        ["Teileanforderung \u00f6ffnen", "Jan-Philip Golding", "K LF 1162", "1781707730505.jpg", "B\u00fchne Meyer", "3V544D"],
        document_seen,
    )
    second = HELPERS["_dedupe_ocr_lines"]("", ["Teileanforderung \u00f6ffnen"], document_seen)
    assert first == ["Teileanforderung \u00f6ffnen"]
    assert second == []


def test_tabular_pdf_page_preserves_column_alignment():
    page = """
Fall                                                                              Ja   Nein   Besonderheiten / Ausnahmen
Aufleuchten einer roten Warnlampe                                                  X          Fahrzeug nicht bewegen
Glasbruch Verglasung                                                                   X     Versicherung
Besch\u00e4digter Reifen                                                                X          Nur bei Mobilit\u00e4tsverlust
Weitere Besch\u00e4digung                                                                   X     R\u00fccksprache erforderlich
"""
    assert HELPERS["_looks_like_tabular_page"](page)
    markdown = HELPERS["_pdf_page_to_markdown"](page, 3)
    assert "```text" in markdown
    assert "Glasbruch Verglasung" in markdown
    assert "   X     Versicherung" in markdown

def test_centered_bullets_are_not_misclassified_as_table():
    block = """
 -   Danach ist der Werkstattstatus noch zu ändern
 -   Sobald dies passiert ist, bekommt der SB eine Mitteilung
 -   Die Kachel erscheint dann im jeweiligen Feld
"""
    assert not HELPERS["_looks_like_fixed_width_table"](block)

def test_short_pdf_keeps_repeated_content():
    pages = ["Interne Richtlinie\nWichtiger Inhalt"] * 3
    assert HELPERS["_detect_repeated_pdf_margin_lines"](pages) == set()

if __name__ == "__main__":
    test_repair_mojibake_for_german_pdf_text()
    test_normalize_pdf_spacing_and_bullets()
    test_paragraphize_visual_line_wraps_but_preserves_lists()
    test_paragraphize_merges_wrapped_list_items_across_blank_lines()
    test_paragraphize_does_not_swallow_paragraph_after_finished_list_item()
    test_paragraphize_merges_sentence_continuation_across_soft_blank()
    test_pdf_margin_cleanup_and_layout_preservation()
    test_short_pdf_keeps_repeated_content()
    test_ocr_deduplicates_page_text_and_redacts_sensitive_values()
    test_ocr_deduplicates_across_document_and_removes_dynamic_examples()
    test_tabular_pdf_page_preserves_column_alignment()
    test_centered_bullets_are_not_misclassified_as_table()
    print("document worker markdown cleanup tests passed")

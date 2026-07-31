import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = ROOT / "stack" / "owui-file-proxy" / "app"


def load(name: str):
    path = APP_ROOT / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class HumanDocumentConversionTests(unittest.TestCase):
    def test_pdf_markdown_is_cleaned_and_structured_for_people(self):
        module = load("human_document")
        source = (
            "# Konvertiert\n\n"
            "## Datei: abc_faq.pdf (pdf)\n\n"
            "<!-- Seite 1 -->\n\n"
            "FAQ zum Piloten Grenzfall der Immobilität\n\n"
            "Stand 10.07.2026\n\n"
            "<!-- Seite 2 -->\n\n"
            "Empfohlene Vorgehensweise\n\n"
            "Ein normaler Absatz.\n\n"
            "Hinweis: Nur für bestimmte Fahrzeuge.\n"
        )
        title = module.infer_human_title(source, "Konvertiert", "abc_faq")
        cleaned = module.prepare_human_markdown(source, title=title)
        self.assertEqual(title, "FAQ zum Piloten Grenzfall der Immobilität")
        self.assertNotIn("Datei:", cleaned)
        self.assertNotIn("<!-- Seite", cleaned)
        self.assertNotIn("# Konvertiert", cleaned)
        self.assertIn("## Empfohlene Vorgehensweise", cleaned)
        self.assertIn("> Hinweis: Nur für bestimmte Fahrzeuge.", cleaned)

    def test_fixed_width_pdf_table_becomes_structured_rows(self):
        theme = load("kahle_document_theme")
        source = (
            "Der Kunde erreicht aus eigener Kraft die Werkstatt\n"
            "eine Weiterfahrt ist nicht zumutbar\n"
            "Fall                                      Ja      Nein     Besonderheiten / Ausnahmen\n"
            "Gelbe Kontrollleuchte                     X                Nur bis zur Prüfung\n"
            "Fortsetzung des ersten Falls                               durch die Werkstatt\n"
            "\n"
            "Glasbruch Verglasung                              X        Versicherung\n"
        )
        result = theme._fixed_width_table(source)
        self.assertIsNotNone(result)
        prefix, rows = result
        self.assertEqual(prefix[0], "Der Kunde erreicht aus eigener Kraft die Werkstatt")
        self.assertEqual(rows[0], ["Fall", "Ja", "Nein", "Besonderheiten / Ausnahmen"])
        self.assertEqual(len(rows), 3)
        self.assertIn("Fortsetzung des ersten Falls", rows[1][0])
        self.assertEqual(rows[2][2], "X")
        self.assertEqual(theme._docx_table_weights(rows), [5.2, 0.75, 0.75, 3.3])

    def test_word_layout_is_fixed_and_callouts_cannot_split(self):
        source = (APP_ROOT / "kahle_document_theme.py").read_text(encoding="utf-8")
        self.assertIn('layout.set(qn("w:type"), "fixed")', source)
        self.assertIn('cant_split = OxmlElement("w:cantSplit")', source)
        self.assertIn("label_cell, body_cell = table.rows[0].cells", source)


if __name__ == "__main__":
    unittest.main()

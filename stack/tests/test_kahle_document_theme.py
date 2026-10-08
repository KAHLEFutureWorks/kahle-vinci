import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
THEME_PATH = ROOT / "stack" / "owui-file-proxy" / "app" / "kahle_document_theme.py"
BRAND_PATH = ROOT / "assets" / "brand" / "colors" / "kahle-brand.json"


def load_theme():
    spec = importlib.util.spec_from_file_location("kahle_document_theme", THEME_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class KahleDocumentThemeTests(unittest.TestCase):
    def test_markdown_parser_keeps_structural_blocks(self):
        theme = load_theme()
        blocks = theme.parse_markdown(
            "# Titel\n\nIntro\n\n- A\n- B\n\n| Feld | Wert |\n|---|---|\n| X | Y |\n\n> Warnung: Frist beachten",
            "Titel",
        )
        blocks = [block for block in blocks if block["type"] != "space"]
        self.assertEqual([block["type"] for block in blocks], ["paragraph", "bullets", "table", "callout"])
        self.assertEqual(blocks[2]["rows"], [["Feld", "Wert"], ["X", "Y"]])

    def test_markdown_links_become_readable_text(self):
        """UI acceptance 08.10.: exported PDFs showed raw [label](/wissen/...) links."""
        theme = load_theme()
        blocks = theme.parse_markdown(
            "Siehe [Prozess](/wissen/api/portal/sources/abc) und [Hersteller](https://example.org/hilfe).\n\n"
            "- [KAHLE Speak Nutzer Kontext](/wissen/api/portal/sources/def)",
            "Titel",
        )
        blocks = [block for block in blocks if block["type"] != "space"]
        self.assertEqual(blocks[0]["text"], "Siehe Prozess und Hersteller (https://example.org/hilfe).")
        self.assertEqual(blocks[1]["items"], ["KAHLE Speak Nutzer Kontext"])

    def test_pdf_text_has_no_glyphs_outside_the_base_font(self):
        """UI acceptance 08.10.: a non-breaking hyphen rendered as a black box."""
        theme = load_theme()
        rendered = theme._rl_inline("Auftragseingangs‑Workflow, 5 % − 2 – ok „ja“")
        self.assertEqual(rendered, "Auftragseingangs-Workflow, 5 % - 2 – ok „ja“")
        rendered.encode("cp1252")

    def test_legal_footer_data_is_central_and_complete(self):
        company = json.loads(BRAND_PATH.read_text(encoding="utf-8"))["company"]
        self.assertEqual(company["name"], "Autohaus KAHLE GmbH & Co. KG")
        self.assertEqual(company["vat_id"], "DE 115 699 464")
        self.assertEqual(company["iban"], "DE79 2519 0001 0028 9647 00")
        self.assertEqual(company["bic"], "VOHADE2HXXX")
        self.assertIn("Karl-Heinz Kahle", company["managing_directors"])

    def test_docx_and_pdf_use_multipage_brand_chrome(self):
        source = THEME_PATH.read_text(encoding="utf-8")
        self.assertIn("section.first_page_footer", source)
        self.assertIn("section.even_page_footer", source)
        self.assertIn("_kahle_page_count", source)
        self.assertIn('styles.add(ParagraphStyle(name="TableHeader"', source)


if __name__ == "__main__":
    unittest.main()
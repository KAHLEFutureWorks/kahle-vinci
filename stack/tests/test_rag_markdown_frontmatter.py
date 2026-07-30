import importlib.util
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "stack" / "owui-file-proxy" / "app" / "rag_markdown.py"
MAIN_PATH = ROOT / "stack" / "owui-file-proxy" / "app" / "main.py"

spec = importlib.util.spec_from_file_location("rag_markdown", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


class RagMarkdownFrontmatterTests(unittest.TestCase):
    def test_exact_default_frontmatter(self):
        result = module.ensure_rag_frontmatter(
            "# Inhalt\n\nText",
            title="BulliHerz Sub-Brand Guideline",
            document_id="BulliHerz_Brand_Guideline.md",
            today=date(2026, 7, 29),
        )
        self.assertTrue(result.startswith(
            "---\n"
            "title: BulliHerz Sub-Brand Guideline\n"
            "document_id: BulliHerz_Brand_Guideline.md\n"
            "owner:\n"
            "status: active\n"
            "valid_until: 2027-07-29\n"
            "notify_before_days: 14\n"
            "rag_index: true\n"
            "---\n\n"
        ))

    def test_existing_frontmatter_is_replaced_not_duplicated(self):
        source = "---\ntitle: Alt\nowner: Person\n---\n\n# Neu\n\nInhalt"
        result = module.ensure_rag_frontmatter(
            source,
            title="Konvertiert",
            document_id="neu.md",
            today=date(2026, 7, 29),
        )
        self.assertEqual(result.count("\n---\n"), 1)
        self.assertIn("title: Neu", result)
        self.assertNotIn("owner: Person", result)

    def test_leap_day_uses_last_valid_day_next_year(self):
        result = module.ensure_rag_frontmatter(
            "Text", title="Test", document_id="test.md", today=date(2024, 2, 29)
        )
        self.assertIn("valid_until: 2025-02-28", result)

    def test_all_downloadable_markdown_paths_apply_frontmatter(self):
        source = MAIN_PATH.read_text(encoding="utf-8")
        self.assertGreaterEqual(source.count("ensure_rag_frontmatter("), 4)
        self.assertIn('version="1.7.0"', source)


if __name__ == "__main__":
    unittest.main()
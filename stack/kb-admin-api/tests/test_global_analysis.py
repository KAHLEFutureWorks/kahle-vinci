from pathlib import Path

from app.global_analysis import (
    ComparisonThresholds, CorpusDocument, GlobalCorpus, GlobalDocumentAnalyzer,
    normalize_markdown,
)
from app.portal_governance import SQLiteGovernanceStore


class Embeddings:
    def embed(self, texts):
        vectors = []
        for text in texts:
            vectors.append([1.0, 0.0] if "Urlaub" in text else [0.0, 1.0])
        return vectors


def test_normalization_removes_frontmatter_and_format_noise():
    left = "---\nowner: a@kahle.de\n---\n# Regel\n**Maximal 10 Tage.**"
    right = "# REGEL\nMaximal   10 Tage."
    assert normalize_markdown(left) == normalize_markdown(right)


def test_global_analysis_sees_cross_kb_exact_duplicate(tmp_path: Path):
    corpus = GlobalCorpus(SQLiteGovernanceStore(tmp_path / "portal.sqlite3"))
    corpus.upsert(CorpusDocument("doc-a", "v-a", "Urlaubsregel", "# Urlaub\nMaximal 10 Tage.", ("service",)))
    result = GlobalDocumentAnalyzer(corpus).analyze(
        version_id="v-new", title="Urlaubsregel", markdown="---\nowner: x\n---\n# Urlaub\nMaximal 10 Tage."
    )
    assert result.exact_document_id == "doc-a"
    assert result.matches[0].knowledgebase_ids == ("service",)
    assert result.matches[0].level == "identical"


def test_semantic_and_lexical_signals_are_combined_and_version_is_suggested(tmp_path: Path):
    corpus = GlobalCorpus(SQLiteGovernanceStore(tmp_path / "portal.sqlite3"))
    corpus.upsert(CorpusDocument("doc-a", "v-a", "Urlaubsregel 2025", "Urlaub darf höchstens 10 Tage dauern.", ("personal",)))
    result = GlobalDocumentAnalyzer(
        corpus, Embeddings(), thresholds=ComparisonThresholds(very_high=.8, medium=.45, low=.2)
    ).analyze(version_id="v-new", title="Urlaubsregel 2026", markdown="Urlaub darf maximal 12 Tage dauern.")
    assert result.matches[0].semantic_score == 1.0
    assert result.matches[0].version_candidate is True
    assert result.contradiction_document_ids == ("doc-a",)
    assert result.matches[0].conflicting_passages

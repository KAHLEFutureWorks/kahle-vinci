from pathlib import Path

from app.global_analysis import (
    ComparisonThresholds, CorpusDocument, GlobalCorpus, GlobalDocumentAnalyzer, IonosEmbeddingProvider,
    normalize_markdown,
)
from app.portal_governance import SQLiteGovernanceStore


class Embeddings:
    def embed(self, texts):
        vectors = []
        for text in texts:
            vectors.append([1.0, 0.0] if "Urlaub" in text else [0.0, 1.0])
        return vectors


class SizeLimitedEmbeddings:
    def __init__(self):
        self.lengths = []

    def embed(self, texts):
        self.lengths = [len(text) for text in texts]
        if any(length > 24_000 for length in self.lengths):
            raise RuntimeError("embedding input too large")
        return [[1.0, 0.0] for _ in texts]


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


def test_large_documents_use_bounded_semantic_representations(tmp_path: Path):
    corpus = GlobalCorpus(SQLiteGovernanceStore(tmp_path / "portal.sqlite3"))
    corpus.upsert(CorpusDocument("doc-a", "v-a", "Handbuch", "A" * 130_000, ("service",)))
    embeddings = SizeLimitedEmbeddings()

    GlobalDocumentAnalyzer(corpus, embeddings).analyze(
        version_id="v-new", title="Neues Handbuch", markdown="B" * 127_000,
    )

    assert embeddings.lengths
    assert max(embeddings.lengths) <= 24_000


def test_withdrawn_or_rejected_drafts_leave_global_comparison_corpus(tmp_path: Path):
    store = SQLiteGovernanceStore(tmp_path / "portal.sqlite3")
    corpus = GlobalCorpus(store)
    corpus.upsert(CorpusDocument("draft", "version", "Entwurf", "# Inhalt\n\nNicht freigegeben", ("service",), "pending"))
    assert [item.document_id for item in corpus.documents()] == ["draft"]
    corpus.set_status("version", "withdrawn")
    assert corpus.documents() == []


def test_ionos_embedding_adapter_retries_transient_outage(monkeypatch):
    import app.global_analysis as module
    attempts=[]
    class Response:
        def raise_for_status(self): return None
        def json(self): return {"data":[{"index":0,"embedding":[1.0,0.0]}]}
    def post(*args, **kwargs):
        attempts.append(1)
        if len(attempts)<3: raise module.requests.ConnectionError("temporary")
        return Response()
    monkeypatch.setattr(module.requests,"post",post)
    monkeypatch.setattr(module.time,"sleep",lambda value:None)
    assert IonosEmbeddingProvider("https://ionos.test","token","model",retries=3).embed(["Text"]) == [[1.0,0.0]]
    assert len(attempts)==3


def test_ionos_embedding_adapter_splits_large_corpus_requests(monkeypatch):
    import app.global_analysis as module

    batches = []

    class Response:
        def __init__(self, texts):
            self.texts = texts

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [
                    {"index": index, "embedding": [float(text.split("-")[-1]), 1.0]}
                    for index, text in enumerate(self.texts)
                ],
            }

    def post(*args, **kwargs):
        texts = list(kwargs["json"]["input"])
        batches.append(texts)
        return Response(texts)

    monkeypatch.setattr(module.requests, "post", post)
    provider = IonosEmbeddingProvider(
        "https://ionos.test", "token", "model", retries=1,
        max_batch_texts=2, max_batch_characters=100,
    )

    vectors = provider.embed([f"document-{index}" for index in range(5)])

    assert [len(batch) for batch in batches] == [2, 2, 1]
    assert [vector[0] for vector in vectors] == [0.0, 1.0, 2.0, 3.0, 4.0]

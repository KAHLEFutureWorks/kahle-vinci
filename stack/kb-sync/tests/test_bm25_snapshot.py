from pathlib import Path

from app.bm25_snapshot import BM25Snapshot
from app.hybrid_index import BM25Corpus


def test_snapshot_roundtrip_binds_sparse_query_to_index_build(tmp_path: Path):
    corpus = BM25Corpus(["Aktion A1b Service", "Allgemeiner Service"])
    path = tmp_path / "bm25.json"
    BM25Snapshot.from_corpus("build-123", corpus).save_atomic(path)
    encoded = BM25Snapshot.load(path).encode_query("Aktion A1b")
    assert encoded["build_id"] == "build-123"
    assert len(encoded["indices"]) == len(encoded["values"])
    assert encoded["indices"]

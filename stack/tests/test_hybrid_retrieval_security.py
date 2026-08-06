import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest


PATH = Path(__file__).resolve().parents[1] / "open-webui-tools" / "hybrid_retrieval.py"
SPEC = importlib.util.spec_from_file_location("hybrid_retrieval", PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_acl_filter_is_mandatory_and_covers_rights_status_publication_and_validity():
    with pytest.raises(module.RetrievalError, match="no_readable"):
        module.RetrievalScope("user-1", (), ())
    scope = module.RetrievalScope("user-1", ("service", "verkauf"), ("v1", "v2"))
    query_filter = module.mandatory_acl_filter(scope, date(2026, 8, 6))
    assert {item["key"] for item in query_filter["must"]} == {
        "knowledgebase_ids", "version_id", "status", "published", "valid_from", "valid_until"
    }
    assert query_filter["must"][0]["match"]["any"] == ["service", "verkauf"]


def test_rrf_combines_dense_and_sparse_without_score_scale_dependency():
    fused = module.reciprocal_rank_fusion([["dense-a", "both"], ["both", "sparse-b"]])
    assert fused[0][0] == "both"


def test_hybrid_request_repeats_acl_in_both_prefetches_and_rejects_leak(monkeypatch):
    captured = {}

    class Response:
        content = b"x"
        def raise_for_status(self): pass
        def json(self):
            return {"result": {"points": [{
                "id": "p1", "score": .9,
                "payload": {"document_id": "secret", "version_id": "v1", "title": "Secret",
                            "content": "secret", "knowledgebase_ids": ["personal"], "status": "active",
                            "published": True, "source_id": "s", "source_url": "/s", "valid_until": "2026-09-01"},
            }]}}

    def post(url, json, timeout):
        captured["body"] = json
        return Response()

    monkeypatch.setattr(module.requests, "post", post)

    class Sparse:
        def encode_query(self, query): return {"build_id": "build-1", "indices": [1], "values": [1.0]}
    class Reranker:
        def rerank(self, query, documents, top_n): return [(0, .99)]

    retriever = module.QdrantHybridRetriever("http://qdrant", "vinci_knowledge", Sparse(), Reranker())
    with pytest.raises(module.RetrievalError, match="acl_violation"):
        retriever.retrieve("frage", [1.0], module.RetrievalScope("u", ("service",), ("v1",)), today=date(2026, 8, 6))
    assert captured["body"]["prefetch"][0]["filter"] == captured["body"]["prefetch"][1]["filter"]
    assert {item["key"] for item in captured["body"]["prefetch"][0]["filter"]["must"]} >= {"build_id"}
    assert captured["body"]["query"] == {"fusion": "rrf"}

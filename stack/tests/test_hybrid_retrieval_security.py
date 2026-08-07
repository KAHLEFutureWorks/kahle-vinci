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


def test_reranking_runs_on_ionos_and_not_on_a_local_service():
    """
    Der lokale CPU-Cross-Encoder brauchte rund zwei Sekunden je Kandidat. Bei den
    von PRD 19.2 erzwungenen 30 bis 50 Kandidaten lief das fail-closed gebaute
    Retrieval damit in jeden Timeout. Reranking gehoert deshalb auf die
    freigegebenen IONOS-Endpunkte (PRD Prinzip 10), und der lokale Dienst darf
    nicht zurueckkehren.
    """
    stack_root = Path(__file__).resolve().parents[1]
    compose = (stack_root / "docker-compose.yml").read_text(encoding="utf-8")
    assert "reranker" not in compose, "local reranker service must stay removed"

    tools = stack_root / "open-webui-tools"
    for name in ("rag_chat_hybrid_tool.py", "kahle_workflow_orchestrator.py"):
        source = (tools / name).read_text(encoding="utf-8")
        assert "IonosReranker(base_url, api_key" in source, name
        assert "TeiReranker(" not in source, f"{name} must not fall back to the local reranker"


def test_ionos_reranker_reads_the_documented_response_shape():
    """IONOS antwortet im Cohere-Format, nicht im TEI-Format."""
    captured = {}

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"results": [{"index": 1, "relevance_score": 0.96},
                                {"index": 0, "relevance_score": 0.02}]}

    def fake_post(url, **kwargs):
        captured.update(url=url, payload=kwargs["json"])
        return Response()

    original = module.requests.post
    module.requests.post = fake_post
    try:
        ranked = module.IonosReranker(
            "https://openai.inference.de-txl.ionos.com/v1", "token", "Qwen/Qwen3-VL-Reranker-8B",
        ).rerank("frage", ["a", "b"], top_n=2)
    finally:
        module.requests.post = original

    assert captured["url"].endswith("/v1/rerank")
    assert captured["payload"]["documents"] == ["a", "b"]
    assert captured["payload"]["model"] == "Qwen/Qwen3-VL-Reranker-8B"
    assert ranked == [(1, 0.96), (0, 0.02)]


def test_distributed_tool_bundles_are_self_contained_and_current():
    """
    OpenWebUI nimmt pro Tool genau eine Datei und stellt keinen Modulsuchpfad
    bereit. Die Quelldateien der Hybrid-Tools verweisen aber auf Klassen aus
    hybrid_retrieval.py; nur die gebauten Bundles unter dist/ sind lauffaehig.
    Dieser Test schlaegt fehl, sobald eine Quelle geaendert und das Bundle nicht
    neu gebaut wurde.
    """
    import importlib.util
    import subprocess

    tools = Path(__file__).resolve().parents[1] / "open-webui-tools"
    result = subprocess.run(
        [sys.executable, str(tools / "build_tools.py"), "--check"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"dist/ ist veraltet:\n{result.stdout}{result.stderr}"

    for name in ("rag_chat_hybrid_tool.py", "kahle_workflow_orchestrator.py"):
        bundle = tools / "dist" / name
        assert bundle.exists(), f"{name} fehlt in dist/"
        spec = importlib.util.spec_from_file_location(f"bundle_{name[:-3]}", bundle)
        loaded = importlib.util.module_from_spec(spec)
        # dataclass loest __module__ ueber sys.modules auf; ohne Registrierung
        # scheitert schon der Import des Bundles.
        sys.modules[spec.name] = loaded
        try:
            spec.loader.exec_module(loaded)
        finally:
            sys.modules.pop(spec.name, None)
        for required in ("Tools", "IonosReranker", "QdrantHybridRetriever"):
            assert hasattr(loaded, required), f"{name} bundle is missing {required}"
        # Dekoratoren gingen beim Zusammenbauen verloren, weil lineno einer
        # Klasse auf das Schluesselwort zeigt und nicht auf @dataclass. Die
        # Klasse nahm dann keine Argumente mehr an und jedes Retrieval brach
        # mit RetrievalError ab.
        scope = loaded.RetrievalScope("user-1", ("kb-1",), ("version-1",))
        assert scope.knowledgebase_ids == ("kb-1",)

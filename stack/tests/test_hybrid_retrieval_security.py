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


def test_rag_tool_reports_content_free_retrieval_metrics_to_portal():
    stack_root = Path(__file__).resolve().parents[1]
    source = (stack_root / "open-webui-tools" / "rag_chat_hybrid_tool.py").read_text(encoding="utf-8")
    built = (stack_root / "open-webui-tools" / "dist" / "rag_chat_hybrid_tool.py").read_text(encoding="utf-8")
    for value in (source, built):
        assert "/portal/internal/retrieval-events" in value
        assert "query_hash" in value and "latency_ms" in value and "source_count" in value
        telemetry = value.split("def _hybrid_record_event", 1)[1].split("class Tools", 1)[0]
        assert '"query": query' not in telemetry and '"content":' not in telemetry


def test_retrieval_metric_payload_hashes_question_and_omits_raw_content(monkeypatch):
    tool_path = Path(__file__).resolve().parents[1] / "open-webui-tools" / "rag_chat_hybrid_tool.py"
    spec = importlib.util.spec_from_file_location("rag_chat_metric_contract", tool_path)
    tool = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(tool)
    captured = {}

    class Response:
        status_code = 200

    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr(tool.requests, "post", post)
    tool._hybrid_record_event("http://portal", "secret", "user-1", "interne geheime Frage",
                              True, 2, tool.time.monotonic() - .1)

    assert captured["url"].endswith("/portal/internal/retrieval-events")
    assert captured["json"]["query_hash"] != "interne geheime Frage"
    assert len(captured["json"]["query_hash"]) == 64
    assert "query" not in captured["json"] and "content" not in captured["json"]


def test_low_relevance_results_are_rejected_after_reranking(monkeypatch):
    class Response:
        content = b"x"
        def raise_for_status(self): pass
        def json(self):
            return {"result": {"points": [{
                "id": "p1", "score": .8,
                "payload": {"document_id": "doc", "version_id": "v1", "title": "Unpassend",
                            "content": "anderes Thema", "knowledgebase_ids": ["service"], "status": "active",
                            "published": True, "source_id": "s", "source_url": "/s",
                            "valid_until": "2026-09-01"},
            }]}}

    monkeypatch.setattr(module.requests, "post", lambda *args, **kwargs: Response())

    class Sparse:
        def encode_query(self, query): return {"build_id": "build-1", "indices": [1], "values": [1.0]}
    class WeakReranker:
        def rerank(self, query, documents, top_n): return [(0, .249)]

    retriever = module.QdrantHybridRetriever(
        "http://qdrant", "vinci_knowledge", Sparse(), WeakReranker(), minimum_rerank_score=.25,
    )
    result = retriever.retrieve(
        "unbelegte Frage", [1.0], module.RetrievalScope("u", ("service",), ("v1",)),
        today=date(2026, 8, 6),
    )

    assert result == []


def test_relevance_threshold_is_validated():
    with pytest.raises(module.RetrievalError, match="minimum_rerank_score_out_of_range"):
        module.QdrantHybridRetriever("http://qdrant", "kb", object(), object(), minimum_rerank_score=1.01)


def test_candidate_pool_keeps_distinct_parents_from_the_same_document_for_reranking():
    points = [
        {"id": f"p{index}", "payload": {"document_id": "doc-1", "parent_id": f"parent-{index}"}}
        for index in range(4)
    ]
    points.append({"id": "duplicate-child", "payload": {"document_id": "doc-1", "parent_id": "parent-1"}})

    candidates = module.QdrantHybridRetriever._parent_centered(points, 50)

    assert [item["payload"]["parent_id"] for item in candidates] == [
        "parent-0", "parent-1", "parent-2", "parent-3"
    ]


def test_explicit_source_identifier_is_extracted_and_folded():
    assert module.explicit_source_identifiers(
        "Was steht in der Quelle KB_KAHLE_Hannover und in Richtlinie-v1.4.pdf?"
    ) == ("kbkahlehannover", "richtliniev14")


def test_natural_document_title_focuses_compliance_question_on_compliance_document():
    candidates = [
        {"payload": {"document_id": "compliance", "title": "KAHLE KI-Compliance v1.2"}},
        {"payload": {"document_id": "policy", "title": "KAHLE KI Policy v1.4"}},
        {"payload": {"document_id": "guideline", "title": "KAHLE KI Richtlinie v1.4"}},
    ]

    assert module.focused_document_ids(
        "Was steht in unserer KI Compliance?", candidates,
    ) == {"compliance"}


def test_broad_results_first_cover_different_documents_before_filling_remaining_slots():
    candidates = [
        {"payload": {"document_id": "a"}},
        {"payload": {"document_id": "a"}},
        {"payload": {"document_id": "a"}},
        {"payload": {"document_id": "b"}},
        {"payload": {"document_id": "b"}},
        {"payload": {"document_id": "c"}},
    ]
    reranked = [(index, 0.99 - index / 100) for index in range(len(candidates))]

    selected = module.diversify_reranked(
        reranked, candidates, result_limit=5, per_document_limit=2,
    )

    assert [index for index, _score in selected] == [0, 1, 3, 4, 5]


def test_named_document_overview_returns_every_main_chapter_and_no_frontmatter(monkeypatch):
    requests_seen = []
    def point(identifier, heading, content, order):
        return {
            "id": identifier, "score": 0.9,
            "payload": {
                "document_id": "compliance", "version_id": "v1",
                "title": "KAHLE KI-Compliance v1.2", "content": content,
                "parent_content": content, "parent_id": identifier,
                "chunk_order": order, "heading_path": heading,
                "knowledgebase_ids": ["richtlinien"], "status": "active",
                "published": True, "source_id": "source-1", "source_url": "/source/v1",
                "valid_until": "2026-11-03", "authority": "5:process", "conflict": False,
            },
        }

    points = [point("meta", [], "---\ndocument_id: compliance\nowner_email: crm@kahle.de\n---", 0)]
    points.extend(
        point(f"chapter-{number}", ["KI-Compliance", f"{number}. Kapitel"],
              f"Inhalt des Hauptkapitels {number}.", number)
        for number in range(1, 9)
    )
    points.extend([
        point("chapter-7-response", ["KI-Compliance", "7. Kapitel", "Incident Response"],
              "Eindämmung, Wiederherstellung und Nachbereitung.", 71),
        point("chapter-7-reporting", ["KI-Compliance", "7. Kapitel", "Meldewege"],
              "Vorfälle werden über die festgelegten Meldewege gemeldet.", 72),
    ])

    class Response:
        def raise_for_status(self): pass
        def json(self): return {"result": {"points": points}}

    def post(url, **kwargs):
        requests_seen.append((url, kwargs.get("json") or {}))
        return Response()

    monkeypatch.setattr(module.requests, "post", post)

    class Sparse:
        def encode_query(self, query):
            return {"build_id": "build-1", "indices": [1], "values": [1.0]}

    class RiskFirstReranker:
        def rerank(self, query, documents, top_n):
            return [(index, 0.99 - index / 100) for index in reversed(range(len(documents)))]

    chunks = module.QdrantHybridRetriever(
        "http://qdrant", "vinci_knowledge", Sparse(), RiskFirstReranker(),
    ).retrieve(
        "Was steht in unserer KI-Compliance?", [1.0],
        module.RetrievalScope("u", ("richtlinien",), ("v1",)),
        today=date(2026, 8, 12),
    )

    assert [chunk.heading_path[-1] for chunk in chunks] == [
        f"{number}. Kapitel" for number in range(1, 9)
    ]
    assert "Eindämmung, Wiederherstellung und Nachbereitung." in chunks[6].parent_content
    assert "festgelegten Meldewege" in chunks[6].parent_content
    assert len(chunks) == 8
    assert all("owner_email:" not in chunk.parent_content for chunk in chunks)
    scroll = next(body for url, body in requests_seen if url.endswith("/points/scroll"))
    must = scroll["filter"]["must"]
    assert {item["key"] for item in must} >= {
        "knowledgebase_ids", "version_id", "status", "published", "valid_from",
        "valid_until", "build_id", "document_id",
    }


def test_title_only_tool_query_still_returns_the_complete_document_overview(monkeypatch):
    def point(number):
        content = f"Vollständiger Inhalt von Kapitel {number}."
        return {
            "id": f"chapter-{number}", "score": .9,
            "payload": {
                "document_id": "compliance", "version_id": "v1",
                "title": "KAHLE KI-Compliance v1.2", "content": content,
                "parent_content": content, "parent_id": f"chapter-{number}",
                "chunk_order": number, "heading_path": ["KI-Compliance", f"{number}. Kapitel"],
                "knowledgebase_ids": ["richtlinien"], "status": "active", "published": True,
                "source_id": "source-1", "source_url": "/source/v1",
                "valid_until": "2026-11-03", "authority": "3:executive_policy", "conflict": False,
            },
        }

    points = [point(number) for number in range(1, 9)]

    class Response:
        def raise_for_status(self): pass
        def json(self): return {"result": {"points": points}}

    monkeypatch.setattr(module.requests, "post", lambda *args, **kwargs: Response())

    class Sparse:
        def encode_query(self, query):
            return {"build_id": "build-1", "indices": [1], "values": [1.0]}

    class Reranker:
        def rerank(self, query, documents, top_n):
            return [(index, .9) for index in reversed(range(len(documents)))]

    chunks = module.QdrantHybridRetriever(
        "http://qdrant", "vinci_knowledge", Sparse(), Reranker(),
    ).retrieve(
        "KAHLE KI-Compliance", [1.0],
        module.RetrievalScope("u", ("richtlinien",), ("v1",)),
        today=date(2026, 8, 12),
    )

    assert [chunk.heading_path[-1] for chunk in chunks] == [
        f"{number}. Kapitel" for number in range(1, 9)
    ]


def test_normative_question_prefers_authoritative_sources_and_removes_duplicate_training_content(monkeypatch):
    def point(identifier, title, content, authority, score):
        return {
            "id": identifier, "score": score,
            "payload": {
                "document_id": identifier, "version_id": "v1", "title": title,
                "content": content, "parent_content": content, "parent_id": identifier,
                "chunk_order": 1, "heading_path": [title, "Vorgaben"],
                "knowledgebase_ids": ["richtlinien"], "status": "active", "published": True,
                "source_id": identifier, "source_url": f"/source/{identifier}",
                "valid_until": "2026-11-03", "authority": authority, "conflict": False,
            },
        }

    shared = "Personenbezogene Daten dürfen nur in freigegebenen Systemen verarbeitet werden."
    points = [
        point("training", "KI Richtlinie Fragebogen", shared, "6:information_or_training", .95),
        point("policy", "KI Datenschutzrichtlinie", shared, "3:executive_policy", .93),
        point("process", "KI Freigabeprozess", "Neue Systeme benötigen eine Freigabe.", "5:process_or_work_instruction", .90),
        point("legal", "EU-AI-Vorgaben", "Gesetzliche Anforderungen sind einzuhalten.", "1:legal_or_regulatory", .88),
        point("department", "Bereichsrichtlinie KI", "Der Fachbereich prüft den Einsatzzweck.", "4:department_policy", .86),
        point("security", "IT-Sicherheitsrichtlinie", "Zugriffe werden technisch beschränkt.", "3:executive_policy", .84),
    ]

    class Response:
        def raise_for_status(self): pass
        def json(self): return {"result": {"points": points}}

    monkeypatch.setattr(module.requests, "post", lambda *args, **kwargs: Response())

    class Sparse:
        def encode_query(self, query):
            return {"build_id": "build-1", "indices": [1], "values": [1.0]}

    class Reranker:
        def rerank(self, query, documents, top_n):
            return [(index, points[index]["score"]) for index in range(len(documents))]

    chunks = module.QdrantHybridRetriever(
        "http://qdrant", "vinci_knowledge", Sparse(), Reranker(),
    ).retrieve(
        "Welche internen Vorgaben gelten für den Einsatz von KI?", [1.0],
        module.RetrievalScope("u", ("richtlinien",), ("v1",)),
        today=date(2026, 8, 12),
    )

    assert "KI Datenschutzrichtlinie" in [chunk.title for chunk in chunks]
    assert "KI Richtlinie Fragebogen" not in [chunk.title for chunk in chunks]
    assert sum(shared in chunk.parent_content for chunk in chunks) == 1


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


def test_local_tool_update_uses_sqlite_and_built_bundles_without_api_key():
    root = Path(__file__).resolve().parents[2]
    register = (root / "scripts" / "openwebui" / "register-kahle-workflow-tool.py").read_text(
        encoding="utf-8"
    )
    updater = (root / "scripts" / "openwebui" / "update-local-rag-tools.ps1").read_text(
        encoding="utf-8"
    )

    assert 'TOOLS_DIR / "dist" / "rag_chat_hybrid_tool.py"' in register
    assert 'TOOLS_DIR / "dist" / "kahle_workflow_orchestrator.py"' in register
    assert "OWUI_DB_PATH=/app/backend/data/webui.db" in updater
    assert "OPENWEBUI_API_KEY" not in updater

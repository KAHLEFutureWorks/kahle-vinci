import importlib.util
import ast
import json
import re
import subprocess
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


def load_tool_helpers(*names):
    source_path = (
        Path(__file__).resolve().parents[1]
        / "open-webui-tools"
        / "rag_chat_hybrid_tool.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    dependencies = set()
    if set(names).intersection({"_filter_evidence_chunks", "_claim_evidence_spans"}):
        dependencies.add("_fold_evidence_text")
    nodes = [
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name in set(names) | dependencies
    ]
    namespace = {"re": re}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source_path), "exec"), namespace)
    return tuple(namespace[name] for name in names)


def test_claim_evidence_uses_exact_relevant_sentences_instead_of_whole_documents():
    (claim_spans,) = load_tool_helpers("_claim_evidence_spans")
    passage = (
        "VaudisX wird zur Kundenpflege genutzt. "
        "Für den technischen Support von VaudisX ist Max Mustermann zuständig. "
        "Microsoft 365 ist ebenfalls verfügbar."
    )

    spans = claim_spans(
        "Wer ist für den technischen Support von VaudisX zuständig?", passage,
    )

    assert spans == [
        "Für den technischen Support von VaudisX ist Max Mustermann zuständig."
    ]


def test_evidence_bundle_carries_claim_span_and_source_sidecar_metadata():
    tool_path = Path(__file__).resolve().parents[1] / "open-webui-tools" / "rag_chat_hybrid_tool.py"
    spec = importlib.util.spec_from_file_location("rag_claim_contract", tool_path)
    tool = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(tool)
    sentence = "Für den technischen Support von VaudisX ist Max Mustermann zuständig."

    bundle = tool._evidence_bundle(
        "Wer ist für den technischen Support von VaudisX zuständig?",
        sentence,
        [{
            "number": 1,
            "document_id": "doc-1",
            "version_id": "v-1",
            "domain": "internal_systems",
            "document_type": "responsibility_matrix",
            "evidence_capabilities": ["explicit_relationship"],
            "source_provider": "knowledge_portal",
            "evidence_text": sentence,
        }],
    )

    assert bundle["supported_claims"] == [{
        "claim_id": "R1C1",
        "source_id": "#1",
        "text": sentence,
        "evidence_span": sentence,
        "document_id": "doc-1",
        "version_id": "v-1",
        "claim_type": "explicit_relationship",
    }]
    assert bundle["sources"][0]["domain"] == "internal_systems"
    assert "evidence_text" not in bundle["sources"][0]


def test_rag_query_sanitizer_removes_forwarded_openwebui_context_prompt():
    (sanitize,) = load_tool_helpers("_sanitize_rag_query")
    contaminated = (
        "### Task: Respond using context. <context><source id=\"1\">"
        "KAHLE_RAG_RESULT\nFOUND: false</source></context> query Wer ist Engin Bayir?"
    )

    assert sanitize(contaminated) == "Wer ist Engin Bayir?"
    assert sanitize("Wie plane ich einen Termin im WPS?") == (
        "Wie plane ich einen Termin im WPS?"
    )


def test_generic_opening_hours_query_requires_location_clarification():
    (clarification,) = load_tool_helpers("_clarification_for_query")

    assert clarification("Wie sind unsere Öffnungszeiten?") == (
        "Für welchen Standort und welchen Bereich (Verkauf, Service oder "
        "Teiledienst) brauchst du die Öffnungszeiten?"
    )
    assert clarification("Wie sind die Öffnungszeiten in Hannover?") == ""


def test_complete_all_location_opening_hours_scope_needs_no_redundant_clarification():
    (clarification,) = load_tool_helpers("_clarification_for_query")

    assert clarification(
        "Nenne die Öffnungszeiten für Verkauf, Service und Teiledienst an allen "
        "KAHLE-Standorten."
    ) == ""


def test_work_instruction_workflow_drops_unrelated_software_release_evidence():
    (filter_chunks,) = load_tool_helpers("_filter_evidence_chunks")
    chunks = [
        type("Chunk", (), {
            "title": "KAHLE Speak Nutzer Kontext",
            "heading_path": ("Updates", "Signierter Freigabeprozess"),
            "parent_content": (
                "Release-Pakete werden mit Prüfsummen und einer kryptografischen "
                "Signatur abgesichert. Der Client akzeptiert nur passende Freigaben."
            ),
        })(),
        type("Chunk", (), {
            "title": "Wissensportal Nutzer Kontext",
            "heading_path": ("Dokumente", "Freigabestufen"),
            "parent_content": (
                "Eine neue Arbeitsanweisung wird hochgeladen, fachlich geprüft, "
                "freigegeben und danach im Wissensportal veröffentlicht."
            ),
        })(),
    ]

    selected = filter_chunks(
        "Beschreibe den Ablauf zur fachlichen Prüfung, Freigabe und Veröffentlichung "
        "einer neuen Arbeitsanweisung.",
        chunks,
    )

    assert [chunk.title for chunk in selected] == ["Wissensportal Nutzer Kontext"]


def test_person_system_support_requires_one_passage_that_expressly_links_both():
    (filter_chunks,) = load_tool_helpers("_filter_evidence_chunks")
    chunks = [
        type("Chunk", (), {
            "title": "Wichtige Kontakte",
            "heading_path": ("IT",),
            "parent_content": "Jan Oltmanns ist CRM-Manager und AI-Officer.",
        })(),
        type("Chunk", (), {
            "title": "Systemlandkarte",
            "heading_path": ("VaudisX",),
            "parent_content": "VaudisX wird zur Kundenpflege und Rechnungserstellung genutzt.",
        })(),
    ]

    assert filter_chunks(
        "Wer ist bei KAHLE für den technischen Support von VaudisX zuständig?",
        chunks,
    ) == []


def test_person_system_support_keeps_explicit_relationship_passage():
    (filter_chunks,) = load_tool_helpers("_filter_evidence_chunks")
    explicit = type("Chunk", (), {
        "title": "Systemkontakte",
        "heading_path": ("VaudisX", "Support"),
        "parent_content": "Für den technischen Support von VaudisX ist Max Mustermann zuständig.",
    })()

    assert filter_chunks(
        "Wer ist bei KAHLE für den technischen Support von VaudisX zuständig?",
        [explicit],
    ) == [explicit]


def test_general_customer_lock_drops_marketing_only_evidence():
    (filter_chunks,) = load_tool_helpers("_filter_evidence_chunks")
    chunks = [type("Chunk", (), {
        "title": "Temporäre Sperrung Hersteller-Zufriedenheitsbefragungen",
        "heading_path": ("DSE", "Befragungssperre"),
        "parent_content": (
            "Über die DSE-Kontaktfreigaben werden Werbung und automatisierte "
            "Herstellerbefragungen zeitweise gesperrt."
        ),
    })()]

    assert filter_chunks(
        "Wie veranlasse ich eine allgemeine Kundensperre in Vaudis?",
        chunks,
    ) == []


def test_general_customer_lock_drops_system_overview_without_lock_or_contact_evidence():
    (filter_chunks,) = load_tool_helpers("_filter_evidence_chunks")
    chunks = [type("Chunk", (), {
        "title": "KAHLE Systemlandkarte",
        "heading_path": ("Service-Systeme",),
        "parent_content": (
            "VaudisX ist ein internes DMS-System zur Kundenpflege und "
            "Rechnungserstellung."
        ),
    })()]

    assert filter_chunks(
        "Wie veranlasse ich eine allgemeine Kundensperre in Vaudis und wer ist "
        "dafür als Datenschutz-Anlaufstelle zuständig?",
        chunks,
    ) == []


def test_general_customer_lock_keeps_explicit_privacy_contact_for_lock_requests():
    (filter_chunks,) = load_tool_helpers("_filter_evidence_chunks")
    contact = type("Chunk", (), {
        "title": "KAHLE Vinci Nutzer Kontext",
        "heading_path": ("Hilfe und Datenschutz",),
        "parent_content": (
            "Bei Datenschutz-, Lösch- oder Werbesperrenanfragen wende dich an "
            "datenschutz@kahle.de."
        ),
    })()

    assert filter_chunks(
        "Wie veranlasse ich eine allgemeine Kundensperre in Vaudis und wer ist "
        "dafür als Datenschutz-Anlaufstelle zuständig?",
        [contact],
    ) == [contact]


def test_ambiguous_customer_lock_query_requires_purpose_clarification():
    clarification, guided = load_tool_helpers(
        "_clarification_for_query", "_guided_response_for_query",
    )

    assert clarification("Wie sperre ich einen Kunden in Vaudis?") == (
        "Geht es darum, Werbung und Befragungen für den Kunden in Hannover, "
        "Wunstorf oder Wedemark zu sperren, oder um eine allgemeine "
        "Kundensperre in Vaudis für einen anderen Standort?"
    )
    assert guided("Wie sperre ich einen Kunden in Vaudis?") == ""


def test_explicit_marketing_opt_out_uses_rag_without_clarification():
    clarification, guided = load_tool_helpers(
        "_clarification_for_query", "_guided_response_for_query",
    )

    query = "Wie sperre ich einen Kunden, wenn er keine Werbung mehr bekommen soll?"

    assert clarification(query) == ""
    assert guided(query) == ""


def test_marketing_opt_out_instruction_blocks_unrelated_vaudis_fields():
    (instruction,) = load_tool_helpers("_rag_answer_instruction")

    value = instruction(
        "Wie sperre ich Werbung und automatisierte Befragungen für einen Kunden "
        "in Vaudis über die DSE-Kontaktfreigaben?"
    )

    assert "Werbewiderspruch" in value
    assert "besondere Merkmale" in value
    assert "Finanzdaten" in value


def test_location_department_overview_instruction_excludes_unrequested_people_and_cross_site_inference():
    (instruction,) = load_tool_helpers("_rag_answer_instruction")

    value = instruction(
        "Erstelle eine Übersicht über Verkauf, Service und Teiledienst an allen KAHLE-Standorten."
    )

    assert "Nenne keine Personen" in value
    assert "Verallgemeinere Angaben eines einzelnen Standorts nicht" in value
    assert "nicht" in value


def test_general_customer_lock_requires_retrieved_evidence_instead_of_static_contact():
    clarification, guided = load_tool_helpers(
        "_clarification_for_query", "_guided_response_for_query",
    )

    query = "Es geht um eine allgemeine Kundensperre in Vaudis."
    assert clarification(query) == ""
    assert guided(query) == ""


def test_kahle_abbreviations_are_expanded_before_opening_hours_clarification():
    expand, clarification = load_tool_helpers(
        "_expand_kahle_query_aliases", "_clarification_for_query",
    )

    expanded = expand("Wie sind unsere TD Öffnungszeiten in NIE?")

    assert expanded == "Wie sind unsere Teiledienst Öffnungszeiten in Nienburg?"
    assert clarification(expanded) == ""


def test_sales_and_stadthagen_abbreviations_are_expanded_before_clarification():
    expand, clarification = load_tool_helpers(
        "_expand_kahle_query_aliases", "_clarification_for_query",
    )

    expanded = expand("Wie sind unsere VK Öffnungszeiten in SHG?")

    assert expanded == "Wie sind unsere Verkauf Öffnungszeiten in Stadthagen?"
    assert clarification(expanded) == ""


def test_all_supported_location_codes_expand_as_standalone_tokens_only():
    (expand,) = load_tool_helpers("_expand_kahle_query_aliases")

    assert expand("HAN WUN WED WAL NEU NIE STA SHG") == (
        "Hannover Wunstorf Wedemark Walsrode Neustadt am Rübenberge "
        "Nienburg Stadthagen Stadthagen"
    )
    assert expand("STATUS und NEUigkeit") == "STATUS und NEUigkeit"


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


def test_procedural_query_discards_system_overviews_before_reranking():
    candidates = [
        {"payload": {
            "title": "WPS Systemübersicht",
            "domain": "internal_systems",
            "document_type": "system_overview",
            "evidence_capabilities": ["system_overview"],
            "classification_status": "inferred", "classification_confidence": .95,
        }},
        {"payload": {
            "title": "WPS Terminbuchung",
            "domain": "internal_systems",
            "document_type": "work_instruction",
            "evidence_capabilities": ["procedure"],
            "classification_status": "inferred", "classification_confidence": .95,
        }},
    ]

    selected = module.pre_rerank_metadata_filter(
        "Wie buche ich einen Termin in WPS?", candidates,
    )

    assert [point["payload"]["title"] for point in selected] == ["WPS Terminbuchung"]


def test_fact_question_keeps_system_overview_without_requiring_a_procedure():
    candidates = [{"payload": {
        "title": "WPS Systemübersicht",
        "domain": "internal_systems",
        "document_type": "system_overview",
        "evidence_capabilities": ["system_overview"],
        "classification_status": "inferred", "classification_confidence": .95,
    }}]

    assert module.pre_rerank_metadata_filter("Was ist WPS?", candidates) == candidates


def test_pre_rerank_filter_consumes_planned_capabilities_when_available():
    candidates = [
        {"payload": {"title": "Übersicht", "evidence_capabilities": ["system_overview"],
                     "classification_status": "inferred", "classification_confidence": .95}},
        {"payload": {"title": "Anleitung", "evidence_capabilities": ["procedure"],
                     "classification_status": "inferred", "classification_confidence": .95}},
    ]

    selected = module.pre_rerank_metadata_filter(
        "Was ist WPS?",
        candidates,
        information_needs=[{"evidence_capabilities": ["procedure"]}],
    )

    assert [point["payload"]["title"] for point in selected] == ["Anleitung"]


def test_system_usage_location_plan_rejects_unrelated_location_document():
    candidates = [
        {"payload": {"title": "Systemlandkarte", "evidence_capabilities": ["system_overview"],
                     "classification_status": "inferred", "classification_confidence": .95}},
        {"payload": {"title": "Befragungssperre Hannover", "evidence_capabilities": ["procedure"],
                     "classification_status": "inferred", "classification_confidence": .95}},
        {"payload": {"title": "WPS Einsatzorte", "parent_content": "WPS wird an den Standorten Hannover und Wunstorf eingesetzt.",
                     "evidence_capabilities": ["explicit_usage_scope"],
                     "classification_status": "inferred", "classification_confidence": .95}},
    ]

    selected = module.pre_rerank_metadata_filter(
        "An welchen Standorten wird WPS eingesetzt?",
        candidates,
        information_needs=[{"kind": "system_usage_locations", "evidence_capabilities": ["explicit_usage_scope"]}],
    )

    assert selected == [candidates[2]]


def test_exact_location_opening_hours_keeps_textual_hours_even_below_global_threshold():
    candidates = [
        {"payload": {"title": "Standort Hannover", "heading_path": ["Kontakt"],
                     "parent_content": "Hannover, Telefon 0511", "document_id": "han"}},
        {"payload": {"title": "Standort Hannover", "heading_path": ["Öffnungszeiten"],
                     "parent_content": "Verkauf: Mo-Fr 9-18, Sa 9-13", "document_id": "han"}},
        {"payload": {"title": "Standort Wunstorf", "heading_path": ["Öffnungszeiten"],
                     "parent_content": "Verkauf: Mo-Fr 9-18, Sa 9-13", "document_id": "wun"}},
    ]
    reranked = [(0, .91), (1, .12), (2, .88)]

    selected = module.select_exact_location_opening_hours(
        "Welche Öffnungszeiten hat der Standort Hannover?",
        reranked,
        candidates,
        result_limit=5,
    )

    assert selected == [(1, .12)]


def test_exact_location_opening_hours_rejects_document_index_without_literal_times():
    candidates = [
        {"payload": {"title": "Standort Hannover", "heading_path": ["Kurzindex"],
                     "parent_content": "Dieser Steckbrief enthält Öffnungszeiten und Kontaktdaten.",
                     "document_id": "han"}},
        {"payload": {"title": "Standort Hannover", "heading_path": ["Öffnungszeiten"],
                     "parent_content": "Verkauf: Mo-Fr 9:00-18:00, Sa 9:00-13:00",
                     "document_id": "han"}},
    ]
    reranked = [(0, .92), (1, .11)]

    selected = module.select_exact_location_opening_hours(
        "Welche Öffnungszeiten hat der Standort Hannover?",
        reranked,
        candidates,
        result_limit=5,
    )

    assert selected == [(1, .11)]


def test_generic_factual_plan_does_not_exclude_specialized_evidence():
    candidates = [{"payload": {
        "title": "Prozessbeschreibung",
        "evidence_capabilities": ["procedure"],
        "classification_status": "inferred",
        "classification_confidence": .95,
    }}]

    selected = module.pre_rerank_metadata_filter(
        "Welche internen Prozesse sind dokumentiert?",
        candidates,
        information_needs=[{"evidence_capabilities": ["factual_support"]}],
    )

    assert selected == candidates


def test_relationship_query_keeps_only_explicit_relationship_sources():
    candidates = [
        {"payload": {"title": "Kontakte", "evidence_capabilities": ["contact_details"],
                     "classification_status": "inferred", "classification_confidence": .95}},
        {"payload": {"title": "Systemkontakte", "evidence_capabilities": ["explicit_relationship"],
                     "classification_status": "inferred", "classification_confidence": .95}},
    ]

    selected = module.pre_rerank_metadata_filter(
        "Wer ist für den technischen Support von VaudisX zuständig?", candidates,
    )

    assert [point["payload"]["title"] for point in selected] == ["Systemkontakte"]


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


def test_all_location_opening_hours_selects_one_result_per_location():
    locations = (
        "Hannover", "Wunstorf", "Wedemark", "Walsrode",
        "Neustadt am Rübenberge", "Nienburg", "Stadthagen",
    )
    candidates = [
        {
            "payload": {
                "document_id": "master-context",
                "title": f"Standort {location}",
                "parent_content": (
                    f"{location}\nÖffnungszeiten: Service Mo-Fr 07:00-18:00"
                ),
            }
        }
        for location in locations
    ]
    candidates.insert(0, {
        "payload": {
            "document_id": "navigation",
            "title": "Navigation und Verknüpfungen",
            "heading_path": ["Navigation"],
            "parent_content": (
                "Öffnungszeiten der Standorte Hannover, Wunstorf, Wedemark, "
                "Walsrode, Neustadt am Rübenberge, Nienburg und Stadthagen"
            ),
        }
    })
    # A second, highly ranked Stadthagen chunk must not displace Walsrode.
    candidates.insert(1, {
        "payload": {
            "document_id": "stadthagen-extra",
            "title": "Standort Stadthagen Zusatz",
            "parent_content": "Stadthagen Öffnungszeiten: Verkauf Mo-Fr 09:00-18:00",
        }
    })
    reranked = [(index, 1.0 - index / 100) for index in range(len(candidates))]

    selected = module.diversify_opening_hours_locations(
        reranked, candidates, result_limit=8,
    )
    selected_text = "\n".join(
        candidates[index]["payload"]["parent_content"] for index, _score in selected
    )

    assert len(selected) == 7
    for location in locations:
        assert selected_text.casefold().count(location.casefold()) == 1


def test_all_location_opening_hours_never_focuses_one_location_document():
    candidates = [{
        "payload": {
            "document_id": "neustadt",
            "title": "Standort Neustadt am Rübenberge",
            "parent_content": "Öffnungszeiten Neustadt am Rübenberge",
        },
    }]
    broad_query = (
        "Öffnungszeiten Verkauf Service Teiledienst alle Standorte Hannover "
        "Wunstorf Wedemark Walsrode Neustadt am Rübenberge Nienburg Stadthagen"
    )

    assert module.focused_document_ids_for_query(broad_query, candidates) == set()
    assert module.focused_document_ids_for_query(
        "Öffnungszeiten Standort Neustadt am Rübenberge", candidates,
    ) == {"neustadt"}


def test_all_location_opening_hours_reranks_the_complete_candidate_pool():
    broad_query = (
        "Öffnungszeiten Verkauf Service Teiledienst alle Standorte Hannover "
        "Wunstorf Wedemark Walsrode Neustadt am Rübenberge Nienburg Stadthagen"
    )

    assert module.rerank_candidate_count(broad_query, 50, result_limit=8) == 50
    assert module.rerank_candidate_count("Öffnungszeiten Hannover", 50, result_limit=8) == 24


def test_all_location_opening_hours_detects_only_truly_missing_location_passages():
    candidates = [{
        "id": "wunstorf-hours",
        "payload": {
            "title": "KB-KAHLE | Standort Wunstorf (LOC-WUN)",
            "heading_path": ["Standort Wunstorf", "Öffnungszeiten"],
            "parent_content": "Service Mo-Fr 07:00-18:00",
        },
    }, {
        "id": "navigation",
        "payload": {
            "title": "Navigation",
            "heading_path": ["Verknüpfungen"],
            "parent_content": "Hannover, Wedemark, Walsrode und Stadthagen",
        },
    }]

    missing = module.missing_opening_hours_locations(candidates)

    assert ("wunstorf",) not in missing
    assert ("hannover",) in missing
    assert ("stadthagen",) in missing


def test_all_location_opening_hours_keeps_exact_location_evidence_below_global_threshold():
    candidates = [{
        "payload": {
            "title": "KB-KAHLE | Standort Stadthagen (LOC-STA)",
            "heading_path": ["Standort Stadthagen", "Öffnungszeiten"],
            "parent_content": "Service Mo-Fr 07:00-18:00",
        },
    }]

    selected = module.diversify_opening_hours_locations(
        [(0, 0.12)], candidates, result_limit=8,
    )

    assert selected == [(0, 0.12)]


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


def test_short_person_query_focuses_document_by_exact_content_terms():
    candidates = [{
        "payload": {
            "document_id": "contacts",
            "title": "KAHLE Wichtige Kontakte Rollen",
            "parent_content": "Geschäftsführer: Thomas Keller (keller@kahle.de)",
        },
    }, {
        "payload": {
            "document_id": "other",
            "title": "Service Richtlinie",
            "parent_content": "Allgemeine Informationen zum Service.",
        },
    }]

    assert module.focused_document_ids("Was weißt du über Thomas Keller?", candidates) == {"contacts"}


def test_wer_ist_person_query_focuses_exact_contact_document():
    candidates = [{
        "payload": {
            "document_id": "contacts",
            "title": "KAHLE Wichtige Kontakte Rollen",
            "parent_content": "Geschäftsführer: Thomas Keller (keller@kahle.de)",
        },
    }, {
        "payload": {
            "document_id": "other",
            "title": "Service Richtlinie",
            "parent_content": "Allgemeine Informationen zum Service.",
        },
    }]

    assert module.focused_document_ids("Wer ist Thomas Keller?", candidates) == {"contacts"}


def test_person_query_prefers_employee_directory_over_history_when_both_match():
    candidates = [{
        "payload": {
            "document_id": "history",
            "title": "KAHLE Unternehmensprofil und Historie",
            "parent_content": "Thomas Keller gehört zur Geschäftsführung.",
        },
    }, {
        "payload": {
            "document_id": "contacts",
            "title": "KAHLE Wichtige Kontakte Rollen",
            "parent_content": "Geschäftsführer: Thomas Keller (keller@kahle.de)",
        },
    }]

    assert module.focused_document_ids("Wer ist Thomas Keller?", candidates) == {"contacts"}


def test_person_query_prefers_future_personio_directory_source():
    candidates = [{
        "payload": {
            "document_id": "contacts",
            "title": "KAHLE Wichtige Kontakte Rollen",
            "parent_content": "IT: Stefan Schrader",
        },
    }, {
        "payload": {
            "document_id": "personio",
            "title": "Personio Mitarbeiterverzeichnis",
            "parent_content": "Stefan Schrader, Leitung IT/EDV",
        },
    }]

    assert module.focused_document_ids("Wer ist Stefan Schrader?", candidates) == {"personio"}


def test_active_version_question_focuses_the_named_document():
    candidates = [{
        "payload": {
            "document_id": "test-guide",
            "title": "Anleitung zur Anlage eines Testvorgangs Kopie",
            "parent_content": "Lege den Testvorgang als Vorgang an.",
        },
    }, {
        "payload": {
            "document_id": "portal-help",
            "title": "KAHLE Wissensportal Versionierung",
            "parent_content": "Aktive Versionen ersetzen vorherige Fassungen.",
        },
    }]

    assert module.focused_document_ids(
        "Welche aktuell gültige Fassung unseres Testvorgangs gilt?", candidates
    ) == {"test-guide"}


def test_named_entity_uses_acl_filtered_hybrid_order_when_reranker_is_unavailable(monkeypatch):
    points = [{
        "id": "p1", "score": .9,
        "payload": {
            "document_id": "contacts", "version_id": "v1",
            "title": "KAHLE Wichtige Kontakte Rollen",
            "content": "Geschäftsführer: Thomas Keller (keller@kahle.de)",
            "parent_content": "Geschäftsführer: Thomas Keller (keller@kahle.de)",
            "knowledgebase_ids": ["allgemein"], "status": "active", "published": True,
            "source_id": "s", "source_url": "/s", "valid_until": "2026-11-01",
        },
    }]

    class Response:
        def raise_for_status(self): pass
        def json(self): return {"result": {"points": points}}

    monkeypatch.setattr(module.requests, "post", lambda *args, **kwargs: Response())

    class Sparse:
        def encode_query(self, query):
            return {"build_id": "build-1", "indices": [1], "values": [1.0]}

    class UnavailableReranker:
        def rerank(self, query, documents, top_n):
            raise module.RetrievalError("reranker_unavailable:http_503")

    chunks = module.QdrantHybridRetriever(
        "http://qdrant", "vinci_knowledge", Sparse(), UnavailableReranker(),
    ).retrieve(
        "Was weißt du über Thomas Keller?", [1.0],
        module.RetrievalScope("u", ("allgemein",), ("v1",)),
        today=date(2026, 8, 17),
    )

    assert [chunk.document_id for chunk in chunks] == ["contacts"]


def test_sparse_encoder_outage_falls_back_to_acl_filtered_dense_search(monkeypatch):
    captured = {"bodies": []}
    points = [{
        "id": "p1", "score": .88,
        "payload": {
            "document_id": "contacts", "version_id": "v1",
            "title": "KAHLE Wichtige Kontakte Rollen",
            "content": "Engin Bayir ist als Führungskraft hinterlegt.",
            "parent_content": "Engin Bayir ist als Führungskraft hinterlegt.",
            "knowledgebase_ids": ["allgemein"], "status": "active", "published": True,
            "source_id": "s", "source_url": "/s", "valid_until": "2026-11-01",
        },
    }]

    class Response:
        def raise_for_status(self): pass
        def json(self): return {"result": {"points": points}}

    def fake_post(url, **kwargs):
        captured["bodies"].append(kwargs["json"])
        return Response()

    monkeypatch.setattr(module.requests, "post", fake_post)

    class SparseUnavailable:
        def encode_query(self, query):
            raise module.RetrievalError("sparse_encoder_unavailable")

    class Reranker:
        def rerank(self, query, documents, top_n):
            return [(0, .91)]

    chunks = module.QdrantHybridRetriever(
        "http://qdrant", "vinci_knowledge", SparseUnavailable(), Reranker(),
    ).retrieve(
        "Wer ist Engin Bayir?", [1.0],
        module.RetrievalScope("u", ("allgemein",), ("v1",)),
        today=date(2026, 8, 19),
    )

    assert [chunk.document_id for chunk in chunks] == ["contacts"]
    search_body = captured["bodies"][0]
    assert search_body["using"] == "dense"
    assert search_body["query"] == [1.0]
    assert "filter" in search_body


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


def test_ionos_reranker_reports_safe_http_diagnostic_without_response_body(monkeypatch):
    response = module.requests.Response()
    response.status_code = 429
    response._content = b"secret provider response"

    def post(*args, **kwargs):
        raise module.requests.HTTPError(response=response)

    monkeypatch.setattr(module.requests, "post", post)
    with pytest.raises(module.RetrievalError) as captured:
        module.IonosReranker("https://example.invalid/v1", "secret", "model").rerank(
            "Thomas Keller", ["internal content"], 1,
        )

    assert str(captured.value) == "reranker_unavailable:http_429"
    assert "secret" not in str(captured.value)


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


def test_local_tool_update_registers_guard_in_the_running_container_database():
    root = Path(__file__).resolve().parents[2]
    updater = root / "scripts" / "openwebui" / "update-local-rag-tools.ps1"
    escaped_updater = str(updater).replace("'", "''")
    command = f"""
$calls = [System.Collections.Generic.List[string]]::new()
function docker {{
    $DockerArgs = @($args)
    $calls.Add(($DockerArgs -join ' '))
    $global:LASTEXITCODE = 0
    if ($DockerArgs[0] -eq 'inspect') {{ 'true' }}
}}
& '{escaped_updater}' -Container 'test-open-webui'
$calls | ConvertTo-Json -Compress
"""

    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    calls = json.loads(result.stdout.strip().splitlines()[-1])

    assert any(
        "stack/open-webui-functions/kahle_toolcall_guard.py" in call.replace("\\", "/")
        and ":/tmp/kahle-vinci/stack/open-webui-functions/kahle_toolcall_guard.py" in call.replace("\\", "/")
        for call in calls
    )
    assert any(
        "OWUI_DB_PATH=/app/backend/data/webui.db" in call
        and "--only kahle_toolcall_guard" in call
        for call in calls
    )

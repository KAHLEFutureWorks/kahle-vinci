#!/usr/bin/env python3
"""Unit checks for the KAHLE workflow orchestrator helper logic."""

from __future__ import annotations

import importlib.util
import asyncio
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "open-webui-tools" / "kahle_workflow_orchestrator.py"


def load_module():
    spec = importlib.util.spec_from_file_location("kahle_workflow_orchestrator", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_internal_kahle_policy_task_routes_to_internal_rag():
    module = load_module()

    intent = module.classify_workflow_intent(
        "Hole dir Infos zu unserer KI Richtlinie und erstelle eine Praesentationsgliederung.",
        "auto",
    )

    assert intent == "internal"


def test_external_news_task_routes_to_external_search():
    module = load_module()

    intent = module.classify_workflow_intent("Recherchiere aktuelle KI News aus Mai 2026.", "auto")

    assert intent == "external"


def test_internal_plus_internet_policy_task_routes_to_mixed():
    module = load_module()

    intent = module.classify_workflow_intent(
        "Hole dir Infos zu unserer KI-Richtlinie. Hole dir aktuelle Infos aus dem Internet zu typischen KI Richtlinien.",
        "auto",
    )

    assert intent == "mixed"


def test_task_plan_for_internal_presentation_uses_rag_before_output():
    module = load_module()

    tasks = module.build_task_plan("internal", "presentation_outline")
    contents = [task["content"] for task in tasks]

    assert contents[0] == "Interne KAHLE-Informationen abrufen"
    assert "Praesentationsgliederung erstellen" in contents[-1]


def test_rag_result_parser_extracts_found_context():
    module = load_module()
    raw = (
        "KAHLE_RAG_RESULT\n"
        "FOUND: true\n"
        "QUERY: KI Richtlinie\n"
        "META: top1_score=0.812 threshold=0.45\n\n"
        "KONTEXT (zitierbar mit [#]):\n"
        "[#1 | kahlerichtlinien | KI.md | chunk 0 | score 0.812]\n"
        "KI darf nur datenschutzkonform genutzt werden."
    )

    parsed = module.parse_rag_result(raw)

    assert parsed["found"] is True
    assert parsed["top1_score"] == 0.812
    assert "datenschutzkonform" in parsed["context"]


def test_web_result_without_ok_is_usable_when_summary_and_sources_exist():
    module = load_module()
    raw = '{"summary":"Kurz-Zusammenfassung","sources":[{"title":"Quelle"}]}'

    parsed = module.parse_web_result(raw)

    assert parsed["ok"] is True
    assert parsed["summary"] == "Kurz-Zusammenfassung"
    assert len(parsed["sources"]) == 1


def test_output_format_is_inferred_from_pdf_request():
    module = load_module()

    fmt = module.infer_download_format("Recherchiere zum CUPRA Tindaya und gib mir das Ergebnis als PDF aus.", "auto")

    assert fmt == "pdf"


def test_workflow_web_query_is_optimized_for_cupra_tindaya_pdf_request():
    module = load_module()

    query = module.build_web_search_query("Recherchiere zum CUPRA Tindaya und gib mir das Ergebnis als PDF aus.")

    assert "CUPRA Tindaya" in query
    assert "Konzeptfahrzeug" in query
    assert "PDF" not in query


def test_report_markdown_contains_web_summary_and_sources():
    module = load_module()
    payload = module.build_final_payload(
        "Recherchiere zum CUPRA Tindaya.",
        "external",
        "research_brief",
        [{"id": "1", "content": "Externe Recherche durchfuehren", "status": "completed"}],
        web={
            "ok": True,
            "summary": "CUPRA Tindaya ist ein Konzeptfahrzeug.",
            "sources": [{"title": "CUPRA Newsroom", "url": "https://example.test/cupra"}],
            "topLinks": [],
        },
    )

    markdown = module.build_report_markdown(payload)

    assert "CUPRA Tindaya ist ein Konzeptfahrzeug" in markdown
    assert "CUPRA Newsroom" in markdown
    assert "https://example.test/cupra" in markdown


def test_workflow_creates_generated_file_payload_for_research_pdf_request():
    module = load_module()

    original_create = module.create_downloadable_file
    try:
        module.create_downloadable_file = lambda content, output_format, filename, title="": {
            "output_kind": "file_saved",
            "filename": filename,
            "download_url": "http://localhost:8091/files/download?rel=edited/test.pdf",
            "sha256": "abc",
            "size_bytes": 123,
        }
        tools = module.Tools()
        tools._run_external_websearch = lambda query, max_results, user: json.dumps(
            {"ok": True, "summary": "CUPRA Tindaya Recherche", "sources": []},
            ensure_ascii=False,
        )

        raw = asyncio.run(
            tools.kahle_workflow_execute(
                "Recherchiere zum CUPRA Tindaya und gib mir das Ergebnis als PDF aus.",
                modus="external",
                output_format="pdf",
            )
        )
        payload = json.loads(raw)

        assert payload["generated_file"]["output_kind"] == "file_saved"
        assert payload["download_url"].startswith("http://localhost:8091/files/download")
        assert payload["filename"].endswith(".pdf")
    finally:
        module.create_downloadable_file = original_create


if __name__ == "__main__":
    test_internal_kahle_policy_task_routes_to_internal_rag()
    test_external_news_task_routes_to_external_search()
    test_internal_plus_internet_policy_task_routes_to_mixed()
    test_task_plan_for_internal_presentation_uses_rag_before_output()
    test_rag_result_parser_extracts_found_context()
    test_web_result_without_ok_is_usable_when_summary_and_sources_exist()
    test_output_format_is_inferred_from_pdf_request()
    test_workflow_web_query_is_optimized_for_cupra_tindaya_pdf_request()
    test_report_markdown_contains_web_summary_and_sources()
    test_workflow_creates_generated_file_payload_for_research_pdf_request()
    print("kahle workflow orchestrator tests passed")

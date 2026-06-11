#!/usr/bin/env python3
"""Unit checks for safe_webcaller query generation."""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "open-webui-tools" / "safe_webcaller.py"


def load_module():
    spec = importlib.util.spec_from_file_location("safe_webcaller", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_claude_ai_query_is_search_optimized():
    module = load_module()

    query = module.build_search_query("Bitte recherchiere einmal zu Claude AI")

    assert "Claude AI" in query
    assert "Anthropic" in query
    assert "Modelle" in query
    assert "recherchiere" not in query.lower()


def test_current_ai_news_query_gets_2026_context():
    module = load_module()

    query = module.build_search_query("Bitte Recherchiere einmal zu den aktuellen KI News")

    assert "KI News" in query
    assert "2026" in query
    assert "OpenAI" in query


def test_cupra_tindaya_query_gets_domain_context():
    module = load_module()

    query = module.build_search_query("Was ist der Cupra Tindaya?")

    assert "CUPRA Tindaya" in query
    assert "Konzeptfahrzeug" in query
    assert "technische Daten" in query


def test_barilla_pesto_query_is_not_polluted_by_output_instructions():
    module = load_module()

    query = module.build_search_query(
        'Bitte recherchiere, welche Pesto-Sorten es aktuell von Barilla gibt. '
        'Erstelle daraus eine Liste mit der Überschrift "Pesto Barilla Sorten" und gib mir das Ganze als Worddatei aus.'
    )

    assert query == "Barilla Pesto Sorten Deutschland aktuell 2026"


def test_spaghetti_manufacturing_query_is_domain_specific():
    module = load_module()

    query = module.build_search_query(
        "Bitte recherchiere einmal, wie Spaghetti hergestellt werden, und sortiere das als Schritt-für-Schritt-Erklärung für Mitarbeiter."
    )

    assert "Spaghetti" in query
    assert "Herstellung" in query
    assert "Hartweizen" in query
    assert "Schritt-für-Schritt" not in query
    assert "Mitarbeiter" not in query


def test_empty_safe_websearch_query_uses_latest_chat_message():
    module = load_module()

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "webui.db"
        con = sqlite3.connect(db_path)
        con.execute(
            "create table chat_message (chat_id text, role text, content text, created_at integer, updated_at integer)"
        )
        con.execute(
            "insert into chat_message values (?, 'user', ?, 10, 10)",
            ("chat-1", "Bitte recherchiere einmal zu den heutigen KI News"),
        )
        con.commit()
        con.close()

        old = os.environ.get("OWUI_DB_PATH")
        os.environ["OWUI_DB_PATH"] = str(db_path)
        try:
            assert "heutigen KI News" in module._latest_user_message("chat-1")
        finally:
            if old is None:
                os.environ.pop("OWUI_DB_PATH", None)
            else:
                os.environ["OWUI_DB_PATH"] = old


def test_blocked_safe_websearch_returns_final_notice_marker():
    module = load_module()

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = ""

        def json(self):
            return {
                "decision": "block_high_risk",
                "notice": "Ich kann die Websuche nicht ausfuehren.",
            }

    class FakeRequests:
        class Timeout(Exception):
            pass

        @staticmethod
        def post(*args, **kwargs):
            return FakeResponse()

    old_requests = module.requests
    old_url = os.environ.get("N8N_SAFE_WEBSEARCH_WEBHOOK_URL")
    try:
        module.requests = FakeRequests
        os.environ["N8N_SAFE_WEBSEARCH_WEBHOOK_URL"] = "http://n8n/webhook/test"
        result = module.Tools().safe_websearch("EU AI Act Hochrisiko-KI-Systeme")

        assert result.startswith(module.FINAL_PREFIX)
        assert result.endswith(module.FINAL_SUFFIX)
        assert "Ich kann die Websuche nicht ausfuehren." in result
    finally:
        module.requests = old_requests
        if old_url is None:
            os.environ.pop("N8N_SAFE_WEBSEARCH_WEBHOOK_URL", None)
        else:
            os.environ["N8N_SAFE_WEBSEARCH_WEBHOOK_URL"] = old_url


def test_safe_websearch_preserves_rich_research_payload():
    module = load_module()

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = ""

        def json(self):
            return {
                "decision": "proceed",
                "summary": "Kurzer Recherchekontext",
                "researchContext": "[1] Detailreicher Kontext",
                "keyFindings": [{"sourceId": 1, "finding": "Konkreter Befund"}],
                "quality": {"fetchedCount": 1, "searchVariants": ["primary", "facet"]},
                "sources": [
                    {
                        "id": 1,
                        "title": "Quelle",
                        "url": "https://example.test/eu-ai-act",
                        "snippet": "Kurzer Treffer",
                        "extract": "Langer, query-fokussierter Auszug mit deutlich mehr Details.",
                    }
                ],
            }

    class FakeRequests:
        class Timeout(Exception):
            pass

        @staticmethod
        def post(*args, **kwargs):
            return FakeResponse()

    old_requests = module.requests
    old_url = os.environ.get("N8N_SAFE_WEBSEARCH_WEBHOOK_URL")
    try:
        module.requests = FakeRequests
        os.environ["N8N_SAFE_WEBSEARCH_WEBHOOK_URL"] = "http://n8n/webhook/test"
        result = module.Tools().safe_websearch("EU AI Act Hochrisiko-KI")
        data = module.json.loads(result)

        assert data["researchContext"] == "[1] Detailreicher Kontext"
        assert data["keyFindings"][0]["finding"] == "Konkreter Befund"
        assert data["quality"]["fetchedCount"] == 1
        assert "query-fokussierter Auszug" in data["sourcesText"]
    finally:
        module.requests = old_requests
        if old_url is None:
            os.environ.pop("N8N_SAFE_WEBSEARCH_WEBHOOK_URL", None)
        else:
            os.environ["N8N_SAFE_WEBSEARCH_WEBHOOK_URL"] = old_url


if __name__ == "__main__":
    test_claude_ai_query_is_search_optimized()
    test_current_ai_news_query_gets_2026_context()
    test_cupra_tindaya_query_gets_domain_context()
    test_barilla_pesto_query_is_not_polluted_by_output_instructions()
    test_spaghetti_manufacturing_query_is_domain_specific()
    test_empty_safe_websearch_query_uses_latest_chat_message()
    test_blocked_safe_websearch_returns_final_notice_marker()
    test_safe_websearch_preserves_rich_research_payload()
    print("safe webcaller tests passed")

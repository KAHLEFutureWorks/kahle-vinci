#!/usr/bin/env python3
"""Unit checks for safe_webcaller query generation."""

from __future__ import annotations

import importlib.util
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


if __name__ == "__main__":
    test_claude_ai_query_is_search_optimized()
    test_current_ai_news_query_gets_2026_context()
    test_cupra_tindaya_query_gets_domain_context()
    print("safe webcaller tests passed")

"""Contracts for the model-visible internal knowledge source policy."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROMPTS = (
    ROOT / "open-webui-prompts" / "kahle-vinci-systemprompt.md",
    ROOT / "open-webui-prompts" / "kahle-vinci-thinking-systemprompt.md",
)
REGISTER = ROOT.parent / "scripts" / "openwebui" / "register-kahle-workflow-tool.py"
MODEL_REGISTER = ROOT.parent / "scripts" / "openwebui" / "register-vinci-models.py"


def load_registration():
    spec = importlib.util.spec_from_file_location("vinci_source_policy", REGISTER)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def load_model_registration():
    spec = importlib.util.spec_from_file_location("vinci_model_source_policy", MODEL_REGISTER)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_base_prompts_publish_one_explicit_internal_source_matrix():
    expected_matrix = (
        "| Informationsbedarf | Zulässige Quelle |",
        "aktuelle Personen, Profile, geschäftliche Einzelkontakte",
        "dokumentierte Prozesse, Zuständigkeiten, Funktionspostfächer",
        "Personio und RAG nur bei echtem Bedarf an beiden Evidenzarten",
        "Kein Web-Fallback bei fehlender Personen- oder Führungskraft-Evidenz",
        "Kompakte Nominalphrasen sind vollständige Suchanfragen",
        "Antworte ausschließlich aus der zurückgegebenen Evidenz und lege Lücken offen",
    )

    for prompt_path in PROMPTS:
        prompt = prompt_path.read_text(encoding="utf-8")

        assert "personio_directory" in prompt
        assert "rag_chat" in prompt
        for expected in expected_matrix:
            assert expected in prompt
        assert "RAG_Chat ist fuer KAHLE-internes Wissen die SSOT." not in prompt


def test_shared_function_calling_prompt_describes_both_internal_sources():
    registration = load_registration()
    prompt = registration.TOOLS_FUNCTION_CALLING_PROMPT

    assert "personio_directory" in prompt
    assert "rag_chat" in prompt
    assert "current people, profiles, business contacts" in prompt
    assert "documented processes, responsibilities, shared mailboxes" in prompt
    assert "both evidence types are actually needed" in prompt
    assert "Do not use rag_chat, web search, or model knowledge as a fallback" in prompt
    assert "RAG_Chat ist fuer KAHLE-internes Wissen die SSOT." not in prompt


def test_registered_descriptions_keep_personio_and_rag_authority_separate():
    registration = load_registration()
    model_registration = load_model_registration()

    rag_description = registration.TOOL_DEFINITIONS["rag_chat"]["specs"][0]["description"]
    assert "dokumentierte KAHLE-Prozesse, Zuständigkeiten, Funktionspostfächer" in rag_description
    assert "Nicht für aktuelle Personen" in rag_description

    model_note = model_registration.make_meta(model_registration.MODELS[0])["kahleKnowledgeNote"]
    assert "personio_directory" in model_note
    assert "rag_chat" in model_note
    assert "aktuelle Personen" in model_note
    assert "dokumentierte Prozesse" in model_note


def test_future_vinci_models_receive_the_shared_internal_source_tools():
    registration = load_registration()
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("create table model (id text, name text)")
    con.execute(
        "insert into model values (?, ?)",
        ("kahle-vinci-future", "KAHLE-Vinci Future"),
    )

    assert registration.resolve_vinci_model_ids(con) == ["kahle-vinci-future"]
    assert registration.shared_vinci_tool_ids()[:2] == [
        "personio_directory",
        "rag_chat",
    ]

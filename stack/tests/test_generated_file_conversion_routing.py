"""Follow-up conversion of a file Vinci generated earlier in the same chat.

"Wandle die eben erstellte PDF in Markdown um" must convert that PDF with
file_to_md_save. Observed live: the model regenerated a new PDF through
kahle_workflow_execute, or the guard wrote a new Markdown file from the
previous answer instead of converting the generated file.
"""

import ast
import importlib.util
import re
import sys
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MIDDLEWARE = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "middleware.py"
GUARD = ROOT / "open-webui-functions" / "kahle_toolcall_guard.py"

PDF_LINK = "http://localhost:8091/files/d/0845f44975a1462c9388af5418014a6c"
DOCX_LINK = "http://localhost:8091/files/d/3244bfb2cbc14ea3b5aa976556528e56"


def load_block_reason():
    source = MIDDLEWARE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    selected = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_ascii_fold", "_kahle_uploaded_conversion_block_reason"}
    ]
    namespace = {"re": re, "unicodedata": unicodedata}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(MIDDLEWARE), "exec"), namespace)
    return namespace["_kahle_uploaded_conversion_block_reason"]


def load_guard():
    spec = importlib.util.spec_from_file_location("guard_generated_conversion", GUARD)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --- model-led path: wrong tools are blocked before they run ------------------


@pytest.mark.parametrize(
    "request_text",
    [
        "Wandle die eben erstellte PDF in Markdown um.",
        "Konvertiere die PDF-Datei bitte nach Markdown",
        "kannst du die pdf in markdown umwandeln?",
    ],
)
def test_pdf_to_markdown_blocks_regeneration_and_allows_conversion(request_text):
    block = load_block_reason()

    for wrong in ("kahle_workflow_execute", "pdf_create_save", "text_create_save", "file_to_docx_save", "docx_create_save"):
        reason = block(wrong, request_text)
        assert "DATEIKONVERTIERUNG_TOOLCALL_BLOCKIERT" in reason, wrong
        assert "file_to_md_save" in reason
    assert block("file_to_md_save", request_text) == ""


def test_pdf_to_word_blocks_regeneration_and_allows_conversion():
    block = load_block_reason()
    request_text = "Wandle die eben erstellte PDF in eine Word-Datei um"

    for wrong in ("kahle_workflow_execute", "docx_create_save", "file_to_md_save"):
        assert "file_to_docx_save" in block(wrong, request_text), wrong
    assert block("file_to_docx_save", request_text) == ""


@pytest.mark.parametrize(
    "request_text",
    [
        "Erstelle aus der Recherche eine PDF",
        "Wandle die Antwort in eine PDF um",
        "Erstelle mir aus dem Ergebnis eine Markdown-Datei",
        "Recherchiere intern zum Thema KI-Compliance und erstelle daraus eine PDF",
    ],
)
def test_new_documents_still_use_the_workflow(request_text):
    block = load_block_reason()

    assert block("kahle_workflow_execute", request_text) == ""


# --- guard rescue: convert the generated file, never re-create it -------------


def chat(request_text: str, previous_answer: str, reply: str) -> dict:
    return {
        "messages": [
            {"role": "user", "content": "Lies die Datei und nenne das Kennwort."},
            {"role": "assistant", "content": "Das Kennwort lautet **Leuchtturm-42**."},
            {"role": "user", "content": "Erstelle aus deiner Antwort eine PDF zum Download."},
            {"role": "assistant", "content": previous_answer},
            {"role": "user", "content": request_text},
            {"role": "assistant", "content": reply},
        ]
    }


def download(link: str, filename: str) -> str:
    return f"Download-Link: [Datei herunterladen]({link})\nDatei: {filename}\nSHA256: abc\nGroesse: 10 Bytes"


@pytest.fixture()
def guard(monkeypatch):
    module = load_guard()
    calls: list[tuple[str, dict]] = []
    created: list[str] = []

    def fake_tool(tool_name, params):
        calls.append((tool_name, dict(params)))
        return {"download_url": "http://localhost:8091/files/d/" + "e" * 32, "filename": "aus_deiner_antwort.md",
                "sha256": "f", "size_bytes": 5}

    def fake_create(content, output_format, filename, title=""):
        created.append(output_format)
        return {"download_url": "http://localhost:8091/files/d/" + "c" * 32, "filename": filename,
                "sha256": "c", "size_bytes": 5}

    monkeypatch.setattr(module, "_call_file_proxy_tool", fake_tool)
    monkeypatch.setattr(module, "_create_file", fake_create)
    return module, calls, created


@pytest.mark.parametrize(
    "reply",
    [
        "Hier ist der Inhalt als Markdown:\n\n# Kennwort\n\nLeuchtturm-42",
        "Ich habe keinen Zugriff auf die PDF.",
    ],
)
def test_guard_converts_the_generated_pdf_instead_of_writing_a_new_file(guard, reply):
    module, calls, created = guard
    body = chat("Wandle die eben erstellte PDF in Markdown um.", download(PDF_LINK, "aus_deiner_antwort.pdf"), reply)

    result = module.Filter().outlet(body, {"id": "u1"}, {"chat_id": "c1"})

    assert calls == [("file_to_md_save", {"file_path": PDF_LINK})]
    assert created == []
    assert "/files/d/" + "e" * 32 in result["messages"][-1]["content"]


def test_guard_uses_the_latest_generated_file_of_the_source_type(guard):
    module, calls, _ = guard
    body = chat(
        "Wandle die PDF-Datei in Markdown um",
        download(PDF_LINK, "aus_deiner_antwort.pdf") + "\n\n" + download(DOCX_LINK, "kennwort.docx"),
        "Gern.",
    )

    module.Filter().outlet(body, {"id": "u1"}, {"chat_id": "c1"})

    assert calls == [("file_to_md_save", {"file_path": PDF_LINK})]


def test_guard_leaves_a_correct_conversion_alone(guard):
    module, calls, created = guard
    reply = download("http://localhost:8091/files/d/" + "9" * 32, "aus_deiner_antwort.md")
    body = chat("Wandle die eben erstellte PDF in Markdown um.", download(PDF_LINK, "aus_deiner_antwort.pdf"), reply)

    result = module.Filter().outlet(body, {"id": "u1"}, {"chat_id": "c1"})

    assert calls == [] and created == []
    assert result["messages"][-1]["content"] == reply


def test_guard_keeps_creating_new_files_from_a_previous_result(guard):
    module, calls, created = guard
    body = chat(
        "Erstelle mir aus deiner Antwort eine Markdown-Datei",
        "Das Kennwort lautet **Leuchtturm-42**, gilt fuer den Testzugang und wurde am Montag vergeben.",
        "Gern.",
    )

    module.Filter().outlet(body, {"id": "u1"}, {"chat_id": "c1"})

    assert calls == []
    assert created == ["md"]


# --- the block names the exact file to convert --------------------------------


def load_pdf_hint():
    source = MIDDLEWARE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_with_generated_pdf_hint"]
    from typing import Any

    namespace: dict = {"Any": Any}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(MIDDLEWARE), "exec"), namespace)
    return namespace["_with_generated_pdf_hint"]


def test_pdf_conversion_block_names_the_latest_generated_pdf():
    block = load_block_reason()
    hint = load_pdf_hint()
    reason = block("kahle_workflow_execute", "Wandle die eben erstellte PDF in Markdown um.")
    generated = [("alt.pdf", DOCX_LINK.replace("3244", "1111")), ("aus_deiner_antwort.pdf", PDF_LINK), ("kennwort.docx", DOCX_LINK)]

    hinted = hint(reason, generated)

    assert hinted.startswith(reason)
    assert f'file_path="{PDF_LINK}"' in hinted
    assert DOCX_LINK not in hinted
    # Nothing to add without a generated PDF or for other block reasons.
    assert hint(reason, [("kennwort.docx", DOCX_LINK)]) == reason
    assert hint("", generated) == ""
    word_reason = block("file_to_docx_save", "Bitte gib mir die Word im Anhang als Markdown aus")
    assert hint(word_reason, generated) == word_reason


def test_native_tool_path_adds_the_pdf_hint_to_the_block():
    source = MIDDLEWARE.read_text(encoding="utf-8")
    native = source[source.index("async def streaming_chat_response_handler("):]
    native = native[native.index("document_comparison_block_reason = ("):]
    native = native[:native.index("elif direct_tool:")]

    assert "_with_generated_pdf_hint(" in native


# --- files the guard generated are found in the chat ---------------------------

HARNESS = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "kahle_knowledge_harness.py"


def test_generated_file_links_read_the_guard_download_format():
    spec = importlib.util.spec_from_file_location("harness_guard_download_format", HARNESS)
    harness = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = harness
    spec.loader.exec_module(harness)
    messages = [
        {"role": "user", "content": "Erstelle aus deiner Antwort eine PDF zum Download."},
        {"role": "assistant", "content": download(PDF_LINK, "aus_deiner_antwort.pdf")},
        {"role": "assistant", "content": download(DOCX_LINK, "kennwort.docx") + "\n\nWeiterer Text."},
    ]

    assert harness.generated_file_links(messages) == [
        ("aus_deiner_antwort.pdf", PDF_LINK),
        ("kennwort.docx", DOCX_LINK),
    ]

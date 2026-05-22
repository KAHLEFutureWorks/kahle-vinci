#!/usr/bin/env python3
"""Regression checks for Markdown-ish text rendered into generated DOCX files."""

from __future__ import annotations

import html
import io
import re
import time
import zipfile
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[1]
PROXY_MAIN = ROOT / "owui-file-proxy" / "app" / "main.py"


def load_docx_render_helpers() -> dict[str, Any]:
    src = PROXY_MAIN.read_text(encoding="utf-8")
    start = src.index("def _strip_single_markdown_markers")
    end = src.index("def _markdown_to_plain_lines")
    ns: dict[str, Any] = {
        "Any": Any,
        "Optional": Optional,
        "html": html,
        "io": io,
        "re": re,
        "time": time,
        "zipfile": zipfile,
        "Document": None,
        "RGBColor": None,
        "KAHLE_DOCX_TEMPLATE": Path("missing-template.docx"),
        "_file_exists": lambda path: False,
        "_brand_value": lambda *args: "",
        "_DOCX_TEMPLATE_USED": type("Flag", (), {"set": lambda self, value: None})(),
        "_safe_style": lambda document, preferred, fallback="Normal": preferred or fallback,
    }
    exec(src[start:end], ns)
    ns["_markdown_to_template_docx_bytes"] = lambda content, title="Dokument": None
    return ns


def document_xml(docx_bytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(docx_bytes), "r") as zf:
        return zf.read("word/document.xml").decode("utf-8")


def test_docx_renderer_strips_markdown_bold_markers_from_numbered_and_bullet_lines():
    helpers = load_docx_render_helpers()
    content = "\n".join(
        [
            "1. **Webbasiertes CRM-System (webCRM.4Net)**:",
            "- **KfzPilot®** ist eine IT-Loesung fuer Autohaeuser.",
            "Normaler Text mit **fetter Passage** und *kursiver Passage*.",
        ]
    )

    xml = document_xml(helpers["_markdown_to_docx_bytes"](content, "KAHLE-Vinci Ergebnis"))

    assert "**" not in xml
    assert "*kursiver Passage*" not in xml
    assert "Webbasiertes CRM-System (webCRM.4Net)" in xml
    assert "KfzPilot" in xml
    assert "fetter Passage" in xml
    assert "<w:b/>" in xml


if __name__ == "__main__":
    test_docx_renderer_strips_markdown_bold_markers_from_numbered_and_bullet_lines()
    print("docx markdown rendering tests passed")

#!/usr/bin/env python3
"""Regression checks for public filenames versus internal storage names."""
from __future__ import annotations

from pathlib import Path
import re
import uuid

ROOT = Path(__file__).resolve().parents[1]
PROXY = ROOT / "owui-file-proxy" / "app" / "main.py"


def load_filename_helpers():
    src = PROXY.read_text(encoding="utf-8")
    start = src.index("def _decode_literal_unicode_escapes")
    end = src.index("def _reject_wildcards")
    ns = {"re": re, "uuid": uuid}
    exec(src[start:end], ns)
    return ns


def test_internal_prefixes_are_never_public():
    visible = load_filename_helpers()["_visible_filename"]
    source = "f0502990-a2ad-47f9-b20c-09ba7b3df5fc_Focus_AI_KI-Compliance-System_v1.0.docx"
    stored = "20260730_151736_1eb251bc_" + source
    expected = "Focus_AI_KI-Compliance-System_v1.0.docx"
    assert visible(source) == expected
    assert visible(stored) == expected
    assert visible("") == ""


def test_download_manifest_and_conversion_use_public_name():
    src = PROXY.read_text(encoding="utf-8")
    assert '"filename": _visible_filename(download_name or Path(rel).name)' in src
    assert '"download_url": _build_download_url(rel, safe_name)' in src
    assert "filename=download_name" in src
    section = src[src.index("def docx_to_pdf_save"):src.index("# Generic single-file -> Markdown")]
    assert "visible_source = _visible_filename(path.name)" in section
    assert 'requested_out.casefold() == "converted.pdf"' in section
    assert 'files = [("files", (visible_source, data, DOCX_MIME))]' in section
    assert "prepare_human_markdown(markdown, title=title)" in section


if __name__ == "__main__":
    test_internal_prefixes_are_never_public()
    test_download_manifest_and_conversion_use_public_name()
    print("public filename contract tests passed")
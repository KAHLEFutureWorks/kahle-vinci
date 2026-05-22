#!/usr/bin/env python3
"""Static contract checks for generated document template usage."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROXY_MAIN = ROOT / "owui-file-proxy" / "app" / "main.py"


def source() -> str:
    return PROXY_MAIN.read_text(encoding="utf-8")


def section(src: str, start: str, end: str) -> str:
    start_idx = src.index(start)
    end_idx = src.index(end, start_idx)
    return src[start_idx:end_idx]


def test_pdf_renderer_does_not_overlay_full_page_pdf_template():
    src = source()
    pdf_rendering = section(src, "def _text_to_reportlab_pdf_bytes", "def _apply_pdf_template")

    assert "_apply_pdf_template(rendered)" not in pdf_rendering
    assert "merge_page" not in pdf_rendering


def test_pdf_template_used_metadata_requires_actual_template_application():
    src = source()

    assert 'saved["template_used"] = bool(SimpleDocTemplate is not None)' not in src


def test_docx_template_used_metadata_requires_successful_template_render():
    src = source()

    assert 'saved["template_used"] = bool(Document is not None and _file_exists(KAHLE_DOCX_TEMPLATE))' not in src


def test_pptx_generation_does_not_discard_all_template_slides_up_front():
    src = source()
    pptx_rendering = section(src, "def _markdown_to_pptx_bytes", "def _sign_download")

    assert "_clear_pptx_slides(prs)" not in pptx_rendering


def test_pptx_generation_limits_text_to_slide_safe_bullets():
    src = source()
    slide_specs = section(src, "def _markdown_to_slide_specs", "def _set_shape_text")

    assert "MAX_PPTX_BULLETS_PER_SLIDE" in src
    assert "MAX_PPTX_BULLET_CHARS" in src
    assert "_shorten_pptx_text" in src
    assert "_fit_pptx_bullets" in slide_specs


def test_docx_to_pdf_save_uses_branded_pdf_renderer():
    src = source()
    docx_to_pdf = section(src, "def docx_to_pdf_save", "# -----------------------------\n# Generic single-file -> Markdown")

    assert 'f"{DOC_WORKER_URL}/bundle/to_md"' in docx_to_pdf
    assert 'f"{DOC_WORKER_URL}/docx/to_pdf"' not in docx_to_pdf
    assert "_text_to_pdf_bytes(markdown, title)" in docx_to_pdf
    assert 'saved["template_used"] = bool(_PDF_TEMPLATE_USED.get())' in docx_to_pdf


def test_filename_sanitizer_decodes_literal_unicode_escapes():
    src = source()

    assert "def _decode_literal_unicode_escapes" in src
    assert "_decode_literal_unicode_escapes(name)" in src
    assert r"(?:\\+u|_u)" in src


def test_pdf_remove_pages_can_infer_last_page_when_pages_missing():
    src = source()
    remove_pages = section(src, "class PdfRemovePagesSaveRequest", "class PdfMergeSaveRequest")
    remove_pages_save = section(src, "def pdf_remove_pages_save", "@app.post(\"/pdf/merge_save\"")

    assert "remove_pages: Optional[list[int]]" in remove_pages
    assert "pages_to_remove: Optional[list[int]]" in remove_pages
    assert "_infer_last_pdf_page" in remove_pages_save


if __name__ == "__main__":
    test_pdf_renderer_does_not_overlay_full_page_pdf_template()
    test_pdf_template_used_metadata_requires_actual_template_application()
    test_docx_template_used_metadata_requires_successful_template_render()
    test_pptx_generation_does_not_discard_all_template_slides_up_front()
    test_pptx_generation_limits_text_to_slide_safe_bullets()
    test_docx_to_pdf_save_uses_branded_pdf_renderer()
    test_filename_sanitizer_decodes_literal_unicode_escapes()
    test_pdf_remove_pages_can_infer_last_page_when_pages_missing()
    print("document template contract tests passed")

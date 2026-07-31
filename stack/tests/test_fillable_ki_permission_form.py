"""Contract tests for the deterministic fillable KI permission form."""
from __future__ import annotations
import asyncio, importlib.util, io, json, sys
from pathlib import Path
from zipfile import ZipFile
from docx import Document
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
FORM_PATH = ROOT / "owui-file-proxy" / "app" / "fillable_forms.py"
PDF_FORM_PATH = ROOT / "owui-file-proxy" / "app" / "fillable_pdf_forms.py"
WORKFLOW_PATH = ROOT / "open-webui-tools" / "kahle_workflow_orchestrator.py"

def _load(name: str, path: Path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module

def test_form_contains_real_word_controls_and_required_sections(tmp_path):
    module = _load("fillable_forms_contract", FORM_PATH)
    data = module.render_ki_permission_form_docx(
        tmp_path / "missing-template.docx",
        tmp_path / "missing-logo.png",
        tmp_path / "missing-brand.json",
        "2026-07-31 12:00:00",
    )
    assert data and data[:2] == b"PK"
    Document(io.BytesIO(data))
    with ZipFile(io.BytesIO(data)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    assert xml.count("<w:sdt>") >= 45
    assert xml.count("<w14:checkbox>") >= 16
    assert xml.count("<w:date>") >= 8
    assert xml.count("<w:dropDownList>") >= 5
    for required in (
        "Antrag auf Freigabe einer KI-Nutzung", "Grund der Genehmigungspflicht",
        "Datenschutzpr?fung", "Gemeinsame Entscheidung", "KI-Beauftragter", "Gesch?ftsf?hrung",
        'w:val="valid_until"', 'w:val="decision_approved"', 'w:val="ai_officer_signature"',
    ):
        assert required in xml
    output = tmp_path / "KI-Nutzungs-und-Freigabeantrag.docx"
    output.write_bytes(data)

def test_pdf_form_contains_real_acroform_controls(tmp_path):
    module = _load("fillable_pdf_forms_contract", PDF_FORM_PATH)
    data = module.render_ki_permission_form_pdf("31.07.2026 12:00")
    output = tmp_path / "KI-Nutzungs-und-Freigabeantrag.pdf"
    output.write_bytes(data)
    reader = PdfReader(output)
    form_fields = reader.get_fields() or {}
    assert len(reader.pages) >= 4
    assert len(form_fields) == 65
    assert form_fields["ai_system_name"]["/FT"] == "/Tx"
    assert form_fields["reason_high_risk"]["/FT"] == "/Btn"
    assert form_fields["risk_level"]["/FT"] == "/Ch"

def test_workflow_detects_fillable_permission_requests_for_docx_and_pdf():
    module = _load("workflow_fillable_detection", WORKFLOW_PATH)
    request = "Bitte erstelle eine ausf?llbare aktive Word Datei als Vorlage, um diese Erlaubnisse schriftlich festzuhalten"
    assert module._looks_like_fillable_ki_permission_form_request(request, "docx")
    assert module._looks_like_fillable_ki_permission_form_request("Bitte gib mir das genau so als interaktive PDF aus", "pdf")
    assert not module._looks_like_fillable_ki_permission_form_request("Erstelle das Ergebnis als Word", "docx")

def test_workflow_routes_form_request_without_rag(monkeypatch):
    module = _load("workflow_fillable_route", WORKFLOW_PATH)
    expected = {"download_url":"https://example.invalid/form.docx","filename":"KI-Nutzungs-und-Freigabeantrag.docx","sha256":"abc","size_bytes":123,"fillable":True}
    monkeypatch.setattr(module, "create_fillable_ki_permission_form", lambda filename, output_format="docx": expected)
    tools = module.Tools()
    tools._run_internal_rag = lambda query: (_ for _ in ()).throw(AssertionError("RAG must not run for deterministic form"))
    raw = asyncio.run(tools.kahle_workflow_execute(
        "Bitte erstelle eine ausf?llbare Word-Vorlage f?r die schriftlichen KI-Freigaben",
        output_format="docx",
    ))
    payload = json.loads(raw)
    assert payload["intent"] == "fillable_ki_permission_form"
    assert payload["fillable"] is True
    assert payload["download_url"] == expected["download_url"]

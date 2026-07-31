"""Regression tests for source-grounded interactive forms."""
from __future__ import annotations
import importlib.util,io,sys,tempfile
from pathlib import Path
from zipfile import ZipFile
from pypdf import PdfReader
ROOT=Path(__file__).resolve().parents[1]

def load(name,path):
    sys.path.insert(0,str(path.parent)); spec=importlib.util.spec_from_file_location(name,path); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module

def sample_schema():
    workflow=load('workflow_dynamic',ROOT/'open-webui-tools'/'kahle_workflow_orchestrator.py')
    request='Erstelle aus unserer Sicherheitsrichtlinie einen interaktiven Word-Wissenstest für Mitarbeitende'
    context='# Sicherheitsrichtlinie\n\n## Freigaben\nNicht freigegebene Systeme dürfen nur nach schriftlicher Genehmigung genutzt werden.\n\n## Datenschutz\nPersonenbezogene Daten dürfen nicht in öffentliche Systeme geladen werden.\n\n## Vorfälle\nSicherheitsvorfälle müssen unverzüglich gemeldet werden.\n\n## Schulung\nMitarbeitende müssen jährlich geschult werden.'
    assert workflow.resolve_explicit_download_format(request,'docx')=='docx'
    assert workflow._looks_like_interactive_form_request(request,'docx')
    schema=workflow.build_context_grounded_form_schema(request,context)
    assert schema and schema['source_grounded'] and schema['form_kind']=='knowledge_test'
    return schema

def test_dynamic_pdf_has_acroform_fields():
    module=load('pdf_dynamic',ROOT/'owui-file-proxy'/'app'/'fillable_pdf_forms.py'); data=module.render_dynamic_form_pdf(sample_schema(),'31.07.2026')
    reader=PdfReader(io.BytesIO(data)); fields=reader.get_fields() or {}
    widget_bottoms=[]
    for page in reader.pages:
        for annotation in page.get('/Annots') or []:
            rect=annotation.get_object().get('/Rect')
            if rect: widget_bottoms.append(float(rect[1]))
    assert len(reader.pages)>=1 and len(fields)>=8 and any(v.get('/FT')=='/Tx' for v in fields.values())
    assert widget_bottoms and min(widget_bottoms)>=62
    assert module._pdf_safe_text("🖥️ Kahle 📄 Vinci") == "Kahle Vinci"

def test_dynamic_docx_has_real_content_controls():
    module=load('docx_dynamic',ROOT/'owui-file-proxy'/'app'/'fillable_forms.py')
    base=ROOT.parent/'.tmp'; base.mkdir(exist_ok=True)
    data=module.render_dynamic_form_docx(base/'missing.docx',base/'missing.png',base/'missing.json','2026-07-31',sample_schema())
    with ZipFile(io.BytesIO(data)) as archive: xml=archive.read('word/document.xml')
    assert xml.count(b'<w:sdt>')>=8 and xml.count(b'<w:date>')>=1

if __name__=='__main__':
    test_dynamic_pdf_has_acroform_fields(); test_dynamic_docx_has_real_content_controls(); print('dynamic interactive form tests passed')
import tempfile
from pathlib import Path

from app.audit_export import AuditExporter
from test_document_lifecycle import setup


def test_unified_audit_exports_governance_and_lifecycle_as_csv_and_pdf():
    with tempfile.TemporaryDirectory() as directory:
        governance, lifecycle, kb_id = setup(Path(directory))
        lifecycle.submit(
            uploaded_by_user_id="employee", owner_user_id="employee", target_knowledgebase_id=kb_id,
            title="Auditdokument", original_filename="audit.md", original_file_id="file",
            original_sha256="a" * 64, valid_workdays=10, confidentiality="internal",
        )
        exporter = AuditExporter(governance.store)
        entries = exporter.entries()
        assert any(entry.event_type == "submitted" for entry in entries)
        assert any(entry.event_type == "knowledgebase_access_changed" for entry in entries)
        csv_data = exporter.csv_bytes()
        assert csv_data.startswith(b"\xef\xbb\xbf") and b"submitted" in csv_data
        assert exporter.pdf_bytes().startswith(b"%PDF-")

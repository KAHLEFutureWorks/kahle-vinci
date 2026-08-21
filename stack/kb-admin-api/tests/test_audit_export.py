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
        assert csv_data.startswith(b"\xef\xbb\xbf")
        csv_text = csv_data.decode("utf-8-sig")
        assert "Ausgeführt von;Aktion;Betroffenes Element;Beschreibung" in csv_text
        assert "Dokument hochgeladen" in csv_text
        assert "employee" not in csv_text.splitlines()[-1].split(";")[1]
        assert exporter.pdf_bytes().startswith(b"%PDF-")


def test_technical_audit_actors_are_presented_as_system_actions():
    with tempfile.TemporaryDirectory() as directory:
        governance, _, _ = setup(Path(directory))
        technical_actors = {
            "migration": "System: Bestandsübernahme",
            "classifier": "System: automatische Klassifizierung",
            "indexer": "System: Veröffentlichung und Indexierung",
            "auto_activation": "System: automatische Veröffentlichung",
        }
        with governance.store.connect() as db:
            for actor_user_id in technical_actors:
                db.execute(
                    """INSERT INTO governance_audit
                       (occurred_at, actor_user_id, event_type, subject_type, subject_id, details_json)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    ("2026-08-06T10:00:00+00:00", actor_user_id, "analysis_recorded",
                     "document", actor_user_id, "{}"),
                )

        entries_by_actor = {
            entry.actor_user_id: entry.actor_name for entry in AuditExporter(governance.store).entries()
        }
        for actor_user_id, label in technical_actors.items():
            assert entries_by_actor[actor_user_id] == label

from pathlib import Path

from app.rag_metadata import RAGMetadataWriter
from test_document_lifecycle import setup, submit


def test_trusted_frontmatter_replaces_uploaded_frontmatter_and_tracks_activation(tmp_path: Path):
    governance, lifecycle, kb_id = setup(tmp_path)
    case = submit(lifecycle, kb_id)
    rag = tmp_path / "files" / case.document_id / case.version_id / "rag.md"
    rag.parent.mkdir(parents=True)
    rag.write_text(
        "---\nowner_email: attacker@example.com\nstatus: active\nrag_index: true\n---\n# Inhalt\nSicher.",
        encoding="utf-8",
    )
    writer = RAGMetadataWriter(governance.store, tmp_path / "files")
    writer.write(case.version_id)
    pending = rag.read_text(encoding="utf-8")
    assert 'owner_email: "employee@kahle.de"' in pending
    assert "attacker@example.com" not in pending
    assert "rag_index: false" in pending
    assert f'document_id: "{case.document_id}"' in pending
    assert f'knowledgebase_ids: ["{kb_id}"]' in pending
    assert "authority_level: 6" in pending

    with governance.store.connect() as db:
        db.execute(
            "UPDATE document_versions SET status='active', valid_from='2026-08-06', "
            "valid_until='2026-10-29', activated_at='2026-08-06T12:00:00+00:00' WHERE version_id=?",
            (case.version_id,),
        )
        db.execute("UPDATE canonical_documents SET active_version_id=? WHERE document_id=?", (case.version_id, case.document_id))
    writer.write(case.version_id)
    active = rag.read_text(encoding="utf-8")
    assert "rag_index: true" in active
    assert 'valid_until: "2026-10-29"' in active
    assert f'source_url: "/wissen/api/portal/sources/{case.version_id}"' in active


def test_metadata_write_retries_a_transient_windows_file_lock(tmp_path: Path, monkeypatch):
    governance, lifecycle, kb_id = setup(tmp_path)
    case = submit(lifecycle, kb_id)
    rag = tmp_path / "files" / case.document_id / case.version_id / "rag.md"
    rag.parent.mkdir(parents=True)
    rag.write_text("# Inhalt\n\nSicher.", encoding="utf-8")
    real_replace = Path.replace
    attempts = []

    def transient_lock(source, target):
        attempts.append(1)
        if len(attempts) == 1:
            raise PermissionError(5, "Zugriff verweigert")
        return real_replace(source, target)

    monkeypatch.setattr(Path, "replace", transient_lock)
    RAGMetadataWriter(governance.store, tmp_path / "files").write(case.version_id)
    assert len(attempts) == 2
    assert f'document_id: "{case.document_id}"' in rag.read_text(encoding="utf-8")

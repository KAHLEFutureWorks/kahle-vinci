import tempfile
from datetime import date
from pathlib import Path

import pytest

from app.global_analysis import GlobalCorpus, GlobalDocumentAnalyzer
from app.legacy_migration import LegacyMigrationService
from app.secure_ingest import QuarantineStorage, SecureFileInspector, SecureIngestPipeline
from test_document_lifecycle import setup


def test_migration_inventory_is_stable_and_quarantines_duplicates(tmp_path: Path):
    governance, lifecycle, _ = setup(tmp_path / "portal")
    root = tmp_path / "legacy"; kb = root / "service"; kb.mkdir(parents=True)
    complete = """---
owner: employee@kahle.de
confidentiality: internal
title: Serviceprozess
authority_type: process_or_work_instruction
authority_level: 5
scope: {"knowledgebase_ids":["service"]}
---
# Ablauf
Nur freigegebenes Wissen.
"""
    (kb / "one.md").write_text(complete, encoding="utf-8")
    (kb / "duplicate.md").write_text(complete, encoding="utf-8")
    (kb / "missing.md").write_text("# Ohne Metadaten\n\nAusreichend langer Inhalt für die Qualitätsprüfung.", encoding="utf-8")
    corpus = GlobalCorpus(governance.store)
    service = LegacyMigrationService(
        governance, lifecycle, GlobalDocumentAnalyzer(corpus), corpus,
        QuarantineStorage(tmp_path / "files"),
    )
    first = service.inventory(root)
    second = service.inventory(root)
    assert [(item.document_id, item.version_id) for item in first] == [
        (item.document_id, item.version_id) for item in second
    ]
    assert next(item for item in first if item.path.endswith("missing.md")).status == "metadata_required"
    assert sum(item.status == "quarantine" for item in first) == 1


def test_ready_legacy_document_is_staged_into_regular_approval_workflow(tmp_path: Path):
    governance, lifecycle, _ = setup(tmp_path / "portal")
    root = tmp_path / "legacy"; kb = root / "service"; kb.mkdir(parents=True)
    path = kb / "service.md"
    path.write_text("""---
owner: employee@kahle.de
confidentiality: internal
title: Serviceprozess
authority_type: process_or_work_instruction
authority_level: 5
scope: {"knowledgebase_ids":["service"]}
---
# Ablauf
Eine eindeutige neue Arbeitsanweisung.
""", encoding="utf-8")
    corpus = GlobalCorpus(governance.store)
    service = LegacyMigrationService(
        governance, lifecycle, GlobalDocumentAnalyzer(corpus), corpus,
        QuarantineStorage(tmp_path / "files"),
    )
    item = service.inventory(root)[0]
    assert item.status == "ready_to_stage"
    case_id = service.stage(root, item.path, "portal")
    case = lifecycle.submission(case_id)
    assert case.document_id == item.document_id
    assert case.version_id == item.version_id
    assert case.status == "pending_manager_approval"
    assert case.requested_action == "create"
    assert case.uploaded_by_user_id == "employee"
    assert [task.case_id for task in lifecycle.tasks_for("employee")] == []
    assert [task.case_id for task in lifecycle.tasks_for("manager")] == [case_id]
    assert service.inventory(root)[0].status == "staged"

    # Bestehende, vor dem Fix angelegte Migrationsvorgänge werden beim Start
    # ebenfalls aus der doppelten Uploader-Entscheidung weitergeführt.
    with governance.store.connect() as db:
        db.execute("UPDATE document_cases SET status='pending_employee_decision',requested_action=NULL WHERE case_id=?", (case_id,))
        db.execute("UPDATE document_versions SET status='pending_employee_decision' WHERE version_id=?", (case.version_id,))
    LegacyMigrationService(
        governance, lifecycle, GlobalDocumentAnalyzer(corpus), corpus,
        QuarantineStorage(tmp_path / "files"),
    )
    assert lifecycle.submission(case_id).status == "pending_manager_approval"


def test_admin_resolves_missing_legacy_metadata_before_staging(tmp_path: Path):
    governance, lifecycle, _ = setup(tmp_path / "portal")
    root = tmp_path / "legacy"; kb = root / "service"; kb.mkdir(parents=True)
    (kb / "missing.md").write_text("# Arbeitsanweisung\n\nVollst?ndiger Inhalt.", encoding="utf-8")
    corpus = GlobalCorpus(governance.store)
    service = LegacyMigrationService(
        governance, lifecycle, GlobalDocumentAnalyzer(corpus), corpus,
        QuarantineStorage(tmp_path / "files"),
    )
    item = service.inventory(root)[0]
    assert item.status == "metadata_required"
    service.resolve_metadata(
        item.path, "portal", owner_email="employee@kahle.de", confidentiality="internal",
        authority_type="process_or_work_instruction", authority_level=5,
        scope={"knowledgebase_ids": ["service"]},
    )
    case_id = service.stage(root, item.path, "portal")
    case = lifecycle.submission(case_id)
    with governance.store.connect() as db:
        metadata = db.execute("SELECT * FROM document_metadata WHERE document_id=?", (case.document_id,)).fetchone()
    assert metadata["authority_level"] == 5


def test_legacy_owner_requires_assigned_manager_for_two_stage_approval(tmp_path: Path):
    governance, lifecycle, kb_id = setup(tmp_path / "portal")
    root = tmp_path / "legacy"; root.mkdir(parents=True)
    (root / "missing.md").write_text("# Arbeitsanweisung\n\nVollständiger Inhalt.", encoding="utf-8")
    corpus = GlobalCorpus(governance.store)
    service = LegacyMigrationService(
        governance, lifecycle, GlobalDocumentAnalyzer(corpus), corpus,
        QuarantineStorage(tmp_path / "files"),
    )
    item = service.inventory(root)[0]
    with pytest.raises(ValueError, match="migration_owner_manager_required"):
        service.resolve_metadata(
            item.path, "portal", owner_email="portal@kahle.de", confidentiality="internal",
            authority_type="process_or_work_instruction", authority_level=5,
            knowledgebase_id=kb_id, scope={"knowledgebase_ids": [kb_id]},
        )


def test_root_level_legacy_file_requires_and_accepts_explicit_target_knowledgebase(tmp_path: Path):
    governance, lifecycle, kb_id = setup(tmp_path / "portal")
    root = tmp_path / "legacy"; root.mkdir(parents=True)
    (root / "ohne-ordner.md").write_text(
        "# Allgemeines Wissen\n\nAusreichend langer Inhalt ohne erkennbaren Zielbereich.",
        encoding="utf-8",
    )
    corpus = GlobalCorpus(governance.store)
    service = LegacyMigrationService(
        governance, lifecycle, GlobalDocumentAnalyzer(corpus), corpus,
        QuarantineStorage(tmp_path / "files"),
    )

    item = service.inventory(root)[0]
    assert item.knowledgebase_slug == ""
    assert "knowledgebase" in item.missing
    service.resolve_metadata(
        item.path, "portal", owner_email="employee@kahle.de", confidentiality="internal",
        authority_type="process_or_work_instruction", authority_level=5,
        knowledgebase_id=kb_id, scope={"description": "Service"},
    )

    resolved = service.inventory(root)[0]
    assert resolved.knowledgebase_slug == "service"
    assert resolved.status == "ready_to_stage"
    with governance.store.connect() as db:
        row = db.execute(
            "SELECT metadata_override_json FROM migration_inventory WHERE path=?", (item.path,),
        ).fetchone()
    assert f'"knowledgebase_ids": ["{kb_id}"]' in row["metadata_override_json"]


def test_inventory_is_recursive_and_pairs_original_with_existing_markdown(tmp_path: Path):
    governance, lifecycle, _ = setup(tmp_path / "portal")
    root = tmp_path / "legacy"; nested = root / "service" / "prozesse"; nested.mkdir(parents=True)
    (nested / "arbeitsablauf.txt").write_text("Originaler Arbeitsablauf mit ausreichend Inhalt.", encoding="utf-8")
    (nested / "arbeitsablauf.md").write_text("""---
owner: employee@kahle.de
confidentiality: internal
authority_type: process_or_work_instruction
authority_level: 5
scope: {"knowledgebase_ids":["service"]}
---
# Arbeitsablauf
Aufbereiteter und ausreichend langer Inhalt.
""", encoding="utf-8")
    corpus = GlobalCorpus(governance.store)
    service = LegacyMigrationService(governance, lifecycle, GlobalDocumentAnalyzer(corpus), corpus,
                                     QuarantineStorage(tmp_path / "files"))
    items = service.inventory(root)
    assert len(items) == 1
    assert items[0].original_path.endswith("arbeitsablauf.txt")
    assert items[0].markdown_path and items[0].markdown_path.endswith("arbeitsablauf.md")
    assert items[0].status == "ready_to_stage"


def test_admin_review_resolves_only_inventoried_original_and_markdown(tmp_path: Path):
    governance, lifecycle, _ = setup(tmp_path / "portal")
    root = tmp_path / "legacy"; kb = root / "service"; kb.mkdir(parents=True)
    original = kb / "ablauf.txt"; markdown = kb / "ablauf.md"
    original.write_text("Originalinhalt für die Prüfung.", encoding="utf-8")
    markdown.write_text("# Aufbereiteter Inhalt für die Prüfung", encoding="utf-8")
    corpus = GlobalCorpus(governance.store)
    service = LegacyMigrationService(governance, lifecycle, GlobalDocumentAnalyzer(corpus), corpus,
                                     QuarantineStorage(tmp_path / "files"))
    item = service.inventory(root)[0]

    assert service.review_file(root, item.path, "original") == original.resolve()
    assert service.review_file(root, item.path, "markdown") == markdown.resolve()
    with pytest.raises(ValueError, match="invalid_migration_file_kind"):
        service.review_file(root, item.path, "other")


def test_admin_review_rejects_inventory_path_outside_knowledge_root(tmp_path: Path):
    governance, lifecycle, _ = setup(tmp_path / "portal")
    root = tmp_path / "legacy"; kb = root / "service"; kb.mkdir(parents=True)
    source = kb / "ablauf.md"; source.write_text("# Prüfbarer Inhalt", encoding="utf-8")
    corpus = GlobalCorpus(governance.store)
    service = LegacyMigrationService(governance, lifecycle, GlobalDocumentAnalyzer(corpus), corpus,
                                     QuarantineStorage(tmp_path / "files"))
    item = service.inventory(root)[0]
    outside = tmp_path / "secret.md"; outside.write_text("geheim", encoding="utf-8")
    with governance.store.connect() as db:
        db.execute("UPDATE migration_inventory SET original_path=? WHERE path=?", ("../secret.md", item.path))

    with pytest.raises(ValueError, match="migration_path_outside_root"):
        service.review_file(root, item.path, "original")


def test_missing_metadata_and_rights_create_visible_tasks(tmp_path: Path):
    governance, lifecycle, _ = setup(tmp_path / "portal")
    root = tmp_path / "legacy"; kb = root / "service"; kb.mkdir(parents=True)
    (kb / "offen.md").write_text("# Noch ungeklärter, aber ausreichend langer Wissensinhalt", encoding="utf-8")
    corpus = GlobalCorpus(governance.store)
    service = LegacyMigrationService(governance, lifecycle, GlobalDocumentAnalyzer(corpus), corpus,
                                     QuarantineStorage(tmp_path / "files"))
    item = service.inventory(root)[0]
    kinds = {task["kind"] for task in service.tasks() if task["path"] == item.path}
    assert {"metadata:owner", "metadata:confidentiality", "metadata:authority_type",
            "metadata:authority_level", "metadata:scope"}.issubset(kinds)


def test_unresolved_inventory_expires_after_30_workdays(tmp_path: Path):
    governance, lifecycle, _ = setup(tmp_path / "portal")
    root = tmp_path / "legacy"; kb = root / "service"; kb.mkdir(parents=True)
    (kb / "offen.md").write_text("# Noch ungeklärter, aber ausreichend langer Wissensinhalt", encoding="utf-8")
    current = {"today": date(2026, 8, 6)}
    corpus = GlobalCorpus(governance.store)
    service = LegacyMigrationService(governance, lifecycle, GlobalDocumentAnalyzer(corpus), corpus,
                                     QuarantineStorage(tmp_path / "files"), today=lambda: current["today"])
    item = service.inventory(root)[0]
    current["today"] = date.fromisoformat(item.transition_deadline)
    assert service.process_transition_deadlines() == [item.path]
    with governance.store.connect() as db:
        row = db.execute("SELECT status,transition_status FROM migration_inventory WHERE path=?", (item.path,)).fetchone()
    assert (row["status"], row["transition_status"]) == ("transition_expired", "expired")


def test_admin_can_exclude_and_restore_legacy_item_without_deleting_source(tmp_path: Path):
    governance, lifecycle, _ = setup(tmp_path / "portal")
    root = tmp_path / "legacy"; kb = root / "service"; kb.mkdir(parents=True)
    source = kb / "unwichtig.md"
    source.write_text("# Historischer, derzeit nicht benötigter Inhalt", encoding="utf-8")
    corpus = GlobalCorpus(governance.store)
    service = LegacyMigrationService(governance, lifecycle, GlobalDocumentAnalyzer(corpus), corpus,
                                     QuarantineStorage(tmp_path / "files"))
    item = service.inventory(root)[0]

    service.exclude(item.path, "portal", "Für Vinci derzeit nicht relevant")
    excluded = service.inventory(root)[0]
    assert excluded.status == "excluded"
    assert excluded.exclusion_reason == "Für Vinci derzeit nicht relevant"
    assert source.exists()
    assert not [task for task in service.tasks() if task["path"] == item.path]
    assert any(event["event_type"] == "migration_excluded"
               for event in governance.audit_events("portal"))

    service.restore_excluded(item.path, "portal", "Erneute fachliche Prüfung")
    restored = service.inventory_items()[0]
    assert restored.status == "metadata_required"
    assert restored.exclusion_reason is None
    assert [task for task in service.tasks() if task["path"] == item.path]
    assert any(event["event_type"] == "migration_restored"
               for event in governance.audit_events("portal"))


def test_original_without_markdown_runs_through_secure_conversion_and_keeps_both_files(tmp_path: Path):
    governance, lifecycle, _ = setup(tmp_path / "portal")
    root = tmp_path / "legacy"; kb = root / "service"; kb.mkdir(parents=True)
    source = kb / "original.txt"
    source.write_text("Dies ist die ursprüngliche und ausreichend lange Arbeitsanweisung.", encoding="utf-8")

    class Scanner:
        def scan(self, filename: str, data: bytes) -> None:
            assert filename == "original.txt" and data

    class Converter:
        def convert(self, filename: str, data: bytes, title: str) -> str:
            return "# Konvertierte Arbeitsanweisung\n\nVollständiger, geprüfter Wissensinhalt.\n"

    storage = QuarantineStorage(tmp_path / "files")
    pipeline = SecureIngestPipeline(SecureFileInspector(), Scanner(), Converter(), storage)
    corpus = GlobalCorpus(governance.store)
    service = LegacyMigrationService(governance, lifecycle, GlobalDocumentAnalyzer(corpus), corpus,
                                     storage, pipeline)
    item = service.inventory(root)[0]
    assert item.markdown_path is None and item.conversion_quality == "pending"
    service.resolve_metadata(item.path, "portal", owner_email="employee@kahle.de",
                             confidentiality="internal", authority_type="process_or_work_instruction",
                             authority_level=5, scope={"knowledgebase_ids": ["service"]})
    case_id = service.stage(root, item.path, "portal")
    case = lifecycle.submission(case_id)
    version_root = tmp_path / "files" / case.document_id / case.version_id
    assert (version_root / "original.txt").read_bytes() == source.read_bytes()
    assert "Konvertierte Arbeitsanweisung" in (version_root / "rag.md").read_text(encoding="utf-8")

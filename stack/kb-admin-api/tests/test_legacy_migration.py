import tempfile
from pathlib import Path

from app.global_analysis import GlobalCorpus, GlobalDocumentAnalyzer
from app.legacy_migration import LegacyMigrationService
from app.secure_ingest import QuarantineStorage
from test_document_lifecycle import setup


def test_migration_inventory_is_stable_and_quarantines_duplicates(tmp_path: Path):
    governance, lifecycle, _ = setup(tmp_path / "portal")
    root = tmp_path / "legacy"; kb = root / "service"; kb.mkdir(parents=True)
    complete = """---
owner: employee@kahle.de
confidentiality: internal
title: Serviceprozess
---
# Ablauf
Nur freigegebenes Wissen.
"""
    (kb / "one.md").write_text(complete, encoding="utf-8")
    (kb / "duplicate.md").write_text(complete, encoding="utf-8")
    (kb / "missing.md").write_text("# Ohne Metadaten", encoding="utf-8")
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
    assert case.status == "pending_employee_decision"

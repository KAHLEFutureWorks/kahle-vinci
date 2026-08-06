import json
import tempfile
from datetime import date
from pathlib import Path

from app.maintenance import MaintenanceService
from app.quality_cases import QualityCaseService
from app.quality_dashboard import QualityDashboard
from app.legacy_migration import LegacyMigrationService
from app.global_analysis import GlobalCorpus, GlobalDocumentAnalyzer
from app.secure_ingest import QuarantineStorage
from test_document_lifecycle import setup


def test_quality_dashboard_combines_workflow_incident_mail_migration_and_backup_state():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); governance, lifecycle, _ = setup(root)
        MaintenanceService(governance.store)
        QualityCaseService(governance.store).system_incident("test", {"error_type":"Test"})
        corpus = GlobalCorpus(governance.store)
        LegacyMigrationService(governance, lifecycle, GlobalDocumentAnalyzer(corpus), corpus,
                               QuarantineStorage(root / "files"))
        backup = root / "backup-state.json"
        backup.write_text(json.dumps({"last_backup":"2026-08-06","last_restore_test":"2026-08"}))
        snapshot = QualityDashboard(governance.store, backup).snapshot(date(2026, 8, 6))
        assert snapshot["open_incidents"] == 1
        assert snapshot["backup"]["last_restore_test"] == "2026-08"
        assert snapshot["mail"] == {"pending": 0, "failed": 0}

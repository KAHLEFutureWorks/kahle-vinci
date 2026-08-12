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
        assert snapshot["expired_documents"] == 0
        assert set(snapshot["workflow_quality"]) == {
            "open_approvals", "average_processing_minutes", "escalations", "overdue_cases",
            "duplicates", "version_candidates", "conflicts", "failed_conversions", "security_findings",
        }


def test_quality_dashboard_aggregates_content_free_retrieval_metrics():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); governance, lifecycle, _ = setup(root)
        MaintenanceService(governance.store)
        QualityCaseService(governance.store)
        corpus = GlobalCorpus(governance.store)
        LegacyMigrationService(governance, lifecycle, GlobalDocumentAnalyzer(corpus), corpus,
                               QuarantineStorage(root / "files"))
        dashboard = QualityDashboard(governance.store, root / "missing-backup.json")
        dashboard.record_retrieval(user_id="employee", query_hash="a" * 64,
                                   found=True, source_count=2, latency_ms=100)
        dashboard.record_retrieval(user_id="employee", query_hash="b" * 64,
                                   found=False, source_count=0, latency_ms=200)
        dashboard.record_retrieval(user_id="employee", query_hash="c" * 64,
                                   found=False, source_count=0, latency_ms=300,
                                   error_code="Timeout")

        metrics = dashboard.snapshot()["retrieval"]
        assert metrics == {
            "window_days": 30, "requests": 3, "document_hit_rate_percent": 33.3,
            "source_coverage_percent": 100.0, "unanswered_questions": 1,
            "average_latency_ms": 200, "p95_latency_ms": 300,
            "error_rate_percent": 33.3,
        }
        with governance.store.connect() as db:
            columns = {row["name"] for row in db.execute("PRAGMA table_info(retrieval_events)")}
        assert "query" not in columns and "content" not in columns

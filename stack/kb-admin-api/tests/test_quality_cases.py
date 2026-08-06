import tempfile
from pathlib import Path

from app.quality_cases import QualityCaseService
from test_document_lifecycle import setup


def test_system_incidents_are_deduplicated_without_document_content():
    with tempfile.TemporaryDirectory() as directory:
        governance, _, _ = setup(Path(directory))
        service = QualityCaseService(governance.store, identifier=lambda: "incident-1")
        first = service.system_incident("conversion", {"error_type": "Timeout", "content": "secret"})
        second = service.system_incident("conversion", {"error_type": "Timeout", "content": "different"})
        assert first == second == "incident-1"
        incident = service.open_cases()["incidents"][0]
        assert "secret" not in incident["diagnostic_json"]


def test_permission_feedback_is_critical_and_captures_effective_rights():
    with tempfile.TemporaryDirectory() as directory:
        governance, _, kb_id = setup(Path(directory))
        service = QualityCaseService(governance.store, identifier=lambda: "feedback-1")
        feedback_id = service.report_rag(
            user_id="employee", reason="suspected_permission_issue", comment="Falscher Bereich",
            question="Frage", answer="Antwort", sources=[{"version_id": "v1"}], passages=[],
            rights=[kb_id], runtime={"model": "mistral", "retrieval": "hybrid-v2"}, request_id="req-1",
        )
        assert feedback_id == "feedback-1"
        feedback = service.open_cases()["feedback"][0]
        assert feedback["severity"] == "critical"
        assert kb_id in feedback["rights_json"]

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


def test_feedback_keeps_selected_documents_and_knowledgebases_separately():
    with tempfile.TemporaryDirectory() as directory:
        governance, _, kb_id = setup(Path(directory))
        service = QualityCaseService(governance.store, identifier=lambda: "feedback-refs")
        service.report_rag(
            user_id="employee", reason="incorrect", comment="Falsche Aussage",
            question="Frage", answer="Antwort", sources=[], passages=[], rights=[kb_id],
            runtime={}, request_id="req-refs", document_ids=["doc-1"],
            knowledgebase_ids=[kb_id],
        )
        feedback = service.open_cases()["feedback"][0]
        assert feedback["document_ids_json"] == '["doc-1"]'
        assert feedback["knowledgebase_ids_json"] == f'["{kb_id}"]'


def test_feedback_and_system_incidents_can_be_resolved_with_a_reason():
    with tempfile.TemporaryDirectory() as directory:
        governance, _, _ = setup(Path(directory))
        identifiers = iter(("feedback-resolve", "incident-resolve"))
        service = QualityCaseService(governance.store, identifier=lambda: next(identifiers))
        service.report_rag(
            user_id="employee", reason="incorrect", comment="Falsch",
            question="Frage", answer="Antwort", sources=[], passages=[], rights=[],
            runtime={}, request_id="request-resolve",
        )
        service.system_incident("retrieval", {"error_code": "timeout"})
        service.resolve("feedback", "feedback-resolve", "Quelle wurde korrigiert.")
        service.resolve("incident", "incident-resolve", "Dienst läuft wieder.")
        cases = service.open_cases()
        assert cases["feedback"] == []
        assert cases["incidents"] == []


def test_feedback_accepts_at_most_five_named_attachments():
    with tempfile.TemporaryDirectory() as directory:
        governance, _, _ = setup(Path(directory))
        service = QualityCaseService(governance.store, identifier=lambda: "feedback-files")
        service.report_rag(
            user_id="employee", reason="incorrect", comment="Siehe Dateien",
            question="Frage", answer="Antwort", sources=[], passages=[], rights=[],
            runtime={}, request_id="request-files",
        )
        for index in range(5):
            service.add_attachment(
                "feedback-files", "employee", attachment_id=f"file-{index}",
                original_filename=f"beleg-{index}.png", stored_filename=f"file-{index}.png",
                media_type="image/png", size_bytes=100,
            )
        assert len(service.attachments_of("feedback-files")) == 5
        try:
            service.add_attachment(
                "feedback-files", "employee", attachment_id="file-6",
                original_filename="zu-viel.png", stored_filename="file-6.png",
                media_type="image/png", size_bytes=100,
            )
        except Exception as exc:
            assert str(exc) == "feedback_attachment_limit_reached"
        else:
            raise AssertionError("sixth attachment must be rejected")

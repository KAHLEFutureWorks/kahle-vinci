import tempfile
from pathlib import Path

from app.mail_delivery import OutboxDispatcher
from app.maintenance import MaintenanceService
from test_document_lifecycle import setup


class FakeTransport:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.messages = []

    def send(self, message):
        if self.fail:
            raise RuntimeError("mail unavailable")
        self.messages.append(message)


def test_outbox_marks_success_and_deduplicates_notification():
    with tempfile.TemporaryDirectory() as directory:
        governance, _, _ = setup(Path(directory))
        service = MaintenanceService(governance.store)
        assert service.enqueue_notification(
            "admin@kahle.de", "system_error", "Fehler", "Vorgang 123", dedupe_key="case-123"
        )
        assert service.enqueue_notification(
            "admin@kahle.de", "system_error", "Fehler", "Vorgang 123", dedupe_key="case-123"
        ) is None
        transport = FakeTransport()
        assert OutboxDispatcher(service, transport).dispatch() == {"sent": 1, "failed": 0}
        assert service.pending_messages() == []


def test_outbox_keeps_failed_message_for_retry():
    with tempfile.TemporaryDirectory() as directory:
        governance, _, _ = setup(Path(directory))
        service = MaintenanceService(governance.store)
        service.enqueue_notification(
            "admin@kahle.de", "system_error", "Fehler", "Vorgang 456", dedupe_key="case-456"
        )
        assert OutboxDispatcher(service, FakeTransport(fail=True)).dispatch() == {"sent": 0, "failed": 1}
        assert len(service.pending_messages()) == 1

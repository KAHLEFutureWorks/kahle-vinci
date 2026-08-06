from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.maintenance_worker import BERLIN, expiry_digest_due, run_once


class Service:
    def __init__(self):
        self.calls = []

    def generate_expiry_digest(self):
        self.calls.append("digest")

    def process_pending_approvals(self):
        self.calls.append("approvals")

    def expire_due_versions(self):
        self.calls.append("expire")
        return []

    def process_trash(self, files_root):
        self.calls.append("trash")
        return {"deleted": []}

    def enforce_retention(self):
        self.calls.append("retention")


def test_expiry_digest_is_due_only_once_after_1030_on_a_berlin_workday():
    before = datetime(2026, 8, 6, 10, 29, tzinfo=BERLIN)
    due = datetime(2026, 8, 6, 10, 30, tzinfo=BERLIN)
    assert not expiry_digest_due(before, None)
    assert expiry_digest_due(due, None)
    assert not expiry_digest_due(due, date(2026, 8, 6))
    assert not expiry_digest_due(datetime(2026, 8, 8, 11, 0, tzinfo=BERLIN), None)


def test_expiry_schedule_uses_berlin_time_when_worker_receives_utc():
    utc = ZoneInfo("UTC")
    assert expiry_digest_due(datetime(2026, 8, 6, 8, 30, tzinfo=utc), None)


def test_regular_maintenance_continues_before_digest_time():
    service = Service()
    run_once(service, None, generate_expiry_digest=False)
    assert service.calls == ["approvals", "expire", "trash", "retention"]
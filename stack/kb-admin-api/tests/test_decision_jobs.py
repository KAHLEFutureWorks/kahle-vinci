from datetime import datetime, timedelta, timezone

from app.decision_jobs import DecisionJobQueue
from app.portal_governance import SQLiteGovernanceStore


def test_decisions_are_persisted_idempotently_and_claimed_strictly_one_at_a_time(tmp_path):
    clock = {"now": datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)}
    identifiers = iter(("job-1", "job-2"))
    queue = DecisionJobQueue(
        SQLiteGovernanceStore(tmp_path / "portal.sqlite3"),
        identifier=lambda: next(identifiers), now=lambda: clock["now"],
    )
    first = queue.enqueue("case-1", "manager-1", "approve", "")
    repeated = queue.enqueue("case-1", "manager-1", "approve", "")
    second = queue.enqueue("case-2", "manager-2", "approve", "")
    assert repeated["job_id"] == first["job_id"]
    assert second["position"] == 2
    assert [job["case_id"] for job in queue.list_active("manager-1")] == ["case-1"]
    assert {job["case_id"] for job in queue.list_active("admin", is_admin=True)} == {"case-1", "case-2"}

    claimed_first = queue.claim_next()
    assert claimed_first["job_id"] == first["job_id"]
    assert queue.claim_next() is None
    queue.complete(first["job_id"], {"case": {"status": "active"}})
    assert queue.list_active("manager-1") == []
    claimed_second = queue.claim_next()
    assert claimed_second["job_id"] == second["job_id"]


def test_expired_processing_lease_is_recovered_after_a_worker_crash(tmp_path):
    clock = {"now": datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)}
    queue = DecisionJobQueue(
        SQLiteGovernanceStore(tmp_path / "portal.sqlite3"),
        identifier=lambda: "job-1", now=lambda: clock["now"], lease_minutes=5,
    )
    queue.enqueue("case-1", "manager-1", "approve", "")
    assert queue.claim_next()["status"] == "processing"
    clock["now"] += timedelta(minutes=6)
    recovered = queue.claim_next()
    assert recovered["job_id"] == "job-1"
    assert recovered["status"] == "processing"

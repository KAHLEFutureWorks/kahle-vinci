from datetime import datetime, timedelta, timezone

from portal_governance import SQLiteGovernanceStore
from upload_jobs import UploadJobError, UploadJobService, UploadSpool


def test_upload_job_is_persistent_and_private(tmp_path):
    service = UploadJobService(
        SQLiteGovernanceStore(tmp_path / "portal.sqlite3"),
        now=lambda: "2026-08-06T10:00:00+02:00",
        identifier=lambda: "job-1",
    )
    job_id = service.create("uploader")
    service.progress(job_id, "conversion", 45)
    assert service.get(job_id, "uploader")["progress"] == 45
    try:
        service.get(job_id, "other")
        assert False, "other users must not see the job"
    except UploadJobError as exc:
        assert str(exc) == "upload_job_not_found"
    service.complete(job_id, {"case_id": "case-1"})
    assert service.get(job_id, "uploader")["result"] == {"case_id": "case-1"}


def test_upload_queue_persists_metadata_claims_globally_in_fifo_order_and_reports_positions(tmp_path):
    store = SQLiteGovernanceStore(tmp_path / "portal.sqlite3")
    instant = [datetime(2026, 8, 17, 14, 0, tzinfo=timezone.utc)]
    service = UploadJobService(store, now=lambda: instant[0])
    first = service.enqueue(
        job_id="job-1", user_id="uploader-1", original_filename="gross.pdf",
        title="Großes Handbuch", knowledgebase_ids=("kb-service",), valid_workdays=60,
        confidentiality="internal", owner_user_id="owner-1", security_review_requested=False,
        staged_path="job-1.upload", file_size_bytes=17_000_000,
    )
    instant[0] += timedelta(seconds=1)
    second = service.enqueue(
        job_id="job-2", user_id="uploader-2", original_filename="klein.pdf",
        title="Kleine Anleitung", knowledgebase_ids=("kb-dispo",), valid_workdays=30,
        confidentiality="internal", owner_user_id="uploader-2", security_review_requested=True,
        staged_path="job-2.upload", file_size_bytes=900_000,
    )

    reopened = UploadJobService(store, now=lambda: instant[0])
    assert reopened.get(first["job_id"], "uploader-1")["position"] == 1
    assert reopened.get(second["job_id"], "uploader-2")["position"] == 2
    assert reopened.get(first["job_id"], "uploader-1")["knowledgebase_ids"] == ["kb-service"]
    assert reopened.get(first["job_id"], "uploader-1")["title"] == "Großes Handbuch"
    assert reopened.claim_next()["job_id"] == "job-1"
    assert reopened.claim_next() is None


def test_upload_queue_expires_interrupted_job_and_continues_with_next(tmp_path):
    store = SQLiteGovernanceStore(tmp_path / "portal.sqlite3")
    instant = [datetime(2026, 8, 17, 14, 0, tzinfo=timezone.utc)]
    service = UploadJobService(store, now=lambda: instant[0], lease_minutes=15)
    for job_id in ("job-1", "job-2"):
        service.enqueue(
            job_id=job_id, user_id="uploader", original_filename=f"{job_id}.pdf",
            title=job_id, knowledgebase_ids=("kb",), valid_workdays=30,
            confidentiality="internal", owner_user_id="uploader", security_review_requested=False,
            staged_path=f"{job_id}.upload", file_size_bytes=100,
        )
        instant[0] += timedelta(seconds=1)
    assert service.claim_next()["job_id"] == "job-1"
    instant[0] += timedelta(minutes=16)

    expired = service.expire_interrupted()

    assert [item["job_id"] for item in expired] == ["job-1"]
    assert service.get("job-1", "uploader")["error_code"] == "upload_worker_interrupted"
    assert service.claim_next()["job_id"] == "job-2"


def test_recover_and_claim_marks_legacy_processing_job_without_lease_interrupted(tmp_path):
    store = SQLiteGovernanceStore(tmp_path / "portal.sqlite3")
    instant = datetime(2026, 8, 17, 15, 0, tzinfo=timezone.utc)
    service = UploadJobService(store, now=lambda: instant)
    legacy_id = service.create("legacy-uploader")
    service.progress(legacy_id, "conversion", 45)
    service.enqueue(
        job_id="next-job", user_id="uploader", original_filename="next.pdf",
        title="Nächster Auftrag", knowledgebase_ids=("kb",), valid_workdays=30,
        confidentiality="internal", owner_user_id="uploader", security_review_requested=False,
        staged_path="next-job.upload", file_size_bytes=100,
    )

    claimed, recovered = service.recover_and_claim_next()

    assert [item["job_id"] for item in recovered] == [legacy_id]
    assert service.get(legacy_id, "legacy-uploader")["error_code"] == "upload_worker_interrupted"
    assert claimed["job_id"] == "next-job"


def test_recover_and_claim_rechecks_a_lease_that_expires_after_worker_start(tmp_path):
    store = SQLiteGovernanceStore(tmp_path / "portal.sqlite3")
    instant = [datetime(2026, 8, 17, 15, 0, tzinfo=timezone.utc)]
    service = UploadJobService(store, now=lambda: instant[0], lease_minutes=15)
    for job_id in ("active-job", "waiting-job"):
        service.enqueue(
            job_id=job_id, user_id="uploader", original_filename=f"{job_id}.pdf",
            title=job_id, knowledgebase_ids=("kb",), valid_workdays=30,
            confidentiality="internal", owner_user_id="uploader", security_review_requested=False,
            staged_path=f"{job_id}.upload", file_size_bytes=100,
        )
        instant[0] += timedelta(seconds=1)
    assert service.claim_next()["job_id"] == "active-job"
    instant[0] += timedelta(minutes=16)

    claimed, recovered = service.recover_and_claim_next()

    assert [item["job_id"] for item in recovered] == ["active-job"]
    assert claimed["job_id"] == "waiting-job"


def test_upload_spool_uses_validated_job_ids_and_removes_terminal_payload(tmp_path):
    spool = UploadSpool(tmp_path / "spool")
    path = spool.stage("job-1", b"PDF data")
    assert path.name == "job-1.upload"
    assert spool.read("job-1") == b"PDF data"
    spool.remove("job-1")
    spool.remove("job-1")
    assert not path.exists()
    try:
        spool.stage("../escape", b"bad")
        assert False, "path traversal must be rejected"
    except UploadJobError as exc:
        assert str(exc) == "invalid_upload_job_id"


def test_upload_spool_creates_storage_only_when_a_payload_is_staged(tmp_path):
    root = tmp_path / "not-created-yet" / "spool"

    spool = UploadSpool(root)

    assert not root.exists()
    spool.stage("job-1", b"PDF data")
    assert root.is_dir()

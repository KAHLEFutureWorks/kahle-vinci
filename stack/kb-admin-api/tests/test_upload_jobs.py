from portal_governance import SQLiteGovernanceStore
from upload_jobs import UploadJobError, UploadJobService


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

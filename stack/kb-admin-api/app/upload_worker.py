from __future__ import annotations

import os
import time

from .main import drain_one_upload_job, recover_interrupted_upload_jobs


def run_forever(poll_seconds: float | None = None) -> None:
    interval = poll_seconds if poll_seconds is not None else float(
        os.getenv("KB_UPLOAD_WORKER_POLL_SECONDS", "2")
    )
    recover_interrupted_upload_jobs()
    while True:
        if drain_one_upload_job():
            continue
        time.sleep(max(0.1, interval))


if __name__ == "__main__":
    run_forever()

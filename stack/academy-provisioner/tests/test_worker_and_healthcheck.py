from __future__ import annotations

from app.healthcheck import health_status
from app.state import SQLiteProvisioningStateStore
from app.worker import run_forever


def test_healthcheck_rejects_stale_heartbeat(tmp_path) -> None:
    state = SQLiteProvisioningStateStore(tmp_path / "state.sqlite3")
    state.record_heartbeat(100)

    assert health_status(state, now_epoch=220, max_age_seconds=120) == 0
    assert health_status(state, now_epoch=221, max_age_seconds=120) == 1


def test_worker_records_heartbeat_after_successful_cycle() -> None:
    class Provisioner:
        def run_once(self):
            return {"completed": 1, "failed": 0, "skipped": 0}

    class State:
        def __init__(self) -> None:
            self.heartbeats: list[int] = []

        def record_heartbeat(self, value: int) -> None:
            self.heartbeats.append(value)

    state = State()
    sleep_calls: list[int] = []

    run_forever(
        Provisioner(), state, interval_seconds=60, now_epoch=lambda: 100,
        sleep=lambda seconds: sleep_calls.append(seconds), max_cycles=1,
    )

    assert state.heartbeats == [100]
    assert sleep_calls == []

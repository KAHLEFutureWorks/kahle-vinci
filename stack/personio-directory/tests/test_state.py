from app.state import SQLiteSyncState


def test_successful_sync_commit_updates_cursor_and_snapshot_atomically(tmp_path):
    state = SQLiteSyncState(tmp_path / "personio.sqlite3")

    with state.run("delta") as run:
        run.replace_indexed_people({"person-1": "2026-08-24T10:00:00Z"})
        run.mark_success("2026-08-24T10:05:00Z")

    assert state.last_successful_delta_at() == "2026-08-24T10:05:00Z"
    assert state.indexed_people() == {"person-1": "2026-08-24T10:00:00Z"}
    assert state.last_run_status() == "completed"


def test_failed_run_preserves_previous_cursor_and_snapshot(tmp_path):
    state = SQLiteSyncState(tmp_path / "personio.sqlite3")
    with state.run("full") as run:
        run.replace_indexed_people({"person-1": "2026-08-24T10:00:00Z"})
        run.mark_success("2026-08-24T10:05:00Z")

    try:
        with state.run("full") as run:
            run.replace_indexed_people({"person-2": "2026-08-24T11:00:00Z"})
            run.mark_success("2026-08-24T11:05:00Z")
            raise RuntimeError("upstream outage")
    except RuntimeError:
        pass

    assert state.last_successful_full_at() == "2026-08-24T10:05:00Z"
    assert state.indexed_people() == {"person-1": "2026-08-24T10:00:00Z"}
    assert state.last_run_status() == "failed"

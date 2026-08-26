from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field

import pytest

from app.sync import DirectorySync, SyncError
from app.state import SQLiteSyncState
from fixtures import MAPPING, raw_person
from app.policy import filter_person


@dataclass
class Client:
    people: list[dict[str, object]]
    mapping: dict[str, str] = field(default_factory=lambda: dict(MAPPING))
    updated_since: str | None = None

    def iter_people(self, updated_since: str | None = None):
        self.updated_since = updated_since
        yield from self.people


class FailingAfterOneClient(Client):
    def iter_people(self, updated_since: str | None = None):
        self.updated_since = updated_since
        yield raw_person("ACTIVE", "INTERNAL")
        raise RuntimeError("raw employee response must not leak")


class FakeIndex:
    def __init__(
        self,
        existing_ids: set[str] | None = None,
        *,
        fail_upsert: bool = False,
        fail_delete: bool = False,
        fail_compensation: bool = False,
    ):
        self.records = {personio_id: active_person(personio_id) for personio_id in existing_ids or set()}
        self.fail_upsert = fail_upsert
        self.fail_delete = fail_delete
        self.fail_compensation = fail_compensation
        self.upserted_ids: set[str] = set()
        self.deleted_ids: set[str] = set()
        self.delete_calls = 0

    def upsert(self, person):
        if self.fail_upsert:
            raise RuntimeError("qdrant body must not leak")
        self.upserted_ids.add(person.personio_id)
        self.records[person.personio_id] = person

    def upsert_many(self, people):
        for person in people:
            self.upsert(person)

    def delete_personio_ids(self, ids: set[str]):
        self.delete_calls += 1
        if self.fail_compensation:
            raise RuntimeError("rollback values must not leak")
        for personio_id in ids:
            self.records.pop(personio_id, None)
        self.deleted_ids.update(ids)
        if self.fail_delete and self.delete_calls == 1:
            raise RuntimeError("qdrant body must not leak")

    def indexed_personio_ids(self) -> set[str]:
        return set(self.records)

    def people_by_personio_ids(self, ids: set[str]):
        return {personio_id: self.records[personio_id] for personio_id in ids if personio_id in self.records}


class CommitFailState(SQLiteSyncState):
    @contextmanager
    def run(self, kind: str):
        with super().run(kind) as run:
            yield run
            raise RuntimeError("sqlite details must not leak")


def active_person(personio_id: str):
    raw = raw_person("ACTIVE", "INTERNAL") | {"id": personio_id}
    person = filter_person(raw, MAPPING)
    assert person is not None
    return person


def test_failed_delta_does_not_advance_success_cursor(tmp_path):
    state = SQLiteSyncState(tmp_path / "personio.sqlite3")
    sync = DirectorySync(FailingAfterOneClient([]), FakeIndex(), state, now=lambda: "2026-08-24T10:10:00Z")

    with pytest.raises(SyncError, match="personio_delta_failed") as error:
        sync.run_delta()

    assert "raw employee" not in str(error.value)
    assert state.last_successful_delta_at() is None
    assert state.indexed_people() == {}


def test_full_sync_deletes_people_missing_from_personio(tmp_path):
    state = SQLiteSyncState(tmp_path / "personio.sqlite3")
    index = FakeIndex(existing_ids={"person-1", "person-removed"})
    report = DirectorySync(Client([raw_person("ACTIVE", "INTERNAL")]), index, state).run_full()

    assert index.deleted_ids == {"person-removed"}
    assert report.upserted == 1
    assert report.deleted == 1
    assert state.indexed_people() == {"person-1": "2026-08-24T10:15:00Z"}


def test_full_sync_indexes_external_employee_without_employment_type_mapping(tmp_path):
    mapping = {
        key: value
        for key, value in MAPPING.items()
        if key not in {"first_name", "last_name", "employment_type"}
    } | {"display_name": "preferred_name"}
    external = raw_person("ACTIVE", "EXTERNAL") | {
        "preferred_name": "Jan Oltmanns",
        "first_name": "must not be used",
        "last_name": "must not be used",
    }
    index = FakeIndex()

    report = DirectorySync(
        Client([external], mapping=mapping),
        index,
        SQLiteSyncState(tmp_path / "personio.sqlite3"),
    ).run_full()

    assert report.upserted == 1
    assert index.records["person-1"].display_name == "Jan Oltmanns"
    assert index.records["person-1"].first_name == "Jan"
    assert index.records["person-1"].last_name == "Oltmanns"


def test_full_sync_reconciles_the_collection_even_when_state_snapshot_is_stale(tmp_path):
    state = SQLiteSyncState(tmp_path / "personio.sqlite3")
    with state.run("full") as run:
        run.replace_indexed_people({"person-1": "2026-08-24T10:00:00Z"})
        run.mark_success("2026-08-24T10:05:00Z")
    index = FakeIndex(existing_ids={"person-1", "person-removed"})

    DirectorySync(Client([raw_person("ACTIVE", "INTERNAL")]), index, state).run_full()

    assert index.deleted_ids == {"person-removed"}


def test_delta_uses_five_minute_overlap_and_skips_invalid_person_without_values(tmp_path):
    state = SQLiteSyncState(tmp_path / "personio.sqlite3")
    with state.run("delta") as run:
        run.mark_success("2026-08-24T10:10:00Z")
    client = Client([raw_person("ACTIVE", "INTERNAL"), raw_person("INACTIVE", "INTERNAL")])

    report = DirectorySync(client, FakeIndex(), state, now=lambda: "2026-08-24T10:15:00Z").run_delta()

    assert client.updated_since == "2026-08-24T10:05:00Z"
    assert report.upserted == 1
    assert report.invalid == 1
    assert report.error_codes == {"invalid_person": 1}
    assert state.last_successful_delta_at() == "2026-08-24T10:15:00Z"


def test_delta_physically_removes_a_previously_indexed_person_who_becomes_ineligible(tmp_path):
    state = SQLiteSyncState(tmp_path / "personio.sqlite3")
    with state.run("delta") as run:
        run.replace_indexed_people({"person-1": "2026-08-24T10:00:00Z"})
        run.mark_success("2026-08-24T10:00:00Z")
    removed = raw_person("INACTIVE", "INTERNAL")
    index = FakeIndex(existing_ids={"person-1"})

    report = DirectorySync(Client([removed]), index, state).run_delta()

    assert index.deleted_ids == {"person-1"}
    assert report.deleted == 1
    assert state.indexed_people() == {}


@pytest.mark.parametrize("preferred_name", [None, "", 123, "Madonna", "Jan 123"])
def test_delta_physically_removes_existing_person_with_ineligible_preferred_name(
    tmp_path, preferred_name
):
    state = SQLiteSyncState(tmp_path / "personio.sqlite3")
    with state.run("delta") as run:
        run.replace_indexed_people({"person-1": "2026-08-24T10:00:00Z"})
        run.mark_success("2026-08-24T10:00:00Z")
    raw = raw_person("ACTIVE", "INTERNAL")
    if preferred_name is None:
        raw.pop("preferred_name")
    else:
        raw["preferred_name"] = preferred_name
    index = FakeIndex(existing_ids={"person-1"})

    report = DirectorySync(Client([raw]), index, state).run_delta()

    assert index.deleted_ids == {"person-1"}
    assert report.deleted == 1
    assert state.indexed_people() == {}


def test_full_sync_is_due_initially_then_after_24_hours(tmp_path):
    state = SQLiteSyncState(tmp_path / "personio.sqlite3")
    sync = DirectorySync(Client([]), FakeIndex(), state)

    assert sync.full_sync_due("2026-08-24T10:00:00Z") is True
    with state.run("full") as run:
        run.mark_success("2026-08-23T10:00:01Z")
    assert sync.full_sync_due("2026-08-24T10:00:00Z") is False
    assert sync.full_sync_due("2026-08-24T10:00:01Z") is True


def test_full_sync_keeps_existing_person_seen_with_transient_non_name_malformed_data(tmp_path):
    state = SQLiteSyncState(tmp_path / "personio.sqlite3")
    index = FakeIndex(existing_ids={"person-1"})
    malformed = raw_person("ACTIVE", "INTERNAL") | {"position": ""}

    report = DirectorySync(Client([malformed]), index, state).run_full()

    assert report.invalid == 1
    assert index.indexed_personio_ids() == {"person-1"}
    assert state.indexed_people() == {"person-1": "2026-08-24T10:15:00Z"}


@pytest.mark.parametrize("preferred_name", [None, "", 123, "Madonna", "Jan 123"])
def test_full_sync_deletes_existing_person_with_ineligible_preferred_name(
    tmp_path, preferred_name
):
    state = SQLiteSyncState(tmp_path / "personio.sqlite3")
    index = FakeIndex(existing_ids={"person-1"})
    raw = raw_person("ACTIVE", "INTERNAL")
    if preferred_name is None:
        raw.pop("preferred_name")
    else:
        raw["preferred_name"] = preferred_name

    report = DirectorySync(Client([raw]), index, state).run_full()

    assert report.invalid == 1
    assert report.deleted == 1
    assert index.indexed_personio_ids() == set()
    assert state.indexed_people() == {}


@pytest.mark.parametrize("failure", ["upsert", "delete"])
def test_failed_index_mutation_restores_records_and_preserves_delta_progress(tmp_path, failure):
    state = SQLiteSyncState(tmp_path / "personio.sqlite3")
    with state.run("delta") as run:
        run.replace_indexed_people({"person-1": "2026-08-24T10:00:00Z"})
        run.mark_success("2026-08-24T10:00:00Z")
    index = FakeIndex(existing_ids={"person-1"}, **{f"fail_{failure}": True})
    people = [raw_person("ACTIVE", "INTERNAL") | {"id": "person-2"}]
    if failure == "delete":
        people.append(raw_person("INACTIVE", "INTERNAL"))

    with pytest.raises(SyncError, match="personio_delta_failed") as error:
        DirectorySync(Client(people), index, state).run_delta()

    assert "qdrant body" not in str(error.value)
    assert index.indexed_personio_ids() == {"person-1"}
    assert state.last_successful_delta_at() == "2026-08-24T10:00:00Z"
    assert state.indexed_people() == {"person-1": "2026-08-24T10:00:00Z"}


def test_state_commit_failure_compensates_index_and_preserves_progress(tmp_path):
    state = CommitFailState(tmp_path / "personio.sqlite3")
    with SQLiteSyncState.run(state, "delta") as run:
        run.replace_indexed_people({"person-1": "2026-08-24T10:00:00Z"})
        run.mark_success("2026-08-24T10:00:00Z")
    index = FakeIndex(existing_ids={"person-1"})

    with pytest.raises(SyncError, match="personio_delta_failed") as error:
        DirectorySync(Client([raw_person("ACTIVE", "INTERNAL") | {"id": "person-2"}]), index, state).run_delta()

    assert "sqlite details" not in str(error.value)
    assert index.indexed_personio_ids() == {"person-1"}
    assert state.last_successful_delta_at() == "2026-08-24T10:00:00Z"
    assert state.indexed_people() == {"person-1": "2026-08-24T10:00:00Z"}


def test_compensation_failure_reports_sanitized_consistency_error(tmp_path):
    state = CommitFailState(tmp_path / "personio.sqlite3")
    index = FakeIndex(fail_compensation=True)

    with pytest.raises(SyncError, match="personio_index_consistency_unrecoverable") as error:
        DirectorySync(Client([raw_person("ACTIVE", "INTERNAL")]), index, state).run_delta()

    assert "rollback values" not in str(error.value)
    assert state.last_successful_delta_at() is None

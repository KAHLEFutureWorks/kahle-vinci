from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .models import PersonRecord
from .policy import filter_person
from .state import SQLiteSyncState


class SyncError(RuntimeError):
    """Sanitized sync failure code; raw Personio responses must never escape."""


@dataclass(frozen=True)
class SyncReport:
    upserted: int
    deleted: int
    invalid: int
    error_codes: dict[str, int]


class DirectorySync:
    def __init__(
        self,
        client: Any,
        index: Any,
        state: SQLiteSyncState,
        *,
        now: Callable[[], str] | None = None,
    ) -> None:
        self._client = client
        self._index = index
        self._state = state
        self._now = now or _utc_now

    def run_delta(self) -> SyncReport:
        cursor = self._state.last_successful_delta_at()
        updated_since = _subtract_overlap(cursor) if cursor else None
        try:
            people, invalid, explicitly_removed, _ = self._eligible_people(
                self._client.iter_people(updated_since)
            )
            snapshot = (self._state.indexed_people() | {
                person.personio_id: person.source_updated_at for person in people
            })
            for personio_id in explicitly_removed:
                snapshot.pop(personio_id, None)
            self._apply_atomically("delta", people, explicitly_removed, snapshot)
        except SyncError:
            raise
        except Exception as error:
            raise SyncError("personio_delta_failed") from error
        return SyncReport(
            len(people), len(explicitly_removed), invalid,
            {"invalid_person": invalid} if invalid else {},
        )

    def run_full(self) -> SyncReport:
        try:
            people, invalid, explicitly_removed, seen_ids = self._eligible_people(
                self._client.iter_people()
            )
            desired = {person.personio_id: person.source_updated_at for person in people}
            existing = set(self._index.indexed_personio_ids())
            valid_ids = set(desired)
            malformed_ids = seen_ids - valid_ids - explicitly_removed
            removed = (existing - seen_ids) | explicitly_removed
            retained = self._index.people_by_personio_ids(malformed_ids & existing)
            desired.update({
                personio_id: person.source_updated_at
                for personio_id, person in retained.items()
            })
            self._apply_atomically("full", people, removed, desired)
        except SyncError:
            raise
        except Exception as error:
            raise SyncError("personio_full_failed") from error
        return SyncReport(len(people), len(removed), invalid, {"invalid_person": invalid} if invalid else {})

    def full_sync_due(self, now: str) -> bool:
        last_full = self._state.last_successful_full_at()
        if last_full is None:
            return True
        return _parse_time(now) - _parse_time(last_full) >= timedelta(hours=24)

    def _eligible_people(
        self, raw_people: Iterable[Mapping[str, object]]
    ) -> tuple[list[PersonRecord], int, set[str], set[str]]:
        mapping = getattr(self._client, "mapping", None)
        if not isinstance(mapping, Mapping):
            assessment = self._client.assess_api()
            mapping = assessment.mapping
        people: list[PersonRecord] = []
        invalid = 0
        explicitly_removed: set[str] = set()
        seen_ids: set[str] = set()
        for raw in raw_people:
            personio_id = raw.get(mapping["personio_id"])
            if isinstance(personio_id, str) and personio_id:
                seen_ids.add(personio_id)
            person = filter_person(raw, mapping)
            if person is None:
                invalid += 1
                if (
                    isinstance(personio_id, str)
                    and personio_id
                    and _is_explicitly_ineligible(raw, mapping)
                ):
                    explicitly_removed.add(personio_id)
                continue
            people.append(person)
        return people, invalid, explicitly_removed, seen_ids

    def _apply_atomically(
        self,
        kind: str,
        people: list[PersonRecord],
        deleted_ids: set[str],
        snapshot: dict[str, str],
    ) -> None:
        affected_ids = {person.personio_id for person in people} | deleted_ids
        prior_records = self._index.people_by_personio_ids(affected_ids)
        try:
            self._upsert(people)
            self._index.delete_personio_ids(deleted_ids)
            with self._state.run(kind) as run:
                run.replace_indexed_people(snapshot)
                run.mark_success(self._now())
        except Exception as error:
            try:
                self._restore_index(affected_ids, prior_records)
            except Exception as rollback_error:
                raise SyncError("personio_index_consistency_unrecoverable") from rollback_error
            raise SyncError(f"personio_{kind}_failed") from error

    def _restore_index(
        self, affected_ids: set[str], prior_records: Mapping[str, PersonRecord]
    ) -> None:
        if affected_ids:
            self._index.delete_personio_ids(affected_ids)
        self._upsert(list(prior_records.values()))

    def _upsert(self, people: list[PersonRecord]) -> None:
        upsert_many = getattr(self._index, "upsert_many", None)
        if callable(upsert_many):
            upsert_many(people)
            return
        for person in people:
            self._index.upsert(person)


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc)


def _subtract_overlap(value: str) -> str:
    return (_parse_time(value) - timedelta(minutes=5)).isoformat(timespec="seconds").replace("+00:00", "Z")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _is_explicitly_ineligible(raw: Mapping[str, object], mapping: Mapping[str, str]) -> bool:
    status = raw.get(mapping["employment_status"])
    employment_type = raw.get(mapping["employment_type"])
    return status not in {"ACTIVE", "LEAVE", "ONBOARDING"} or employment_type != "INTERNAL"

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol

from .learningsuite import ProvisioningError
from .models import EligibleUser


class UserReader(Protocol):
    def eligible_users(self) -> list[EligibleUser]: ...

    def invalid_user_ids(self) -> list[str]: ...


class LearningSuiteClient(Protocol):
    def resolve_course_id(self, course_name: str) -> str: ...

    def find_or_create_member(self, user: EligibleUser) -> str: ...

    def has_course_access(self, member_id: str, course_id: str) -> bool: ...

    def grant_course_access(self, member_id: str, course_id: str) -> None: ...


class ProvisioningState(Protocol):
    def record_completed(self, user_id: str, member_id: str, *, now_epoch: int) -> None: ...

    def record_failure(self, user_id: str, error_code: str, *, now_epoch: int) -> None: ...


class AcademyProvisioner:
    def __init__(
        self,
        reader: UserReader,
        client: LearningSuiteClient,
        state: ProvisioningState,
        course_name: str,
        *,
        now_epoch: Callable[[], float] = time.time,
    ) -> None:
        self.reader = reader
        self.client = client
        self.state = state
        self.course_name = course_name
        self.now_epoch = now_epoch

    def run_once(self) -> dict[str, int]:
        result = {"completed": 0, "failed": 0, "skipped": 0}
        users = self.reader.eligible_users()
        for user_id in self.reader.invalid_user_ids():
            self.state.record_failure(user_id, "invalid_name", now_epoch=self._now())
            result["failed"] += 1

        if not users:
            return result

        course_id = self.client.resolve_course_id(self.course_name)
        for user in users:
            try:
                member_id = self.client.find_or_create_member(user)
                if not self.client.has_course_access(member_id, course_id):
                    self.client.grant_course_access(member_id, course_id)
                self.state.record_completed(user.openwebui_id, member_id, now_epoch=self._now())
                result["completed"] += 1
            except ProvisioningError as exc:
                self.state.record_failure(user.openwebui_id, exc.code, now_epoch=self._now())
                result["failed"] += 1
        return result

    def _now(self) -> int:
        return int(self.now_epoch())

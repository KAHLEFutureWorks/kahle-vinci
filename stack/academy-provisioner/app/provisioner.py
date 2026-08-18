from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol

from .learningsuite import ProvisioningError
from .models import EligibleUser, InvalidUser


MAX_NEW_USERS_PER_CYCLE = 20


class UserReader(Protocol):
    def eligible_users(self) -> list[EligibleUser]: ...

    def invalid_users(self) -> list[InvalidUser]: ...


class LearningSuiteClient(Protocol):
    def resolve_course_id(self, course_name: str) -> str: ...

    def find_or_create_member(self, user: EligibleUser) -> str: ...

    def has_course_access(self, member_id: str, course_id: str) -> bool: ...

    def grant_course_access(self, member_id: str, course_id: str) -> None: ...


class WelcomeMailer(Protocol):
    def send_welcome(self, user: EligibleUser) -> None: ...


class ProvisioningState(Protocol):
    def was_completed(self, user_id: str) -> bool: ...

    def last_error(self, user_id: str) -> str | None: ...

    def record_completed(self, user_id: str, member_id: str, *, now_epoch: int) -> None: ...

    def record_failure(self, user_id: str, error_code: str, *, now_epoch: int) -> None: ...

    def welcome_was_sent(self, email: str) -> bool: ...

    def record_welcome_sent(self, email: str, *, now_epoch: int) -> None: ...


class AcademyProvisioner:
    def __init__(
        self,
        reader: UserReader,
        client: LearningSuiteClient,
        state: ProvisioningState,
        course_name: str,
        *,
        allowed_emails: frozenset[str] | None,
        welcome_mailer: WelcomeMailer | None = None,
        now_epoch: Callable[[], float] = time.time,
    ) -> None:
        self.reader = reader
        self.client = client
        self.state = state
        self.course_name = course_name
        self.allowed_emails = allowed_emails
        self.welcome_mailer = welcome_mailer
        self.now_epoch = now_epoch

    def run_once(self) -> dict[str, int]:
        result = {"completed": 0, "failed": 0, "skipped": 0}
        users = self.reader.eligible_users()
        invalid_users = self.reader.invalid_users()
        if self.allowed_emails is not None:
            allowed_invalid_users = [
                user for user in invalid_users if user.email in self.allowed_emails
            ]
            result["skipped"] += len(invalid_users) - len(allowed_invalid_users)
            invalid_users = allowed_invalid_users
        for user in invalid_users:
            self.state.record_failure(user.openwebui_id, user.error_code, now_epoch=self._now())
            result["failed"] += 1

        if self.allowed_emails is not None:
            allowed_users = [user for user in users if user.email in self.allowed_emails]
            result["skipped"] += len(users) - len(allowed_users)
            users = allowed_users

        pending_users = [user for user in users if not self.state.was_completed(user.openwebui_id)]
        pending_users.sort(
            key=lambda user: (self.state.last_error(user.openwebui_id) is not None, user.openwebui_id)
        )
        result["skipped"] += len(users) - len(pending_users)
        users_to_provision = pending_users[:MAX_NEW_USERS_PER_CYCLE]
        result["skipped"] += len(pending_users) - len(users_to_provision)
        if not users_to_provision:
            return result

        course_id = self.client.resolve_course_id(self.course_name)
        for user in users_to_provision:
            try:
                if self.welcome_mailer and not self.state.welcome_was_sent(user.email):
                    self.welcome_mailer.send_welcome(user)
                    self.state.record_welcome_sent(user.email, now_epoch=self._now())
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

from __future__ import annotations

import pytest

from app.learningsuite import ProvisioningError
from app.models import EligibleUser, InvalidUser
from app.provisioner import AcademyProvisioner


class FakeReader:
    def __init__(self, users: list[EligibleUser], invalid_users: list[InvalidUser] | None = None) -> None:
        self.users = users
        self.invalid_users_list = invalid_users or []

    def eligible_users(self) -> list[EligibleUser]:
        return self.users

    def invalid_users(self) -> list[InvalidUser]:
        return self.invalid_users_list


class FakeState:
    def __init__(self) -> None:
        self.completed: list[tuple[str, str]] = []
        self.failures: list[tuple[str, str]] = []
        self.welcome_sent: set[str] = set()

    def was_completed(self, user_id: str) -> bool:
        return any(completed_user_id == user_id for completed_user_id, _ in self.completed)

    def last_error(self, user_id: str) -> str | None:
        for failed_user_id, error_code in reversed(self.failures):
            if failed_user_id == user_id:
                return error_code
        return None

    def record_completed(self, user_id: str, member_id: str, *, now_epoch: int) -> None:
        self.completed.append((user_id, member_id))

    def record_failure(self, user_id: str, error_code: str, *, now_epoch: int) -> None:
        self.failures.append((user_id, error_code))

    def welcome_was_sent(self, email: str) -> bool:
        return email in self.welcome_sent

    def record_welcome_sent(self, email: str, *, now_epoch: int) -> None:
        self.welcome_sent.add(email)


class FakeClient:
    def __init__(self, *, has_access: bool = False) -> None:
        self.has_access = has_access
        self.grants: list[tuple[str, str]] = []
        self.created: list[str] = []

    def resolve_course_id(self, _: str) -> str:
        return "course-1"

    def find_or_create_member(self, user: EligibleUser) -> str:
        self.created.append(user.openwebui_id)
        return f"member-{user.openwebui_id}"

    def has_course_access(self, _: str, __: str) -> bool:
        return self.has_access

    def grant_course_access(self, member_id: str, course_id: str) -> None:
        self.grants.append((member_id, course_id))


class FakeWelcomeMailer:
    def __init__(self) -> None:
        self.sent: list[EligibleUser] = []

    def send_welcome(self, user: EligibleUser) -> None:
        self.sent.append(user)


def test_first_role_release_sends_one_welcome_before_academy_provisioning() -> None:
    user = EligibleUser("user-1", "reschke@kahle.de", "Ralf", "Reschke", "user")
    client = FakeClient()
    state = FakeState()
    mailer = FakeWelcomeMailer()
    provisioner = AcademyProvisioner(
        FakeReader([user]),
        client,
        state,
        "Einführung in die KAHLE-Vinci Nutzung",
        allowed_emails=frozenset({"reschke@kahle.de"}),
        welcome_mailer=mailer,
        now_epoch=lambda: 100,
    )

    first = provisioner.run_once()
    second = provisioner.run_once()

    assert first == {"completed": 1, "failed": 0, "skipped": 0}
    assert second == {"completed": 0, "failed": 0, "skipped": 1}
    assert mailer.sent == [user]
    assert state.welcome_sent == {"reschke@kahle.de"}
    assert client.created == ["user-1"]


def test_failed_welcome_mail_blocks_academy_email_and_retries_later() -> None:
    class FailingWelcomeMailer(FakeWelcomeMailer):
        def send_welcome(self, user: EligibleUser) -> None:
            raise ProvisioningError("welcome_mail_failed")

    user = EligibleUser("user-1", "reschke@kahle.de", "Ralf", "Reschke", "user")
    client = FakeClient()
    state = FakeState()

    result = AcademyProvisioner(
        FakeReader([user]),
        client,
        state,
        "Einführung in die KAHLE-Vinci Nutzung",
        allowed_emails=frozenset({"reschke@kahle.de"}),
        welcome_mailer=FailingWelcomeMailer(),
        now_epoch=lambda: 100,
    ).run_once()

    assert result == {"completed": 0, "failed": 1, "skipped": 0}
    assert state.failures == [("user-1", "welcome_mail_failed")]
    assert state.welcome_sent == set()
    assert client.created == []
    assert client.grants == []


def test_existing_course_access_never_sends_another_course_email() -> None:
    user = EligibleUser("user-1", "amal@kahle.de", "Amal", "Remo", "user")
    client = FakeClient(has_access=True)
    state = FakeState()

    result = AcademyProvisioner(
        FakeReader([user]), client, state, "Einführung in die KAHLE-Vinci Nutzung",
        allowed_emails=None, now_epoch=lambda: 100
    ).run_once()

    assert result == {"completed": 1, "failed": 0, "skipped": 0}
    assert client.grants == []
    assert state.completed == [("user-1", "member-user-1")]


def test_failure_for_one_user_does_not_block_next_user() -> None:
    class FailingFirstClient(FakeClient):
        def find_or_create_member(self, user: EligibleUser) -> str:
            if user.openwebui_id == "user-1":
                raise ProvisioningError("member_create_failed")
            return super().find_or_create_member(user)

    users = [
        EligibleUser("user-1", "a@kahle.de", "A", "One", "user"),
        EligibleUser("user-2", "b@kahle.de", "B", "Two", "admin"),
    ]
    client = FailingFirstClient()
    state = FakeState()

    result = AcademyProvisioner(
        FakeReader(users), client, state, "Einführung in die KAHLE-Vinci Nutzung",
        allowed_emails=None, now_epoch=lambda: 100
    ).run_once()

    assert result == {"completed": 1, "failed": 1, "skipped": 0}
    assert state.failures == [("user-1", "member_create_failed")]
    assert state.completed == [("user-2", "member-user-2")]
    assert client.grants == [("member-user-2", "course-1")]


def test_invalid_openwebui_identity_is_recorded_without_calling_learningsuite() -> None:
    client = FakeClient()
    state = FakeState()

    result = AcademyProvisioner(
        FakeReader([], [InvalidUser("user-1", "invalid", "invalid_email")]),
        client,
        state,
        "Einführung in die KAHLE-Vinci Nutzung",
        allowed_emails=None,
        now_epoch=lambda: 100,
    ).run_once()

    assert result == {"completed": 0, "failed": 1, "skipped": 0}
    assert state.failures == [("user-1", "invalid_email")]
    assert client.created == []


def test_completed_user_is_skipped_without_any_learningsuite_request() -> None:
    user = EligibleUser("user-1", "amal@kahle.de", "Amal", "Remo", "user")
    client = FakeClient()
    state = FakeState()
    state.record_completed("user-1", "member-user-1", now_epoch=90)

    result = AcademyProvisioner(
        FakeReader([user]), client, state, "Einführung in die KAHLE-Vinci Nutzung",
        allowed_emails=None, now_epoch=lambda: 100
    ).run_once()

    assert result == {"completed": 0, "failed": 0, "skipped": 1}
    assert client.created == []
    assert client.grants == []


def test_new_users_are_bounded_to_a_rate_safe_batch() -> None:
    users = [
        EligibleUser(f"user-{number}", f"user-{number}@kahle.de", "Test", str(number), "user")
        for number in range(21)
    ]
    client = FakeClient()
    state = FakeState()

    result = AcademyProvisioner(
        FakeReader(users), client, state, "Einführung in die KAHLE-Vinci Nutzung",
        allowed_emails=None, now_epoch=lambda: 100
    ).run_once()

    assert result == {"completed": 20, "failed": 0, "skipped": 1}
    assert len(client.created) == 20


def test_transport_failure_for_one_user_does_not_block_next_user() -> None:
    class TransportFailingClient(FakeClient):
        def find_or_create_member(self, user: EligibleUser) -> str:
            if user.openwebui_id == "user-1":
                raise ProvisioningError("learningsuite_request_failed")
            return super().find_or_create_member(user)

    users = [
        EligibleUser("user-1", "a@kahle.de", "A", "One", "user"),
        EligibleUser("user-2", "b@kahle.de", "B", "Two", "user"),
    ]
    client = TransportFailingClient()
    state = FakeState()

    result = AcademyProvisioner(
        FakeReader(users), client, state, "Einführung in die KAHLE-Vinci Nutzung",
        allowed_emails=None, now_epoch=lambda: 100
    ).run_once()

    assert result == {"completed": 1, "failed": 1, "skipped": 0}
    assert state.failures == [("user-1", "learningsuite_request_failed")]
    assert state.completed == [("user-2", "member-user-2")]


def test_new_user_is_not_starved_by_a_full_batch_of_retries() -> None:
    class AlwaysFailingClient(FakeClient):
        def find_or_create_member(self, user: EligibleUser) -> str:
            if user.openwebui_id != "user-21":
                raise ProvisioningError("member_create_failed")
            return super().find_or_create_member(user)

    users = [
        EligibleUser(f"user-{number:02}", f"user-{number}@kahle.de", "Test", str(number), "user")
        for number in range(1, 22)
    ]
    client = AlwaysFailingClient()
    state = FakeState()
    provisioner = AcademyProvisioner(
        FakeReader(users), client, state, "Einführung in die KAHLE-Vinci Nutzung",
        allowed_emails=None, now_epoch=lambda: 100
    )

    provisioner.run_once()
    result = provisioner.run_once()

    assert result["completed"] == 1
    assert ("user-21", "member-user-21") in state.completed


def test_allowlist_processes_only_matching_email() -> None:
    users = [
        EligibleUser("user-1", "janssen@kahle.de", "Jan", "Janssen", "user"),
        EligibleUser("user-2", "another.user@kahle.de", "Another", "User", "admin"),
    ]
    client = FakeClient()
    state = FakeState()

    result = AcademyProvisioner(
        FakeReader(users),
        client,
        state,
        "Einführung in die KAHLE-Vinci Nutzung",
        allowed_emails=frozenset({"janssen@kahle.de"}),
        now_epoch=lambda: 100,
    ).run_once()

    assert result == {"completed": 1, "failed": 0, "skipped": 1}
    assert client.created == ["user-1"]


def test_allowlist_skips_invalid_identity_outside_rollout_scope() -> None:
    client = FakeClient()
    state = FakeState()

    result = AcademyProvisioner(
        FakeReader([], [InvalidUser("user-2", "another.user@kahle.de", "invalid_name")]),
        client,
        state,
        "Einführung in die KAHLE-Vinci Nutzung",
        allowed_emails=frozenset({"janssen@kahle.de"}),
        now_epoch=lambda: 100,
    ).run_once()

    assert result == {"completed": 0, "failed": 0, "skipped": 1}
    assert state.failures == []
    assert client.created == []


def test_allowlist_decision_is_required_for_every_provisioner() -> None:
    with pytest.raises(TypeError):
        AcademyProvisioner(
            FakeReader([]),
            FakeClient(),
            FakeState(),
            "Einführung in die KAHLE-Vinci Nutzung",
        )

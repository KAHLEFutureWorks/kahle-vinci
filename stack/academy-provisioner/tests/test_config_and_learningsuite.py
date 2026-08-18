from __future__ import annotations

from unittest.mock import Mock

import pytest
import requests

from app.config import ConfigError, ProvisioningConfig
from app.learningsuite import ProvisioningError, RequestsLearningSuiteClient
from app.models import EligibleUser


class Response:
    def __init__(self, status_code: int, payload: object):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


def test_config_rejects_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEARNINGSUITE_API_KEY", raising=False)

    with pytest.raises(ConfigError, match="learningsuite_api_key_required"):
        ProvisioningConfig.from_env()


def test_resolve_course_id_rejects_duplicate_exact_title() -> None:
    session = Mock()
    session.get.return_value = Response(
        200,
        [
            {"id": "course-1", "name": "Einführung in die KAHLE-Vinci Nutzung"},
            {"id": "course-2", "name": "Einführung in die KAHLE-Vinci Nutzung"},
        ],
    )
    client = RequestsLearningSuiteClient("https://api.test/api/v1", "secret", session)

    with pytest.raises(ProvisioningError, match="course_name_ambiguous"):
        client.resolve_course_id("Einführung in die KAHLE-Vinci Nutzung")


def test_new_member_receives_only_course_access_email() -> None:
    session = Mock()
    session.get.side_effect = [
        Response(404, {"error": "not found"}),
        Response(200, []),
    ]
    session.post.return_value = Response(200, {"id": "member-1"})
    session.put.return_value = Response(200, {"ok": True})
    client = RequestsLearningSuiteClient("https://api.test/api/v1", "secret", session)

    member_id = client.find_or_create_member(
        EligibleUser("user-1", "amal@kahle.de", "Amal", "Remo", "user")
    )
    client.grant_course_access(member_id, "course-1")

    assert member_id == "member-1"
    assert session.post.call_args.kwargs["json"] == {
        "email": "amal@kahle.de",
        "firstName": "Amal",
        "lastName": "Remo",
        "ignoreIfAlreadyExists": True,
        "disableLoginEmail": True,
        "locale": "de",
    }
    assert session.put.call_args.kwargs["json"] == {
        "courseIds": ["course-1"],
        "disableAccessNotificationEmail": False,
        "sendLoginLinkInCourseEmail": True,
    }


def test_transport_errors_are_exposed_as_sanitized_provisioning_errors() -> None:
    session = Mock()
    session.get.side_effect = requests.Timeout("connection timed out")
    client = RequestsLearningSuiteClient("https://api.test/api/v1", "secret", session)

    with pytest.raises(ProvisioningError, match="learningsuite_request_failed"):
        client.find_or_create_member(
            EligibleUser("user-1", "amal@kahle.de", "Amal", "Remo", "user")
        )

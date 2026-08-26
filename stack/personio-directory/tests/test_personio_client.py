from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.config import PersonioConfig
from app.personio import PersonioClient, PersonioError


@dataclass
class Call:
    method: str
    url: str
    kwargs: dict[str, object]


class Response:
    def __init__(self, status_code: int, payload: object, headers: dict[str, str] | None = None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.content = b"{}"

    def json(self) -> object:
        return self._payload


class FakeSession:
    def __init__(self, responses: list[Response]):
        self.responses = list(responses)
        self.calls: list[Call] = []

    def request(self, method: str, url: str, **kwargs: object) -> Response:
        self.calls.append(Call(method, url, kwargs))
        if not self.responses:
            raise AssertionError(f"unexpected request: {method} {url}")
        return self.responses.pop(0)


@pytest.fixture
def config() -> PersonioConfig:
    return PersonioConfig(client_id="client", client_secret="secret")


def v1_attributes() -> Response:
    return Response(200, {"data": [
        {"key": "id", "label": "ID"},
        {"key": "preferred_name", "label": "Name (preferred)"},
        {"key": "position", "label": "Position"},
        {"key": "department", "label": "Abteilung"},
        {"key": "team", "label": "Team"},
        {"key": "office", "label": "Standort"},
        {"key": "email", "label": "Geschäftliche E-Mail"},
        {"key": "phone", "label": "Geschäftliche Telefonnummer"},
        {"key": "status", "label": "Beschäftigungsstatus"},
        {"key": "updated_at", "label": "Letzte Änderung"},
    ]})


def test_assessment_falls_back_to_v1_when_v2_team_is_not_resolved(config):
    session = FakeSession([
        Response(200, {"access_token": "v2-token", "expires_in": 3600}),
        Response(200, {"data": [{"id": "person-1", "first_name": "Only", "last_name": "Test"}]}),
        Response(200, {"data": []}),
        Response(200, {"data": {"token": "v1-token", "expires_in": 3600}}),
        v1_attributes(),
    ])
    client = PersonioClient(config, session=session, sleep=lambda _: None, random_value=lambda: 0)

    assessment = client.assess_api()

    assert assessment.version == "v1"
    assert assessment.mapping["business_email"] == "email"
    assert "v2_team_unresolved" in assessment.reason_codes
    assert all(
        call.method.lower() == "get"
        or call.url in {config.v1_token_url, config.v2_token_url}
        for call in session.calls
    )
    assert not any(call.method.lower() in {"patch", "put", "delete"} for call in session.calls)


def test_assessment_prefers_v2_when_all_required_fields_are_useful(config):
    session = FakeSession([
        Response(200, {"access_token": "v2-token", "expires_in": 3600}),
        Response(200, {"data": [{
            "id": "person-1",
            "preferred_name": "Only Test",
            "email": "only.test@example.invalid",
            "updated_at": "2026-08-24T10:15:00Z",
            "employments": [{
                "status": "ACTIVE",
                "employment_type": "EXTERNAL",
                "position": {"name": "Beratung"},
                "department": {"name": "Service"},
                "team": {"name": "Nord"},
                "office": {"name": "Hannover"},
                "business_phone": "+49 1",
            }],
        }]}),
    ])
    client = PersonioClient(config, session=session, sleep=lambda _: None, random_value=lambda: 0)

    assessment = client.assess_api()

    assert assessment.version == "v2"
    assert set(assessment.mapping) >= {
        "personio_id", "display_name", "employment_status", "position",
        "department", "team", "office", "business_email", "business_phone",
        "source_updated_at",
    }
    assert {"first_name", "last_name", "employment_type"}.isdisjoint(assessment.mapping)
    assert assessment.reason_codes == ()


def test_v1_assessment_requires_preferred_name_but_not_split_names_or_employment_type(config):
    session = FakeSession([
        Response(200, {"access_token": "v2-token", "expires_in": 3600}),
        Response(200, {"data": []}),
        Response(200, {"data": {"token": "v1-token", "expires_in": 3600}}),
        v1_attributes(),
    ])
    client = PersonioClient(config, session=session, sleep=lambda _: None, random_value=lambda: 0)

    assessment = client.assess_api()

    assert assessment.version == "v1"
    assert assessment.mapping["display_name"] == "preferred_name"
    assert {"first_name", "last_name", "employment_type"}.isdisjoint(assessment.mapping)


def test_v1_assessment_still_requires_last_modified_for_delta_sync(config):
    attributes_without_last_modified = v1_attributes()._payload
    attributes_without_last_modified = {
        "data": [
            attribute
            for attribute in attributes_without_last_modified["data"]
            if attribute["key"] != "updated_at"
        ]
    }
    session = FakeSession([
        Response(200, {"access_token": "v2-token", "expires_in": 3600}),
        Response(200, {"data": []}),
        Response(200, {"data": {"token": "v1-token", "expires_in": 3600}}),
        Response(200, attributes_without_last_modified),
    ])
    client = PersonioClient(config, session=session, sleep=lambda _: None, random_value=lambda: 0)

    with pytest.raises(PersonioError, match="personio_required_fields_unresolved"):
        client.assess_api()


def test_v1_assessment_maps_actual_last_modified_at_key_and_label(config):
    live_shape_attributes = v1_attributes()._payload
    live_shape_attributes = {
        "data": [
            (
                {"key": "last_modified_at", "label": "Last modified at"}
                if attribute["key"] == "updated_at"
                else attribute
            )
            for attribute in live_shape_attributes["data"]
        ]
    }
    session = FakeSession([
        Response(200, {"access_token": "v2-token", "expires_in": 3600}),
        Response(200, {"data": []}),
        Response(200, {"data": {"token": "v1-token", "expires_in": 3600}}),
        Response(200, live_shape_attributes),
    ])
    client = PersonioClient(config, session=session, sleep=lambda _: None, random_value=lambda: 0)

    assessment = client.assess_api()

    assert assessment.version == "v1"
    assert assessment.mapping["source_updated_at"] == "last_modified_at"


def test_v1_assessment_maps_exact_business_phone_unicode_label(config):
    attributes_with_live_phone_label = v1_attributes()._payload
    attributes_with_live_phone_label = {
        "data": [
            (
                {
                    "key": "custom_business_phone",
                    "label": "Telefonnummer geschäftlich",
                }
                if attribute["key"] == "phone"
                else attribute
            )
            for attribute in attributes_with_live_phone_label["data"]
        ]
    }
    session = FakeSession([
        Response(200, {"access_token": "v2-token", "expires_in": 3600}),
        Response(200, {"data": []}),
        Response(200, {"data": {"token": "v1-token", "expires_in": 3600}}),
        Response(200, attributes_with_live_phone_label),
    ])
    client = PersonioClient(config, session=session, sleep=lambda _: None, random_value=lambda: 0)

    assessment = client.assess_api()

    assert assessment.version == "v1"
    assert assessment.mapping["business_phone"] == "custom_business_phone"


def test_v1_iter_people_uses_bounded_offset_pagination_and_updated_since(config):
    session = FakeSession([
        Response(200, {"data": {"token": "v1-token", "expires_in": 3600}}),
        Response(200, {"data": [{"id": {"value": f"person-{number}"}} for number in range(100)]}),
        Response(200, {"data": []}),
    ])
    client = PersonioClient(config, session=session, sleep=lambda _: None, random_value=lambda: 0)
    client._assessment = type("Assessment", (), {"version": "v1", "mapping": {}})()

    people = list(client.iter_people(updated_since="2026-08-24T00:00:00Z"))

    assert len(people) == 100
    assert people[0] == {"id": "person-0"}
    calls = [call for call in session.calls if call.url.endswith("/v1/company/employees")]
    assert [call.kwargs["params"] for call in calls] == [
        {"limit": 100, "offset": 0, "updated_since": "2026-08-24T00:00:00Z"},
        {"limit": 100, "offset": 100, "updated_since": "2026-08-24T00:00:00Z"},
    ]


def test_v2_iter_people_follows_cursor_links(config):
    session = FakeSession([
        Response(200, {"access_token": "v2-token", "expires_in": 3600}),
        Response(200, {"data": [{"id": "person-1", "employments": []}], "links": {"next": "https://api.personio.de/v2/persons?cursor=next"}}),
        Response(200, {"data": [{"id": "person-2", "employments": []}], "links": {"next": None}}),
    ])
    client = PersonioClient(config, session=session, sleep=lambda _: None, random_value=lambda: 0)
    client._assessment = type("Assessment", (), {"version": "v2", "mapping": {}})()

    people = list(client.iter_people())

    assert [person["id"] for person in people] == ["person-1", "person-2"]
    calls = [call for call in session.calls if "/v2/persons" in call.url]
    assert calls[0].kwargs["params"] == {"limit": 50}
    assert calls[1].url.endswith("cursor=next")


def test_v2_iter_people_accepts_documented_envelope_and_nested_cursor_shapes(config):
    session = FakeSession([
        Response(200, {"access_token": "v2-token", "expires_in": 3600}),
        Response(200, {
            "_data": [{"id": "synthetic-person-1", "employments": []}],
            "_meta": {"links": {"next": {
                "href": "https://api.personio.de/v2/persons?cursor=page-2",
            }}},
        }),
        Response(200, {
            "_data": [{"id": "synthetic-person-2", "employments": []}],
            "_meta": {"links": {
                "next": "https://api.personio.de/v2/persons?cursor=page-3",
            }},
        }),
        Response(200, {
            "_data": [{"id": "synthetic-person-3", "employments": []}],
            "_meta": {"links": {"next": None}},
        }),
    ])
    client = PersonioClient(config, session=session, sleep=lambda _: None, random_value=lambda: 0)
    client._assessment = type("Assessment", (), {"version": "v2", "mapping": {}})()

    people = list(client.iter_people())

    assert [person["id"] for person in people] == [
        "synthetic-person-1",
        "synthetic-person-2",
        "synthetic-person-3",
    ]
    calls = [call for call in session.calls if "/v2/persons" in call.url]
    assert calls[1].url.endswith("cursor=page-2")
    assert calls[2].url.endswith("cursor=page-3")


def test_v2_documented_nested_cursor_keeps_host_validation(config):
    session = FakeSession([
        Response(200, {"access_token": "v2-token", "expires_in": 3600}),
        Response(200, {
            "_data": [{"id": "synthetic-person-1", "employments": []}],
            "_meta": {"links": {"next": {
                "href": "https://invalid.example/v2/persons?cursor=unsafe",
            }}},
        }),
    ])
    client = PersonioClient(config, session=session, sleep=lambda _: None, random_value=lambda: 0)
    client._assessment = type("Assessment", (), {"version": "v2", "mapping": {}})()

    with pytest.raises(PersonioError, match="personio_cursor_invalid"):
        list(client.iter_people())


def test_v2_documented_nested_cursor_rejects_invalid_href_shape(config):
    session = FakeSession([
        Response(200, {"access_token": "v2-token", "expires_in": 3600}),
        Response(200, {
            "_data": [],
            "_meta": {"links": {"next": {"href": ["not-a-string"]}}},
        }),
    ])
    client = PersonioClient(config, session=session, sleep=lambda _: None, random_value=lambda: 0)
    client._assessment = type("Assessment", (), {"version": "v2", "mapping": {}})()

    with pytest.raises(PersonioError, match="personio_response_invalid"):
        list(client.iter_people())


@pytest.mark.parametrize("invalid_cursor", ["", " \t "])
def test_v2_legacy_cursor_rejects_blank_strings(config, invalid_cursor):
    session = FakeSession([
        Response(200, {"access_token": "v2-token", "expires_in": 3600}),
        Response(200, {
            "data": [{"id": "synthetic-person-1", "employments": []}],
            "links": {"next": invalid_cursor},
        }),
    ])
    client = PersonioClient(config, session=session, sleep=lambda _: None, random_value=lambda: 0)
    client._assessment = type("Assessment", (), {"version": "v2", "mapping": {}})()

    with pytest.raises(PersonioError, match="personio_response_invalid"):
        list(client.iter_people())


@pytest.mark.parametrize("invalid_cursor", ["", " \t "])
def test_v2_documented_nested_cursor_rejects_blank_href(config, invalid_cursor):
    session = FakeSession([
        Response(200, {"access_token": "v2-token", "expires_in": 3600}),
        Response(200, {
            "_data": [{"id": "synthetic-person-1", "employments": []}],
            "_meta": {"links": {"next": {"href": invalid_cursor}}},
        }),
    ])
    client = PersonioClient(config, session=session, sleep=lambda _: None, random_value=lambda: 0)
    client._assessment = type("Assessment", (), {"version": "v2", "mapping": {}})()

    with pytest.raises(PersonioError, match="personio_response_invalid"):
        list(client.iter_people())


def test_v2_assessment_resolves_separate_employment_records(config):
    session = FakeSession([
        Response(200, {"access_token": "v2-token", "expires_in": 3600}),
        Response(200, {"data": [{
            "id": "person-1", "preferred_name": "Only Test",
            "email": "only.test@example.invalid",
            "updated_at": "2026-08-24T10:15:00Z",
        }]}),
        Response(200, {"data": [{
            "status": "ACTIVE", "employment_type": "INTERNAL",
            "position": {"name": "Beratung"}, "department": {"name": "Service"},
            "team": {"name": "Nord"}, "office": {"name": "Hannover"},
            "business_phone": "+49 1",
        }]}),
    ])
    client = PersonioClient(config, session=session, sleep=lambda _: None, random_value=lambda: 0)

    assert client.assess_api().version == "v2"
    assert any("/v2/persons/person-1/employments" in call.url for call in session.calls)


def test_v2_assessment_accepts_documented_employment_envelope(config):
    session = FakeSession([
        Response(200, {"access_token": "v2-token", "expires_in": 3600}),
        Response(200, {
            "_data": [{
                "id": "synthetic-person-1",
                "preferred_name": "Synthetic Person",
                "email": "directory@example.invalid",
                "updated_at": "2026-08-24T10:15:00Z",
            }],
            "_meta": {"links": {"next": None}},
        }),
        Response(200, {"_data": [{
            "status": "ACTIVE",
            "employment_type": "INTERNAL",
            "position": {"name": "Beratung"},
            "department": {"name": "Service"},
            "team": {"name": "Nord"},
            "office": {"name": "Hannover"},
            "business_phone": "+49 555 000001",
        }]}),
    ])
    client = PersonioClient(config, session=session, sleep=lambda _: None, random_value=lambda: 0)

    assessment = client.assess_api()

    assert assessment.version == "v2"
    assert assessment.reason_codes == ()


def test_incomplete_documented_v2_envelope_falls_back_to_v1(config):
    session = FakeSession([
        Response(200, {"access_token": "v2-token", "expires_in": 3600}),
        Response(200, {
            "_data": [{
                "id": "synthetic-person-1",
                "email": "directory@example.invalid",
            }],
            "_meta": {"links": {"next": None}},
        }),
        Response(200, {"_data": [{
            "status": "ACTIVE",
            "employment_type": "INTERNAL",
            "position": {"name": "Beratung"},
            "department": {"name": "Service"},
            "office": {"name": "Hannover"},
        }]}),
        Response(200, {"data": {"token": "v1-token", "expires_in": 3600}}),
        v1_attributes(),
    ])
    client = PersonioClient(config, session=session, sleep=lambda _: None, random_value=lambda: 0)

    assessment = client.assess_api()

    assert assessment.version == "v1"
    assert "v2_team_unresolved" in assessment.reason_codes
    assert "directory@example.invalid" not in assessment.field_labels


def test_client_raises_sanitized_code_for_invalid_response_shape(config):
    session = FakeSession([
        Response(200, {"access_token": "v2-token", "expires_in": 3600}),
        Response(200, {"data": "not-a-list"}),
    ])
    client = PersonioClient(config, session=session, sleep=lambda _: None, random_value=lambda: 0)

    with pytest.raises(PersonioError, match="personio_response_invalid") as error:
        client.assess_api()

    assert "not-a-list" not in str(error.value)


def test_client_honors_retry_after_without_leaking_response_body(config):
    delays: list[float] = []
    session = FakeSession([
        Response(429, {"detail": "not for logs"}, {"Retry-After": "2"}),
        Response(200, {"data": {"token": "v1-token", "expires_in": 3600}}),
    ])
    client = PersonioClient(config, session=session, sleep=delays.append, random_value=lambda: 0)

    assert client._token("v1") == "v1-token"
    assert delays == [2.0]


def test_client_honors_long_valid_retry_after_without_an_arbitrary_cap(config):
    delays: list[float] = []
    session = FakeSession([
        Response(429, {"detail": "not for logs"}, {"Retry-After": "120"}),
        Response(200, {"data": {"token": "v1-token", "expires_in": 3600}}),
    ])
    client = PersonioClient(config, session=session, sleep=delays.append, random_value=lambda: 0.9)

    assert client._token("v1") == "v1-token"
    assert delays == [120.0]


def test_client_uses_bounded_backoff_and_jitter_for_invalid_retry_after(config):
    delays: list[float] = []
    session = FakeSession([
        Response(429, {"detail": "not for logs"}, {"Retry-After": "tomorrow"}),
        Response(200, {"data": {"token": "v1-token", "expires_in": 3600}}),
    ])
    client = PersonioClient(config, session=session, sleep=delays.append, random_value=lambda: 0.5)

    assert client._token("v1") == "v1-token"
    assert delays == [0.75]


def test_v1_auth_uses_body_credentials_and_documented_24h_lifetime(config):
    now = [100.0]
    session = FakeSession([
        Response(200, {"data": {"token": "v1-stable-token"}}),
        Response(200, {"data": {"token": "v1-refreshed-token"}}),
    ])
    client = PersonioClient(
        config,
        session=session,
        clock=lambda: now[0],
        sleep=lambda _: None,
        random_value=lambda: 0,
    )

    assert client._token("v1") == "v1-stable-token"
    auth_call = session.calls[0]
    assert auth_call.url == "https://api.personio.de/v1/auth"
    assert auth_call.kwargs["data"] == {
        "client_id": "client",
        "client_secret": "secret",
    }
    assert "params" not in auth_call.kwargs

    now[0] = 100.0 + 86400 - 301
    assert client._token("v1") == "v1-stable-token"
    now[0] = 100.0 + 86400 - 300
    assert client._token("v1") == "v1-refreshed-token"


def test_v1_auth_nested_expiry_controls_cache_and_top_level_does_not_override(config):
    now = [100.0]
    session = FakeSession([
        Response(200, {
            "data": {"token": "v1-first-token", "expires_in": 600},
            "expires_in": 86400,
        }),
        Response(200, {
            "data": {"token": "v1-second-token", "expires_in": 600},
        }),
    ])
    client = PersonioClient(
        config,
        session=session,
        clock=lambda: now[0],
        sleep=lambda _: None,
    )

    assert client._token("v1") == "v1-first-token"
    now[0] = 399.0
    assert client._token("v1") == "v1-first-token"
    now[0] = 400.0
    assert client._token("v1") == "v1-second-token"


def test_v1_auth_ignores_top_level_expiry_when_nested_expiry_is_absent(config):
    now = [100.0]
    session = FakeSession([
        Response(200, {
            "data": {"token": "v1-stable-token"},
            "expires_in": 1,
        }),
    ])
    client = PersonioClient(
        config,
        session=session,
        clock=lambda: now[0],
        sleep=lambda _: None,
    )

    assert client._token("v1") == "v1-stable-token"
    now[0] = 1000.0
    assert client._token("v1") == "v1-stable-token"
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    "invalid_expiry",
    [True, False, 0, -1, float("nan"), float("inf"), "3600", None],
)
def test_v1_auth_rejects_malformed_nested_expiry(config, invalid_expiry):
    response_marker = "SYNTHETIC_V1_TOKEN_DO_NOT_LEAK"
    session = FakeSession([
        Response(200, {"data": {
            "token": response_marker,
            "expires_in": invalid_expiry,
        }}),
    ])
    client = PersonioClient(config, session=session, sleep=lambda _: None)

    with pytest.raises(PersonioError, match="personio_auth_response_invalid") as error:
        client._token("v1")

    assert response_marker not in str(error.value)


def test_v1_auth_rejects_v2_envelope_without_leaking_secret(config):
    secret_marker = "SYNTHETIC_SECRET_DO_NOT_LEAK"
    client_config = PersonioConfig(
        client_id="synthetic-client",
        client_secret=secret_marker,
    )
    session = FakeSession([
        Response(200, {"access_token": secret_marker, "expires_in": 3600}),
    ])
    client = PersonioClient(client_config, session=session, sleep=lambda _: None)

    with pytest.raises(PersonioError, match="personio_auth_response_invalid") as error:
        client._token("v1")

    assert secret_marker not in str(error.value)
    assert secret_marker not in session.calls[0].url
    assert "params" not in session.calls[0].kwargs


def test_v2_auth_rejects_v1_envelope_and_keeps_form_body(config):
    response_marker = "SYNTHETIC_RESPONSE_TOKEN_DO_NOT_LEAK"
    session = FakeSession([
        Response(200, {"data": {"token": response_marker, "expires_in": 3600}}),
    ])
    client = PersonioClient(config, session=session, sleep=lambda _: None)

    with pytest.raises(PersonioError, match="personio_auth_response_invalid") as error:
        client._token("v2")

    assert response_marker not in str(error.value)
    auth_call = session.calls[0]
    assert auth_call.url == "https://api.personio.de/v2/auth/token"
    assert auth_call.kwargs["data"] == {
        "client_id": "client",
        "client_secret": "secret",
        "grant_type": "client_credentials",
        "scope": "personio:persons:read",
    }
    assert "params" not in auth_call.kwargs


def test_token_is_reused_until_five_minutes_before_expiry(config):
    now = [100.0]
    session = FakeSession([
        Response(200, {"data": {"token": "first-token", "expires_in": 600}}),
        Response(200, {"data": {"token": "second-token", "expires_in": 600}}),
    ])
    client = PersonioClient(
        config,
        session=session,
        clock=lambda: now[0],
        sleep=lambda _: None,
        random_value=lambda: 0,
    )

    assert client._token("v1") == "first-token"
    now[0] = 299.0
    assert client._token("v1") == "first-token"
    now[0] = 400.0
    assert client._token("v1") == "second-token"


def test_short_lived_valid_token_is_accepted_but_never_reused(config):
    session = FakeSession([
        Response(200, {"data": {"token": "short-one", "expires_in": 60}}),
        Response(200, {"data": {"token": "short-two", "expires_in": 60}}),
    ])
    client = PersonioClient(config, session=session, sleep=lambda _: None, random_value=lambda: 0)

    assert client._token("v1") == "short-one"
    assert client._token("v1") == "short-two"
    assert len(session.calls) == 2


def test_v2_assessment_uses_a_bounded_representative_sample_and_safe_labels(config):
    session = FakeSession([
        Response(200, {"access_token": "v2-token", "expires_in": 3600}),
        Response(200, {"data": [
            {
                "id": "person-1", "preferred_name": "One Test",
                "email": "one@example.invalid",
                "updated_at": "2026-08-24T10:15:00Z",
                "attributes": [{"key": "work_phone", "label": "Dienstliche Telefonnummer", "value": "hidden"}],
                "employments": [{
                    "status": "ACTIVE", "employment_type": "INTERNAL",
                    "position": {"name": "Beratung"}, "department": {"name": "Service"},
                    "office": {"name": "Hannover"}, "business_phone": "+49 1",
                }],
            },
            {
                "id": "person-2", "preferred_name": "Two Test",
                "email": "two@example.invalid",
                "updated_at": "2026-08-24T10:15:00Z",
                "employments": [{
                    "status": "ACTIVE", "employment_type": "INTERNAL",
                    "position": {"name": "Beratung"}, "department": {"name": "Service"},
                    "team": {"name": "Nord"}, "office": {"name": "Hannover"},
                    "business_phone": "+49 2",
                }],
            },
        ]}),
    ])
    client = PersonioClient(config, session=session, sleep=lambda _: None, random_value=lambda: 0)

    assessment = client.assess_api()

    assert assessment.version == "v2"
    assert "Dienstliche Telefonnummer" in assessment.field_labels
    assert "one@example.invalid" not in assessment.field_labels


def test_client_rejects_oversized_response_before_parsing(config):
    response = Response(200, {"data": {"token": "v1-token", "expires_in": 3600}})
    response.content = b"x" * (config.max_response_bytes + 1)
    client = PersonioClient(config, session=FakeSession([response]), sleep=lambda _: None)

    with pytest.raises(PersonioError, match="personio_response_too_large"):
        client._token("v1")

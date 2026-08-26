from __future__ import annotations

import math
import random
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote, urlparse

import requests

from .config import PersonioConfig


class PersonioError(RuntimeError):
    """Safe, code-only error for the read-only Personio boundary."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ApiAssessment:
    version: str
    mapping: dict[str, str]
    field_labels: tuple[str, ...]
    reason_codes: tuple[str, ...] = ()


_CANONICAL_FIELDS = (
    "personio_id",
    "display_name",
    "position",
    "department",
    "team",
    "office",
    "business_email",
    "business_phone",
    "employment_status",
    "source_updated_at",
)
_V2_REQUIRED_FIELDS = (
    "personio_id",
    "display_name",
    "employment_status",
    "position",
    "department",
    "team",
    "office",
    "business_email",
    "business_phone",
    "source_updated_at",
)
_V2_SAMPLE_LIMIT = 10
_V1_TOKEN_LIFETIME_SECONDS = 24 * 60 * 60
_SENSITIVE_MARKERS = (
    "absence",
    "bank",
    "birth",
    "compensation",
    "contract",
    "health",
    "personal",
    "performance",
    "private",
    "review",
    "salary",
    "sick",
    "tax",
)
_V1_ALIASES: dict[str, tuple[str, ...]] = {
    "display_name": ("name (preferred)",),
    "position": ("position", "job title", "job_position", "rolle"),
    "department": ("department", "abteilung", "bereich"),
    "team": ("team",),
    "office": ("office", "standort", "location", "workplace"),
    "business_email": ("email", "email address", "e-mail", "geschäftliche e-mail", "dienstliche e-mail"),
    "business_phone": (
        "phone",
        "telephone",
        "telefon",
        "geschäftliche telefonnummer",
        "telefonnummer geschäftlich",
        "dienstliche telefonnummer",
    ),
    "employment_status": ("status", "employment status", "beschäftigungsstatus"),
    "source_updated_at": (
        "updated_at",
        "updated at",
        "last_modified_at",
        "last modified at",
        "last modified",
        "letzte änderung",
    ),
    "supervisor_personio_id": ("supervisor", "vorgesetzte", "vorgesetzter"),
}


class PersonioClient:
    """Personio API adapter with an intentionally read-only public surface."""

    def __init__(
        self,
        config: PersonioConfig,
        session: requests.Session | Any | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        self.config = config
        self.session = session or requests.Session()
        self._sleep = sleep
        self._clock = clock
        self._wall_clock = wall_clock
        self._random_value = random_value
        self._tokens: dict[str, tuple[str, float]] = {}
        self._assessment: ApiAssessment | None = None
        self._discovered_attributes: dict[str, str] | None = None

    def discover_attributes(self) -> dict[str, str]:
        """Return v1 API attribute keys and their safe labels, without values."""
        if self._discovered_attributes is not None:
            return dict(self._discovered_attributes)
        response = self._get("/v1/company/employees/attributes", version="v1")
        payload = self._json_object(response)
        attributes = payload.get("data")
        if not isinstance(attributes, list):
            raise PersonioError("personio_response_invalid")
        discovered: dict[str, str] = {}
        for attribute in attributes:
            if not isinstance(attribute, Mapping):
                continue
            key = _clean_text(attribute.get("key") or attribute.get("id"))
            label = _clean_text(attribute.get("label") or attribute.get("name"))
            if key and label and not _is_sensitive_source(key, label):
                discovered[key] = label
        self._discovered_attributes = discovered
        return dict(discovered)

    def assess_api(self) -> ApiAssessment:
        """Select v2 only when all necessary directory fields have useful values."""
        if self._assessment is not None:
            return self._assessment

        try:
            assessment = self._assess_v2()
        except PersonioError as error:
            if error.code == "personio_response_invalid":
                raise
            assessment = None
            v2_reasons = ("v2_unavailable",)
        else:
            v2_reasons = assessment.reason_codes
            if not assessment.reason_codes:
                self._assessment = assessment
                return assessment

        attributes = self.discover_attributes()
        mapping = self._v1_mapping(attributes)
        missing = tuple(
            f"v1_{field}_unresolved" for field in _CANONICAL_FIELDS if field not in mapping
        )
        if missing:
            raise PersonioError("personio_required_fields_unresolved")
        self._assessment = ApiAssessment(
            version="v1",
            mapping=mapping,
            field_labels=tuple(sorted(attributes.values())),
            reason_codes=tuple(sorted(set(v2_reasons + missing))),
        )
        return self._assessment

    def iter_people(self, updated_since: str | None = None) -> Iterator[dict[str, object]]:
        assessment = self.assess_api()
        if assessment.version == "v2":
            yield from self._iter_v2_people(updated_since)
            return
        yield from self._iter_v1_people(updated_since)

    def _assess_v2(self) -> ApiAssessment:
        response = self._get("/v2/persons", version="v2", params={"limit": 50})
        people, _ = self._v2_page(response)
        sample_people = [
            self._with_v2_employments(person)
            for person in people[:_V2_SAMPLE_LIMIT]
        ]
        samples = [_flatten_v2_person(person) for person in sample_people]
        available_sources = _v2_available_sources(sample_people)
        mapping = {
            "personio_id": "id",
            "display_name": "preferred_name",
            "position": "position",
            "department": "department",
            "team": "team",
            "office": "office",
            "business_email": "email",
            "business_phone": "business_phone",
            "employment_status": "employment_status",
            "source_updated_at": "updated_at",
        }
        if "supervisor" in available_sources:
            mapping["supervisor_personio_id"] = "supervisor"
        reasons = tuple(
            f"v2_{field}_unresolved"
            for field in _V2_REQUIRED_FIELDS
            if mapping[field] not in available_sources
            or not any(_clean_text(sample.get(mapping[field])) for sample in samples)
        )
        return ApiAssessment(
            version="v2",
            mapping=mapping,
            field_labels=_v2_field_labels(sample_people, available_sources),
            reason_codes=reasons,
        )

    def _iter_v1_people(self, updated_since: str | None) -> Iterator[dict[str, object]]:
        supervisor_source = self.assess_api().mapping.get("supervisor_personio_id", "")
        offset = 0
        while True:
            params: dict[str, object] = {"limit": 100, "offset": offset}
            if updated_since:
                params["updated_since"] = updated_since
            response = self._get("/v1/company/employees", version="v1", params=params)
            payload = self._json_object(response)
            people = payload.get("data")
            if not isinstance(people, list):
                raise PersonioError("personio_response_invalid")
            for person in people:
                if not isinstance(person, Mapping):
                    continue
                flattened = _flatten_v1_person(
                    person, supervisor_source=supervisor_source
                )
                if flattened is not None:
                    yield flattened
            if len(people) < 100:
                return
            offset += 100

    def _iter_v2_people(self, updated_since: str | None) -> Iterator[dict[str, object]]:
        url = f"{self.config.api_base_url}/v2/persons"
        params: dict[str, object] | None = {"limit": 50}
        if updated_since:
            params["updated_at.gt"] = updated_since
        while True:
            response = self._get_url(url, version="v2", params=params)
            people, next_url = self._v2_page(response)
            for person in people:
                yield _flatten_v2_person(self._with_v2_employments(person))
            if not next_url:
                return
            self._validate_v2_cursor(next_url)
            url, params = next_url, None

    def _v2_page(self, response: object) -> tuple[list[Mapping[str, object]], str | None]:
        payload = self._json_object(response)
        data = _v2_data(payload)
        if "_meta" in payload:
            metadata = payload.get("_meta")
            if not isinstance(metadata, Mapping):
                raise PersonioError("personio_response_invalid")
            links = metadata.get("links", {})
        else:
            links = payload.get("links", {})
        if not isinstance(links, Mapping):
            raise PersonioError("personio_response_invalid")
        next_link = links.get("next")
        if isinstance(next_link, Mapping):
            if "href" not in next_link:
                raise PersonioError("personio_response_invalid")
            next_url = next_link.get("href")
        else:
            next_url = next_link
        if next_url is not None and not isinstance(next_url, str):
            raise PersonioError("personio_response_invalid")
        if isinstance(next_url, str) and not next_url.strip():
            raise PersonioError("personio_response_invalid")
        return data, next_url

    def _with_v2_employments(self, person: Mapping[str, object]) -> Mapping[str, object]:
        """Resolve v2 employment data only when it was not included by Persons."""
        employments = person.get("employments")
        if isinstance(employments, list):
            return person
        person_id = _clean_text(person.get("id"))
        if not person_id:
            return person
        response = self._get(
            f"/v2/persons/{quote(person_id, safe='')}/employments",
            version="v2",
        )
        payload = self._json_object(response)
        return dict(person) | {"employments": _v2_data(payload)}

    def _v1_mapping(self, attributes: Mapping[str, str]) -> dict[str, str]:
        mapping = {"personio_id": "id"}
        for field, aliases in _V1_ALIASES.items():
            source = _find_alias(attributes, aliases)
            if source:
                mapping[field] = source
        return mapping

    def _get(self, path: str, *, version: str, params: Mapping[str, object] | None = None) -> object:
        return self._get_url(f"{self.config.api_base_url}{path}", version=version, params=params)

    def _get_url(self, url: str, *, version: str, params: Mapping[str, object] | None = None) -> object:
        token = self._token(version)
        headers = {"Authorization": self._bearer_header(token)}
        return self._request("get", url, headers=headers, params=params)

    @staticmethod
    def _bearer_header(token: str) -> str:
        return " ".join(("Bearer", token))

    def _token(self, version: str) -> str:
        cached = self._tokens.get(version)
        if cached and self._clock() < cached[1] - 300:
            return cached[0]
        token_url = self.config.v2_token_url if version == "v2" else self.config.v1_token_url
        data: dict[str, str] = {
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
        }
        if version == "v2":
            data["grant_type"] = "client_credentials"
            data["scope"] = "personio:persons:read"
        response = self._request("post", token_url, data=data)
        payload = self._json_object(response)
        if version == "v2":
            token = _clean_text(payload.get("access_token"))
            expires_in = payload.get("expires_in")
        else:
            token_data = payload.get("data")
            if not isinstance(token_data, Mapping):
                raise PersonioError("personio_auth_response_invalid")
            token = _clean_text(token_data.get("token"))
            expires_in = (
                token_data.get("expires_in")
                if "expires_in" in token_data
                else _V1_TOKEN_LIFETIME_SECONDS
            )
        if (
            not token
            or (version == "v1" and isinstance(expires_in, bool))
            or not isinstance(expires_in, (int, float))
            or not math.isfinite(float(expires_in))
            or expires_in <= 0
        ):
            raise PersonioError("personio_auth_response_invalid")
        if expires_in > 300:
            self._tokens[version] = (token, self._clock() + float(expires_in))
        return token

    def _request(self, method: str, url: str, **kwargs: object) -> object:
        for attempt in range(self.config.max_retries + 1):
            try:
                response = self.session.request(method, url, timeout=self.config.timeout_seconds, **kwargs)
            except requests.RequestException as error:
                if attempt >= self.config.max_retries:
                    raise PersonioError("personio_request_failed") from error
                self._backoff(attempt, None)
                continue
            status = int(getattr(response, "status_code", 0))
            if 200 <= status < 300:
                self._validate_response_size(response)
                return response
            if status == 429 or 500 <= status < 600:
                if attempt >= self.config.max_retries:
                    raise PersonioError("personio_retry_exhausted")
                self._backoff(attempt, getattr(response, "headers", None))
                continue
            raise PersonioError(f"personio_http_{status if status else 'invalid'}")
        raise PersonioError("personio_retry_exhausted")

    def _backoff(self, attempt: int, headers: object) -> None:
        retry_after = None
        if isinstance(headers, Mapping):
            value = headers.get("Retry-After")
            retry_after = self._retry_after_seconds(value)
        delay = retry_after if retry_after is not None else min(8.0, 0.5 * (2**attempt))
        if retry_after is None:
            delay += min(0.5, max(0.0, self._random_value()) * 0.5)
        self._sleep(delay)

    def _retry_after_seconds(self, value: object) -> float | None:
        if not isinstance(value, str):
            return None
        try:
            seconds = float(value)
        except ValueError:
            try:
                seconds = parsedate_to_datetime(value).timestamp() - self._wall_clock()
            except (TypeError, ValueError, IndexError, OverflowError):
                return None
        if not math.isfinite(seconds) or seconds < 0:
            return None
        return seconds

    def _validate_response_size(self, response: object) -> None:
        content = getattr(response, "content", b"")
        if isinstance(content, (bytes, bytearray)) and len(content) > self.config.max_response_bytes:
            raise PersonioError("personio_response_too_large")

    @staticmethod
    def _json_object(response: object) -> dict[str, object]:
        try:
            payload = response.json()  # type: ignore[union-attr]
        except (AttributeError, TypeError, ValueError) as error:
            raise PersonioError("personio_response_invalid") from error
        if not isinstance(payload, dict):
            raise PersonioError("personio_response_invalid")
        return payload

    def _validate_v2_cursor(self, next_url: str) -> None:
        parsed = urlparse(next_url)
        expected = urlparse(self.config.api_base_url)
        if (
            parsed.scheme != expected.scheme
            or parsed.netloc != expected.netloc
            or parsed.path != "/v2/persons"
        ):
            raise PersonioError("personio_cursor_invalid")


def _clean_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _v2_data(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
    data = payload.get("_data") if "_data" in payload else payload.get("data")
    if not isinstance(data, list) or not all(
        isinstance(item, Mapping) for item in data
    ):
        raise PersonioError("personio_response_invalid")
    return list(data)


def _is_sensitive_source(*values: str) -> bool:
    text = " ".join(values).casefold()
    return any(marker in text for marker in _SENSITIVE_MARKERS)


def _find_alias(attributes: Mapping[str, str], aliases: tuple[str, ...]) -> str:
    normalized_aliases = {_normalize(alias) for alias in aliases}
    for key, label in attributes.items():
        if _normalize(key) in normalized_aliases or _normalize(label) in normalized_aliases:
            return key
    return ""


def _normalize(value: str) -> str:
    return " ".join(value.casefold().replace("_", " ").replace("-", " ").split())


def _field_value(value: object) -> str:
    if isinstance(value, Mapping):
        for key in ("value", "name", "label", "title"):
            resolved = _clean_text(value.get(key))
            if resolved:
                return resolved
        attributes = value.get("attributes")
        if isinstance(attributes, Mapping):
            return _clean_text(attributes.get("name"))
        return ""
    return _clean_text(value)


def _flatten_v1_person(
    person: Mapping[str, object], *, supervisor_source: str = ""
) -> dict[str, object] | None:
    if "attributes" not in person:
        return {
            str(key): (
                _relationship_personio_id(value)
                if key == supervisor_source
                else _field_value(value)
            )
            for key, value in person.items()
        }

    attributes = person.get("attributes")
    if not isinstance(attributes, Mapping) or not attributes:
        return None
    flattened: dict[str, object] = {}
    for key, attribute in attributes.items():
        if (
            not isinstance(key, str)
            or not key.strip()
            or not isinstance(attribute, Mapping)
            or "value" not in attribute
        ):
            return None
        value = attribute.get("value")
        if key == supervisor_source:
            flattened[key] = _relationship_personio_id(value)
        elif key == "id" and isinstance(value, int) and not isinstance(value, bool):
            flattened[key] = str(value)
        else:
            flattened[key] = _field_value(value)
    return flattened


def _flatten_v2_person(person: Mapping[str, object]) -> dict[str, object]:
    employment: Mapping[str, object] = {}
    employments = person.get("employments")
    if isinstance(employments, list) and employments and isinstance(employments[0], Mapping):
        employment = employments[0]
    return {
        "id": _field_value(person.get("id")),
        "preferred_name": _field_value(
            person.get("preferred_name") or person.get("preferredName")
        ),
        "email": _field_value(person.get("email") or person.get("business_email")),
        "business_phone": _field_value(employment.get("business_phone") or person.get("business_phone")),
        "employment_status": _field_value(employment.get("status")),
        "position": _field_value(employment.get("position")),
        "department": _field_value(employment.get("department")),
        "team": _field_value(employment.get("team")),
        "office": _field_value(employment.get("office")),
        "supervisor": _relationship_personio_id(employment.get("supervisor")),
        "updated_at": _field_value(person.get("updated_at") or employment.get("updated_at")),
    }


def _relationship_personio_id(value: object) -> str:
    if isinstance(value, Mapping):
        candidate = value.get("id")
        attributes = value.get("attributes")
        if candidate is None and isinstance(attributes, Mapping):
            candidate = attributes.get("id")
        if isinstance(candidate, Mapping):
            candidate = candidate.get("value")
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            return str(candidate)
        if isinstance(candidate, str) and candidate.strip().isdigit():
            return candidate.strip()
    return ""


def _v2_available_sources(people: list[Mapping[str, object]]) -> set[str]:
    """Return safe v2 schema keys seen in a bounded assessment sample."""
    sources: set[str] = set()
    for person in people:
        if "id" in person:
            sources.add("id")
        if "preferred_name" in person or "preferredName" in person:
            sources.add("preferred_name")
        if "email" in person or "business_email" in person:
            sources.add("email")
        if "updated_at" in person:
            sources.add("updated_at")
        employments = person.get("employments")
        if not isinstance(employments, list):
            continue
        for employment in employments:
            if not isinstance(employment, Mapping):
                continue
            if "status" in employment:
                sources.add("employment_status")
            for field in ("position", "department", "team", "office", "business_phone", "supervisor"):
                if field in employment:
                    sources.add(field)
            if "business_phone" in person:
                sources.add("business_phone")
            if "updated_at" in employment:
                sources.add("updated_at")
    return sources


def _v2_field_labels(
    people: list[Mapping[str, object]], available_sources: set[str]
) -> tuple[str, ...]:
    """Expose schema names and metadata labels, never values from person records."""
    labels = {f"v2:{source}" for source in available_sources}
    for person in people:
        labels.update(_attribute_labels(person))
        employments = person.get("employments")
        if isinstance(employments, list):
            for employment in employments:
                if isinstance(employment, Mapping):
                    labels.update(_attribute_labels(employment))
    return tuple(sorted(labels))


def _attribute_labels(record: Mapping[str, object]) -> set[str]:
    labels: set[str] = set()
    for key in ("attributes", "custom_attributes"):
        attributes = record.get(key)
        if not isinstance(attributes, list):
            continue
        for attribute in attributes:
            if not isinstance(attribute, Mapping):
                continue
            source = _clean_text(attribute.get("key"))
            label = _clean_text(attribute.get("label") or attribute.get("name"))
            if source and _is_safe_metadata_label(source, label):
                labels.add(label)
    return labels


def _is_safe_metadata_label(source: str, label: str) -> bool:
    return (
        bool(label)
        and len(label) <= 80
        and "@" not in label
        and not _is_sensitive_source(source, label)
    )

from collections.abc import Mapping

from app.models import PersonRecord


_PERSON_FIELDS = frozenset(PersonRecord.__dataclass_fields__)
_DERIVED_PERSON_FIELDS = frozenset({"first_name", "last_name"})
_MAPPED_PERSON_FIELDS = _PERSON_FIELDS - _DERIVED_PERSON_FIELDS
_ALLOWED_STATUSES = frozenset({"ACTIVE", "LEAVE", "ONBOARDING"})
_REQUIRED_VALUE_FIELDS = frozenset(
    {"personio_id", "display_name", "employment_status", "source_updated_at"}
)
_OPTIONAL_VALUE_FIELDS = _MAPPED_PERSON_FIELDS - _REQUIRED_VALUE_FIELDS
_PERSONIO_ID_SOURCE = "id"
_SENSITIVE_SOURCE_MARKERS = (
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


def filter_person(
    raw: Mapping[str, object], mapping: Mapping[str, str]
) -> PersonRecord | None:
    """Return a canonical directory record only when its mapping is safe."""
    if set(mapping) != _MAPPED_PERSON_FIELDS or any(
        not isinstance(source, str) or not source.strip()
        for source in mapping.values()
    ):
        return None
    if mapping["personio_id"] != _PERSONIO_ID_SOURCE:
        return None
    if any(
        marker in source.casefold()
        for source in mapping.values()
        for marker in _SENSITIVE_SOURCE_MARKERS
    ):
        return None

    values = {field: raw.get(source) for field, source in mapping.items()}
    if any(
        not isinstance(values[field], str) or not values[field].strip()
        for field in _REQUIRED_VALUE_FIELDS
    ):
        return None
    for field in _OPTIONAL_VALUE_FIELDS:
        value = values[field]
        values[field] = value.strip() if isinstance(value, str) else ""
    for field in _REQUIRED_VALUE_FIELDS:
        values[field] = values[field].strip()

    status = values["employment_status"].upper()
    if status not in _ALLOWED_STATUSES:
        return None
    values["employment_status"] = status

    preferred_name = preferred_name_parts(values["display_name"])
    if preferred_name is None:
        return None
    display_name, first_name, last_name = preferred_name
    values["display_name"] = display_name
    values["first_name"] = first_name
    values["last_name"] = last_name
    values["business_email"] = _kahle_business_email(values["business_email"])

    return PersonRecord(**values)  # type: ignore[arg-type]


def preferred_name_parts(value: object) -> tuple[str, str, str] | None:
    """Normalize and split the sole supported human-name source."""
    if not isinstance(value, str):
        return None
    display_name = " ".join(value.split())
    parts = display_name.split(" ")
    if len(parts) < 2 or any(not _valid_name_part(part) for part in parts):
        return None
    return display_name, " ".join(parts[:-1]), parts[-1]


def _valid_name_part(part: str) -> bool:
    allowed_punctuation = frozenset({"-", "'", "’", "."})
    return any(char.isalpha() for char in part) and all(
        char.isalpha() or char in allowed_punctuation for char in part
    )


def _kahle_business_email(value: object) -> str:
    if not isinstance(value, str):
        return ""
    candidate = value.strip().casefold()
    if candidate.count("@") != 1 or any(char.isspace() for char in candidate):
        return ""
    local_part, domain = candidate.split("@", 1)
    if not local_part or domain != "kahle.de":
        return ""
    return candidate


def public_payload(
    person: PersonRecord | None, onboarding_requested: bool
) -> dict[str, object]:
    """Build evidence-safe fields, reducing onboarding records at the boundary."""
    if person is None:
        return {}
    if person.employment_status == "ONBOARDING":
        if not onboarding_requested:
            return {}
        return {
            "display_name": person.display_name,
            "position": person.position,
            "department": person.department,
            "team": person.team,
            "office": person.office,
        }
    return {
        "personio_id": person.personio_id,
        "first_name": person.first_name,
        "last_name": person.last_name,
        "display_name": person.display_name,
        "position": person.position,
        "department": person.department,
        "team": person.team,
        "office": person.office,
        "business_email": person.business_email,
        "business_phone": person.business_phone,
        "employment_status": person.employment_status,
        "source_updated_at": person.source_updated_at,
    }

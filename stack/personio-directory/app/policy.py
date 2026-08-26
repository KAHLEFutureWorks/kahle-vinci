from collections.abc import Mapping

from app.models import PersonRecord


_PERSON_FIELDS = frozenset(PersonRecord.__dataclass_fields__)
_DERIVED_PERSON_FIELDS = frozenset({"first_name", "last_name"})
_MAPPED_PERSON_FIELDS = _PERSON_FIELDS - _DERIVED_PERSON_FIELDS
_ALLOWED_STATUSES = frozenset({"ACTIVE", "LEAVE", "ONBOARDING"})
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
    if any(not isinstance(value, str) or not value.strip() for value in values.values()):
        return None

    status = values["employment_status"]
    if status not in _ALLOWED_STATUSES:
        return None

    preferred_name = preferred_name_parts(values["display_name"])
    if preferred_name is None:
        return None
    display_name, first_name, last_name = preferred_name
    values["display_name"] = display_name
    values["first_name"] = first_name
    values["last_name"] = last_name

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

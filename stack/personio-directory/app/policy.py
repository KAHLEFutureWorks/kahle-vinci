from collections.abc import Mapping

from app.models import PersonRecord


_PERSON_FIELDS = frozenset(PersonRecord.__dataclass_fields__)
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
    if set(mapping) != _PERSON_FIELDS or any(
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
    if status not in _ALLOWED_STATUSES or values["employment_type"] != "INTERNAL":
        return None

    return PersonRecord(**values)  # type: ignore[arg-type]


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
        "employment_type": person.employment_type,
        "source_updated_at": person.source_updated_at,
    }

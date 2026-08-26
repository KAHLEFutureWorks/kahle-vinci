import pytest

from app.policy import filter_person, public_payload
from fixtures import MAPPING, raw_person


PREFERRED_NAME_MAPPING = {
    key: value
    for key, value in MAPPING.items()
    if key not in {"first_name", "last_name", "employment_type"}
} | {"display_name": "preferred_name"}


def preferred_person(name: object, employment_type: str = "EXTERNAL"):
    return raw_person("ACTIVE", employment_type) | {
        "preferred_name": name,
        "first_name": "must not be used",
        "last_name": "must not be used",
    }


def test_policy_keeps_active_and_leave_but_hides_onboarding_by_default():
    assert filter_person(raw_person("ACTIVE", "INTERNAL"), MAPPING) is not None
    assert filter_person(raw_person("LEAVE", "INTERNAL"), MAPPING) is not None
    onboarding = filter_person(raw_person("ONBOARDING", "INTERNAL"), MAPPING)
    assert onboarding is not None
    assert public_payload(onboarding, onboarding_requested=False) == {}


def test_onboarding_payload_is_reduced_before_evidence_creation():
    person = filter_person(raw_person("ONBOARDING", "INTERNAL"), MAPPING)
    assert public_payload(person, onboarding_requested=True) == {
        "display_name": "Erika Beispiel",
        "position": "Serviceberaterin",
        "department": "Service",
        "team": "Service Hannover",
        "office": "Hannover",
    }


def test_policy_rejects_inactive_people_but_ignores_external_type():
    assert filter_person(raw_person("INACTIVE", "INTERNAL"), MAPPING) is None
    assert filter_person(raw_person("ACTIVE", "EXTERNAL"), MAPPING) is not None


def test_policy_rejects_personio_id_mapped_from_a_non_id_source():
    raw = raw_person("ACTIVE", "INTERNAL") | {"employee_number": "E-100"}
    mapping = MAPPING | {"personio_id": "employee_number"}

    assert filter_person(raw, mapping) is None


def test_policy_rejects_sensitive_source_mapping_for_any_directory_field():
    raw = raw_person("ACTIVE", "INTERNAL") | {"salary_position": "Serviceberaterin"}
    mapping = MAPPING | {"position": "salary_position"}

    assert filter_person(raw, mapping) is None


def test_policy_rejects_missing_required_value():
    raw = raw_person("ACTIVE", "INTERNAL") | {"preferred_name": ""}

    assert filter_person(raw, MAPPING) is None


@pytest.mark.parametrize(
    "field",
    ["position", "department", "team", "office", "business_email", "business_phone"],
)
def test_policy_keeps_person_when_optional_directory_field_is_empty(field):
    raw = raw_person("ACTIVE", "INTERNAL") | {field: ""}

    assert filter_person(raw, MAPPING) is not None


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("JAN.OLTMANNS@KAHLE.DE", "jan.oltmanns@kahle.de"),
        ("private@example.com", ""),
        ("attack@kahle.de.example.com", ""),
        ("not-an-email", ""),
    ],
)
def test_policy_keeps_only_business_email_at_exact_kahle_domain(email, expected):
    person = filter_person(raw_person("ACTIVE", "INTERNAL") | {"business_email": email}, MAPPING)

    assert person is not None
    assert person.business_email == expected


def test_policy_accepts_an_optional_supervisor_personio_id_without_public_disclosure():
    raw = raw_person("ACTIVE", "INTERNAL") | {"supervisor_id": "42"}
    mapping = MAPPING | {"supervisor_personio_id": "supervisor_id"}

    person = filter_person(raw, mapping)

    assert person is not None
    assert person.supervisor_personio_id == "42"
    assert "supervisor_personio_id" not in public_payload(person, onboarding_requested=False)


def test_policy_rejects_unknown_employment_status():
    assert filter_person(raw_person("SABBATICAL", "INTERNAL"), MAPPING) is None


def test_policy_derives_jan_oltmanns_only_from_preferred_name():
    person = filter_person(preferred_person("  Jan   Oltmanns  "), PREFERRED_NAME_MAPPING)

    assert person is not None
    assert person.display_name == "Jan Oltmanns"
    assert person.first_name == "Jan"
    assert person.last_name == "Oltmanns"


def test_policy_uses_last_token_as_last_name_for_multiword_preferred_name():
    person = filter_person(
        preferred_person("Max van der Mustermann"),
        PREFERRED_NAME_MAPPING,
    )

    assert person is not None
    assert person.display_name == "Max van der Mustermann"
    assert person.first_name == "Max van der"
    assert person.last_name == "Mustermann"


@pytest.mark.parametrize("preferred_name", ["", "   ", "Madonna", "Jan 123"])
def test_policy_rejects_blank_single_token_or_malformed_preferred_name(preferred_name):
    assert filter_person(
        preferred_person(preferred_name),
        PREFERRED_NAME_MAPPING,
    ) is None


def test_policy_includes_external_employee_without_mapping_employment_type():
    person = filter_person(
        preferred_person("Erika Beispiel", employment_type="EXTERNAL"),
        PREFERRED_NAME_MAPPING,
    )

    assert person is not None
    assert person.display_name == "Erika Beispiel"

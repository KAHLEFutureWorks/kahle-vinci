from app.policy import filter_person, public_payload
from fixtures import MAPPING, raw_person


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


def test_policy_rejects_inactive_and_external_people():
    assert filter_person(raw_person("INACTIVE", "INTERNAL"), MAPPING) is None
    assert filter_person(raw_person("ACTIVE", "EXTERNAL"), MAPPING) is None


def test_policy_rejects_personio_id_mapped_from_a_non_id_source():
    raw = raw_person("ACTIVE", "INTERNAL") | {"employee_number": "E-100"}
    mapping = MAPPING | {"personio_id": "employee_number"}

    assert filter_person(raw, mapping) is None


def test_policy_rejects_sensitive_source_mapping_for_any_directory_field():
    raw = raw_person("ACTIVE", "INTERNAL") | {"salary_position": "Serviceberaterin"}
    mapping = MAPPING | {"position": "salary_position"}

    assert filter_person(raw, mapping) is None


def test_policy_rejects_missing_required_value():
    raw = raw_person("ACTIVE", "INTERNAL") | {"first_name": ""}

    assert filter_person(raw, MAPPING) is None


def test_policy_rejects_unknown_employment_status():
    assert filter_person(raw_person("SABBATICAL", "INTERNAL"), MAPPING) is None

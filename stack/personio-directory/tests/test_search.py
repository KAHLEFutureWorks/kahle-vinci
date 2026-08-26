from __future__ import annotations

import pytest

from app.models import DirectoryQuery, PersonRecord
from app.search import DirectorySearch, classify_directory_query


class FakeDirectoryIndex:
    def __init__(self, people: list[PersonRecord]) -> None:
        self.people = {person.personio_id: person for person in people}

    def indexed_personio_ids(self) -> set[str]:
        return set(self.people)

    def people_by_personio_ids(
        self, personio_ids: set[str]
    ) -> dict[str, PersonRecord]:
        return {
            personio_id: self.people[personio_id]
            for personio_id in personio_ids
            if personio_id in self.people
        }


def person(
    personio_id: str,
    *,
    name: str,
    position: str = "Serviceberater",
    department: str = "Service",
    team: str = "Service Hannover",
    office: str = "Hannover",
    status: str = "ACTIVE",
    supervisor_personio_id: str = "",
) -> PersonRecord:
    first_name, last_name = name.split(" ", 1)
    return PersonRecord(
        personio_id=personio_id,
        first_name=first_name,
        last_name=last_name,
        display_name=name,
        position=position,
        department=department,
        team=team,
        office=office,
        business_email=f"{first_name.casefold()}.{last_name.casefold()}@kahle.de",
        business_phone="+49 511 123456",
        employment_status=status,  # type: ignore[arg-type]
        source_updated_at="2026-08-24T10:15:00Z",
        supervisor_personio_id=supervisor_personio_id,
    )


def search(people: list[PersonRecord]) -> DirectorySearch:
    return DirectorySearch(
        FakeDirectoryIndex(people),
        sync_completed_at="2026-08-24T10:15:00Z",
    )


def query(text: str, intent: str | None = None) -> DirectoryQuery:
    return DirectoryQuery(
        text=text,
        intent=intent or classify_directory_query(text),  # type: ignore[arg-type]
        user_id="test-user",
        user_role="user",
    )


@pytest.mark.parametrize(
    "text",
    [
        "Wer ist aktuell im Onboarding?",
        "Welche neuen Serviceberater sind im Onboarding?",
        "Welche Onboarding-Mitarbeitenden kommen nach Hannover?",
    ],
)
def test_explicit_onboarding_queries_select_onboarding_search(text: str):
    assert classify_directory_query(text) == "onboarding_search"


def test_new_alone_does_not_expose_onboarding():
    assert classify_directory_query("Welche neuen Kollegen arbeiten in Hannover?") != "onboarding_search"


@pytest.mark.parametrize(
    "text",
    [
        "Was weißt du über Erika Beispiel?",
        "Wo arbeitet Erika Beispiel?",
        "Was macht Erika Beispiel?",
    ],
)
def test_natural_person_questions_use_person_lookup(text: str):
    assert classify_directory_query(text) == "person_lookup"


def test_supervisor_question_uses_dedicated_fail_closed_directory_intent():
    directory = search([person("1", name="Erika Beispiel")])

    evidence = directory.search(query("Wer davon ist die Führungskraft?"))

    assert classify_directory_query("Wer davon ist die Führungskraft?") == "supervisor_lookup"
    assert evidence.status == "not_found"
    assert evidence.claims == ()


def test_supervisor_follow_up_returns_only_the_explicitly_evidenced_prior_candidate():
    leader = person("1", name="Erika Beispiel", position="Teiledienstleitung", department="Teiledienst")
    report = person(
        "2",
        name="Anna Adler",
        position="Teiledienstberaterin",
        department="Teiledienst",
        supervisor_personio_id="1",
    )
    directory = search([leader, report])
    supervisor_query = DirectoryQuery(
        text="Wer davon ist die Führungskraft?",
        intent="supervisor_lookup",
        user_id="test-user",
        user_role="user",
        candidate_query="Wer arbeitet im Teiledienst in Hannover?",
    )

    evidence = directory.search(supervisor_query)

    assert [claim["display_name"] for claim in evidence.claims] == ["Erika Beispiel"]
    assert "supervisor_personio_id" not in repr(evidence.claims)


def test_named_person_query_requires_exact_full_name_or_email_before_expansion():
    erika = person("1", name="Erika Beispiel")
    directory = search([erika])

    partial = directory.search(query("Was weißt du über Erika?", "person_lookup"))
    by_name = directory.search(query("Was weißt du über ERIKA, BEISPIEL?", "person_lookup"))
    by_email = directory.search(query("Wo arbeitet erika.beispiel@kahle.de?", "person_lookup"))

    assert partial.status == "not_found"
    assert by_name.claims[0]["display_name"] == "Erika Beispiel"
    assert by_email.claims[0]["display_name"] == "Erika Beispiel"


def test_short_who_is_person_question_uses_exact_gate_and_rejects_partial_names():
    erika = person("1", name="Erika Beispiel")
    directory = search([erika])

    partial = directory.search(query("Wer ist Erika?"))
    by_full_name = directory.search(query("Wer ist Erika Beispiel?"))

    assert classify_directory_query("Wer ist Erika?") == "person_lookup"
    assert partial.status == "not_found"
    assert by_full_name.claims[0]["display_name"] == "Erika Beispiel"


def test_multiword_who_is_question_stays_behind_exact_person_gate():
    max_van_der_mustermann = person("1", name="Max van der Mustermann")
    directory = search([max_van_der_mustermann])

    partial = directory.search(query("Wer ist Max van der?"))
    exact = directory.search(query("Wer ist Max van der Mustermann?"))

    assert classify_directory_query("Wer ist Max van der?") == "person_lookup"
    assert partial.status == "not_found"
    assert exact.claims[0]["display_name"] == "Max van der Mustermann"


def test_onboarding_evidence_is_reduced_before_claims_and_never_leaks_contacts_or_ids():
    onboarding = person("17", name="Nora Neu", status="ONBOARDING")
    directory = search([onboarding])

    ordinary = directory.search(query("Welche Serviceberater arbeiten in Hannover?", "directory_search"))
    explicit = directory.search(query("Wer ist im Onboarding?", "onboarding_search"))

    assert ordinary.status == "not_found"
    assert explicit.claims == (
        {
            "display_name": "Nora Neu",
            "position": "Serviceberater",
            "department": "Service",
            "team": "Service Hannover",
            "office": "Hannover",
            "source_id": "P1",
        },
    )
    assert "personio_id" not in repr(explicit.claims)
    assert "business_email" not in repr(explicit.claims)
    assert "business_phone" not in repr(explicit.claims)
    assert "employment_status" not in repr(explicit.claims)


def test_general_onboarding_question_returns_all_onboarding_people_without_filler_filters():
    nora = person("17", name="Nora Neu", status="ONBOARDING")
    erik = person("18", name="Erik Einstieg", status="ONBOARDING", position="Verkäufer")

    evidence = search([nora, erik]).search(
        query("Welche neuen Mitarbeiter sind aktuell bei uns im Onboarding?")
    )

    assert evidence.status == "ok"
    assert [claim["display_name"] for claim in evidence.claims] == [
        "Erik Einstieg",
        "Nora Neu",
    ]
    assert all(
        set(claim) == {"display_name", "position", "department", "team", "office", "source_id"}
        for claim in evidence.claims
    )


def test_role_limited_onboarding_question_keeps_the_explicit_role_filter():
    onboarding_service = person("17", name="Nora Neu", status="ONBOARDING")
    onboarding_sales = person(
        "18", name="Erik Einstieg", status="ONBOARDING", position="Verkäufer"
    )

    evidence = search([onboarding_service, onboarding_sales]).search(
        query("Welche neuen Serviceberater sind aktuell im Onboarding?")
    )

    assert evidence.status == "ok"
    assert [claim["display_name"] for claim in evidence.claims] == ["Nora Neu"]


def test_directory_search_combines_role_and_office_filters_and_uses_stable_personio_sources():
    erika = person("2", name="Erika Beispiel")
    anna = person("1", name="Anna Adler")
    berlin = person("3", name="Berta Berlin", office="Berlin")

    evidence = search([erika, anna, berlin]).search(
        query("Welche Serviceberater arbeiten in Hannover?", "directory_search")
    )

    assert [claim["display_name"] for claim in evidence.claims] == ["Anna Adler", "Erika Beispiel"]
    assert [claim["source_id"] for claim in evidence.claims] == ["P1", "P2"]
    assert evidence.sources == (
        {"id": "P1", "kind": "personio_directory"},
        {"id": "P2", "kind": "personio_directory"},
    )
    assert evidence.sync_completed_at == "2026-08-24T10:15:00Z"
    assert evidence.stale is False
    assert "employment_type" not in repr(evidence.claims)


def test_directory_search_matches_teiledienst_and_hannover_as_explicit_dimensions():
    matching = person(
        "1", name="Anna Adler", position="Teiledienstberater", department="Teiledienst"
    )
    wrong_office = person(
        "2", name="Berta Berlin", position="Teiledienstberater", department="Teiledienst", office="Berlin"
    )

    evidence = search([matching, wrong_office]).search(
        query("Wer arbeitet im Teiledienst in Hannover?", "directory_search")
    )

    assert [claim["display_name"] for claim in evidence.claims] == ["Anna Adler"]


def test_directory_search_normalizes_serviceassistenzen_and_office_preposition():
    matching = person(
        "1", name="Anna Adler", position="Serviceassistenz", office="Wedemark"
    )
    wrong_role = person(
        "2", name="Berta Berlin", position="Serviceberater", office="Wedemark"
    )

    evidence = search([matching, wrong_role]).search(
        query("Wie heißen die Serviceassistenzen in der Wedemark?", "directory_search")
    )

    assert [claim["display_name"] for claim in evidence.claims] == ["Anna Adler"]


def test_sales_role_description_is_a_directory_search_with_brand_and_area_filters():
    matching = person(
        "1",
        name="Anna Adler",
        position="Automobilverkäufer",
        department="Neuwagen",
        team="SEAT",
    )
    wrong_brand = person(
        "2",
        name="Berta Berlin",
        position="Automobilverkäufer",
        department="Neuwagen",
        team="CUPRA",
    )
    wrong_area = person(
        "3",
        name="Clara Celle",
        position="Automobilverkäufer",
        department="Gebrauchtwagen",
        team="SEAT",
    )

    directory = search([matching, wrong_brand, wrong_area])
    evidence = directory.search(query("Wer ist Verkäufer von Seat Neuwagen?"))

    assert classify_directory_query("Wer ist Verkäufer von Seat Neuwagen?") == "directory_search"
    assert [claim["display_name"] for claim in evidence.claims] == ["Anna Adler"]


def test_controlled_role_search_returns_no_unrelated_people_when_a_dimension_is_missing():
    service = person("1", name="Anna Adler", position="Serviceassistenz", office="Wedemark")

    evidence = search([service]).search(
        query("Wie heißen die Serviceassistenzen in Celle?", "directory_search")
    )

    assert evidence.status == "not_found"


def test_team_name_does_not_accidentally_add_an_office_filter():
    hannover_team_in_berlin = person(
        "1", name="Anna Adler", team="Service Hannover", office="Berlin"
    )

    evidence = search([hannover_team_in_berlin]).search(
        query("Wer arbeitet im Team Service Hannover?", "directory_search")
    )

    assert [claim["display_name"] for claim in evidence.claims] == ["Anna Adler"]


def test_coworkers_use_team_before_position_and_office_with_safe_disclosure():
    target = person("1", name="Erika Beispiel", team="Service Hannover")
    teammate = person("2", name="Anna Adler", team="Service Hannover")
    same_role_other_team = person("3", name="Berta Beispiel", team="Verkauf Hannover")
    directory = search([target, teammate, same_role_other_team])

    result = directory.coworkers(target)
    evidence = directory.search(query("Mit wem arbeitet Erika Beispiel zusammen?", "coworker_lookup"))

    assert result.basis == "team"
    assert [person.display_name for person in result.people] == ["Anna Adler"]
    assert evidence.claims[0]["relationship_basis"] == "team"
    assert "keine tatsächliche" in str(evidence.claims[0]["relationship_disclaimer"])


def test_coworker_results_exclude_people_on_leave_but_normal_search_keeps_them():
    target = person("1", name="Erika Beispiel", team="Service Hannover")
    leave_teammate = person("2", name="Anna Adler", team="Service Hannover", status="LEAVE")
    directory = search([target, leave_teammate])

    coworkers = directory.coworkers(target)
    normal_search = directory.search(
        query("Welche Serviceberater arbeiten in Hannover?", "directory_search")
    )

    assert coworkers.basis == "team"
    assert coworkers.people == ()
    assert [claim["display_name"] for claim in normal_search.claims] == ["Anna Adler", "Erika Beispiel"]


def test_coworkers_fall_back_to_position_and_office_when_no_team_exists():
    target = person("1", name="Erika Beispiel", team="")
    colleague = person("2", name="Anna Adler", team="", position="Serviceberater", office="Hannover")
    other_office = person("3", name="Berta Beispiel", team="", position="Serviceberater", office="Berlin")

    result = search([target, colleague, other_office]).coworkers(target)

    assert result.basis == "position_and_office"
    assert [person.display_name for person in result.people] == ["Anna Adler"]


def test_coworkers_fall_back_to_department_and_office_when_no_team_or_position_exists():
    target = person("1", name="Erika Beispiel", team="", position="")
    colleague = person("2", name="Anna Adler", team="", position="", department="Service", office="Hannover")
    other_department = person("3", name="Berta Beispiel", team="", position="", department="Verkauf", office="Hannover")

    result = search([target, colleague, other_department]).coworkers(target)

    assert result.basis == "department_and_office"
    assert [person.display_name for person in result.people] == ["Anna Adler"]


def test_coworkers_never_fall_back_to_office_alone():
    target = person("1", name="Erika Beispiel", team="", position="", department="")
    only_same_office = person("2", name="Anna Adler", team="", position="", department="Verkauf")

    result = search([target, only_same_office]).coworkers(target)

    assert result.basis is None
    assert result.people == ()

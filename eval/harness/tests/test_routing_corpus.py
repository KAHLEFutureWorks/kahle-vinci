from collections import Counter
from pathlib import Path

from harness_eval import load_cases

CORPUS = Path(__file__).resolve().parents[1] / "routing_cases.yml"
CATEGORY_TOOLS = {
    "personio_person": {"personio_directory"},
    "personio_list": {"personio_directory"},
    "supervisor": {"personio_directory"},
    "onboarding_people": {"personio_directory"},
    "onboarding_process": {"rag_chat"},
    "procedure": {"rag_chat"},
    "responsibility": {"rag_chat"},
    "functional_contact": {"rag_chat"},
    "organization_contact": {"personio_directory", "rag_chat"},
    "person_process": {"personio_directory", "rag_chat"},
    "abbreviation": {"rag_chat"},
    "internal_knowledge": {"rag_chat"},
    "scope_location": {"rag_chat"},
    "no_knowledge_tool": set(),
}
VARIABLE_CATEGORIES = {"followup", "unanswerable"}


def test_corpus_size_and_category_coverage():
    cases = load_cases(CORPUS)
    counts = Counter(case.category for case in cases)

    assert len(cases) >= 90
    assert set(counts) == set(CATEGORY_TOOLS) | VARIABLE_CATEGORIES
    assert all(count >= 2 for count in counts.values())


def test_fixed_categories_follow_adr_008_source_policy():
    for case in load_cases(CORPUS):
        if case.category in CATEGORY_TOOLS:
            assert case.expected_tools == frozenset(CATEGORY_TOOLS[case.category]), case.case_id


def test_findings_are_covered_and_umlaut_pairs_expect_procedures():
    cases = load_cases(CORPUS)
    findings = Counter(finding for case in cases for finding in case.findings)

    assert {"K1", "K2", "K3", "U1"} <= set(findings)
    assert all(findings[name] >= 2 for name in ("K1", "K2", "K3", "U1"))
    assert all(case.expected_procedural is True for case in cases if "K1" in case.findings)


def test_unanswerable_cases_expect_abstention():
    unanswerable = [case for case in load_cases(CORPUS) if case.category == "unanswerable"]

    assert unanswerable
    assert all(case.expect_abstention is True for case in unanswerable)

import pytest

from harness_eval import load_cases, nearest_rank, routing_outcome, summarize_routing


def test_harness_module_is_importable_from_eval_paths():
    import kahle_knowledge_harness

    assert kahle_knowledge_harness.SCHEMA_VERSION == "kahle.knowledge-harness.v1"


def _write(tmp_path, body):
    path = tmp_path / "cases.yml"
    path.write_text(body, encoding="utf-8")
    return path


VALID = """
schema_version: kahle.harness-routing-cases.v1
cases:
  - id: person_profile
    category: personio_person
    question: "Wer ist Max Mustermann?"
    expected_tools: [personio_directory]
  - id: followup_supervisor
    category: followup
    history:
      - {role: user, content: "Wer ist Max Mustermann?"}
      - {role: assistant, content: "Serviceberater [P1]."}
    question: "Und wer ist seine Führungskraft?"
    expected_tools: [personio_directory]
    findings: [K2]
    expected_procedural: false
    expect_abstention: false
"""


def test_load_cases_parses_history_flags_and_findings(tmp_path):
    cases = load_cases(_write(tmp_path, VALID))

    assert [case.case_id for case in cases] == ["person_profile", "followup_supervisor"]
    followup = cases[1]
    assert followup.expected_tools == frozenset({"personio_directory"})
    assert followup.findings == ("K2",)
    assert followup.expected_procedural is False
    assert followup.expect_abstention is False
    assert followup.messages() == [
        {"role": "user", "content": "Wer ist Max Mustermann?"},
        {"role": "assistant", "content": "Serviceberater [P1]."},
        {"role": "user", "content": "Und wer ist seine Führungskraft?"},
    ]
    assert cases[0].expected_procedural is None


@pytest.mark.parametrize(
    "case_yaml, message",
    [
        ("  - {id: a_case, category: x, question: q, expected_tools: [web_search]}", "expected_tools"),
        ("  - {id: A-Case, category: x, question: q, expected_tools: []}", "Fall-ID"),
        ("  - {id: a_case, category: x, question: q, expected_tools: [], history: [{role: system, content: x}]}", "history"),
        ("  - {id: a_case, category: x, question: q, expected_tools: [], expect_abstention: vielleicht}", "expect_abstention"),
        ("  - {id: a_case, category: '', question: q, expected_tools: []}", "category"),
    ],
)
def test_load_cases_rejects_invalid_cases(tmp_path, case_yaml, message):
    body = "schema_version: kahle.harness-routing-cases.v1\ncases:\n" + case_yaml + "\n"

    with pytest.raises(ValueError, match=message):
        load_cases(_write(tmp_path, body))


def test_load_cases_rejects_duplicates_and_unknown_schema(tmp_path):
    duplicate = (
        "schema_version: kahle.harness-routing-cases.v1\ncases:\n"
        "  - {id: a_case, category: x, question: q, expected_tools: []}\n"
        "  - {id: a_case, category: x, question: q, expected_tools: []}\n"
    )
    with pytest.raises(ValueError, match="Doppelte"):
        load_cases(_write(tmp_path, duplicate))
    with pytest.raises(ValueError, match="schema_version"):
        load_cases(_write(tmp_path, "schema_version: other\ncases: []\n"))


@pytest.mark.parametrize(
    "expected, actual, outcome",
    [
        ({"rag_chat"}, {"rag_chat"}, "correct"),
        (set(), set(), "correct"),
        (set(), {"web_search"}, "correct"),
        ({"personio_directory", "rag_chat"}, {"rag_chat"}, "missing_source"),
        ({"rag_chat"}, set(), "missing_source"),
        ({"rag_chat"}, {"personio_directory", "rag_chat"}, "extra_source"),
        (set(), {"rag_chat"}, "extra_source"),
        ({"rag_chat"}, {"personio_directory"}, "wrong_source"),
    ],
)
def test_routing_outcome_compares_only_knowledge_tools(expected, actual, outcome):
    assert routing_outcome(expected, actual) == outcome


def test_nearest_rank_percentiles():
    assert nearest_rank([], 0.5) is None
    assert nearest_rank([400, 100, 300, 200], 0.5) == 200
    assert nearest_rank([400, 100, 300, 200], 0.95) == 400


def test_summarize_routing_groups_by_model_and_category():
    rows = [
        {"model": "m1", "category": "procedure", "outcome": "correct", "procedural_match": True},
        {"model": "m1", "category": "procedure", "outcome": "correct", "procedural_match": False},
        {"model": "m1", "category": "responsibility", "outcome": "wrong_source"},
        {"model": "m2", "category": "procedure", "outcome": "error"},
    ]

    summary = summarize_routing(rows)

    assert summary["m1"]["total"] == 3
    assert summary["m1"]["correct"] == 2
    assert summary["m1"]["accuracy"] == 0.6667
    assert summary["m1"]["outcomes"] == {"correct": 2, "wrong_source": 1}
    assert summary["m1"]["by_category"]["responsibility"] == {
        "total": 1, "correct": 0, "accuracy": 0.0,
    }
    assert summary["m1"]["procedural_checked"] == 2
    assert summary["m1"]["procedural_accuracy"] == 0.5
    assert summary["m2"]["accuracy"] == 0.0

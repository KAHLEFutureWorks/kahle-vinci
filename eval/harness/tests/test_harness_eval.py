import json

import pytest

from harness_eval import (
    RoutingCase,
    actual_knowledge_tools,
    answer_text,
    load_cases,
    nearest_rank,
    routing_outcome,
    score_answer,
    summarize_answers,
    summarize_routing,
)


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


def _message(text="", violations=(), status="accepted", latency=1200, tools=(), actual=()):
    return {
        "content": text,
        "output": [
            *({"type": "function_call", "name": name} for name in tools),
            {"type": "message", "content": [{"type": "output_text", "text": text}]},
        ],
        "kahle_answer_validation": {
            "attempts": [{"status": status, "violations": [{"code": code} for code in violations]}]
        },
        "kahle_harness_metrics": {
            "latency_ms": latency,
            "routing_comparison": {"actual_tools": list(actual)},
        },
    }


def _case(expect_abstention=None):
    return RoutingCase(
        case_id="some_case",
        category="procedure",
        question="Frage?",
        expected_tools=frozenset({"rag_chat"}),
        expect_abstention=expect_abstention,
    )


def test_actual_knowledge_tools_combines_calls_and_metrics():
    message = _message(tools=("rag_chat", "safe_webcaller"), actual=("personio_directory",))

    assert actual_knowledge_tools(message) == frozenset({"rag_chat", "personio_directory"})


def test_answer_text_falls_back_to_output_items():
    message = _message(text="Belegte Antwort [R1].")
    message["content"] = ""

    assert answer_text(message) == "Belegte Antwort [R1]."


def test_score_answer_keeps_only_blocking_codes_and_no_text():
    message = _message(
        text="Dazu habe ich keine verlässliche freigegebene Information.",
        violations=("unsupported_technical_approval", "unknown_source_id"),
        status="retry_required",
    )

    score = score_answer(_case(expect_abstention=True), message)

    assert score == {
        "blocking_violations": ["unknown_source_id"],
        "validation_status": "retry_required",
        "abstained": True,
        "abstention_correct": True,
        "answer_present": True,
        "latency_ms": 1200,
    }
    assert "verlässliche" not in json.dumps(score, ensure_ascii=False)


def test_score_answer_without_validation_or_expectation():
    message = {"content": "Antwort", "output": []}

    score = score_answer(_case(), message)

    assert score["validation_status"] == "not_run"
    assert score["blocking_violations"] == []
    assert score["abstention_correct"] is None
    assert score["latency_ms"] is None


def test_summarize_answers_rates_and_latency():
    rows = [
        {"model": "m", "answer_present": True, "blocking_violations": ["citation_missing"],
         "abstention_correct": True, "latency_ms": 100, "wall_ms": 1000},
        {"model": "m", "answer_present": True, "blocking_violations": [],
         "abstention_correct": False, "latency_ms": 300, "wall_ms": 3000},
        {"model": "m", "answer_present": False, "blocking_violations": [],
         "abstention_correct": None, "latency_ms": None, "wall_ms": 2000},
    ]

    summary = summarize_answers(rows)["m"]

    assert summary["total"] == 3
    assert summary["answer_present_rate"] == 0.6667
    assert summary["blocking_violation_rate"] == 0.3333
    assert summary["blocking_violation_codes"] == {"citation_missing": 1}
    assert summary["abstention_checked"] == 2
    assert summary["abstention_accuracy"] == 0.5
    assert summary["latency_p50_ms"] == 100
    assert summary["latency_p95_ms"] == 300
    assert summary["wall_p50_ms"] == 2000

import json
from pathlib import Path
from types import SimpleNamespace

from harness_eval import RoutingCase, load_cases
from offline_routing_eval import PLANNER_MODEL, evaluate_case, main, run_offline

CORPUS = Path(__file__).resolve().parents[1] / "routing_cases.yml"


class FakeHarness:
    def __init__(self, tools, procedural):
        self.calls = []
        self._tools = tools
        self._procedural = procedural

    def resolve_request(self, query, messages):
        self.calls.append(("resolve", query, len(messages)))
        return SimpleNamespace(retrieval_query=f"aufgelöst: {query}")

    def plan_retrieval(self, query, resolved_query, messages, model_id, permission_scope):
        self.calls.append(("plan", query, resolved_query, len(messages), model_id, permission_scope))
        return SimpleNamespace(required_tools=self._tools)

    def _is_procedural(self, query):
        self.calls.append(("procedural", query))
        return self._procedural


def test_evaluate_case_plans_on_resolved_query_with_history():
    case = RoutingCase(
        case_id="followup_case",
        category="followup",
        question="Und in WPS?",
        expected_tools=frozenset({"rag_chat"}),
        history=({"role": "user", "content": "Wie ändere ich X?"}, {"role": "assistant", "content": "So [R1]."}),
        findings=("K1",),
        expected_procedural=True,
    )
    harness = FakeHarness(tools=("personio_directory",), procedural=True)

    row = evaluate_case(case, harness)

    assert row == {
        "model": PLANNER_MODEL,
        "case_id": "followup_case",
        "category": "followup",
        "expected_tools": ["rag_chat"],
        "actual_tools": ["personio_directory"],
        "outcome": "wrong_source",
        "findings": ["K1"],
        "procedural_match": True,
    }
    assert harness.calls[1] == (
        "plan", "Und in WPS?", "aufgelöst: Und in WPS?", 3, PLANNER_MODEL, {"user_id": "eval"},
    )
    assert harness.calls[2] == ("procedural", "aufgelöst: Und in WPS?")


def test_run_offline_with_real_harness_covers_whole_corpus():
    import kahle_knowledge_harness

    cases = load_cases(CORPUS)
    report = run_offline(cases, kahle_knowledge_harness)

    assert report["mode"] == "offline_planner"
    assert report["case_count"] == len(cases) == len(report["rows"])
    summary = report["summary"][PLANNER_MODEL]
    assert summary["total"] == len(cases)
    assert 0.0 < summary["accuracy"] <= 1.0
    assert "question" not in json.dumps(report["rows"])


def test_main_writes_json_report(tmp_path):
    output = tmp_path / "out" / "baseline.json"

    assert main(["--output", str(output)]) == 0

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema_version"] == "kahle.harness-eval.v1"
    assert report["summary"][PLANNER_MODEL]["total"] == report["case_count"]

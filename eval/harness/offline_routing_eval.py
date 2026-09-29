"""Measure the deterministic harness planner against the routing corpus.

Runs without models, so it stays usable while IONOS is unavailable.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from _repo_paths import ensure_repo_paths
from harness_eval import (
    SCHEMA_VERSION,
    RoutingCase,
    load_cases,
    routing_outcome,
    summarize_routing,
)

PLANNER_MODEL = "legacy-planner"
DEFAULT_CASES = Path(__file__).with_name("routing_cases.yml")


def evaluate_case(case: RoutingCase, harness: Any) -> dict[str, Any]:
    messages = case.messages()
    resolved = harness.resolve_request(case.question, messages).retrieval_query
    plan = harness.plan_retrieval(
        case.question, resolved, messages, PLANNER_MODEL, {"user_id": "eval"}
    )
    actual = sorted(set(plan.required_tools))
    row: dict[str, Any] = {
        "model": PLANNER_MODEL,
        "case_id": case.case_id,
        "category": case.category,
        "expected_tools": sorted(case.expected_tools),
        "actual_tools": actual,
        "outcome": routing_outcome(case.expected_tools, actual),
        "findings": list(case.findings),
    }
    if case.expected_procedural is not None:
        row["procedural_match"] = (
            bool(harness._is_procedural(resolved)) == case.expected_procedural
        )
    return row


def run_offline(cases: list[RoutingCase], harness: Any) -> dict[str, Any]:
    rows = [evaluate_case(case, harness) for case in cases]
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "offline_planner",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "case_count": len(cases),
        "summary": summarize_routing(rows),
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    ensure_repo_paths()
    import kahle_knowledge_harness

    report = run_offline(load_cases(args.cases), kahle_knowledge_harness)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summary = report["summary"][PLANNER_MODEL]
    print(
        f"{PLANNER_MODEL}: {summary['correct']}/{summary['total']} korrekt "
        f"({summary['accuracy']:.1%}), procedural {summary['procedural_accuracy']:.1%}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

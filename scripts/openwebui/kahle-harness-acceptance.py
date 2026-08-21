"""Build a deterministic acceptance report from normalized Vinci harness runs.

The reporter does not call models, read OpenWebUI's database or infer missing
results.  Browser, API and test-container runners can all provide the same run
schema, while unavailable models and unauthorized profiles remain explicit.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "kahle.harness-acceptance-report.v1"


def _nearest_rank(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _run_failures(run: Mapping[str, Any]) -> list[str]:
    metrics = run.get("metrics") if isinstance(run.get("metrics"), Mapping) else {}
    failures = []
    if metrics.get("tool_called") != "rag_chat":
        failures.append("required_tool_not_called")
    if not metrics.get("permission_scope_present"):
        failures.append("permission_scope_missing")
    delivery_status = str(metrics.get("delivery_status") or "")
    accepted_delivery = delivery_status in {
        "accepted", "safe_fallback", "safe_timeout_fallback",
    } or (
        not delivery_status and metrics.get("final_validation_status") == "accepted"
    )
    if not accepted_delivery:
        failures.append("answer_not_accepted")
    if not metrics.get("feedback_link_present"):
        failures.append("feedback_link_missing")
    if metrics.get("evidence_status") == "supported" and not (
        int(metrics.get("source_count") or 0) > 0
    ):
        failures.append("supported_answer_without_source")
    return failures


def build_acceptance_report(
    runs: Iterable[Mapping[str, Any]],
    *,
    expected_models: Iterable[str],
    profile_authorization: Mapping[str, bool],
    required_case_ids: Iterable[str] = (),
) -> dict[str, Any]:
    normalized_runs = [dict(run) for run in runs]
    by_model_profile: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for run in normalized_runs:
        metrics = run.get("metrics") if isinstance(run.get("metrics"), Mapping) else {}
        model_name = str(metrics.get("model_name") or metrics.get("model_id") or "")
        profile = str(run.get("profile") or "")
        if model_name and profile:
            by_model_profile.setdefault((model_name, profile), []).append(run)

    coverage = []
    counts = {"passed": 0, "failed": 0, "unavailable": 0, "not_authorized": 0}
    models = tuple(dict.fromkeys(str(model) for model in expected_models))
    required_cases = tuple(dict.fromkeys(str(case_id) for case_id in required_case_ids))
    for profile, authorized in profile_authorization.items():
        for model_name in models:
            matching = by_model_profile.get((model_name, str(profile)), [])
            reasons: list[str] = []
            if not authorized:
                status = "not_authorized"
            elif not matching:
                status = "unavailable"
            else:
                for run in matching:
                    reasons.extend(_run_failures(run))
                completed_cases = {str(run.get("case_id") or "") for run in matching}
                reasons.extend(
                    f"missing_case:{case_id}"
                    for case_id in required_cases
                    if case_id not in completed_cases
                )
                reasons = sorted(set(reasons))
                status = "failed" if reasons else "passed"
            counts[status] += 1
            coverage.append(
                {
                    "model_name": model_name,
                    "profile": str(profile),
                    "status": status,
                    "run_count": len(matching),
                    "reasons": reasons,
                }
            )

    accepted_metrics = [
        run.get("metrics")
        for run in normalized_runs
        if not _run_failures(run) and isinstance(run.get("metrics"), Mapping)
    ]
    latencies = [
        int(metrics["latency_ms"])
        for metrics in accepted_metrics
        if isinstance(metrics.get("latency_ms"), (int, float))
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "summary": counts,
        "coverage": coverage,
        "metrics": {
            "sample_size": len(accepted_metrics),
            "latency_p50_ms": _nearest_rank(latencies, 0.50),
            "latency_p95_ms": _nearest_rank(latencies, 0.95),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON file containing runs and coverage")
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    report = build_acceptance_report(
        payload.get("runs") or [],
        expected_models=payload.get("expected_models") or [],
        profile_authorization=payload.get("profile_authorization") or {},
        required_case_ids=payload.get("required_case_ids") or [],
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["summary"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

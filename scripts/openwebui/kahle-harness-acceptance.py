"""Build a deterministic acceptance report from normalized Vinci harness runs.

The reporter does not call models, read OpenWebUI's database or infer missing
results.  Browser, API and test-container runners can all provide the same run
schema, while unavailable models and unauthorized profiles remain explicit.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "kahle.harness-acceptance-report.v1"
ALLOWED_TOOLS = ("personio_directory", "rag_chat")
ALLOWED_SOURCE_KINDS = ("personio_directory", "rag_chat")
ALLOWED_INTENTS = ("employee_directory", "internal_knowledge")
ALLOWED_EVIDENCE_STATUS = ("supported", "partially_supported", "unsupported")
ALLOWED_VALIDATION_STATUS = (
    "accepted",
    "safe_fallback",
    "safe_timeout_fallback",
    "retry_required",
    "timeout",
    "not_run",
)
ALLOWED_PROFILES = ("employee", "manager", "user", "admin", "pending")
MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
CASE_ID = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
ASSERTION_ID = re.compile(r"^[a-z][a-z0-9_]{0,127}$")


class MatrixContractError(RuntimeError):
    """A safe-code failure for an invalid versioned acceptance matrix."""


def _nearest_rank(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _safe_list(value: Any, allowed: Iterable[str]) -> list[str]:
    allowed_values = tuple(allowed)
    if not isinstance(value, (list, tuple)):
        return []
    return [
        item
        for item in dict.fromkeys(str(item) for item in value)
        if item in allowed_values
    ]


def _safe_value(value: Any, allowed: Iterable[str], fallback: str) -> str:
    normalized = str(value or "")
    return normalized if normalized in tuple(allowed) else fallback


def _actual_tools(metrics: Mapping[str, Any]) -> list[str]:
    explicit = _safe_list(metrics.get("actual_tools"), ALLOWED_TOOLS)
    if explicit or isinstance(metrics.get("actual_tools"), (list, tuple)):
        return explicit
    called = str(metrics.get("tool_called") or "")
    if called in ALLOWED_TOOLS:
        return [called]
    return []


def _source_kinds(metrics: Mapping[str, Any]) -> list[str]:
    return _safe_list(metrics.get("source_kinds"), ALLOWED_SOURCE_KINDS)


def _required_assertions(contract: Mapping[str, Any]) -> tuple[str, ...]:
    assertions = [
        value
        for value in contract.get("required_assertions") or ()
        if isinstance(value, str) and value.replace("_", "").isalnum()
    ]
    if contract.get("forbidden_fields") and "forbidden_fields_absent" not in assertions:
        assertions.append("forbidden_fields_absent")
    return tuple(dict.fromkeys(assertions))


def _normalized_contract(contract: Mapping[str, Any] | None) -> dict[str, Any]:
    normalized = dict(contract or {})
    if "expected_tools" not in normalized and normalized.get("required_tool"):
        normalized["expected_tools"] = [str(normalized["required_tool"])]
    return normalized


def _run_failures(
    run: Mapping[str, Any],
    contract: Mapping[str, Any] | None = None,
    *,
    legacy_reason_format: bool = False,
) -> list[str]:
    metrics = run.get("metrics") if isinstance(run.get("metrics"), Mapping) else {}
    contract = _normalized_contract(
        contract if isinstance(contract, Mapping) else {}
    )
    case_id = str(run.get("case_id") or "")
    prefix = f"case:{case_id}:" if case_id else "case:unknown:"
    failures = []
    contract = contract or {}
    expected_tools = _safe_list(contract.get("expected_tools"), ALLOWED_TOOLS)
    actual_tools = _actual_tools(metrics)
    if contract:
        if actual_tools != expected_tools:
            failures.append("expected_tools_mismatch")
        expected_intent = str(contract.get("expected_intent") or "")
        if expected_intent and str(metrics.get("intent_kind") or "") != expected_intent:
            failures.append(
                f"{prefix}unexpected_intent:{str(metrics.get('intent_kind') or 'missing')}"
                if legacy_reason_format
                else "expected_intent_mismatch"
            )
        allowed_evidence = tuple(
            str(value) for value in contract.get("allowed_evidence_status") or ()
        )
        if allowed_evidence and str(metrics.get("evidence_status") or "") not in allowed_evidence:
            failures.append(
                f"{prefix}evidence_status_not_allowed:{str(metrics.get('evidence_status') or 'missing')}"
                if legacy_reason_format
                else "evidence_status_not_allowed"
            )
        expected_sources = _safe_list(
            contract.get("expected_source_kinds"), ALLOWED_SOURCE_KINDS
        )
        actual_sources = _source_kinds(metrics)
        if expected_sources and actual_sources != expected_sources:
            failures.append("expected_source_kinds_mismatch")
        allowed_sources = _safe_list(
            contract.get("allowed_source_kinds"), ALLOWED_SOURCE_KINDS
        )
        if allowed_sources and any(
            source not in allowed_sources for source in actual_sources
        ):
            failures.append("source_kind_not_allowed")
        metric_assertions = (
            metrics.get("assertions")
            if isinstance(metrics.get("assertions"), Mapping)
            else {}
        )
        run_assertions = (
            run.get("assertions")
            if isinstance(run.get("assertions"), Mapping)
            else {}
        )
        assertions = {**run_assertions, **metric_assertions}
        for assertion in _required_assertions(contract):
            if assertion not in assertions:
                failures.append(
                    f"{prefix}assertion_missing:{assertion}"
                    if legacy_reason_format
                    else f"assertion_failed:{assertion}"
                )
            elif assertions.get(assertion) is not True:
                failures.append(
                    f"{prefix}assertion_failed:{assertion}"
                    if legacy_reason_format
                    else f"assertion_failed:{assertion}"
                )
    elif metrics.get("tool_called") != "rag_chat":
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
    tools_requiring_feedback = expected_tools if contract else actual_tools
    if "rag_chat" in tools_requiring_feedback and not metrics.get("feedback_link_present"):
        failures.append("feedback_link_missing")
    if metrics.get("evidence_status") == "supported" and not (
        int(metrics.get("source_count") or 0) > 0
    ):
        failures.append("supported_answer_without_source")

    return failures


def _comparison_value(run: Mapping[str, Any], field: str) -> Any:
    metrics = run.get("metrics") if isinstance(run.get("metrics"), Mapping) else {}
    comparison = (
        run.get("comparison") if isinstance(run.get("comparison"), Mapping) else {}
    )
    value = metrics.get(field) if field == "evidence_status" else comparison.get(field)
    if field == "source_ids":
        if not isinstance(value, (list, tuple, set)):
            return ()
        return tuple(sorted({str(item) for item in value if str(item)}))
    return str(value or "")


def _parity_failures(
    runs: Iterable[Mapping[str, Any]],
    case_contracts: Mapping[str, Mapping[str, Any]],
) -> dict[tuple[str, str, str], list[str]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for run in runs:
        case_id = str(run.get("case_id") or "")
        profile = str(run.get("profile") or "")
        contract = case_contracts.get(case_id) or {}
        if contract.get("compare_across_models"):
            grouped.setdefault((profile, case_id), []).append(run)

    failures: dict[tuple[str, str, str], list[str]] = {}
    for (profile, case_id), matching in grouped.items():
        fields = [str(field) for field in case_contracts[case_id].get("compare_across_models") or []]
        mismatches = [
            field
            for field in fields
            if len({_comparison_value(run, field) for run in matching}) > 1
            or any(not _comparison_value(run, field) for run in matching)
        ]
        if not mismatches:
            continue
        reason = f"case:{case_id}:model_parity_mismatch:{','.join(mismatches)}"
        for run in matching:
            metrics = run.get("metrics") if isinstance(run.get("metrics"), Mapping) else {}
            model_name = str(metrics.get("model_name") or metrics.get("model_id") or "")
            failures.setdefault((model_name, profile, case_id), []).append(reason)
    return failures


def case_contracts_from_matrix(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    contracts: dict[str, dict[str, Any]] = {}
    for case in payload.get("cases") or ():
        if not isinstance(case, Mapping):
            continue
        case_id = str(case.get("id") or "")
        if case_id and case_id.replace("_", "").isalnum():
            contracts[case_id] = dict(case)
    return contracts


def _matrix_contract(
    matrix: Mapping[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...], dict[str, dict[str, Any]]]:
    if matrix.get("schema_version") != "kahle.harness-acceptance-matrix.v1":
        raise MatrixContractError("matrix_schema_invalid")
    raw_models = matrix.get("expected_models")
    raw_profiles = matrix.get("profiles")
    raw_cases = matrix.get("cases")
    if not isinstance(raw_models, list) or not raw_models:
        raise MatrixContractError("matrix_models_required")
    if not isinstance(raw_profiles, list) or not raw_profiles:
        raise MatrixContractError("matrix_profiles_required")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise MatrixContractError("matrix_cases_required")

    models = tuple(dict.fromkeys(str(model) for model in raw_models))
    profiles = tuple(dict.fromkeys(str(profile) for profile in raw_profiles))
    if len(models) != len(raw_models) or any(not MODEL_ID.fullmatch(model) for model in models):
        raise MatrixContractError("matrix_model_id_invalid")
    if len(profiles) != len(raw_profiles) or any(profile not in ALLOWED_PROFILES for profile in profiles):
        raise MatrixContractError("matrix_profile_invalid")

    contracts = case_contracts_from_matrix(matrix)
    if len(contracts) != len(raw_cases):
        raise MatrixContractError("matrix_case_id_invalid")
    for case_id, contract in contracts.items():
        if not CASE_ID.fullmatch(case_id):
            raise MatrixContractError("matrix_case_id_invalid")
        expected_tools = contract.get("expected_tools")
        if not isinstance(expected_tools, list) or _safe_list(expected_tools, ALLOWED_TOOLS) != expected_tools:
            raise MatrixContractError("matrix_expected_tools_invalid")
        if contract.get("expected_intent") not in ALLOWED_INTENTS:
            raise MatrixContractError("matrix_intent_invalid")
        statuses = contract.get("allowed_evidence_status")
        if (
            not isinstance(statuses, list)
            or not statuses
            or _safe_list(statuses, ALLOWED_EVIDENCE_STATUS) != statuses
        ):
            raise MatrixContractError("matrix_evidence_status_invalid")
        for source_key in ("expected_source_kinds", "allowed_source_kinds"):
            source_kinds = contract.get(source_key)
            if source_kinds is not None and (
                not isinstance(source_kinds, list)
                or _safe_list(source_kinds, ALLOWED_SOURCE_KINDS) != source_kinds
            ):
                raise MatrixContractError("matrix_source_kinds_invalid")
        case_profiles = contract.get("profiles", profiles)
        if (
            not isinstance(case_profiles, (list, tuple))
            or not case_profiles
            or any(profile not in profiles for profile in case_profiles)
        ):
            raise MatrixContractError("matrix_case_profile_invalid")
        if not isinstance(contract.get("forbidden_fields"), list) or not contract.get("forbidden_fields"):
            raise MatrixContractError("matrix_forbidden_fields_required")
        raw_assertions = contract.get("required_assertions") or []
        if not isinstance(raw_assertions, list) or any(
            not isinstance(assertion, str) or not ASSERTION_ID.fullmatch(assertion)
            for assertion in raw_assertions
        ):
            raise MatrixContractError("matrix_assertion_id_invalid")
    return models, profiles, contracts


def _run_identity(run: Mapping[str, Any]) -> tuple[str, str, str]:
    metrics = run.get("metrics") if isinstance(run.get("metrics"), Mapping) else {}
    return (
        str(metrics.get("model_id") or metrics.get("model_name") or ""),
        str(run.get("profile") or ""),
        str(run.get("case_id") or ""),
    )


def _safe_result(
    run: Mapping[str, Any],
    contract: Mapping[str, Any],
    *,
    known_case_ids: set[str],
    known_model_ids: set[str],
) -> dict[str, Any]:
    metrics = run.get("metrics") if isinstance(run.get("metrics"), Mapping) else {}
    required = _required_assertions(contract)
    incoming_assertions = (
        metrics.get("assertions")
        if isinstance(metrics.get("assertions"), Mapping)
        else {}
    )
    assertions = {
        name: incoming_assertions.get(name) is True
        for name in required
    }
    latency = metrics.get("latency_ms")
    case_id = str(run.get("case_id") or "")
    model_id = str(metrics.get("model_id") or metrics.get("model_name") or "")
    validation_status = (
        metrics.get("delivery_status")
        or metrics.get("final_validation_status")
        or ""
    )
    return {
        "case_id": case_id if case_id in known_case_ids else "unknown_case",
        "model_id": model_id if model_id in known_model_ids else "unknown_model",
        "expected_tools": _safe_list(contract.get("expected_tools"), ALLOWED_TOOLS),
        "actual_tools": _actual_tools(metrics),
        "intent": _safe_value(
            metrics.get("intent_kind"), ALLOWED_INTENTS, "unknown_intent"
        ),
        "evidence_status": _safe_value(
            metrics.get("evidence_status"), ALLOWED_EVIDENCE_STATUS, "unknown"
        ),
        "source_kinds": _source_kinds(metrics),
        "validation_status": _safe_value(
            validation_status, ALLOWED_VALIDATION_STATUS, "unknown"
        ),
        "latency_ms": int(latency) if isinstance(latency, (int, float)) else None,
        "assertions": assertions,
    }


def build_acceptance_report(
    runs: Iterable[Mapping[str, Any]],
    *,
    matrix: Mapping[str, Any] | None = None,
    profile_authorization: Mapping[str, bool] | None = None,
    expected_models: Iterable[str] = (),
    required_case_ids: Iterable[str] = (),
    case_contracts: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_runs = [dict(run) for run in runs if isinstance(run, Mapping)]
    authorization = profile_authorization or {}
    if matrix is not None:
        models, profiles, contracts = _matrix_contract(matrix)
        legacy_mode = False
    else:
        legacy_mode = True
        legacy_required_cases = tuple(str(case_id) for case_id in required_case_ids)
        legacy_required_case_set = set(legacy_required_cases)
        models = tuple(dict.fromkeys(str(model) for model in expected_models))
        profiles = tuple(dict.fromkeys(str(profile) for profile in authorization))
        contracts = {
            str(case_id): _normalized_contract(contract)
            for case_id, contract in (case_contracts or {}).items()
            if not legacy_required_cases or str(case_id) in legacy_required_case_set
        }
    parity_failures = _parity_failures(normalized_runs, contracts)
    by_model_profile: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for run in normalized_runs:
        model_name, profile, _ = _run_identity(run)
        if model_name in models and profile in profiles:
            by_model_profile.setdefault((model_name, profile), []).append(run)

    coverage = []
    counts = {"passed": 0, "failed": 0, "unavailable": 0, "not_authorized": 0}
    for profile in profiles:
        authorized = authorization.get(profile) is True
        required_cases = tuple(
            case_id
            for case_id, contract in contracts.items()
            if profile in tuple(contract.get("profiles") or profiles)
        )
        for model_name in models:
            matching = by_model_profile.get((model_name, str(profile)), [])
            reasons: list[str] = []
            if not authorized:
                status = "not_authorized"
                reasons = ["profile_not_authorized"]
            elif not matching:
                status = "unavailable"
                reasons = ["model_unavailable"]
            else:
                for run in matching:
                    reasons.extend(
                        _run_failures(
                            run,
                            contracts.get(str(run.get("case_id") or "")),
                            legacy_reason_format=legacy_mode,
                        )
                    )
                    reasons.extend(
                        parity_failures.get(_run_identity(run), ())
                    )
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

    accepted_metrics = []
    for run in normalized_runs:
        model_name, profile, case_id = _run_identity(run)
        metrics = run.get("metrics")
        if (
            model_name in models
            and profile in profiles
            and authorization.get(profile) is True
            and case_id in contracts
            and isinstance(metrics, Mapping)
            and not _run_failures(
                run,
                contracts[case_id],
                legacy_reason_format=legacy_mode,
            )
        ):
            accepted_metrics.append(metrics)
    latencies = [
        int(metrics["latency_ms"])
        for metrics in accepted_metrics
        if isinstance(metrics.get("latency_ms"), (int, float))
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "summary": counts,
        "coverage": coverage,
        "results": [
            _safe_result(
                run,
                contracts.get(str(run.get("case_id") or ""), {}),
                known_case_ids=set(contracts),
                known_model_ids=set(models),
            )
            for run in normalized_runs
        ],
        "metrics": {
            "sample_size": len(accepted_metrics),
            "latency_p50_ms": _nearest_rank(latencies, 0.50),
            "latency_p95_ms": _nearest_rank(latencies, 0.95),
        },
    }


def build_report_from_payload(
    payload: Mapping[str, Any], *, matrix: Mapping[str, Any]
) -> dict[str, Any]:
    runs = payload.get("runs")
    authorization = payload.get("profile_authorization")
    return build_acceptance_report(
        runs if isinstance(runs, list) else (),
        matrix=matrix,
        profile_authorization=(
            authorization if isinstance(authorization, Mapping) else {}
        ),
    )


def acceptance_exit_code(report: Mapping[str, Any]) -> int:
    coverage = report.get("coverage")
    if not isinstance(coverage, list) or not coverage:
        return 1
    if not all(isinstance(entry, Mapping) for entry in coverage):
        return 1
    return 0 if all(entry.get("status") == "passed" for entry in coverage) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON file containing runs and coverage")
    args = parser.parse_args()
    loaded_payload = json.loads(args.input.read_text(encoding="utf-8"))
    payload = loaded_payload if isinstance(loaded_payload, Mapping) else {}
    matrix_path = Path(__file__).with_name("kahle-harness-acceptance-matrix.json")
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    report = build_report_from_payload(payload, matrix=matrix)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return acceptance_exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())

"""Privacy-safe routing and answer metrics for the KAHLE knowledge harness.

Results carry identifiers, tool sets, violation codes, abstention flags and
latencies only. Questions and answer texts never leave this module.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

SCHEMA_VERSION = "kahle.harness-eval.v1"
CORPUS_SCHEMA_VERSION = "kahle.harness-routing-cases.v1"
KNOWLEDGE_TOOLS = frozenset({"personio_directory", "rag_chat"})
# Only codes that signal a false statement or a missing proof count as
# blocking. Heuristic validator codes produce false alarms (analysis K4).
BLOCKING_VIOLATION_CODES = frozenset(
    {
        "answer_missing",
        "unknown_source_id",
        "citation_missing",
        "unbound_contact_literal",
        "unbound_link_target",
        "contact_link_mismatch",
        "required_document_sections_missing",
    }
)
_ABSTENTION = re.compile(
    r"(?i)\b(?:keine\s+(?:verlässliche|verlaessliche|passende)\s+freigegebene"
    r"|kein(?:e)?\s+intern(?:es|en)?\s+(?:wissen|informationen?))"
)
_CASE_ID = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_BOOLEAN_FLAGS = ("expected_procedural", "expect_abstention")


@dataclass(frozen=True)
class RoutingCase:
    case_id: str
    category: str
    question: str
    expected_tools: frozenset[str]
    history: tuple[dict[str, str], ...] = ()
    findings: tuple[str, ...] = ()
    expected_procedural: bool | None = None
    expect_abstention: bool | None = None

    def messages(self) -> list[dict[str, str]]:
        return [
            *(dict(turn) for turn in self.history),
            {"role": "user", "content": self.question},
        ]


def _parse_case(raw: Any) -> RoutingCase:
    if not isinstance(raw, dict):
        raise ValueError("Jeder Fall muss ein Mapping sein.")
    case_id = str(raw.get("id") or "")
    if not _CASE_ID.fullmatch(case_id):
        raise ValueError(f"Ungültige Fall-ID: {case_id!r}")
    question = str(raw.get("question") or "").strip()
    category = str(raw.get("category") or "").strip()
    if not question or not category:
        raise ValueError(f"{case_id}: question und category sind Pflicht.")
    expected = raw.get("expected_tools")
    if not isinstance(expected, list) or not set(expected) <= KNOWLEDGE_TOOLS:
        raise ValueError(
            f"{case_id}: expected_tools muss eine Teilmenge von "
            f"{sorted(KNOWLEDGE_TOOLS)} sein."
        )
    history: list[dict[str, str]] = []
    for turn in raw.get("history") or ():
        if (
            not isinstance(turn, dict)
            or turn.get("role") not in {"user", "assistant"}
            or not str(turn.get("content") or "").strip()
        ):
            raise ValueError(f"{case_id}: history enthält einen ungültigen Turn.")
        history.append({"role": turn["role"], "content": str(turn["content"])})
    for flag in _BOOLEAN_FLAGS:
        if flag in raw and not isinstance(raw[flag], bool):
            raise ValueError(f"{case_id}: {flag} muss true oder false sein.")
    return RoutingCase(
        case_id=case_id,
        category=category,
        question=question,
        expected_tools=frozenset(expected),
        history=tuple(history),
        findings=tuple(str(item) for item in raw.get("findings") or ()),
        expected_procedural=raw.get("expected_procedural"),
        expect_abstention=raw.get("expect_abstention"),
    )


def load_cases(path: Path) -> list[RoutingCase]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if payload.get("schema_version") != CORPUS_SCHEMA_VERSION:
        raise ValueError("Unbekannte schema_version im Routing-Korpus.")
    cases = [_parse_case(item) for item in payload.get("cases") or ()]
    ids = [case.case_id for case in cases]
    duplicates = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
    if duplicates:
        raise ValueError(f"Doppelte Fall-IDs: {duplicates}")
    return cases


def routing_outcome(expected: Iterable[str], actual: Iterable[str]) -> str:
    expected_set = frozenset(expected) & KNOWLEDGE_TOOLS
    actual_set = frozenset(actual) & KNOWLEDGE_TOOLS
    if actual_set == expected_set:
        return "correct"
    if actual_set < expected_set:
        return "missing_source"
    if actual_set > expected_set:
        return "extra_source"
    return "wrong_source"


def nearest_rank(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _rate(part: int, total: int) -> float:
    return round(part / total, 4) if total else 0.0


def summarize_routing(rows: list[dict[str, Any]]) -> dict[str, Any]:
    models: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = models.setdefault(
            str(row["model"]),
            {
                "total": 0,
                "correct": 0,
                "outcomes": Counter(),
                "categories": {},
                "procedural_checked": 0,
                "procedural_correct": 0,
            },
        )
        correct = row["outcome"] == "correct"
        entry["total"] += 1
        entry["correct"] += int(correct)
        entry["outcomes"][str(row["outcome"])] += 1
        category = entry["categories"].setdefault(str(row["category"]), [0, 0])
        category[0] += 1
        category[1] += int(correct)
        if row.get("procedural_match") is not None:
            entry["procedural_checked"] += 1
            entry["procedural_correct"] += int(bool(row["procedural_match"]))
    return {
        model: {
            "total": entry["total"],
            "correct": entry["correct"],
            "accuracy": _rate(entry["correct"], entry["total"]),
            "outcomes": dict(sorted(entry["outcomes"].items())),
            "by_category": {
                name: {"total": total, "correct": correct, "accuracy": _rate(correct, total)}
                for name, (total, correct) in sorted(entry["categories"].items())
            },
            "procedural_checked": entry["procedural_checked"],
            "procedural_accuracy": _rate(
                entry["procedural_correct"], entry["procedural_checked"]
            ),
        }
        for model, entry in sorted(models.items())
    }


def actual_knowledge_tools(message: dict[str, Any]) -> frozenset[str]:
    names = {
        str(item.get("name") or "")
        for item in message.get("output") or ()
        if isinstance(item, dict) and item.get("type") == "function_call"
    }
    metrics = message.get("kahle_harness_metrics") or {}
    comparison = metrics.get("routing_comparison") or {}
    names.update(str(tool) for tool in comparison.get("actual_tools") or ())
    return frozenset(names) & KNOWLEDGE_TOOLS


def answer_text(message: dict[str, Any]) -> str:
    content = str(message.get("content") or "").strip()
    if content:
        return content
    parts = [
        str(part.get("text") or "")
        for item in message.get("output") or ()
        if isinstance(item, dict) and item.get("type") == "message"
        for part in item.get("content") or ()
        if isinstance(part, dict) and part.get("type") == "output_text"
    ]
    return "\n".join(part for part in parts if part).strip()


def _last_validation_attempt(message: dict[str, Any]) -> dict[str, Any]:
    attempts = (message.get("kahle_answer_validation") or {}).get("attempts") or []
    last = attempts[-1] if attempts else {}
    return last if isinstance(last, dict) else {}


def score_answer(case: RoutingCase, message: dict[str, Any]) -> dict[str, Any]:
    text = answer_text(message)
    attempt = _last_validation_attempt(message)
    # Recorded severity wins; older records without it fall back to the code list.
    blocking = sorted(
        {
            str(violation.get("code") or "")
            for violation in attempt.get("violations") or ()
            if isinstance(violation, dict)
            and (
                violation.get("severity") == "blocking"
                or (
                    "severity" not in violation
                    and violation.get("code") in BLOCKING_VIOLATION_CODES
                )
            )
        }
    )
    abstained = bool(_ABSTENTION.search(text))
    metrics = message.get("kahle_harness_metrics") or {}
    latency = metrics.get("latency_ms")
    return {
        "blocking_violations": blocking,
        "validation_status": str(attempt.get("status") or "not_run"),
        "abstained": abstained,
        "abstention_correct": (
            None if case.expect_abstention is None else abstained == case.expect_abstention
        ),
        "answer_present": bool(text),
        "latency_ms": (
            int(latency) if isinstance(latency, (int, float)) and latency >= 0 else None
        ),
        "retry_count": int(metrics.get("retry_count") or 0),
        "fallback_used": bool(metrics.get("fallback_used")),
        "delivery_status": str(metrics.get("delivery_status") or "not_run"),
    }


def summarize_answers(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["model"]), []).append(row)
    summary: dict[str, Any] = {}
    for model, items in sorted(grouped.items()):
        checked = [row for row in items if row.get("abstention_correct") is not None]
        latencies = [row["latency_ms"] for row in items if isinstance(row.get("latency_ms"), int)]
        walls = [row["wall_ms"] for row in items if isinstance(row.get("wall_ms"), int)]
        codes = Counter(
            code for row in items for code in row.get("blocking_violations") or ()
        )
        summary[model] = {
            "total": len(items),
            "answer_present_rate": _rate(
                sum(bool(row.get("answer_present")) for row in items), len(items)
            ),
            "blocking_violation_rate": _rate(
                sum(bool(row.get("blocking_violations")) for row in items), len(items)
            ),
            "blocking_violation_codes": dict(sorted(codes.items())),
            "abstention_checked": len(checked),
            "abstention_accuracy": _rate(
                sum(bool(row["abstention_correct"]) for row in checked), len(checked)
            ),
            "retry_rate": _rate(
                sum(int(row.get("retry_count") or 0) > 0 for row in items), len(items)
            ),
            "fallback_rate": _rate(
                sum(bool(row.get("fallback_used")) for row in items), len(items)
            ),
            "latency_p50_ms": nearest_rank(latencies, 0.5),
            "latency_p95_ms": nearest_rank(latencies, 0.95),
            "wall_p50_ms": nearest_rank(walls, 0.5),
            "wall_p95_ms": nearest_rank(walls, 0.95),
        }
    return summary

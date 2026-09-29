"""Privacy-safe routing and answer metrics for the KAHLE knowledge harness.

Results carry identifiers, tool sets, violation codes, abstention flags and
latencies only. Questions and answer texts never leave this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = "kahle.harness-eval.v1"
CORPUS_SCHEMA_VERSION = "kahle.harness-routing-cases.v1"
KNOWLEDGE_TOOLS = frozenset({"personio_directory", "rag_chat"})
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

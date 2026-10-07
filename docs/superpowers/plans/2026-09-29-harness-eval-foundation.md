# Harness-Eval-Grundlage (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein reproduzierbarer Eval misst Quellenrouting und Antwortqualität des KAHLE-Wissens-Harness. Er läuft offline gegen den Harness-Planer und zur Laufzeit je Vinci-Modell gegen die lokale Open-WebUI-Umgebung. Er ist die Baseline für die Phasen 0, 2, 3 und 4 der [Roadmap](2026-09-29-harness-quality-roadmap.md).

**Architecture:** Neues Verzeichnis `eval/harness/`.

- **Korpus:** Ein versioniertes YAML (`routing_cases.yml`) beschreibt Fälle mit erwarteter Quellenmenge nach ADR-008.
- **`harness_eval.py`:** Reine Funktionen für Laden, Routing-Bewertung und Antwort-Bewertung. Die Metriken enthalten keine Personendaten.
- **`offline_routing_eval.py`:** Bewertet `resolve_request` und `plan_retrieval` des Harness ohne Modell. Läuft daher auch, solange IONOS gestört ist.
- **`runtime_harness_eval.py`:** Schickt jeden Fall über die persistierte Open-WebUI-Chatschleife an `localhost:3004`, einmal je Modell, und liest `kahle_harness_metrics` und `kahle_answer_validation` aus der gespeicherten Nachricht. Dafür wird der bestehende Client aus `eval/rag/run_runtime_eval.py` wiederverwendet.
- **Ergebnisse:** Sie enthalten weder Antworttexte noch Fragen, nur IDs, Toolmengen, Verstoßcodes, Enthaltungs-Flags und Latenzen.

**Tech Stack:** Python 3.11 (`.venv-verify`), pytest, PyYAML, requests, PowerShell-Verification-Runner.

---

## Vorbereitung

`main` enthält uncommittete Änderungen an Guard und Orchestrator, die nicht zu diesem Plan gehören. Nicht stashen, nicht mitcommitten, nur die in den Tasks genannten Dateien stagen.

```bash
git switch -c feat/harness-eval-foundation
```

Targeted-Testbefehl für diesen Plan (aus dem Repository-Root):

```bash
./.venv-verify/Scripts/python.exe -m pytest eval/harness/tests -q -p no:cacheprovider
```

## Dateistruktur

| Datei | Verantwortung |
| --- | --- |
| Create `eval/harness/_repo_paths.py` | Setzt die Importpfade (Harness-Override, Tool-Quellen, `eval/rag`) für Tests und CLIs |
| Create `eval/harness/harness_eval.py` | Fallmodell, Korpus laden, Routing- und Antwortbewertung, Zusammenfassungen |
| Create `eval/harness/routing_cases.yml` | Versionierter Routing-Korpus (99 Fälle) |
| Create `eval/harness/offline_routing_eval.py` | Offline-CLI gegen den Harness-Planer |
| Create `eval/harness/runtime_harness_eval.py` | Laufzeit-CLI gegen Open WebUI je Modell |
| Modify `eval/rag/run_runtime_eval.py` | `_start_and_wait()` aus `ask()` herauslösen (Wiederverwendung) |
| Create `eval/harness/tests/conftest.py` | Importpfade für pytest |
| Create `eval/harness/tests/test_harness_eval.py` | Unit-Tests der Bewertungsfunktionen |
| Create `eval/harness/tests/test_routing_corpus.py` | Vertragstests für den echten Korpus |
| Create `eval/harness/tests/test_offline_routing_eval.py` | Offline-Runner |
| Create `eval/harness/tests/test_runtime_harness_eval.py` | Laufzeit-Runner mit Fake-Session |
| Create `eval/harness/results/2026-09-29-offline-baseline.json` | Eingecheckte Offline-Baseline |
| Modify `.gitignore` | Rohzeilen `eval/harness/results/*.jsonl` ignorieren |
| Modify `scripts/run-local-tests.ps1` | Suite „Harness-Evaluation“ in Fast/Full |
| Modify `docs/VERIFICATION.md` | Tier-Tabelle und Specialized-Befehl |

---

### Task 1: Importpfade für Tests und CLIs

**Files:**
- Create: `eval/harness/_repo_paths.py`
- Create: `eval/harness/tests/conftest.py`
- Test: `eval/harness/tests/test_harness_eval.py`

- [ ] **Step 1: Write the failing test**

`eval/harness/tests/test_harness_eval.py`:

```python
def test_harness_module_is_importable_from_eval_paths():
    import kahle_knowledge_harness

    assert kahle_knowledge_harness.SCHEMA_VERSION == "kahle.knowledge-harness.v1"
```

`eval/harness/tests/conftest.py`:

```python
import sys
from pathlib import Path

HARNESS_EVAL_DIR = Path(__file__).resolve().parents[1]
if str(HARNESS_EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(HARNESS_EVAL_DIR))

from _repo_paths import ensure_repo_paths  # noqa: E402

ensure_repo_paths()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv-verify/Scripts/python.exe -m pytest eval/harness/tests -q -p no:cacheprovider`
Expected: FAIL/ERROR mit `ModuleNotFoundError: No module named '_repo_paths'`

- [ ] **Step 3: Write minimal implementation**

`eval/harness/_repo_paths.py`:

```python
"""Import paths for the harness evaluation, independent of the working directory."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_RELATIVE_PATHS = (
    "eval/harness",
    "eval/rag",
    "stack/open-webui-tools",
    "stack/open-webui-overrides/open_webui/utils",
)


def ensure_repo_paths() -> None:
    for relative in reversed(_RELATIVE_PATHS):
        path = str(REPO_ROOT / relative)
        if path not in sys.path:
            sys.path.insert(0, path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv-verify/Scripts/python.exe -m pytest eval/harness/tests -q -p no:cacheprovider`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add eval/harness/_repo_paths.py eval/harness/tests/conftest.py eval/harness/tests/test_harness_eval.py
git commit -m "test(eval): bootstrap harness evaluation import paths"
```

---

### Task 2: Fallmodell und Korpus laden

**Files:**
- Create: `eval/harness/harness_eval.py`
- Test: `eval/harness/tests/test_harness_eval.py`

- [ ] **Step 1: Write the failing tests**

An `eval/harness/tests/test_harness_eval.py` anhängen:

```python
import pytest

from harness_eval import load_cases


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv-verify/Scripts/python.exe -m pytest eval/harness/tests -q -p no:cacheprovider`
Expected: ERROR `ModuleNotFoundError: No module named 'harness_eval'`

- [ ] **Step 3: Write minimal implementation**

`eval/harness/harness_eval.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv-verify/Scripts/python.exe -m pytest eval/harness/tests -q -p no:cacheprovider`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add eval/harness/harness_eval.py eval/harness/tests/test_harness_eval.py
git commit -m "feat(eval): load versioned harness routing cases"
```

---

### Task 3: Routing bewerten und zusammenfassen

**Files:**
- Modify: `eval/harness/harness_eval.py`
- Test: `eval/harness/tests/test_harness_eval.py`

- [ ] **Step 1: Write the failing tests**

An `eval/harness/tests/test_harness_eval.py` anhängen:

```python
from harness_eval import nearest_rank, routing_outcome, summarize_routing


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv-verify/Scripts/python.exe -m pytest eval/harness/tests -q -p no:cacheprovider`
Expected: ERROR `ImportError: cannot import name 'nearest_rank'`

- [ ] **Step 3: Write minimal implementation**

An `eval/harness/harness_eval.py` anhängen (Imports oben ergänzen: `import math`, `from collections import Counter`, `from typing import Any, Iterable`):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv-verify/Scripts/python.exe -m pytest eval/harness/tests -q -p no:cacheprovider`
Expected: `18 passed`

- [ ] **Step 5: Commit**

```bash
git add eval/harness/harness_eval.py eval/harness/tests/test_harness_eval.py
git commit -m "feat(eval): score and summarize harness source routing"
```

---

### Task 4: Antworten bewerten, ohne Text zu speichern

Blockierend sind nur Codes, die eine falsche Aussage oder einen fehlenden Beleg
anzeigen. Heuristische Codes (`unsupported_technical_approval` usw.) zählen
nicht, weil sie laut Analyse K4 Fehlalarme erzeugen. Phase 0 überführt diese
Liste in Schweregrade im Harness selbst.

**Files:**
- Modify: `eval/harness/harness_eval.py`
- Test: `eval/harness/tests/test_harness_eval.py`

- [ ] **Step 1: Write the failing tests**

An `eval/harness/tests/test_harness_eval.py` anhängen:

```python
import json

from harness_eval import (
    RoutingCase,
    actual_knowledge_tools,
    answer_text,
    score_answer,
    summarize_answers,
)


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv-verify/Scripts/python.exe -m pytest eval/harness/tests -q -p no:cacheprovider`
Expected: ERROR `ImportError: cannot import name 'actual_knowledge_tools'`

- [ ] **Step 3: Write minimal implementation**

In `eval/harness/harness_eval.py` unter `KNOWLEDGE_TOOLS` ergänzen:

```python
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
```

Am Dateiende anhängen:

```python
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
    codes = {
        str(violation.get("code") or "")
        for violation in attempt.get("violations") or ()
        if isinstance(violation, dict)
    }
    abstained = bool(_ABSTENTION.search(text))
    latency = (message.get("kahle_harness_metrics") or {}).get("latency_ms")
    return {
        "blocking_violations": sorted(codes & BLOCKING_VIOLATION_CODES),
        "validation_status": str(attempt.get("status") or "not_run"),
        "abstained": abstained,
        "abstention_correct": (
            None if case.expect_abstention is None else abstained == case.expect_abstention
        ),
        "answer_present": bool(text),
        "latency_ms": (
            int(latency) if isinstance(latency, (int, float)) and latency >= 0 else None
        ),
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
            "latency_p50_ms": nearest_rank(latencies, 0.5),
            "latency_p95_ms": nearest_rank(latencies, 0.95),
            "wall_p50_ms": nearest_rank(walls, 0.5),
            "wall_p95_ms": nearest_rank(walls, 0.95),
        }
    return summary
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv-verify/Scripts/python.exe -m pytest eval/harness/tests -q -p no:cacheprovider`
Expected: `23 passed`

- [ ] **Step 5: Commit**

```bash
git add eval/harness/harness_eval.py eval/harness/tests/test_harness_eval.py
git commit -m "feat(eval): score harness answers without retaining answer text"
```

---

### Task 5: Routing-Korpus

Erwartete Quellen folgen ADR-008:

- Personen, Rollenlisten, Standorte, Onboarding-Personen und Führungskräfte → `personio_directory`
- Prozesse, Zuständigkeiten, Funktionspostfächer, Abkürzungen und Geltungsbereiche → `rag_chat`
- Abteilungskontakte und Fragen, die eine Person mit einem Prozess verbinden → beide
- Schreibaufträge, Code, Allgemeinwissen, Datum, Aufgaben und Websuche → kein Wissens-Tool

Die Namen sind Testnamen.

**Files:**
- Create: `eval/harness/routing_cases.yml`
- Test: `eval/harness/tests/test_routing_corpus.py`

- [ ] **Step 1: Write the failing test**

`eval/harness/tests/test_routing_corpus.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv-verify/Scripts/python.exe -m pytest eval/harness/tests/test_routing_corpus.py -q -p no:cacheprovider`
Expected: FAIL mit `FileNotFoundError` für `routing_cases.yml`

- [ ] **Step 3: Create the corpus**

`eval/harness/routing_cases.yml`:

```yaml
schema_version: kahle.harness-routing-cases.v1
# Erwartete Quellen nach ADR-008. Testnamen, keine realen Mitarbeiterdaten.
# findings verweisen auf docs/research/2026-09-29-vinci-harness-analyse.md.
cases:
  # --- Personio: einzelne Person ---
  - {id: person_profile_mustermann, category: personio_person, question: "Wer ist Max Mustermann?", expected_tools: [personio_directory]}
  - {id: person_phone_mustermann, category: personio_person, question: "Welche Telefonnummer hat Max Mustermann?", expected_tools: [personio_directory]}
  - {id: person_reach_beispiel, category: personio_person, question: "Wie erreiche ich Anna Beispiel?", expected_tools: [personio_directory]}
  - {id: person_job_beispiel, category: personio_person, question: "Was macht Anna Beispiel bei uns?", expected_tools: [personio_directory]}
  - {id: person_position_mustermann, category: personio_person, question: "Welche Position hat Max Mustermann?", expected_tools: [personio_directory]}
  - {id: person_location_beispiel, category: personio_person, question: "Wo arbeitet Anna Beispiel?", expected_tools: [personio_directory]}
  - {id: person_contact_mustermann, category: personio_person, question: "Kontaktdaten von Max Mustermann bitte", expected_tools: [personio_directory]}
  - {id: person_info_beispiel, category: personio_person, question: "Infos über Anna Beispiel", expected_tools: [personio_directory]}
  # --- Personio: Rollen- und Standortlisten ---
  - {id: list_serviceberater_wunstorf, category: personio_list, question: "Wer sind die Serviceberater in Wunstorf?", expected_tools: [personio_directory]}
  - {id: list_teiledienst_hannover, category: personio_list, question: "Welche Mitarbeiter arbeiten im Teiledienst in Hannover?", expected_tools: [personio_directory]}
  - {id: list_serviceassistenz_nominal, category: personio_list, question: "Serviceassistenzen Neustadt", expected_tools: [personio_directory]}
  - {id: list_verkaeufer_stadthagen, category: personio_list, question: "Liste mir alle Verkäufer in Stadthagen auf", expected_tools: [personio_directory]}
  - {id: list_buchhaltung_people, category: personio_list, question: "Wer arbeitet in der Buchhaltung?", expected_tools: [personio_directory]}
  - {id: list_marketing_people, category: personio_list, question: "Welche Kollegen sind im Marketing?", expected_tools: [personio_directory]}
  - {id: list_automobilverkaeufer_walsrode, category: personio_list, question: "Gib mir die Automobilverkäufer in Walsrode", expected_tools: [personio_directory]}
  - {id: list_count_serviceberater_nienburg, category: personio_list, question: "Wie viele Serviceberater gibt es in Nienburg?", expected_tools: [personio_directory]}
  # --- Personio: Führungskräfte ---
  - {id: supervisor_von_mustermann, category: supervisor, question: "Wer ist die Führungskraft von Max Mustermann?", expected_tools: [personio_directory]}
  - {id: supervisor_vorgesetzter_beispiel, category: supervisor, question: "Wer ist der Vorgesetzte von Anna Beispiel?", expected_tools: [personio_directory]}
  - {id: supervisor_genitive_mustermann, category: supervisor, question: "Wer ist Max Mustermanns Führungskraft?", expected_tools: [personio_directory]}
  - {id: supervisor_typo, category: supervisor, question: "Wer ist die Fürhungskraft von Anna Beispiel?", expected_tools: [personio_directory]}
  - {id: supervisor_team_lead_beispiel, category: supervisor, question: "Wer leitet das Team von Anna Beispiel?", expected_tools: [personio_directory]}
  - {id: supervisor_role_group, category: supervisor, question: "Wer ist der Chef der Serviceberater in Wunstorf?", expected_tools: [personio_directory]}
  # --- Personio: Onboarding-Personen ---
  - {id: onboarding_people_now, category: onboarding_people, question: "Wer ist gerade im Onboarding?", expected_tools: [personio_directory]}
  - {id: onboarding_people_month, category: onboarding_people, question: "Welche neuen Mitarbeiter kommen diesen Monat ins Onboarding?", expected_tools: [personio_directory]}
  - {id: onboarding_people_hannover, category: onboarding_people, question: "Welche Mitarbeiter sind aktuell im Onboarding in Hannover?", expected_tools: [personio_directory]}
  # --- RAG: Onboarding-Prozess ---
  - {id: onboarding_process_flow, category: onboarding_process, question: "Wie läuft der Onboarding-Prozess für neue Mitarbeiter ab?", expected_tools: [rag_chat], expected_procedural: true}
  - {id: onboarding_process_workshop, category: onboarding_process, question: "Was gehört zur Einarbeitung in der Werkstatt?", expected_tools: [rag_chat]}
  # --- RAG: Anleitungen mit Umlaut-/ASCII-Paaren (K1) ---
  - {id: procedure_address_umlaut, category: procedure, question: "Wie ändere ich eine Kundenadresse in Vaudis?", expected_tools: [rag_chat], findings: [K1], expected_procedural: true}
  - {id: procedure_address_ascii, category: procedure, question: "Wie aendere ich eine Kundenadresse in Vaudis?", expected_tools: [rag_chat], findings: [K1], expected_procedural: true}
  - {id: procedure_order_umlaut, category: procedure, question: "Wie öffne ich einen Werkstattauftrag in WPS?", expected_tools: [rag_chat], findings: [K1], expected_procedural: true}
  - {id: procedure_order_ascii, category: procedure, question: "Wie oeffne ich einen Werkstattauftrag in WPS?", expected_tools: [rag_chat], findings: [K1], expected_procedural: true}
  - {id: procedure_dialog_umlaut, category: procedure, question: "Wie läuft die Dialogannahme ab?", expected_tools: [rag_chat], findings: [K1], expected_procedural: true}
  - {id: procedure_dialog_ascii, category: procedure, question: "Wie laeuft die Dialogannahme ab?", expected_tools: [rag_chat], findings: [K1], expected_procedural: true}
  - {id: procedure_hu_umlaut, category: procedure, question: "Wie führe ich eine HU-Anmeldung durch?", expected_tools: [rag_chat], findings: [K1], expected_procedural: true}
  - {id: procedure_hu_ascii, category: procedure, question: "Wie fuehre ich eine HU-Anmeldung durch?", expected_tools: [rag_chat], findings: [K1], expected_procedural: true}
  - {id: procedure_slot_umlaut, category: procedure, question: "Wie wähle ich im WPS einen freien Termin aus?", expected_tools: [rag_chat], findings: [K1], expected_procedural: true}
  - {id: procedure_slot_ascii, category: procedure, question: "Wie waehle ich im WPS einen freien Termin aus?", expected_tools: [rag_chat], findings: [K1], expected_procedural: true}
  # --- RAG: Anleitungen außerhalb der geschlossenen Verbliste (K3) ---
  - {id: procedure_new_customer, category: procedure, question: "Wie lege ich einen Neukunden in Vaudis an?", expected_tools: [rag_chat], findings: [K3], expected_procedural: true}
  - {id: procedure_cancel_invoice, category: procedure, question: "Wie storniere ich eine Rechnung?", expected_tools: [rag_chat], findings: [K3], expected_procedural: true}
  - {id: procedure_courtesy_car, category: procedure, question: "Wie reserviere ich einen Leihwagen für einen Werkstattkunden?", expected_tools: [rag_chat], findings: [K3], expected_procedural: true}
  - {id: procedure_test_drive_imperative, category: procedure, question: "Anleitung: Probefahrt in EVA erfassen", expected_tools: [rag_chat], expected_procedural: true}
  - {id: procedure_warranty_steps, category: procedure, question: "Welche Schritte sind für eine Garantieanfrage nötig?", expected_tools: [rag_chat], expected_procedural: true}
  - {id: procedure_calendar_plan, category: procedure, question: "Wie plane ich einen Termin im Werkstattkalender?", expected_tools: [rag_chat], expected_procedural: true}
  # --- RAG: Zuständigkeiten (K2) ---
  - {id: responsibility_warranty, category: responsibility, question: "Wer ist für Garantieanträge zuständig?", expected_tools: [rag_chat], findings: [K2]}
  - {id: responsibility_role_tasks, category: responsibility, question: "Welche Aufgaben hat ein Serviceberater?", expected_tools: [rag_chat], findings: [K2]}
  - {id: responsibility_lease_returns, category: responsibility, question: "Wer kümmert sich um Leasingrückläufer?", expected_tools: [rag_chat], findings: [K2]}
  - {id: responsibility_dunning, category: responsibility, question: "Wer ist für Mahnungen zuständig?", expected_tools: [rag_chat], findings: [K2, U3]}
  - {id: responsibility_complaints, category: responsibility, question: "Welche Abteilung bearbeitet Kundenbeschwerden?", expected_tools: [rag_chat], findings: [K2, U3]}
  - {id: responsibility_work_instruction_approval, category: responsibility, question: "Wer ist für die Freigabe von Arbeitsanweisungen verantwortlich?", expected_tools: [rag_chat], findings: [K2]}
  - {id: responsibility_vehicle_prep, category: responsibility, question: "Welche Rolle ist für die Fahrzeugaufbereitung verantwortlich?", expected_tools: [rag_chat], findings: [K2]}
  - {id: responsibility_data_access, category: responsibility, question: "Wer ist zuständig, wenn ein Kunde eine Datenauskunft verlangt?", expected_tools: [rag_chat], findings: [K2]}
  # --- RAG: Funktionspostfächer und Kontaktwege ---
  - {id: functional_applications_mailbox, category: functional_contact, question: "Wie lautet das Funktionspostfach für Bewerbungen?", expected_tools: [rag_chat]}
  - {id: functional_sick_note, category: functional_contact, question: "Wohin schicke ich eine Krankmeldung?", expected_tools: [rag_chat]}
  - {id: functional_privacy_central, category: functional_contact, question: "Gibt es eine zentrale E-Mail-Adresse für Datenschutzanfragen?", expected_tools: [rag_chat]}
  - {id: functional_it_contact_page, category: functional_contact, question: "Wo finde ich die Kontaktseite der IT?", expected_tools: [rag_chat]}
  - {id: functional_it_ticket, category: functional_contact, question: "Wie melde ich ein IT-Problem, gibt es ein Ticketsystem?", expected_tools: [rag_chat]}
  - {id: functional_applications_submit, category: functional_contact, question: "An wen reiche ich Bewerbungen ein?", expected_tools: [rag_chat]}
  # --- Beide: Abteilungskontakte ---
  - {id: org_contact_accounting, category: organization_contact, question: "Wie erreiche ich die Buchhaltung?", expected_tools: [personio_directory, rag_chat]}
  - {id: org_contact_hr_extension, category: organization_contact, question: "Was ist die Durchwahl der Personalabteilung?", expected_tools: [personio_directory, rag_chat]}
  - {id: org_contact_marketing, category: organization_contact, question: "Wer ist Ansprechpartner im Marketing und wie erreiche ich das Team?", expected_tools: [personio_directory, rag_chat]}
  - {id: org_contact_it_nominal, category: organization_contact, question: "Kontaktdaten der IT", expected_tools: [personio_directory, rag_chat]}
  - {id: org_contact_parts_wunstorf, category: organization_contact, question: "Wie komme ich mit dem Teiledienst in Wunstorf in Kontakt?", expected_tools: [personio_directory, rag_chat]}
  - {id: org_contact_dispatch_mail, category: organization_contact, question: "Welche E-Mail-Adresse hat die Disposition?", expected_tools: [personio_directory, rag_chat]}
  # --- Beide: Person und dokumentierter Prozess ---
  - {id: person_process_project, category: person_process, question: "Was hat Max Mustermann mit dem Projekt Digitales Autohaus zu tun?", expected_tools: [personio_directory, rag_chat]}
  - {id: person_process_role_duties, category: person_process, question: "Welche Rolle hat Anna Beispiel und welche Aufgaben gehören laut Arbeitsanweisung dazu?", expected_tools: [personio_directory, rag_chat]}
  - {id: person_process_handover, category: person_process, question: "Ist Anna Beispiel noch im Verkauf, und wie läuft dort die Übergabe an den Service?", expected_tools: [personio_directory, rag_chat]}
  - {id: person_process_relation, category: person_process, question: "Wie hängen Max Mustermann und das Vaudis-Projekt zusammen?", expected_tools: [personio_directory, rag_chat]}
  # --- RAG: Abkürzungen ---
  - {id: abbreviation_td, category: abbreviation, question: "Was bedeutet TD?", expected_tools: [rag_chat]}
  - {id: abbreviation_da, category: abbreviation, question: "Wofür steht DA bei KAHLE?", expected_tools: [rag_chat]}
  - {id: abbreviation_vk, category: abbreviation, question: "Was ist die Abkürzung VK?", expected_tools: [rag_chat]}
  - {id: abbreviation_wps, category: abbreviation, question: "Was bedeutet WPS?", expected_tools: [rag_chat]}
  # --- RAG: allgemeines internes Wissen ---
  - {id: internal_service_systems, category: internal_knowledge, question: "Welche Systeme nutzt KAHLE im Service?", expected_tools: [rag_chat]}
  - {id: internal_wps_locations, category: internal_knowledge, question: "An welchen Standorten wird WPS eingesetzt?", expected_tools: [rag_chat]}
  - {id: internal_opening_hours, category: internal_knowledge, question: "Welche Öffnungszeiten hat der Service in Hannover?", expected_tools: [rag_chat]}
  - {id: internal_dialog_notes, category: internal_knowledge, question: "Was ist bei der Dialogannahme zu beachten?", expected_tools: [rag_chat]}
  - {id: internal_ai_policy, category: internal_knowledge, question: "Gibt es eine Richtlinie zur Nutzung von KI?", expected_tools: [rag_chat]}
  - {id: internal_complaint_notes, category: internal_knowledge, question: "Was muss ich bei einer Reklamation beachten?", expected_tools: [rag_chat]}
  # --- RAG: Geltungsbereich nach Standort (U1) ---
  - {id: scope_opt_out_vaudis, category: scope_location, question: "Wie hinterlege ich einen Werbewiderspruch in Vaudis?", expected_tools: [rag_chat], findings: [U1], expected_procedural: true}
  - {id: scope_survey_opt_out, category: scope_location, question: "Ein Kunde möchte keine Zufriedenheitsbefragungen mehr erhalten, was muss ich tun?", expected_tools: [rag_chat], findings: [U1]}
  - {id: scope_opt_out_walsrode, category: scope_location, question: "Wie sperre ich einen Kunden für Werbung am Standort Walsrode?", expected_tools: [rag_chat], findings: [U1], expected_procedural: true}
  - {id: scope_dse_wunstorf, category: scope_location, question: "Wie deaktiviere ich die DSE-Kontaktfreigaben in Wunstorf?", expected_tools: [rag_chat], findings: [U1]}
  # --- Kein Wissens-Tool ---
  - {id: none_customer_mail, category: no_knowledge_tool, question: "Schreibe mir eine E-Mail an einen Kunden wegen einer Terminverschiebung.", expected_tools: []}
  - {id: none_rephrase, category: no_knowledge_tool, question: "Formuliere diesen Satz freundlicher: Das Auto ist noch nicht fertig.", expected_tools: []}
  - {id: none_translate, category: no_knowledge_tool, question: "Übersetze Fahrzeugannahme ins Englische.", expected_tools: []}
  - {id: none_general_capital, category: no_knowledge_tool, question: "Was ist die Hauptstadt von Frankreich?", expected_tools: []}
  - {id: none_today, category: no_knowledge_tool, question: "Welcher Tag ist heute?", expected_tools: []}
  - {id: none_reminder, category: no_knowledge_tool, question: "Erinnere mich morgen um 9 Uhr an den Rückruf.", expected_tools: []}
  - {id: none_my_tasks, category: no_knowledge_tool, question: "Zeig mir meine offenen Aufgaben.", expected_tools: []}
  - {id: none_script_help, category: no_knowledge_tool, question: 'Warum funktioniert dieses Skript nicht? robocopy C:\quelle D:\ziel /MIR', expected_tools: []}
  - {id: none_general_leasing, category: no_knowledge_tool, question: "Erkläre mir allgemein den Unterschied zwischen Leasing und Finanzierung.", expected_tools: []}
  - {id: none_web_news, category: no_knowledge_tool, question: "Recherchiere aktuelle News zum VW ID.7.", expected_tools: []}
  # --- Folgefragen mit Verlauf ---
  - id: followup_supervisor_reference
    category: followup
    history:
      - {role: user, content: "Wer ist Max Mustermann?"}
      - {role: assistant, content: "Max Mustermann ist laut Personio Serviceberater in Wunstorf [P1]."}
    question: "Und wer ist seine Führungskraft?"
    expected_tools: [personio_directory]
  - id: followup_procedure_other_system
    category: followup
    history:
      - {role: user, content: "Wie ändere ich eine Kundenadresse in Vaudis?"}
      - {role: assistant, content: "Öffne den Kundenstamm und ändere die Adresse [R1]."}
    question: "Und in WPS?"
    expected_tools: [rag_chat]
  - id: followup_scope_location_reply
    category: followup
    history:
      - {role: user, content: "Wie hinterlege ich einen Werbewiderspruch in Vaudis?"}
      - {role: assistant, content: "Für welchen Standort möchtest du den Werbewiderspruch hinterlegen?"}
    question: "Hannover"
    expected_tools: [rag_chat]
    findings: [U1]
  - id: followup_people_contact
    category: followup
    history:
      - {role: user, content: "Wer arbeitet im Teiledienst in Hannover?"}
      - {role: assistant, content: "Laut Personio arbeitet dort Anna Beispiel [P1]."}
    question: "Und wie erreiche ich sie?"
    expected_tools: [personio_directory]
  - id: followup_system_procedure
    category: followup
    history:
      - {role: user, content: "Welche Systeme nutzt KAHLE im Service?"}
      - {role: assistant, content: "Im Service werden WPS und Vaudis genutzt [R1]."}
    question: "Wie plane ich darin einen Termin?"
    expected_tools: [rag_chat]
  - id: followup_rewrite_text
    category: followup
    history:
      - {role: user, content: "Schreib mir einen kurzen Intranet-Text zum Tag der offenen Tür."}
      - {role: assistant, content: "Am Samstag öffnen wir unsere Türen für alle Kolleginnen und Kollegen."}
    question: "Mach ihn kürzer."
    expected_tools: []
  # --- Nicht beantwortbar: Enthaltung erwartet ---
  - {id: unanswerable_unknown_identifier, category: unanswerable, question: "Welche interne Regel gilt für die Kennung ZX-999-NICHT-VORHANDEN?", expected_tools: [rag_chat], expect_abstention: true}
  - {id: unanswerable_unknown_person, category: unanswerable, question: "Wer ist Zyx Nichtvorhandenmann?", expected_tools: [personio_directory], expect_abstention: true}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv-verify/Scripts/python.exe -m pytest eval/harness/tests -q -p no:cacheprovider`
Expected: `27 passed` (Korpus: 99 Fälle)

- [ ] **Step 5: Commit**

```bash
git add eval/harness/routing_cases.yml eval/harness/tests/test_routing_corpus.py
git commit -m "feat(eval): add ADR-008 harness routing corpus"
```

---

### Task 6: Offline-Eval gegen den Harness-Planer

Der Offline-Eval bildet den Middleware-Aufruf nach: Zuerst liefert
`resolve_request()` die aufgelöste Anfrage, dann plant `plan_retrieval()`
darauf. Die Legacy-Gate-Logik der Middleware gehört nicht dazu. Die
Baseline misst deshalb den Harness-Planer, nicht die komplette
Middleware-Entscheidung.

**Files:**
- Create: `eval/harness/offline_routing_eval.py`
- Test: `eval/harness/tests/test_offline_routing_eval.py`

- [ ] **Step 1: Write the failing tests**

`eval/harness/tests/test_offline_routing_eval.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv-verify/Scripts/python.exe -m pytest eval/harness/tests/test_offline_routing_eval.py -q -p no:cacheprovider`
Expected: ERROR `ModuleNotFoundError: No module named 'offline_routing_eval'`

- [ ] **Step 3: Write minimal implementation**

`eval/harness/offline_routing_eval.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv-verify/Scripts/python.exe -m pytest eval/harness/tests -q -p no:cacheprovider`
Expected: `30 passed`

- [ ] **Step 5: Commit**

```bash
git add eval/harness/offline_routing_eval.py eval/harness/tests/test_offline_routing_eval.py
git commit -m "feat(eval): measure harness planner routing offline"
```

---

### Task 7: Offline-Baseline erzeugen und prüfen

**Files:**
- Create: `eval/harness/results/2026-09-29-offline-baseline.json`
- Modify: `.gitignore`

- [ ] **Step 1: Baseline erzeugen**

Run:
```bash
./.venv-verify/Scripts/python.exe eval/harness/offline_routing_eval.py --output eval/harness/results/2026-09-29-offline-baseline.json
```
Expected: Eine Zeile `legacy-planner: N/99 korrekt (...)`. Vorschau bei der Planerstellung am 29.09.: **84/99 Routing korrekt, 11 `procedural`-Abweichungen**. Die 15 Routingfehler verteilen sich so:

- K2: `responsibility_warranty` und `responsibility_role_tasks` → Personio.
- Tippfehler bei der Führungskraft: `supervisor_typo`.
- Nominalphrasen und Listen: `list_serviceassistenz_nominal`, `list_count_serviceberater_nienburg`.
- Der Planer-Default `rag_chat` greift bei Allgemeinwissen, Datum und Websuche.
- Folgefragen: `followup_people_contact`, `followup_rewrite_text`.

Die `procedural`-Abweichungen betreffen alle fünf Umlautvarianten (K1; die ASCII-Varianten sind korrekt), die drei K3-Fälle sowie `onboarding_process_flow`, `scope_opt_out_vaudis` und `scope_opt_out_walsrode`.

- [ ] **Step 2: Befunde in der Baseline gegenprüfen**

Run:
```bash
./.venv-verify/Scripts/python.exe -c "import json; r=json.load(open('eval/harness/results/2026-09-29-offline-baseline.json',encoding='utf-8')); print(json.dumps(r['summary']['legacy-planner']['by_category'], indent=1)); print([x['case_id'] for x in r['rows'] if x.get('procedural_match') is False])"
```
Expected, entsprechend der Analyse:

- `responsibility` hat Fehlrouting, z. B. `responsibility_warranty` mit `wrong_source`.
- `procedural_match=False` tritt u. a. bei `procedure_address_umlaut`, `procedure_order_umlaut`, `procedure_new_customer` und `procedure_cancel_invoice` auf.

Weichen die Zahlen deutlich von der Vorschau ab, gleiche vor dem Commit Korpus und Analyse ab. Den Korpus nicht an den Planer anpassen.

- [ ] **Step 3: Rohzeilen der Laufzeit ignorieren**

In `.gitignore` direkt unter der Zeile `eval/rag/results/rag-runtime-eval-*.jsonl` ergänzen:

```gitignore
eval/harness/results/*.jsonl
```

- [ ] **Step 4: Commit**

```bash
git add .gitignore eval/harness/results/2026-09-29-offline-baseline.json
git commit -m "test(eval): record offline harness routing baseline"
```

---

### Task 8: Laufzeit-Client aus `eval/rag` wiederverwendbar machen

**Files:**
- Modify: `eval/rag/run_runtime_eval.py` (Methode `OpenWebUIRuntimeClient.ask`)
- Test: `eval/rag/tests/test_run_runtime_eval.py` (bestehend, unverändert)

- [ ] **Step 1: Bestehende Tests als Sicherheitsnetz laufen lassen**

Run: `cd eval/rag && W=$(cd ../.. && pwd -W) && PYTHONPATH="$W/eval/rag;$W/stack/kb-sync" ../../.venv-verify/Scripts/python.exe -m pytest tests -q -p no:cacheprovider; cd ../..`
Expected: alle bestehenden Tests PASS

- [ ] **Step 2: Refactoring ohne Verhaltensänderung**

In `eval/rag/run_runtime_eval.py` den Teil von `ask()` ab `started = self.session.post(` bis einschließlich `raise TimeoutError(...)` durch einen Aufruf ersetzen. Der Aufbau des Bodys bleibt unverändert:

```python
        return self._start_and_wait(body, assistant_message_id, state)

    def _start_and_wait(
        self,
        body: dict[str, Any],
        assistant_message_id: str,
        state: ConversationState | None,
    ) -> tuple[dict, ConversationState]:
        started = self.session.post(
            f"{self.base_url}/api/chat/completions", json=body, timeout=self.timeout_seconds
        )
        started.raise_for_status()
        task = started.json()
        chat_id = str(task.get("chat_id") or (state.chat_id if state else ""))
        if not task.get("status") or not chat_id:
            raise RuntimeError(f"OpenWebUI did not start the chat task: {task}")

        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            try:
                chat_response = self.session.get(
                    f"{self.base_url}/api/v1/chats/{chat_id}", timeout=min(30, self.timeout_seconds)
                )
            except requests.Timeout:
                time.sleep(self.poll_seconds)
                continue
            chat_response.raise_for_status()
            chat = chat_response.json().get("chat") or {}
            messages = ((chat.get("history") or {}).get("messages") or {})
            message = messages.get(assistant_message_id)
            if message and message.get("error"):
                raise RuntimeError(f"OpenWebUI chat task failed: {message['error']}")
            if message and message.get("done") is True:
                return message, ConversationState(chat_id, assistant_message_id)
            time.sleep(self.poll_seconds)
        raise TimeoutError(f"OpenWebUI chat task did not finish within {self.timeout_seconds}s")
```

- [ ] **Step 3: Tests erneut laufen lassen**

Run: `cd eval/rag && W=$(cd ../.. && pwd -W) && PYTHONPATH="$W/eval/rag;$W/stack/kb-sync" ../../.venv-verify/Scripts/python.exe -m pytest tests -q -p no:cacheprovider; cd ../..`
Expected: gleiche Anzahl PASS wie in Step 1

- [ ] **Step 4: Commit**

```bash
git add eval/rag/run_runtime_eval.py
git commit -m "refactor(eval): extract OpenWebUI chat task polling"
```

---

### Task 9: Laufzeit-Client für Harness-Fälle

Anders als der RAG-Eval schickt dieser Client

- keinen eigenen System-Prompt (der Modell-Prompt der Vinci-Preset gilt),
- keinen Such-Prefix,
- den vollständigen Verlauf,
- die in Open WebUI hinterlegten `toolIds` des Modells.

So sieht das Modell denselben Kontext wie im Browser.

**Files:**
- Create: `eval/harness/runtime_harness_eval.py`
- Test: `eval/harness/tests/test_runtime_harness_eval.py`

- [ ] **Step 1: Write the failing tests**

`eval/harness/tests/test_runtime_harness_eval.py`:

```python
import json

from harness_eval import RoutingCase
from runtime_harness_eval import (
    HarnessRuntimeClient,
    base_model_id,
    error_row,
    model_tool_ids,
    run_case,
)

MODEL = {
    "id": "kahle-vinci",
    "info": {"base_model_id": "mistralai/Mistral-Small-24B-Instruct", "meta": {"toolIds": ["rag_chat", "zeit"]}},
}


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class Session:
    def __init__(self, message_extra=None):
        self.headers = {}
        self.posts = []
        self.message_extra = message_extra or {}

    def post(self, url, json, timeout):
        self.posts.append((url, json))
        return Response({"status": True, "chat_id": "chat-1"})

    def get(self, url, timeout):
        if url.endswith("/api/models"):
            return Response({"data": [{"id": "other"}, MODEL]})
        assistant_id = self.posts[-1][1]["id"]
        message = {"role": "assistant", "done": True, "content": "Geheime Antwort [R1].", "output": [
            {"type": "function_call", "name": "rag_chat"},
        ], **self.message_extra}
        return Response({"chat": {"history": {"messages": {assistant_id: message}}}})


CASE = RoutingCase(
    case_id="followup_case",
    category="followup",
    question="Und in WPS?",
    expected_tools=frozenset({"rag_chat"}),
    history=({"role": "user", "content": "Wie ändere ich X?"}, {"role": "assistant", "content": "So [R1]."}),
)


def _client(session):
    return HarnessRuntimeClient("http://local", "key", "kahle-vinci", poll_seconds=0, session=session)


def test_model_metadata_helpers():
    assert model_tool_ids(MODEL) == ["rag_chat", "zeit"]
    assert base_model_id(MODEL) == "mistralai/Mistral-Small-24B-Instruct"
    assert model_tool_ids({"id": "x"}) == []


def test_model_info_selects_configured_model():
    assert _client(Session()).model_info()["id"] == "kahle-vinci"


def test_ask_messages_sends_full_history_without_system_override():
    session = Session()

    message, chat_id = _client(session).ask_messages(CASE.messages(), ["rag_chat"])

    url, body = session.posts[-1]
    assert url == "http://local/api/chat/completions"
    assert body["messages"] == CASE.messages()
    assert all(item["role"] != "system" for item in body["messages"])
    assert body["tool_ids"] == ["rag_chat"]
    assert body["user_message"]["content"] == "Und in WPS?"
    assert chat_id == "chat-1"
    assert message["done"] is True


def test_run_case_builds_privacy_safe_row():
    session = Session({"kahle_harness_metrics": {"latency_ms": 900}})

    row, chat_id = run_case(_client(session), CASE, ["rag_chat"])

    assert chat_id == "chat-1"
    assert row["model"] == "kahle-vinci"
    assert row["outcome"] == "correct"
    assert row["actual_tools"] == ["rag_chat"]
    assert row["latency_ms"] == 900
    assert isinstance(row["wall_ms"], int)
    serialized = json.dumps(row, ensure_ascii=False)
    assert "Geheime Antwort" not in serialized
    assert "Und in WPS" not in serialized


def test_error_row_keeps_only_error_type():
    row = error_row("kahle-vinci", CASE, RuntimeError("secret upstream detail"))

    assert row["outcome"] == "error"
    assert row["error"] == "RuntimeError"
    assert "secret" not in json.dumps(row)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv-verify/Scripts/python.exe -m pytest eval/harness/tests/test_runtime_harness_eval.py -q -p no:cacheprovider`
Expected: ERROR `ModuleNotFoundError: No module named 'runtime_harness_eval'`

- [ ] **Step 3: Write minimal implementation**

`eval/harness/runtime_harness_eval.py`:

```python
"""Run the harness routing corpus through OpenWebUI for each Vinci model.

Specialized Verification: requires a running local stack, working IONOS models
and an OpenWebUI API key in the environment. Results contain no questions,
answers or personal data.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

from _repo_paths import ensure_repo_paths

ensure_repo_paths()

from harness_eval import (  # noqa: E402
    RoutingCase,
    actual_knowledge_tools,
    routing_outcome,
    score_answer,
)
from run_runtime_eval import OpenWebUIRuntimeClient  # noqa: E402

DEFAULT_MODELS = ("kahle-vinci", "kahle-vinci-thinking", "kahle-vinci-max-thinking")


class HarnessRuntimeClient(OpenWebUIRuntimeClient):
    def model_info(self) -> dict[str, Any]:
        response = self.session.get(f"{self.base_url}/api/models", timeout=30)
        response.raise_for_status()
        for model in response.json().get("data") or ():
            if isinstance(model, dict) and model.get("id") == self.model:
                return model
        raise RuntimeError(f"Modell nicht gefunden: {self.model}")

    def ask_messages(
        self, messages: list[dict[str, str]], tool_ids: list[str]
    ) -> tuple[dict[str, Any], str]:
        user_message_id = str(uuid4())
        assistant_message_id = str(uuid4())
        body = {
            "model": self.model,
            "id": assistant_message_id,
            "parent_id": None,
            "session_id": str(uuid4()),
            "user_message": {
                "id": user_message_id,
                "parentId": None,
                "childrenIds": [assistant_message_id],
                "role": "user",
                "content": messages[-1]["content"],
                "timestamp": int(time.time()),
            },
            "messages": [dict(message) for message in messages],
            "tool_ids": list(tool_ids),
            "stream": True,
        }
        message, state = self._start_and_wait(body, assistant_message_id, None)
        return message, state.chat_id


def model_tool_ids(model: dict[str, Any]) -> list[str]:
    meta = (model.get("info") or {}).get("meta") or {}
    return [str(tool) for tool in meta.get("toolIds") or () if str(tool)]


def base_model_id(model: dict[str, Any]) -> str:
    return str((model.get("info") or {}).get("base_model_id") or "")


def _base_row(model: str, case: RoutingCase) -> dict[str, Any]:
    return {
        "model": model,
        "case_id": case.case_id,
        "category": case.category,
        "expected_tools": sorted(case.expected_tools),
        "findings": list(case.findings),
    }


def run_case(
    client: HarnessRuntimeClient, case: RoutingCase, tool_ids: list[str]
) -> tuple[dict[str, Any], str]:
    started = time.monotonic()
    message, chat_id = client.ask_messages(case.messages(), tool_ids)
    wall_ms = round((time.monotonic() - started) * 1000)
    actual = sorted(actual_knowledge_tools(message))
    row = {
        **_base_row(client.model, case),
        "actual_tools": actual,
        "outcome": routing_outcome(case.expected_tools, actual),
        "wall_ms": wall_ms,
        **score_answer(case, message),
    }
    return row, chat_id


def error_row(model: str, case: RoutingCase, error: BaseException) -> dict[str, Any]:
    return {
        **_base_row(model, case),
        "actual_tools": [],
        "outcome": "error",
        "error": type(error).__name__,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv-verify/Scripts/python.exe -m pytest eval/harness/tests -q -p no:cacheprovider`
Expected: `35 passed`

- [ ] **Step 5: Commit**

```bash
git add eval/harness/runtime_harness_eval.py eval/harness/tests/test_runtime_harness_eval.py
git commit -m "feat(eval): run harness cases through the OpenWebUI chat workflow"
```

---

### Task 10: Laufzeit-CLI mit Bericht je Modell

**Files:**
- Modify: `eval/harness/runtime_harness_eval.py`
- Test: `eval/harness/tests/test_runtime_harness_eval.py`

- [ ] **Step 1: Write the failing tests**

An `eval/harness/tests/test_runtime_harness_eval.py` anhängen:

```python
import pytest

import runtime_harness_eval
from runtime_harness_eval import main


class FakeClient:
    instances = []

    def __init__(self, base_url, api_key, model, timeout_seconds, poll_seconds):
        self.model = model
        self.deleted = []
        FakeClient.instances.append(self)

    def model_info(self):
        return {"id": self.model, "info": {"base_model_id": f"base/{self.model}", "meta": {"toolIds": ["rag_chat"]}}}

    def ask_messages(self, messages, tool_ids):
        if "Kennung" in messages[-1]["content"]:
            raise TimeoutError("upstream")
        return {"content": "Antwort [R1].", "output": [{"type": "function_call", "name": "rag_chat"}]}, f"chat-{len(self.deleted)}"

    def delete_chat(self, chat_id):
        self.deleted.append(chat_id)


def _cases_file(tmp_path):
    path = tmp_path / "cases.yml"
    path.write_text(
        "schema_version: kahle.harness-routing-cases.v1\ncases:\n"
        "  - {id: rag_case, category: procedure, question: 'Wie lege ich X an?', expected_tools: [rag_chat]}\n"
        "  - {id: broken_case, category: unanswerable, question: 'Kennung ZX?', expected_tools: [rag_chat], expect_abstention: true}\n",
        encoding="utf-8",
    )
    return path


def test_main_requires_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENWEBUI_API_KEY", raising=False)

    with pytest.raises(SystemExit, match="OPENWEBUI_API_KEY"):
        main(["--cases", str(_cases_file(tmp_path)), "--output-dir", str(tmp_path)])


def test_main_writes_rows_and_summary_per_model(tmp_path, monkeypatch):
    FakeClient.instances = []
    monkeypatch.setenv("OPENWEBUI_API_KEY", "key")
    monkeypatch.setattr(runtime_harness_eval, "HarnessRuntimeClient", FakeClient)

    exit_code = main([
        "--cases", str(_cases_file(tmp_path)),
        "--output-dir", str(tmp_path),
        "--models", "kahle-vinci,kahle-vinci-thinking",
    ])

    assert exit_code == 0
    summary_path = next(tmp_path.glob("harness-runtime-eval-*.json"))
    rows_path = next(tmp_path.glob("harness-runtime-eval-*.jsonl"))
    report = json.loads(summary_path.read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines()]
    assert report["mode"] == "runtime"
    assert report["models"]["kahle-vinci"] == {"base_model_id": "base/kahle-vinci", "tool_ids": ["rag_chat"]}
    assert report["routing"]["kahle-vinci"]["outcomes"] == {"correct": 1, "error": 1}
    assert report["answers"]["kahle-vinci"]["total"] == 1
    assert len(rows) == 4
    assert all(client.deleted == ["chat-0"] for client in FakeClient.instances)
    assert "Antwort" not in rows_path.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv-verify/Scripts/python.exe -m pytest eval/harness/tests/test_runtime_harness_eval.py -q -p no:cacheprovider`
Expected: ERROR `ImportError: cannot import name 'main'`

- [ ] **Step 3: Write minimal implementation**

In `eval/harness/runtime_harness_eval.py` die Imports ergänzen:

```python
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
```

und den Import aus `harness_eval` erweitern um `SCHEMA_VERSION`, `load_cases`, `summarize_answers` und `summarize_routing`. Am Dateiende anhängen:

```python
DEFAULT_CASES = Path(__file__).with_name("routing_cases.yml")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:3004")
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output-dir", type=Path, default=Path("eval/harness/results"))
    parser.add_argument("--api-key-env", default="OPENWEBUI_API_KEY")
    parser.add_argument("--category", default="")
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--keep-chats", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        raise SystemExit(f"Fehlender API-Schlüssel in {args.api_key_env}")
    cases = load_cases(args.cases)
    if args.category:
        cases = [case for case in cases if case.category == args.category]
    if args.max_cases:
        cases = cases[: args.max_cases]
    models = [model.strip() for model in args.models.split(",") if model.strip()]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    rows_path = args.output_dir / f"harness-runtime-eval-{stamp}.jsonl"
    summary_path = args.output_dir / f"harness-runtime-eval-{stamp}.json"
    rows: list[dict[str, Any]] = []
    model_meta: dict[str, Any] = {}

    with rows_path.open("w", encoding="utf-8") as output:
        for model_id in models:
            client = HarnessRuntimeClient(
                args.base_url, api_key, model_id, args.timeout, args.poll_seconds
            )
            info = client.model_info()
            tool_ids = model_tool_ids(info)
            model_meta[model_id] = {"base_model_id": base_model_id(info), "tool_ids": tool_ids}
            for case in cases:
                chat_id = ""
                try:
                    row, chat_id = run_case(client, case, tool_ids)
                except Exception as error:  # one failed case must not stop the matrix
                    row = error_row(model_id, case, error)
                rows.append(row)
                output.write(json.dumps(row, ensure_ascii=False) + "\n")
                output.flush()
                if chat_id and not args.keep_chats:
                    try:
                        client.delete_chat(chat_id)
                    except Exception:
                        pass
                print(f"{model_id} {case.case_id}: {row['outcome']}")

    report = {
        "schema_version": SCHEMA_VERSION,
        "mode": "runtime",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base_url": args.base_url,
        "models": model_meta,
        "case_count": len(cases),
        "routing": summarize_routing(rows),
        "answers": summarize_answers([row for row in rows if row["outcome"] != "error"]),
    }
    summary_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for model_id, summary in report["routing"].items():
        print(f"{model_id}: Routing {summary['accuracy']:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv-verify/Scripts/python.exe -m pytest eval/harness/tests -q -p no:cacheprovider`
Expected: `37 passed`

- [ ] **Step 5: Commit**

```bash
git add eval/harness/runtime_harness_eval.py eval/harness/tests/test_runtime_harness_eval.py
git commit -m "feat(eval): report harness runtime metrics per Vinci model"
```

---

### Task 11: In Verification und Doku einhängen

**Files:**
- Modify: `scripts/run-local-tests.ps1` (Array `$pythonSuites`)
- Modify: `docs/VERIFICATION.md` (Tier-Tabelle und Abschnitt „IONOS und Retrieval“)

- [ ] **Step 1: Suite registrieren**

In `scripts/run-local-tests.ps1` im Array `$pythonSuites` direkt nach dem Eintrag `RAG-Evaluation` einfügen:

```powershell
    @{
        Name = "Harness-Evaluation"; Path = "eval/harness/tests"; MinimumTier = "Fast"
        WorkingDirectory = "eval/harness"; Tests = "tests"; PythonPath = @("eval/harness")
    },
```

- [ ] **Step 2: Doku ergänzen**

In `docs/VERIFICATION.md` in der Tabelle „Inhalt der Tiers“ nach der Zeile für `eval/rag/tests` einfügen:

```markdown
| `eval/harness/tests` | bei Harness-, Routing- oder Eval-Änderungen | ja | ja |
```

Im Abschnitt „IONOS und Retrieval“ nach dem bestehenden Codeblock ergänzen:

````markdown
Harness-Eval. Der Offline-Lauf braucht kein Modell. Der Laufzeit-Lauf braucht
den lokalen Stack, antwortende IONOS-Modelle und `OPENWEBUI_API_KEY`:

```powershell
python eval\harness\offline_routing_eval.py --output eval\harness\results\<datum>-offline.json
python eval\harness\runtime_harness_eval.py --base-url http://localhost:3004
```

Die Ergebnisse enthalten keine Fragen, Antworttexte oder Personendaten.
Zusammenfassungen (`*.json`) dürfen eingecheckt werden, Rohzeilen (`*.jsonl`)
nicht.
````

- [ ] **Step 3: Fast Verify**

Run:
```powershell
.\scripts\run-local-tests.ps1 -Tier Fast -Python .\.venv-verify\Scripts\python.exe -Npm npm.cmd
```
Expected: Exit-Code 0, „Harness-Evaluation“ in der Übersicht als bestanden.

- [ ] **Step 4: Commit**

```bash
git add scripts/run-local-tests.ps1 docs/VERIFICATION.md
git commit -m "chore(verify): run harness evaluation tests in Fast and Full"
```

---

### Task 12: Laufzeit-Baseline je Modell (sobald IONOS antwortet)

Dieser Task ist Specialized. Er braucht:

- antwortende IONOS-Modelle,
- `localhost:3004`,
- ein Bearer-Token des Nutzers in `OPENWEBUI_API_KEY`. Weil `ENABLE_API_KEYS` lokal nicht gesetzt ist, funktionieren `sk-…`-Schlüssel nicht. Verwendet wird das JWT-Sitzungstoken aus *Einstellungen → Konto*. Der Nutzer setzt es selbst, der Agent gibt keine Tokens ein und legt keine an.

Bestätigte Modellzuordnung (29.09.): `kahle-vinci` = Mistral-Small-24B, `kahle-vinci-thinking` = gpt-oss-120b, `kahle-vinci-max-thinking` = Qwen3.5-397B.

- [ ] **Step 1: Modellzuordnung und Tools prüfen**

Run (mit gesetztem Schlüssel):
```bash
./.venv-verify/Scripts/python.exe eval/harness/runtime_harness_eval.py --max-cases 1 --category procedure
```
Expected: Je Modell eine Zeile `… procedure_address_umlaut: correct|…`. Im Summary-JSON steht unter `models` für jedes Vinci-Modell die tatsächliche `base_model_id`. Erwartet sind Mistral-Small-24B, gpt-oss-120b und Qwen3.5-397B, das bestätigt die Zuordnung. `tool_ids` enthält `rag_chat`.

- [ ] **Step 2: Baseline in beiden Routingmodi**

1. Aktueller lokaler Modus `model_led` (Overlay `docker-compose.local-edge.yml`): Voller Lauf ohne `--max-cases`.
2. Danach den `open-webui`-Container mit `KAHLE_KNOWLEDGE_ROUTING_MODE=legacy` neu erstellen und denselben Lauf wiederholen. Anschließend den Container wieder mit dem Overlay-Wert erstellen.

- [ ] **Step 3: Zusammenfassungen einchecken**

Beide Summary-Dateien umbenennen in `eval/harness/results/2026-MM-TT-runtime-model-led.json` bzw. `…-runtime-legacy.json`. Vorher prüfen, dass sie keine Frage- oder Antworttexte enthalten, dann committen:

```bash
git add eval/harness/results/*-runtime-*.json
git commit -m "test(eval): record runtime harness baseline per model and routing mode"
```

## Abnahme Phase 1

- `eval/harness/tests` ist Teil von Fast und Full, alle Tests grün.
- Die Offline-Baseline ist eingecheckt und zeigt K1, K2 und K3 messbar.
- Die Laufzeit-Baseline je Modell und Routingmodus ist eingecheckt, oder
  ausdrücklich als blockiert durch IONOS vermerkt.
- Danach startet Phase 0 mit einem eigenen TDD-Plan. Ziel: Offline-Accuracy
  und `procedural_accuracy` steigen, Laufzeitwerte werden nicht schlechter.

## Begleitänderung

- `2fce087`: Das Abfragen der Open-WebUI-Chat-Aufgabe in `eval/rag/run_runtime_eval.py` wurde in den `OpenWebUIRuntimeClient` herausgelöst.
- Der Laufzeit-Client des Harness-Evals (`eval/harness/runtime_harness_eval.py`) erbt davon, statt die Logik zu kopieren.
- Das Verhalten des RAG-Evals ist unverändert.

# Harness Phase 2: Antwort vor der Anzeige prüfen, einmal korrigieren, sonst enthalten

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Antworten mit internem Wissen (`rag_chat`, `personio_directory`) werden vor der Anzeige gepuffert und deterministisch geprüft. Ein blockierender Verstoß löst genau einen Korrekturaufruf ohne Tools aus. Besteht auch der zweite Entwurf nicht, folgt eine neutrale Enthaltung. Grundlage ist die Spezifikation vom 01.09. (`docs/superpowers/specs/2026-09-01-model-led-knowledge-routing-design.md`, Abschnitt „Antwortvalidierung vor der sichtbaren Ausgabe“), Befund 1 der Analyse und die Roadmap.

**Architecture:**

- **Reine, testbare Bausteine im Harness:** Zitierregel, gezielter Korrektur-Prompt, Enthaltungstext.
- **Middleware:**
  - eine reine async-Funktion `_enforce_knowledge_answer` mit injizierter Regenerierungsfunktion (vollständig ohne Modell testbar),
  - Hilfsfunktionen für Nachrichtenaufbau, Text-Extraktion und Timeout,
  - ein schmaler Anschluss an drei Stellen des Streaming-Pfads: Puffer-Flag, Tool-Hook, Validierungsstelle.
- **Schalter `KAHLE_ANSWER_ENFORCEMENT` (`observe` | `enforce`):** Der Basis-Stack bleibt bei `observe`, also dem heutigen Verhalten, das lokale Overlay nutzt `enforce`. Rückfall: den Schalter zurücksetzen.

**Tech Stack:** Python 3.11, pytest, Open WebUI v0.11.0-Overrides, Laufzeit-Eval `eval/harness`.

## Belege aus der Prototyp-Prüfung (30.09.)

Direkte Aufrufe an die drei Basismodelle über den Open-WebUI-OpenAI-Router, am Middleware-Pfad vorbei, genau wie der geplante Korrekturaufruf. Synthetische Testdaten.

| Annahme | Ergebnis |
| --- | --- |
| Ein Korrekturaufruf mit `retry_prompt()` behebt `citation_missing` und `unknown_source_id` | Mistral 6/6, gpt-oss 6/6, Qwen 6/6 |
| Dauer des Korrekturaufrufs | Mistral und gpt-oss ≈ 1–2 s; Qwen 10–71 s (Reasoning) |
| Qwen-Reasoning per `chat_template_kwargs.enable_thinking=false` oder `reasoning_effort=low` abschaltbar | **Nein**, IONOS ignoriert beides → Timeout pro Modell nötig |
| Qwen akzeptiert System-Nachrichten nach einer Nutzer-Nachricht | **Nein** (`400 System message must be at the beginning`). Zwei System-Nachrichten **am Anfang** sind erlaubt. |
| Mistral akzeptiert Tool-Verlauf ohne `tools`-Parameter | Ja, aber nur mit gültiger Tool-Call-ID. Die synthetische ID `call_1` wurde abgelehnt (`must be a-z, A-Z, 0-9, with a length of 9`). |
| Tool-Ergebnis als Text in einer Nutzer-Nachricht | Von allen drei Modellen akzeptiert und korrekt zitiert |

**Folgerungen für das Design:**

- Der Korrekturaufruf übergibt Tool-Ergebnisse als Text in einer Nutzer-Nachricht, nicht als Tool-Nachrichten.
- Die Korrekturanweisung kommt als Nutzer-Nachricht, nicht als System-Nachricht.
- System-Nachrichten stehen nur am Anfang.
- Der Timeout richtet sich nach dem Basismodell, mit einem Default von 45 s und 120 s für Qwen.

Befund aus der Laufzeit-Messung, der hier mit behoben wird: Qwen setzt in 4 Fällen ohne Personio-Treffer ein erfundenes `[P1]`. Nachgeprüft 2/2, Personio lieferte 0 Treffer.

## Vorbereitung und Befehle

Branch `feat/harness-eval-foundation`. Dateien mit CRLF-Enden über Edit-Werkzeug oder Python-Skripte mit CRLF-Erhalt ändern, nicht per `sed` oder Heredoc: Beides hat in 0b Backslashes und Zeilenumbrüche zerstört.

```bash
P=./.venv-verify/Scripts/python.exe
$P -m pytest stack/tests/test_kahle_harness_phase2.py -q -p no:cacheprovider
$P -m pytest stack/tests -q -p no:cacheprovider          # Ausgang: 1255 passed
$P -m pytest eval/harness/tests -q -p no:cacheprovider   # Ausgang: 39 passed
```

## Dateistruktur

| Datei | Änderung |
| --- | --- |
| `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py` | Zitierregel ohne Quelle; `AnswerValidation.retry_prompt(source_ids=…)`; `knowledge_abstention_answer()` |
| `stack/open-webui-overrides/open_webui/utils/middleware.py` | Hilfsfunktionen, `_enforce_knowledge_answer`, Puffer, Anschluss an die Validierungsstelle, Metriken |
| `stack/docker-compose.yml`, `stack/docker-compose.local-edge.yml` | `KAHLE_ANSWER_ENFORCEMENT` |
| `eval/harness/harness_eval.py` | Retry- und Fallback-Kennzahlen |
| Create `stack/tests/test_kahle_harness_phase2.py` | alle neuen Tests |

---

### Task 1: Kein Zitat ohne vorhandene Quelle

**Files:** Harness `answer_prompt()`; Test `stack/tests/test_kahle_harness_phase2.py`

- [ ] **Step 1: Failing test**

`stack/tests/test_kahle_harness_phase2.py`:

```python
import asyncio
import ast
import copy
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "kahle_knowledge_harness.py"
MIDDLEWARE = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "middleware.py"


def load_harness():
    spec = importlib.util.spec_from_file_location("kahle_harness_phase2", HARNESS)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def load_middleware_functions(*names, **extra_globals):
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    nodes = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
    ]
    assert {node.name for node in nodes} == set(names)
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    namespace = {"Any": Any, "asyncio": asyncio, "copy": copy, "json": json, "re": re,
                 "os": __import__("os"), **extra_globals}
    exec(compile(module, str(MIDDLEWARE), "exec"), namespace)
    return namespace


PERSONIO_MISS = {"status": "not_found", "claims": [], "sources": [], "sync_completed_at": None, "stale": False}


def test_contract_forbids_citations_without_an_existing_source():
    harness = load_harness()
    decision = harness.build_decision(
        query="Wer ist Zyx Nichtvorhandenmann?", resolved_query="Wer ist Zyx Nichtvorhandenmann?",
        messages=[], model_id="m", permission_scope={"user_id": "u"}, rag_result="",
        personio_result=PERSONIO_MISS,
    )

    prompt = decision.answer_prompt()
    assert "Zitiere ausschließlich Quellen-IDs aus evidence_bundle.source_ids" in prompt
    assert "Ist source_ids leer, setze kein Zitat" in prompt
    assert harness.validate_answer("Dazu gibt es keinen Eintrag [P1].", decision.to_dict()).retry_required
```

- [ ] **Step 2:** Run → FAIL (Satz fehlt)
- [ ] **Step 3: Implement.** In `answer_prompt()` im Instruktionstext nach `"Personio-Belege als [P1]. "` einfügen:

```python
            "Zitiere ausschließlich Quellen-IDs aus evidence_bundle.source_ids. "
            "Ist source_ids leer, setze kein Zitat. "
```

- [ ] **Step 4:** Tests → PASS; Harness-Bestandssuiten grün.
- [ ] **Step 5: Commit** `fix(harness): forbid citations without an existing source`

### Task 2: Gezielter Korrektur-Prompt und neutraler Enthaltungstext

**Files:** Harness `AnswerValidation.retry_prompt`, neue Funktion `knowledge_abstention_answer`

- [ ] **Step 1: Failing tests** (anhängen):

```python
def test_retry_prompt_names_allowed_sources_and_concrete_fixes():
    harness = load_harness()
    validation = harness.AnswerValidation(
        schema_version="kahle.answer-validation.v1", status="retry_required",
        violations=(
            {"code": "unknown_source_id", "severity": "blocking", "message": "x", "source_ids": ["P1"]},
            {"code": "citation_missing", "severity": "blocking", "message": "y"},
            {"code": "unsupported_example", "severity": "advisory", "message": "z"},
        ),
    )

    prompt = validation.retry_prompt(source_ids=("1", "2"))

    assert prompt.startswith("KAHLE_KNOWLEDGE_ANSWER_RETRY\n")
    payload = json.loads(prompt.split("\n", 1)[1])
    assert payload["allowed_source_ids"] == ["[1]", "[2]"]
    assert [item["code"] for item in payload["violations"]] == ["unknown_source_id", "citation_missing"]
    assert "Entferne jedes Zitat, das nicht in allowed_source_ids steht." in payload["instructions"]
    assert "Belege jede interne Aussage mit einer Quellen-ID aus allowed_source_ids." in payload["instructions"]


def test_retry_prompt_without_sources_forbids_citations():
    harness = load_harness()
    validation = harness.AnswerValidation("kahle.answer-validation.v1", "retry_required",
        ({"code": "unknown_source_id", "severity": "blocking", "message": "x"},))

    payload = json.loads(validation.retry_prompt().split("\n", 1)[1])

    assert payload["allowed_source_ids"] == []
    assert "Setze kein Zitat." in payload["instructions"]


def test_abstention_answer_is_neutral_and_mentions_sources_only_if_present():
    harness = load_harness()

    assert harness.knowledge_abstention_answer(has_sources=False) == (
        "Dazu habe ich keine verlässliche freigegebene Information."
    )
    with_sources = harness.knowledge_abstention_answer(has_sources=True)
    assert with_sources.startswith("Dazu habe ich keine verlässliche freigegebene Information.")
    assert "Quellen" in with_sources
    assert "[" not in with_sources
```

- [ ] **Step 2:** Run → FAIL
- [ ] **Step 3: Implement.** `retry_prompt` ersetzen:

```python
    def retry_prompt(self, source_ids: tuple[str, ...] = ()) -> str:
        """Return a structured, model-neutral correction order for the same evidence."""
        blocking = [item for item in self.violations if item.get("severity", "blocking") == "blocking"]
        allowed = [f"[{source_id}]" for source_id in source_ids]
        codes = {str(item.get("code") or "") for item in blocking}
        instructions = [
            "Erzeuge die Antwort erneut aus derselben Evidenz. Ergänze keine neuen Informationen.",
        ]
        if not allowed:
            instructions.append("Setze kein Zitat.")
        else:
            if codes & {"unknown_source_id"}:
                instructions.append("Entferne jedes Zitat, das nicht in allowed_source_ids steht.")
            if codes & {"citation_missing"}:
                instructions.append(
                    "Belege jede interne Aussage mit einer Quellen-ID aus allowed_source_ids."
                )
        if codes & {"unbound_contact_literal", "unbound_link_target", "contact_link_mismatch"}:
            instructions.append(
                "Entferne jede E-Mail-Adresse, Telefonnummer und jeden Link, der nicht wörtlich "
                "in der Evidenz steht."
            )
        if codes & {"required_document_sections_missing"}:
            instructions.append("Gib jeden verpflichtenden Abschnitt in der vorgegebenen Reihenfolge aus.")
        payload = {
            "schema_version": "kahle.answer-retry.v2",
            "violations": [
                {key: item[key] for key in ("code", "message", "source_ids") if key in item}
                for item in blocking
            ],
            "allowed_source_ids": allowed,
            "instructions": " ".join(instructions),
        }
        return (
            "KAHLE_KNOWLEDGE_ANSWER_RETRY\n"
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )
```

Direkt nach der Klasse `AnswerValidation` einfügen:

```python
_ABSTENTION_TEXT = "Dazu habe ich keine verlässliche freigegebene Information."


def knowledge_abstention_answer(*, has_sources: bool) -> str:
    """Neutral fallback after a failed correction; never states internal facts."""
    if not has_sources:
        return _ABSTENTION_TEXT
    return (
        f"{_ABSTENTION_TEXT} Die gefundenen Quellen sind unten verlinkt; bitte prüfe sie "
        "direkt oder formuliere die Frage genauer."
    )
```

- [ ] **Step 4:** Tests → PASS. Bestandstests, die `kahle.answer-retry.v1` oder den alten Instruktionstext prüfen (`test_kahle_knowledge_harness.py`, ca. Zeile 2413): Erwartung auf `v2` bzw. `"Ergänze keine neuen Informationen"` umstellen. Die Kernaussagen bleiben: Die Originalantwort ist nicht enthalten, und die Codes sind enthalten.
- [ ] **Step 5: Commit** `feat(harness): targeted correction prompt and neutral abstention`

### Task 3: Middleware-Hilfsfunktionen

**Files:** `middleware.py` (neue Top-Level-Funktionen direkt vor `def _observe_model_led_answer`)

- [ ] **Step 1: Failing tests** (anhängen):

```python
def test_enforcement_mode_defaults_to_observe(monkeypatch):
    mode = load_middleware_functions("_answer_enforcement_mode")["_answer_enforcement_mode"]
    monkeypatch.delenv("KAHLE_ANSWER_ENFORCEMENT", raising=False)
    assert mode() == "observe"
    monkeypatch.setenv("KAHLE_ANSWER_ENFORCEMENT", "enforce")
    assert mode() == "enforce"
    monkeypatch.setenv("KAHLE_ANSWER_ENFORCEMENT", "kaputt")
    assert mode() == "observe"


def test_retry_timeout_depends_on_base_model(monkeypatch):
    timeout = load_middleware_functions("_answer_retry_timeout")["_answer_retry_timeout"]
    monkeypatch.delenv("KAHLE_ANSWER_RETRY_TIMEOUTS", raising=False)
    assert timeout("mistralai/Mistral-Small-24B-Instruct") == 45
    assert timeout("Qwen/Qwen3.5-397B-A17B") == 120
    monkeypatch.setenv("KAHLE_ANSWER_RETRY_TIMEOUTS", '{"default": 30, "openai/": 60}')
    assert timeout("openai/gpt-oss-120b") == 60
    assert timeout("Qwen/Qwen3.5-397B-A17B") == 30


def test_retry_messages_keep_systems_first_and_flatten_tool_results():
    build = load_middleware_functions("_knowledge_retry_messages")["_knowledge_retry_messages"]
    messages = [
        {"role": "system", "content": "Systemprompt"},
        {"role": "system", "content": "KAHLE_KNOWLEDGE_ANSWER_CONTRACT\n{}"},
        {"role": "user", "content": "Frühere Frage"},
        {"role": "assistant", "content": "Frühere Antwort"},
        {"role": "user", "content": "Aktuelle Frage"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "fc_pre", "type": "function"}]},
        {"role": "tool", "tool_call_id": "fc_pre", "content": "KAHLE_RAG_RESULT\n[2] Vorab-Beleg"},
    ]
    output = [
        {"type": "function_call", "call_id": "call_1", "name": "rag_chat", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "call_1", "output": [{"type": "input_text", "text": "KAHLE_RAG_RESULT\n[1] Beleg"}]},
        {"type": "message", "content": [{"type": "output_text", "text": "Entwurf ohne Zitat."}]},
    ]

    result = build(messages, output, "KAHLE_KNOWLEDGE_ANSWER_RETRY\n{}")

    roles = [item["role"] for item in result]
    assert roles == ["system", "system", "user", "assistant", "user", "user", "assistant", "user"]
    assert "rag_chat" in result[5]["content"] and "[1] Beleg" in result[5]["content"]
    assert "[2] Vorab-Beleg" in result[5]["content"]
    assert result[6]["content"] == "Entwurf ohne Zitat."
    assert result[7]["content"].startswith("KAHLE_KNOWLEDGE_ANSWER_RETRY")
    assert all("tool_calls" not in item and item["role"] != "tool" for item in result)


@pytest.mark.parametrize(
    "response, expected",
    [
        ({"choices": [{"message": {"content": "<think>x</think>\n\nAntwort [1]."}}]}, "Antwort [1]."),
        ({"choices": [{"message": {"content": "\n\nAntwort [1]."}}]}, "Antwort [1]."),
        ({"choices": []}, ""),
    ],
)
def test_completion_text_strips_reasoning(response, expected):
    extract = load_middleware_functions("_completion_text")["_completion_text"]
    assert extract(response) == expected


def test_replace_last_answer_text_only_touches_the_final_message():
    replace_text = load_middleware_functions("_replace_last_answer_text")["_replace_last_answer_text"]
    output = [
        {"type": "message", "content": [{"type": "output_text", "text": "alt 1"}]},
        {"type": "function_call", "name": "rag_chat"},
        {"type": "message", "content": [{"type": "output_text", "text": "alt 2"}]},
    ]

    replace_text(output, "neu")

    assert output[0]["content"][0]["text"] == "alt 1"
    assert output[2]["content"][0]["text"] == "neu"
```

- [ ] **Step 2:** Run → FAIL (Funktionen fehlen)
- [ ] **Step 3: Implement** (vor `def _observe_model_led_answer(`):

```python
def _answer_enforcement_mode() -> str:
    mode = str(os.getenv('KAHLE_ANSWER_ENFORCEMENT') or 'observe').strip().lower()
    return mode if mode in {'observe', 'enforce'} else 'observe'


_DEFAULT_ANSWER_RETRY_TIMEOUTS = {'default': 45, 'Qwen/': 120}


def _answer_retry_timeout(base_model_id: str) -> int:
    """Seconds for one correction call; reasoning models need longer."""
    try:
        configured = json.loads(os.getenv('KAHLE_ANSWER_RETRY_TIMEOUTS') or 'null')
    except (TypeError, ValueError):
        configured = None
    timeouts = configured if isinstance(configured, dict) else _DEFAULT_ANSWER_RETRY_TIMEOUTS
    model = str(base_model_id or '')
    for prefix, seconds in timeouts.items():
        if prefix != 'default' and model.startswith(prefix):
            return int(seconds)
    return int(timeouts.get('default', 45))


def _knowledge_retry_messages(
    messages: list[dict[str, Any]], output: list[dict[str, Any]], retry_prompt: str,
) -> list[dict[str, Any]]:
    """Provider-neutral correction request.

    Systems stay first (Qwen rejects later system messages), tool results are
    passed as plain text (Mistral validates tool-call ids strictly), and the
    correction order is a user turn.
    """
    systems = [
        {'role': 'system', 'content': str(item.get('content') or '')}
        for item in messages if isinstance(item, dict) and item.get('role') == 'system'
    ]
    history = [
        {'role': item['role'], 'content': item['content']}
        for item in messages
        if isinstance(item, dict) and item.get('role') in {'user', 'assistant'}
        and isinstance(item.get('content'), str) and item['content'].strip()
    ]
    # Pre-routed evidence lives in form_data messages as tool turns.
    tool_texts = [
        str(item.get('content') or '')
        for item in messages
        if isinstance(item, dict) and item.get('role') == 'tool' and item.get('content')
    ]
    draft = ''
    for item in output or []:
        if item.get('type') == 'function_call_output':
            parts = item.get('output') or []
            text = '\n'.join(
                str(part.get('text') or '') for part in parts if isinstance(part, dict)
            ) if isinstance(parts, list) else str(parts)
            tool_texts.append(text)
        elif item.get('type') == 'function_call':
            tool_texts.append(f"Werkzeugaufruf: {item.get('name')}")
        elif item.get('type') == 'message':
            for part in item.get('content') or []:
                if part.get('type') == 'output_text':
                    draft = str(part.get('text') or '')
    result = [*systems, *history]
    if tool_texts:
        result.append({
            'role': 'user',
            'content': 'Ergebnisse der internen Werkzeuge dieser Anfrage:\n\n' + '\n\n'.join(tool_texts),
        })
    result.append({'role': 'assistant', 'content': draft})
    result.append({'role': 'user', 'content': retry_prompt})
    return result


def _completion_text(response: Any) -> str:
    if hasattr(response, 'body'):
        try:
            response = json.loads(response.body)
        except (TypeError, ValueError):
            return ''
    choices = response.get('choices') if isinstance(response, dict) else None
    if not choices:
        return ''
    text = str((choices[0].get('message') or {}).get('content') or '')
    text = re.sub(r'(?is)<(think|thinking|reasoning)>.*?</\1>', '', text)
    return text.strip()


def _replace_last_answer_text(output: list[dict[str, Any]], text: str) -> None:
    for item in reversed(output or []):
        if item.get('type') != 'message':
            continue
        for part in reversed(item.get('content') or []):
            if part.get('type') == 'output_text':
                part['text'] = text
                return
```

- [ ] **Step 4:** Tests → PASS
- [ ] **Step 5: Commit** `feat(middleware): provider-neutral helpers for answer correction`

### Task 4: `_enforce_knowledge_answer`

- [ ] **Step 1: Failing tests** (anhängen):

```python
def _enforce_namespace():
    harness = load_harness()
    namespace = load_middleware_functions(
        "_enforce_knowledge_answer", "_knowledge_retry_messages",
        "_replace_last_answer_text", "_last_kahle_answer_text",
        validate_knowledge_harness_answer=harness.validate_answer,
        knowledge_abstention_answer=harness.knowledge_abstention_answer,
        AnswerValidation=harness.AnswerValidation,
    )
    return harness, namespace["_enforce_knowledge_answer"]


def _payload(harness):
    rag = "KAHLE_RAG_RESULT\nFOUND: true\nCONTEXT:\n[1] Handbuch | A\nÖffnen Sie die Maske.\n"
    return harness.build_decision(
        query="Wie öffne ich die Maske?", resolved_query="Wie öffne ich die Maske?", messages=[],
        model_id="m", permission_scope={"user_id": "u"}, rag_result=rag,
    ).to_dict()


def _output(text):
    return [{"type": "message", "content": [{"type": "output_text", "text": text}]}]


def _run(enforce, output, payload, replies, timeout=5):
    calls = []

    async def regenerate(messages):
        calls.append(messages)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    result = asyncio.run(enforce(
        output, payload, messages=[{"role": "user", "content": "Frage"}],
        reference_urls=(), regenerate=regenerate, timeout_seconds=timeout,
    ))
    return result, calls


def test_accepted_answer_is_delivered_without_retry():
    harness, enforce = _enforce_namespace()
    output = _output("Öffnen Sie die Maske [1].")

    result, calls = _run(enforce, output, _payload(harness), [])

    assert calls == []
    assert (result["delivery_status"], result["retry_count"], result["fallback_used"]) == ("accepted", 0, False)
    assert output[0]["content"][0]["text"] == "Öffnen Sie die Maske [1]."


def test_blocking_violation_is_corrected_once():
    harness, enforce = _enforce_namespace()
    output = _output("Öffnen Sie die Maske.")

    result, calls = _run(enforce, output, _payload(harness), ["Öffnen Sie die Maske [1]."])

    assert len(calls) == 1 and calls[0][-1]["content"].startswith("KAHLE_KNOWLEDGE_ANSWER_RETRY")
    assert (result["delivery_status"], result["retry_count"], result["fallback_used"]) == ("corrected", 1, False)
    assert [attempt["status"] for attempt in result["attempts"]] == ["retry_required", "accepted"]
    assert output[0]["content"][0]["text"] == "Öffnen Sie die Maske [1]."


@pytest.mark.parametrize("reply", ["Immer noch ohne Zitat.", asyncio.TimeoutError(), RuntimeError("upstream")])
def test_failed_correction_falls_back_to_neutral_abstention(reply):
    harness, enforce = _enforce_namespace()
    output = _output("Öffnen Sie die Maske.")

    result, calls = _run(enforce, output, _payload(harness), [reply])

    assert len(calls) == 1
    assert (result["delivery_status"], result["retry_count"], result["fallback_used"]) == ("abstained", 1, True)
    assert output[0]["content"][0]["text"].startswith("Dazu habe ich keine verlässliche freigegebene Information.")


def test_advisory_findings_never_trigger_a_retry():
    harness, enforce = _enforce_namespace()
    output = _output("Öffnen Sie die Maske [1]. Das ist technisch möglich.")

    result, calls = _run(enforce, output, _payload(harness), [])

    assert calls == []
    assert result["delivery_status"] == "accepted"
```

- [ ] **Step 2:** Run → FAIL
- [ ] **Step 3: Implement** (direkt nach `_replace_last_answer_text`):

```python
async def _enforce_knowledge_answer(
    output: list[dict[str, Any]],
    harness_payload: dict[str, Any],
    *,
    messages: list[dict[str, Any]],
    reference_urls: tuple[str, ...],
    regenerate: Any,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Validate before delivery; one tool-free correction; else abstain.

    The function never formulates internal facts itself: it either keeps a
    model answer that passed the blocking checks or replaces it with a neutral
    abstention.
    """
    first = validate_knowledge_harness_answer(
        _last_kahle_answer_text(output), harness_payload, reference_urls=reference_urls,
    )
    attempts = [first.to_dict()]
    if not first.retry_required:
        return {'attempts': attempts, 'delivery_status': 'accepted', 'retry_count': 0, 'fallback_used': False}

    evidence = harness_payload.get('evidence_bundle') or {}
    source_ids = tuple(
        str(source.get('id') or source.get('number') or source.get('source_id') or '').lstrip('#')
        for source in evidence.get('sources') or ()
        if isinstance(source, dict)
    )
    retry_prompt = first.retry_prompt(source_ids=tuple(item for item in source_ids if item))
    corrected = ''
    try:
        corrected = await asyncio.wait_for(
            regenerate(_knowledge_retry_messages(messages, output, retry_prompt)),
            timeout=timeout_seconds,
        )
    except Exception as error:  # timeout or upstream failure → neutral abstention
        attempts.append({'status': 'retry_failed', 'error': type(error).__name__, 'violations': []})
    if corrected:
        second = validate_knowledge_harness_answer(
            corrected, harness_payload, reference_urls=reference_urls,
        )
        attempts.append(second.to_dict())
        if not second.retry_required:
            _replace_last_answer_text(output, corrected)
            return {'attempts': attempts, 'delivery_status': 'corrected', 'retry_count': 1, 'fallback_used': False}
    _replace_last_answer_text(
        output, knowledge_abstention_answer(has_sources=bool(source_ids)),
    )
    return {'attempts': attempts, 'delivery_status': 'abstained', 'retry_count': 1, 'fallback_used': True}
```

Import in `middleware.py` bei den Harness-Imports ergänzen: `knowledge_abstention_answer`.

- [ ] **Step 4:** Tests → PASS (`validate_answer` akzeptiert bereits `reference_urls=`)
- [ ] **Step 5: Commit** `feat(middleware): enforce the answer contract with one correction`

### Task 5: Puffer im Streaming-Pfad

Der Antworttext wird bei internen Wissens-Turns zurückgehalten. Reasoning und Toolstatus bleiben sichtbar.

- [ ] **Step 1: Failing tests** (anhängen):

```python
def test_hold_hides_answer_text_but_keeps_reasoning():
    safe = load_middleware_functions("_stream_safe_output", "_strip_pseudo_toolcall_stream_text",
                                     "_collapse_immediately_repeated_paragraph_sequence")["_stream_safe_output"]
    output = [
        {"type": "reasoning", "content": [{"type": "text", "text": "denke"}], "summary": []},
        {"type": "message", "content": [{"type": "output_text", "text": "Antwort"}]},
    ]

    held = safe(output, suppress_message_text=True, suppress_reasoning=False)

    assert held[0]["content"] == [{"type": "text", "text": "denke"}]
    assert held[1]["content"][0]["text"] == ""
    assert safe(output, suppress_message_text=True)[0]["content"] == []


def test_stream_holds_knowledge_answers_in_enforce_mode():
    source = MIDDLEWARE.read_text(encoding="utf-8")

    assert "hold_knowledge_answer = (" in source
    assert "suppress_message_text=suppress_initial_rag_response or hold_knowledge_answer" in source
    assert "suppress_reasoning=suppress_initial_rag_response" in source
    assert re.search(
        r"if tool_function_name in \{'rag_chat', 'personio_directory'\}:\s+"
        r"hold_knowledge_answer = _answer_enforcement_mode\(\) == 'enforce'",
        source,
    )
```

- [ ] **Step 2:** Run → FAIL
- [ ] **Step 3: Implement**
  - `_stream_safe_output(output, *, suppress_message_text=False, suppress_reasoning=None)`. Am Anfang `if suppress_reasoning is None: suppress_reasoning = suppress_message_text`. Im Reasoning-Zweig `suppress_message_text` durch `suppress_reasoning` ersetzen.
  - Direkt nach der Berechnung von `suppress_initial_rag_response` (vor `def full_output():`):

```python
            hold_knowledge_answer = (
                _answer_enforcement_mode() == 'enforce'
                and bool(metadata.get('kahle_knowledge_harness_active'))
            )
```

  - In beiden `_stream_safe_output(...)`-Aufrufen in `full_output()`: `suppress_message_text=suppress_initial_rag_response or hold_knowledge_answer, suppress_reasoning=suppress_initial_rag_response`.
  - Im Tool-Loop, direkt vor `if tool_function_name == 'rag_chat':` (bei `canonical_rag_sources.extend`):

```python
                        if tool_function_name in {'rag_chat', 'personio_directory'}:
                            hold_knowledge_answer = _answer_enforcement_mode() == 'enforce'
```

  Liegt diese Stelle in einer verschachtelten Funktion, muss `hold_knowledge_answer` dort als `nonlocal` deklariert werden. Vorher per Code-Lesen prüfen. Der Test deckt die Zuweisung ab, nicht den Gültigkeitsbereich. Deshalb anschließend `python -m py_compile` auf `middleware.py` ausführen.

- [ ] **Step 4:** Tests → PASS; `stack/tests` vollständig grün
- [ ] **Step 5: Commit** `feat(middleware): hold knowledge answers until validated`

### Task 6: Anschluss an der Validierungsstelle und Metriken

- [ ] **Step 1: Failing test** (anhängen):

```python
def test_validation_point_enforces_in_enforce_mode_and_records_metrics():
    source = MIDDLEWARE.read_text(encoding="utf-8")
    block = source[source.index("validation_attempts = []"):source.index("if not shadow_validation:\n")]

    assert "_answer_enforcement_mode() == 'enforce'" in block
    assert "await _enforce_knowledge_answer(" in block
    assert "timeout_seconds=_answer_retry_timeout(" in block
    assert "'retry_count': enforcement['retry_count']" in block
    assert "'fallback_used': enforcement['fallback_used']" in block
    assert "'delivery_status': enforcement['delivery_status']" in block
    assert "Antwort wird anhand der Quellen geprüft" in source
```

- [ ] **Step 2:** Run → FAIL
- [ ] **Step 3: Implement.** An der Stelle `validation_attempts = []` den Block bis vor `if harness_payload:` ersetzen:

```python
                validation_attempts = []
                enforcement = {'retry_count': 0, 'fallback_used': False, 'delivery_status': None}
                harness_payload = _ephemeral_kahle_harness_payload(request)
                shadow_validation = bool(
                    harness_payload
                    and (harness_payload.get('retrieval_plan') or {}).get('mode') == 'model_led'
                )
                enforce_answer = bool(
                    _answer_enforcement_mode() == 'enforce'
                    and metadata.get('kahle_knowledge_harness_active')
                    and harness_payload
                )
                if enforce_answer:
                    await event_emitter({
                        'type': 'status',
                        'data': {'description': 'Antwort wird anhand der Quellen geprüft', 'done': False},
                    })

                    async def regenerate(retry_messages):
                        response = await generate_chat_completion(
                            request,
                            {'model': model_id, 'messages': retry_messages,
                             'stream': False, 'metadata': metadata},
                            user,
                            bypass_system_prompt=True,
                        )
                        return _completion_text(response)

                    enforcement = await _enforce_knowledge_answer(
                        output,
                        harness_payload,
                        messages=form_data.get('messages', []) or [],
                        reference_urls=_canonical_kahle_reference_urls(canonical_rag_sources),
                        regenerate=regenerate,
                        timeout_seconds=_answer_retry_timeout(
                            str((model.get('info') or {}).get('base_model_id') or model_id)
                            if isinstance(model, dict) else str(model_id)
                        ),
                    )
                    validation_attempts = enforcement['attempts']
                    metadata['kahle_answer_validation'] = {
                        'schema_version': 'kahle.answer-validation-run.v1',
                        'mode': 'enforce',
                        'attempts': validation_attempts,
                    }
                    await event_emitter({
                        'type': 'status',
                        'data': {'description': 'Antwort wird anhand der Quellen geprüft', 'done': True},
                    })
                    shadow_validation = True
                    _append_canonical_rag_source_links(output, canonical_rag_sources)
                    _append_canonical_rag_feedback_link(output, canonical_rag_feedback_link)
                elif shadow_validation:
```

Der bisherige Rest bleibt erhalten und wird zu `elif`/`else`-Zweigen:

- Das bisherige `if shadow_validation:` mit dem Anhängen der Links wird zu `elif shadow_validation:`.
- Die folgenden Beobachtungszweige laufen nur, wenn `not enforce_answer`.

In `metadata['kahle_harness_metrics']` die festen Werte ersetzen:

```python
                        'retry_count': enforcement['retry_count'],
                        'fallback_used': enforcement['fallback_used'],
                        'delivery_status': (
                            enforcement['delivery_status']
                            or ('observed' if shadow_validation else
                                validation_attempts[-1].get('status') if validation_attempts else 'not_run')
                        ),
```

Imports prüfen: `generate_chat_completion` ist in `middleware.py` bereits importiert (Tool-Loop).

Compose:
- `stack/docker-compose.yml` unter den Harness-Variablen: `KAHLE_ANSWER_ENFORCEMENT: ${KAHLE_ANSWER_ENFORCEMENT:-observe}`
- `stack/docker-compose.local-edge.yml`: `KAHLE_ANSWER_ENFORCEMENT: "enforce"`

- [ ] **Step 4:** Tests → PASS; `py_compile` auf `middleware.py`; `stack/tests` vollständig; `compose_static_check.py` grün
- [ ] **Step 5: Commit** `feat(middleware): deliver only validated knowledge answers in enforce mode`

### Task 7: Eval erfasst Korrektur und Enthaltung

- [ ] **Step 1: Failing test** in `eval/harness/tests/test_harness_eval.py`:

```python
def test_score_and_summary_include_correction_metrics():
    message = _message(text="Antwort [1].")
    message["kahle_harness_metrics"].update({"retry_count": 1, "fallback_used": False, "delivery_status": "corrected"})

    score = score_answer(_case(), message)
    summary = summarize_answers([{"model": "m", **score, "wall_ms": 10}])["m"]

    assert (score["retry_count"], score["fallback_used"], score["delivery_status"]) == (1, False, "corrected")
    assert summary["retry_rate"] == 1.0 and summary["fallback_rate"] == 0.0
```

- [ ] **Step 2:** Run → FAIL
- [ ] **Step 3: Implement.** In `score_answer` zusätzlich zurückgeben: `retry_count` (int, Default 0), `fallback_used` (bool) und `delivery_status` (str), alles aus `kahle_harness_metrics`. In `summarize_answers` `retry_rate` und `fallback_rate` ergänzen. Der Abstention-Regex erkennt den neuen Enthaltungstext bereits („keine verlässliche freigegebene“).
- [ ] **Step 4:** `eval/harness/tests` → PASS
- [ ] **Step 5: Commit** `feat(eval): report correction and abstention rates`

### Task 8: Verify, Ausrollen, Laufzeitmessung

- [ ] Full Verify → Exit 0
- [ ] Ausrollen wie für 0b: Prompts, Tools und Guard registrieren, `open-webui` mit dem Overlay neu **erstellen**, nicht nur neu starten, damit `KAHLE_ANSWER_ENFORCEMENT=enforce` greift. Container-Env danach per `docker exec open-webui printenv KAHLE_ANSWER_ENFORCEMENT` prüfen.
- [ ] Rauchtest: ein Fall je Modell. Das Ergebnis ist gültig, wenn `delivery_status` gesetzt ist.
- [ ] Voller Laufzeit-Eval (99 Fälle × 3 Modelle), Vergleich mit `2026-09-30-runtime-phase0b.json`
- [ ] Zusammenfassung einchecken: `eval/harness/results/<datum>-runtime-phase2.json`

## Abnahme Phase 2

- Ausgelieferte Antworten mit blockierendem Verstoß: **0** je Modell. Enthaltungen zählen als ausgeliefert ohne Verstoß.
- Retry-Rate, Fallback-Rate und p50/p95-Latenz je Modell sind dokumentiert. Erwartung aus dem Prototyp: Retry-Rate ≈ Blocking-Rate aus 0b (Mistral ≈ 27 %, gpt-oss ≈ 21 %, Qwen ≈ 11 %), Fallback deutlich darunter, Mehrlatenz im Retry-Fall ≈ 1–2 s bzw. 10–70 s bei Qwen.
- Routing-Trefferquote nicht schlechter als 0b.
- Ist die Fallback-Rate eines Modells über 10 %: Befund dokumentieren und Nachschärfung des Korrektur-Prompts als eigenen Task planen, statt den Validator aufzuweichen.

## Begleitänderung

- `809fd84`: Für die Laufzeitmessung musste der Open-WebUI-Container neu erstellt werden. Unter Windows PowerShell 5.1 gab `ConvertFrom-Json` das Docker-JSON-Array als ein einziges Objekt zurück, und `scripts/start-stack.ps1` hielt deshalb alle Container für fremd.
- `scripts/StackRuntime.psm1` zählt die Elemente jetzt einzeln auf; abgesichert ist das durch einen Test in `stack/tests/test_stack_runtime.py`.

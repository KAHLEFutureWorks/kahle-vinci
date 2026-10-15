# Harness Phase 4b: Prompt-Zusammensetzung messen und Tokens senken

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die Prompt-Tokens je Wissensantwort spürbar senken (Ziel: Median mindestens −15 % je Modell gegenüber der 4a-Messung), ohne dass Routing, Verstöße oder Nachbesserungen schlechter werden.

**Architecture:** Zuerst wird gemessen, woraus der Prompt der Antwort besteht: eine reine Funktion `prompt_composition()` im Harness zählt Zeichen je Bestandteil, die Middleware hängt das Ergebnis an `kahle_harness_metrics`, die Eval übernimmt es. Erst danach wird gekürzt, und zwar nur dort, wo die Messung einen großen Posten zeigt: doppelte Dokumentpassagen im Bauplan (technisch) und Antwortregeln im Systemprompt, die der Harness bereits erzwingt (redaktionell, mit Freigabe je Abschnitt).

**Tech Stack:** Python 3.11, Open-WebUI-Overrides (`middleware.py`, `kahle_knowledge_harness.py`), pytest, `eval/harness`.

---

## Ausgangslage (gemessen 12.10., Phase 4a)

| Modell | `prompt_tokens` Median |
| --- | --- |
| Mistral (`vinci-2-clone-clone-clone`) | 17.496 |
| gpt-oss (`kahle-vinci-thinking`) | 12.798 |
| `kahle-vinci-max-thinking` | 16.865 |

Bekannte Posten (09.10. und 13.10., gezählt in Dateien und Code, nicht im laufenden Prompt):

- Systemprompt `kahle-vinci-systemprompt.md` 29.308 Zeichen; davon Abschnitt „3) TOOL-ROUTING“ mit dem Block „Regeln:“ allein ca. 9.400 Zeichen (ca. 2.500 Token).
- Tool-Spezifikationen ca. 13.000 Zeichen.
- Der Bauplan (`KAHLE_KNOWLEDGE_ANSWER_BLUEPRINT`) trägt je Claim ein `evidence_span`. Diese Spans sind Auszüge derselben Passagen, die vollständig im `rag_chat`-Ergebnis stehen (`_supported_claims`: bis zu 4 × 500 Zeichen je Passage, bei Anleitungen jeder Satz). Wie viel davon im selben Prompt doppelt steht, ist **nicht gemessen**.

## Dateien

| Datei | Änderung |
| --- | --- |
| `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py` | neue Funktion `prompt_composition()`; Task 5: `AnswerBlueprint.to_prompt_dict()` |
| `stack/open-webui-overrides/open_webui/utils/middleware.py` | Zusammensetzung vor jedem Antwortaufruf im Tool-Loop erfassen und in `kahle_harness_metrics` übernehmen |
| `eval/harness/harness_eval.py` | `score_answer` übernimmt `prompt_composition`; `summarize_answers` meldet Mediane je Bestandteil |
| `stack/tests/test_kahle_harness_phase4b.py` | neue Tests |
| `eval/harness/tests/test_harness_eval.py` | Tests für die Übernahme in die Eval |
| `stack/open-webui-prompts/kahle-vinci-systemprompt.md`, `kahle-vinci-thinking-systemprompt.md` | Task 6, nur nach Freigabe |

---

### Task 1: Zusammensetzung als reine Funktion

**Files:**
- Modify: `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py` (neue Funktion am Dateiende)
- Test: `stack/tests/test_kahle_harness_phase4b.py`

- [ ] **Step 1: Failing test schreiben**

```python
"""Phase 4b: measure what the answer prompt is made of, then cut the largest parts."""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "kahle_knowledge_harness.py"


def load_harness():
    spec = importlib.util.spec_from_file_location("kahle_harness_phase4b", HARNESS)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PASSAGE = (
    "Reklamationen werden im Garantieportal erfasst. Die Werkstattleitung prüft "
    "den Antrag innerhalb von zwei Arbeitstagen und gibt ihn frei."
)
SPAN = "Die Werkstattleitung prüft den Antrag innerhalb von zwei Arbeitstagen"
BLUEPRINT = {"sections": [{"section_id": "s1", "heading": "Ablauf", "order": 1, "coverage": "supported",
                           "claims": [{"claim_id": "c1", "source_id": "1", "evidence_span": SPAN,
                                       "evidence_role": "editorial"}]}]}
CONTRACT = (
    "KAHLE_KNOWLEDGE_ANSWER_CONTRACT\n{\"schema_version\":\"kahle.answer-contract.v1\"}\n"
    "\nKAHLE_KNOWLEDGE_ANSWER_BLUEPRINT\n" + json.dumps(BLUEPRINT, ensure_ascii=False) + "\n"
    "Formuliere die sichtbare Antwort.\nAntworte nur aus der bereitgestellten Evidenz."
)
DUTIES = "KAHLE_KNOWLEDGE_ANSWER_DUTIES\n- Belege jede interne Aussage."


def test_composition_counts_each_part_once_and_finds_duplicate_spans():
    harness = load_harness()
    messages = [
        {"role": "system", "content": "Du bist Vinci."},
        {"role": "system", "content": CONTRACT},
        {"role": "user", "content": "Wie läuft eine Reklamation?\n\n" + DUTIES},
        {"role": "assistant", "content": ""},
        {"role": "tool", "content": "[1] Garantie\n" + PASSAGE},
    ]
    tools = [{"type": "function", "function": {"name": "rag_chat", "parameters": {}}}]

    result = harness.prompt_composition(messages, tools)

    blueprint_line = json.dumps(BLUEPRINT, ensure_ascii=False)
    assert result["system_chars"] == len("Du bist Vinci.")
    assert result["blueprint_chars"] == len(blueprint_line)
    assert result["contract_chars"] == len(CONTRACT) - len(blueprint_line)
    assert result["duties_chars"] == len(DUTIES)
    assert result["conversation_chars"] == len("Wie läuft eine Reklamation?\n\n")
    assert result["tool_result_chars"] == len("[1] Garantie\n" + PASSAGE)
    assert result["tool_spec_chars"] == len(json.dumps(tools, ensure_ascii=False))
    assert result["duplicate_span_chars"] == len(SPAN)
    assert result["total_chars"] == sum(
        value for key, value in result.items()
        if key.endswith("_chars") and key not in {"total_chars", "duplicate_span_chars"}
    )


def test_context_blocks_in_system_messages_count_as_tool_results():
    harness = load_harness()
    rag_system = "Regeln.\n<context>\n[1] Garantie\n" + PASSAGE + "\n</context>\nEnde."

    result = harness.prompt_composition([{"role": "system", "content": rag_system}], None)

    context = "<context>\n[1] Garantie\n" + PASSAGE + "\n</context>"
    assert result["tool_result_chars"] == len(context)
    assert result["system_chars"] == len(rag_system) - len(context)
    assert result["tool_spec_chars"] == 0


def test_composition_accepts_list_content_and_ignores_garbage():
    harness = load_harness()
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "Hallo"}, {"type": "image_url"}]},
        "kein dict",
        {"role": "system", "content": None},
    ]

    result = harness.prompt_composition(messages, [])

    assert result["conversation_chars"] == len("Hallo")
    assert result["total_chars"] == len("Hallo")
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run (Repository-Root): `.\.venv-verify\Scripts\python.exe -m pytest stack\tests\test_kahle_harness_phase4b.py -q -p no:cacheprovider`
Expected: FAIL mit `AttributeError: module 'kahle_harness_phase4b' has no attribute 'prompt_composition'`

- [ ] **Step 3: Minimale Implementierung am Ende von `kahle_knowledge_harness.py`**

```python
_COMPOSITION_CONTEXT = re.compile(r"<context>.*?</context>", re.S)
_CONTRACT_MARKER = "KAHLE_KNOWLEDGE_ANSWER_CONTRACT\n"
_BLUEPRINT_MARKER = "KAHLE_KNOWLEDGE_ANSWER_BLUEPRINT\n"
_DUTIES_MARKER = "KAHLE_KNOWLEDGE_ANSWER_DUTIES\n"


def _composition_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def prompt_composition(messages: Any, tools: Any) -> dict[str, int]:
    """Characters per prompt part of one model call; values only, no text."""
    parts = dict.fromkeys(
        ("system_chars", "contract_chars", "blueprint_chars", "duties_chars",
         "tool_result_chars", "conversation_chars", "tool_spec_chars"), 0,
    )
    tool_texts: list[str] = []
    spans: list[str] = []
    for message in messages or ():
        if not isinstance(message, dict):
            continue
        text = _composition_text(message.get("content"))
        if message.get("role") == "tool":
            parts["tool_result_chars"] += len(text)
            tool_texts.append(text)
            continue
        for block in _COMPOSITION_CONTEXT.findall(text):
            parts["tool_result_chars"] += len(block)
            tool_texts.append(block)
        text = _COMPOSITION_CONTEXT.sub("", text)
        duties_at = text.find(_DUTIES_MARKER)
        if duties_at >= 0:
            parts["duties_chars"] += len(text) - duties_at
            text = text[:duties_at]
        contract_at = text.find(_CONTRACT_MARKER)
        if contract_at >= 0:
            contract = text[contract_at:]
            text = text[:contract_at]
            blueprint_at = contract.find(_BLUEPRINT_MARKER)
            if blueprint_at >= 0:
                line_start = blueprint_at + len(_BLUEPRINT_MARKER)
                line_end = contract.find("\n", line_start)
                line = contract[line_start:] if line_end < 0 else contract[line_start:line_end]
                parts["blueprint_chars"] += len(line)
                contract = contract[:line_start] + contract[line_start + len(line):]
                try:
                    blueprint = json.loads(line)
                except ValueError:
                    blueprint = {}
                spans.extend(
                    str(claim.get("evidence_span") or "")
                    for section in blueprint.get("sections") or ()
                    for claim in section.get("claims") or ()
                    if isinstance(claim, dict)
                )
            parts["contract_chars"] += len(contract)
        key = "system_chars" if message.get("role") == "system" else "conversation_chars"
        parts[key] += len(text)
    if tools:
        parts["tool_spec_chars"] = len(json.dumps(tools, ensure_ascii=False))
    parts["total_chars"] = sum(parts.values())
    parts["duplicate_span_chars"] = sum(
        len(span) for span in spans
        if len(span.strip()) >= 20 and any(span.strip() in tool for tool in tool_texts)
    )
    return parts
```

- [ ] **Step 4: Test laufen lassen**

Run: `.\.venv-verify\Scripts\python.exe -m pytest stack\tests\test_kahle_harness_phase4b.py -q -p no:cacheprovider`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py stack/tests/test_kahle_harness_phase4b.py
git commit -m "feat(harness): count prompt characters per part of one model call"
```

### Task 2: Erfassung in der Middleware und Übernahme in die Eval

**Files:**
- Modify: `stack/open-webui-overrides/open_webui/utils/middleware.py` (Import ca. Zeile 94; Tool-Loop vor `generate_chat_completion` ca. Zeile 8256 und 8440; Metriken ca. Zeile 8538)
- Modify: `eval/harness/harness_eval.py` (`score_answer` ca. Zeile 219, `summarize_answers` ca. Zeile 265)
- Test: `stack/tests/test_kahle_harness_phase4b.py`, `eval/harness/tests/test_harness_eval.py`

- [ ] **Step 1: Failing tests schreiben**

An `stack/tests/test_kahle_harness_phase4b.py` anhängen (statische Prüfung wie in `test_kahle_harness_phase4a.py`, weil die Middleware ohne Open WebUI nicht importierbar ist):

```python
MIDDLEWARE = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "middleware.py"


def test_middleware_records_composition_before_each_answer_call_and_reports_it():
    source = MIDDLEWARE.read_text(encoding="utf-8")
    record = (
        "metadata['_kahle_prompt_composition'] = prompt_composition(\n"
    )
    assert source.count(record) == 2
    assert "'prompt_composition': metadata.get('_kahle_prompt_composition') or {}," in source
    assert "    prompt_composition,\n" in source
```

An `eval/harness/tests/test_harness_eval.py` anhängen (`_case()` ist dort bereits definiert, ca. Zeile 158):

```python
def test_score_and_summary_carry_prompt_composition():
    from harness_eval import score_answer, summarize_answers

    composition = {"system_chars": 100, "tool_result_chars": 50, "duplicate_span_chars": 10}
    message = {"content": "Antwort [1]", "kahle_harness_metrics": {"prompt_composition": composition}}
    row = score_answer(_case(), message)
    assert row["prompt_composition"] == composition

    summary = summarize_answers([
        {**row, "model": "m", "outcome": "correct"},
        {**row, "model": "m", "outcome": "correct",
         "prompt_composition": {"system_chars": 300, "tool_result_chars": 70, "duplicate_span_chars": 30}},
    ])
    assert summary["m"]["composition_p50"]["system_chars"] == 100
    assert summary["m"]["composition_p50"]["duplicate_span_chars"] == 10
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag prüfen**

Run: `.\.venv-verify\Scripts\python.exe -m pytest stack\tests\test_kahle_harness_phase4b.py -q -p no:cacheprovider`
Expected: FAIL in `test_middleware_records_composition_before_each_answer_call_and_reports_it`

Run: `.\.venv-verify\Scripts\python.exe -m pytest eval\harness\tests\test_harness_eval.py -q -p no:cacheprovider -k composition`
Expected: FAIL mit `KeyError: 'prompt_composition'`

- [ ] **Step 3: Middleware ändern**

Im Import-Block `from open_webui.utils.kahle_knowledge_harness import (` alphabetisch passend ergänzen:

```python
    person_confirmation_names,
    prompt_composition,
    released_decision_payload,
```

Unmittelbar vor `res = await generate_chat_completion(` im Antwortpfad (ca. Zeile 8256, nach dem Block mit `final_answer_prompt`) und ebenso vor dem zweiten Aufruf im Tool-Loop (ca. Zeile 8440) einfügen, jeweils mit der dortigen Einrückung:

```python
                        metadata['_kahle_prompt_composition'] = prompt_composition(
                            new_form_data.get('messages'), new_form_data.get('tools'),
                        )
```

Der letzte Aufruf überschreibt den vorherigen; gemessen wird also der Prompt der ausgelieferten Antwort, nicht der Retry der Antwortprüfung.

In `metadata['kahle_harness_metrics'] = {` (ca. Zeile 8538) nach `'latency_ms': elapsed_ms,` ergänzen:

```python
                        'prompt_composition': metadata.get('_kahle_prompt_composition') or {},
```

- [ ] **Step 4: Eval ändern**

In `score_answer` nach `"completion_tokens": ...` ergänzen:

```python
        "prompt_composition": dict(metrics.get("prompt_composition") or {}),
```

In `summarize_answers` vor `summary[model] = {` ergänzen:

```python
        composition_keys = sorted({key for row in items for key in row.get("prompt_composition") or {}})
        composition_p50 = {
            key: nearest_rank(
                [row["prompt_composition"][key] for row in items
                 if isinstance((row.get("prompt_composition") or {}).get(key), int)],
                0.5,
            )
            for key in composition_keys
        }
```

und im Dictionary nach `"completion_tokens_p50": ...` ergänzen:

```python
            "composition_p50": composition_p50,
```

- [ ] **Step 5: Tests laufen lassen**

Run: `.\.venv-verify\Scripts\python.exe -m pytest stack\tests\test_kahle_harness_phase4b.py -q -p no:cacheprovider`
Expected: `4 passed`

Run: `.\.venv-verify\Scripts\python.exe -m pytest eval\harness\tests -q -p no:cacheprovider`
Expected: alle bestanden

- [ ] **Step 6: Commit**

```bash
git add stack/open-webui-overrides/open_webui/utils/middleware.py eval/harness/harness_eval.py stack/tests/test_kahle_harness_phase4b.py eval/harness/tests/test_harness_eval.py
git commit -m "eval(harness): report the prompt composition of each answer"
```

**Abweichung bei der Umsetzung (15.10., `d1a3a4b`):** Die Messung in der Middleware kam leer bzw. ohne Systemprompt an. Open WebUI fügt den Modell-Systemprompt erst im OpenAI-Router hinzu, und `utils/chat.py` gibt dem Router eine zusammengeführte Kopie der Metadaten. Gemessen wird deshalb in `routers/openai.py` direkt nach `apply_system_prompt_to_body` auf `request.state.metadata` (Hintergrundaufgaben mit `metadata.task` ausgenommen); die Middleware liest den Wert von dort. Erfasst wird der letzte Aufruf; nach einer Nachbesserung der Antwortprüfung ist das der Nachbesserungsaufruf ohne Tools, während `prompt_tokens` aus der Nutzungsangabe des Chats stammt.

### Task 3: Messung der Zusammensetzung und Entscheidungspunkt

- [ ] **Step 1: Open WebUI neu starten** (Middleware und Harness sind gemountet): `docker restart open-webui`, danach `http://localhost:3004/health` = `200`

- [ ] **Step 2: Laufzeit-Eval je Modell einzeln.** Token aus `%USERPROFILE%\.kahle-owui-token` nur im Prozess setzen und vorher mit `/api/models` = `200` prüfen.

```powershell
$env:OPENWEBUI_API_KEY = (Get-Content "$env:USERPROFILE\.kahle-owui-token" -Raw).Trim()
.\.venv-verify\Scripts\python.exe eval\harness\runtime_harness_eval.py --base-url http://localhost:3004 --models kahle-vinci-thinking --output-dir tmp\runtime-phase4b-composition
```

Wiederholen mit `--models vinci-2-clone-clone-clone` und `--models kahle-vinci-max-thinking`.

- [ ] **Step 3: Plausibilität prüfen.** `system_chars` muss bei Antworten mit Wissenstool in der Größenordnung des Systemprompts liegen (27.000–30.000 Zeichen). Liegt der Wert deutlich darunter, steht der Prompt an einer Stelle, die die Funktion nicht erfasst; dann zuerst Task 1 um diesen Fall ergänzen.

- [ ] **Step 4: Ergebnis in diesen Plan eintragen** (Tabelle: Median je Bestandteil und Modell) und committen:

```bash
git add docs/superpowers/plans/2026-10-13-harness-phase4b-prompt-composition-and-token-cut.md
git commit -m "eval(harness): phase 4b prompt composition measurement"
```

**Ergebnis (15.10., je 114 Fälle, Median in Zeichen, Prompt des letzten Aufrufs):**

| Bestandteil | gpt-oss (`thinking`) | Mistral (`vinci-2`) | `max-thinking` |
| --- | --- | --- | --- |
| Tool-Spezifikationen | 30.478 (49 %) | 30.478 (48 %) | 30.478 (49 %) |
| Systemprompt | 27.332 (44 %) | 29.252 (46 %) | 27.332 (44 %) |
| Antwortvertrag | 3.129 (5 %) | 3.133 (5 %) | 3.170 (5 %) |
| Tool-Ergebnisse, nur Fälle mit Ergebnis | 1.930 | 1.630 | 1.394 |
| Bauplan / doppelte Spans | 0 / 0 | 0 / 0 | 0 / 0 |
| Summe | 62.053 | 63.939 | 62.788 |
| `prompt_tokens` Median | 12.798 | 17.450 | 16.779 |
| Routing korrekt | 104 | 105 | 105 |

Tool-Spezifikationen je Gruppe (52 Funktionen, 30.376 Zeichen; Kurzlauf nach `5bf2a84`, bei beiden Modellen identisch):

| Gruppe | Funktionen | Zeichen | Überschneidung |
| --- | --- | --- | --- |
| Open-WebUI-Bordwerkzeuge Kalender | `create/update/search/delete_calendar_event` | 3.787 | keine |
| Open-WebUI-Bordwerkzeuge Automationen | `create/update/list/toggle/delete_automation` | 3.416 | doppelt zu `owui_productivity` `automations_*` (1.835) |
| Open-WebUI-Bordwerkzeuge Notizen | `write_note`, `replace_note_content`, `search_notes`, `view_note` | 1.920 | doppelt zu `notes_*` (1.240) |
| Open-WebUI-Bordwerkzeuge Aufgaben | `create_tasks`, `update_task` | 1.267 | doppelt zu `tasks_*` (969) und `kv_task_*` |
| Open-WebUI-Bordwerkzeuge Zeit | `get_current_timestamp`, `calculate_timestamp` | 1.071 | doppelt zu `zeit_berechnung` (1.308) |
| `server:doc-worker` | 11 Datei-Funktionen | 7.439 | keine; bei jeder Anfrage, auch ohne Datei |
| `kahle_tasks` | `kv_task_*` | 3.657 | siehe Aufgaben |
| `owui_productivity` | `automations_*`, `notes_*`, `tasks_*` | 4.044 | siehe oben |
| `zeit_berechnung`, `kahle_workflow`, `safe_websearch` | | 1.308 / 1.606 / 861 | |

Folgerungen: Task 5 entfällt (keine doppelten Passagen). Die Hebel sind Tool-Spezifikationen und Systemprompt; der Tool-Posten enthält mindestens 7.674 Zeichen Doppelungen (Bordwerkzeuge zu Automationen, Notizen, Aufgaben, Zeit).

- [ ] **Step 5: Entscheidungspunkt.** Task 5 wird nur umgesetzt, wenn `duplicate_span_chars` im Median bei mindestens einem Modell **≥ 1.000 Zeichen** liegt. Task 6 wird dem Nutzer mit den gemessenen Anteilen vorgelegt; ohne Freigabe entfällt er.

### Task 4: (entfällt bewusst) Tool-Spezifikationen

Die Tool-Spezifikationen (ca. 13.000 Zeichen) bleiben in 4b unverändert: Sie werden von Open WebUI aus den registrierten Tools erzeugt, und eine Kürzung der Tool-Beschreibungen ändert das Routing aller Modelle. Zeigt Task 3 sie als größten Posten, wird dafür ein eigener Plan geschrieben.

### Task 5: Bauplan ohne doppelte Passagen (nur nach Entscheidungspunkt)

Grundsatz: Das Modell sieht die vollständige Passage weiterhin im `rag_chat`-Ergebnis. Im Bauplan genügt ein kurzer Anker, damit der Claim seiner Passage zugeordnet werden kann. Die Antwortprüfung arbeitet weiter mit dem internen `AnswerBlueprint` und dessen vollständigen Spans; nur die Prompt-Fassung wird kürzer.

**Files:**
- Modify: `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py` (`AnswerBlueprintClaim`, `AnswerBlueprint`, `answer_prompt` ca. Zeile 377)
- Test: `stack/tests/test_kahle_harness_phase4b.py`

- [ ] **Step 1: Failing test schreiben**

```python
def test_prompt_blueprint_anchors_spans_but_keeps_validation_spans_complete():
    harness = load_harness()
    long_span = "Die Werkstattleitung prüft den Antrag innerhalb von zwei Arbeitstagen " * 4
    claim = harness.AnswerBlueprintClaim("c1", "1", long_span, "editorial")

    prompt_claim = claim.to_prompt_dict()

    assert claim.to_dict()["evidence_span"] == long_span
    assert prompt_claim["evidence_span"].endswith("…")
    assert len(prompt_claim["evidence_span"]) <= harness.PROMPT_SPAN_ANCHOR_CHARS + 1
    assert long_span.startswith(prompt_claim["evidence_span"][:-1])
    short = harness.AnswerBlueprintClaim("c2", "1", "Kurzer Satz.", "editorial")
    assert short.to_prompt_dict()["evidence_span"] == "Kurzer Satz."
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `.\.venv-verify\Scripts\python.exe -m pytest stack\tests\test_kahle_harness_phase4b.py -q -p no:cacheprovider -k anchors`
Expected: FAIL mit `AttributeError: 'AnswerBlueprintClaim' object has no attribute 'to_prompt_dict'`

- [ ] **Step 3: Implementierung**

Über `class AnswerBlueprintClaim` einfügen:

```python
# The full passage stays in the rag_chat result; the prompt blueprint only
# needs enough text to find the claim there (phase 4b, measured duplicate).
PROMPT_SPAN_ANCHOR_CHARS = 120
```

In `AnswerBlueprintClaim` ergänzen:

```python
    def to_prompt_dict(self) -> dict[str, str]:
        span = self.evidence_span
        if len(span) > PROMPT_SPAN_ANCHOR_CHARS:
            span = span[:PROMPT_SPAN_ANCHOR_CHARS].rstrip() + "…"
        return {**asdict(self), "evidence_span": span}
```

In `AnswerBlueprintSection` und `AnswerBlueprint` je eine Methode `to_prompt_dict()` ergänzen, die `to_dict()` entspricht, aber `claim.to_prompt_dict()` bzw. `section.to_prompt_dict()` verwendet. In `answer_prompt()` (ca. Zeile 378) `self.answer_blueprint.to_dict()` durch `self.answer_blueprint.to_prompt_dict()` ersetzen. `to_dict()` und alle anderen Aufrufer bleiben unverändert.

- [ ] **Step 4: Tests laufen lassen**

Run: `.\.venv-verify\Scripts\python.exe -m pytest stack\tests -q -p no:cacheprovider -k "harness"`
Expected: alle bestanden. Prüft ein bestehender Test, dass ein vollständiger Span im Prompt steht, wird er auf den Anker umgestellt und die Änderung im Commit begründet; ein Test der Antwortprüfung darf nicht angepasst werden müssen.

- [ ] **Step 5: Commit**

```bash
git add stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py stack/tests/test_kahle_harness_phase4b.py
git commit -m "feat(harness): anchor blueprint spans in the prompt instead of repeating passages"
```

### Task 6: Kürzung der Systemprompts (nur mit Freigabe je Abschnitt)

Die Systemprompts sind redaktioneller Inhalt. Nichts wird ohne ausdrückliche Freigabe entfernt.

**Files:**
- Create: `docs/superpowers/plans/2026-10-13-harness-phase4b-systemprompt-proposal.md`
- Modify (nach Freigabe): `stack/open-webui-prompts/kahle-vinci-systemprompt.md`, `stack/open-webui-prompts/kahle-vinci-thinking-systemprompt.md`

- [ ] **Step 1: Vorschlag erstellen.** Für jede Regel im Block „Regeln:“ unter „3) TOOL-ROUTING: PFLICHTEN UND REIHENFOLGE“ eine Tabellenzeile: Regeltext (gekürzt), Zeichen, Status. Status ist genau einer von:
  - `erzwungen` mit Fundstelle im Harness (Datei und Funktion, z. B. `plan_retrieval`, `validate_answer`, `answer_prompt`) und dem Test, der es belegt;
  - `teilweise` mit der Lücke;
  - `nur Prompt` (bleibt stehen).

  Nur `erzwungen` wird zur Streichung vorgeschlagen. Summe der vorgeschlagenen Zeichen je Datei angeben.

- [ ] **Step 2: Vorschlag dem Nutzer vorlegen** und Freigabe je Zeile einholen. Ohne Antwort zu einer Zeile bleibt sie stehen.

- [ ] **Step 3: Freigegebene Zeilen in beiden Prompt-Dateien entfernen.** Danach prüfen, dass die bestehenden Prompt-Tests weiter gelten:

Run: `.\.venv-verify\Scripts\python.exe -m pytest stack\tests -q -p no:cacheprovider -k "prompt or harness"`
Expected: alle bestanden. Schlägt ein Test fehl, weil er genau eine freigegebene Regel prüft, wird der Test mit Verweis auf die Freigabe entfernt; jeder andere Fehlschlag stoppt die Kürzung dieser Zeile.

- [ ] **Step 4: In Open WebUI übernehmen** über `scripts/openwebui/register-kahle-workflow-tool.py` (schreibt `params.system` aus der Prompt-Datei); vorher `--help` lesen und nur die lokalen Modelle aktualisieren.

- [ ] **Step 5: Commit**

```bash
git add stack/open-webui-prompts/kahle-vinci-systemprompt.md stack/open-webui-prompts/kahle-vinci-thinking-systemprompt.md docs/superpowers/plans/2026-10-13-harness-phase4b-systemprompt-proposal.md
git commit -m "fix(prompts): drop routing rules the harness already enforces"
```

### Task 7: Verify, Messung und Abnahme

- [ ] **Step 1: Full Verify**

Run: `.\scripts\run-local-tests.ps1 -Tier Full -Python .\.venv-verify\Scripts\python.exe -Npm npm.cmd`
Expected: `EXIT=0`

- [ ] **Step 2: `docker restart open-webui`**, `/health` = `200`

- [ ] **Step 3: Laufzeit-Eval je Modell** wie Task 3 mit `--output-dir tmp\runtime-phase4b` und Zusammenfassung nach `eval/harness/results/<Datum>-runtime-phase4b.json`

- [ ] **Step 4: Abnahme gegen die 4a-Messung**

| Kriterium | Ziel |
| --- | --- |
| `prompt_tokens_p50` je Modell | mindestens −15 % gegenüber 4a |
| Routing korrekt je Modell | mindestens 4a minus 2 Fälle (gemessene Streuung ±3) |
| ausgelieferte blockierende Verstöße | 0 |
| `retry_required` je Modell | nicht mehr als 4a plus 2 |

Verfehlt ein Modell das Routing-Kriterium, wird `max-thinking` und das betroffene Modell einmal nachgemessen, bevor eine Änderung zurückgenommen wird.

- [ ] **Step 5: Ergebnis eintragen, committen, pushen**

```bash
git add eval/harness/results/<Datum>-runtime-phase4b.json docs/superpowers/plans/2026-10-13-harness-phase4b-prompt-composition-and-token-cut.md
git commit -m "eval(harness): phase 4b measurement"
git push origin feat/harness-eval-foundation
```

## Nicht Teil dieses Plans (folgt in 4c)

- **Modellprofile:** gezielte Zusatzpflichten je Basismodell.
- **Strukturierte Ausgabe prüfen.**
- **Messung ohne Vorabplanung** als Voraussetzung für Release B.
- **Tool-Spezifikationen kürzen** (siehe Task 4).

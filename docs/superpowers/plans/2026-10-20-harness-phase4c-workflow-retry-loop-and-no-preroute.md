# Harness Phase 4c: Wiederholungsschleife bei Dateiumwandlung und Messung ohne Vorabplanung

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) Die blockierten Wiederholungsaufrufe von `kahle_workflow_execute` bei „Wandle die eben erstellte PDF in Markdown um“ messbar machen und auf höchstens einen blockierten Aufruf je Antwort senken. (2) Messen, wie alle drei Modelle ohne Vorabplanung abschneiden, als Voraussetzung für Release B.

**Architecture:** Ein neues Eval-Modul führt das dreistufige Datei-Gespräch (Wissensfrage → „Erstelle mir aus dem Ergebnis eine PDF“ → „Wandle die eben erstellte PDF in eine Markdown-Datei um“) mehrfach je Modell im selben Chat aus und zählt nur Tool-Namen, Blockierungen, Erfolg und Dauer. Erst mit dieser Ausgangsmessung wird zwischen zwei konkreten Lösungen entschieden. Die Messung ohne Vorabplanung nutzt den vorhandenen Schalter `KAHLE_MODEL_LED_PREROUTE_OFF_MODELS` und die bestehende Laufzeit-Eval.

**Tech Stack:** Python 3.11, `eval/harness`, Open-WebUI-Overrides (`middleware.py`), pytest, Docker Compose.

---

## Ausgangslage

- Am 19.10. beobachtet (Folgesitzung, `872731e`, `e010432`, `8cd953c`): Bittet der Nutzer, eine im Chat erzeugte PDF umzuwandeln, gibt die Middleware jedem Aufruf von `kahle_workflow_execute` die Meldung `DATEIKONVERTIERUNG_TOOLCALL_BLOCKIERT: …` zurück (`_kahle_uploaded_conversion_block_reason`, `middleware.py` ca. Zeile 791, Anwendung im nativen Tool-Loop ca. Zeile 8045). `kahle-vinci-thinking` (gpt-oss) ruft das Tool trotzdem 3- bis 13-mal erneut auf, bis die Schleifengrenze `CHAT_RESPONSE_MAX_TOOL_CALL_ITERATIONS` greift. Das Ergebnis ist korrekt, kostet aber Latenz.
- Nutzerentscheidung 19.10.: **keine Vorab-Weiche**, die die Anfrage vor dem Modell umleitet; die Lösung wird im Harness-Programm mit Messung erarbeitet.
- Am 15.10. (Phase 4b, A/B-Probe, je ein Lauf) rief gpt-oss in Runde 3 gar kein Tool auf; Mistral und `max-thinking` scheiterten beim ersten `file_to_md_save` mit HTTP 400 (seither durch die Folgesitzung behoben). Belastbare Zahlen über mehrere Läufe gibt es nicht.
- Release B (Regex-Vorabplanung entfernen) ist bis zu einer Messung ohne Vorabplanung verschoben. Der Schalter existiert: `_model_led_preroute_disabled` (`middleware.py` ca. Zeile 223) liest `KAHLE_MODEL_LED_PREROUTE_OFF_MODELS` (kommagetrennte Modell-IDs), durchgereicht in `stack/docker-compose.local-edge.yml`.

## Dateien

| Datei | Änderung |
| --- | --- |
| `eval/harness/file_followup_eval.py` | neu: dreistufiges Datei-Gespräch je Modell, mehrere Wiederholungen |
| `eval/harness/tests/test_file_followup_eval.py` | neu: Tests der Auswertung ohne Laufzeit |
| `stack/open-webui-overrides/open_webui/utils/middleware.py` | Task 4 (nur die gewählte Variante) |
| `stack/tests/test_generated_file_conversion_routing.py` | Task 4: Test der gewählten Variante |
| `docs/VERIFICATION.md` | Abschnitt Harness-Eval um den neuen Lauf ergänzen |

---

### Task 1: Auswertung des Datei-Gesprächs als reine Funktionen

**Files:**
- Create: `eval/harness/file_followup_eval.py`
- Test: `eval/harness/tests/test_file_followup_eval.py`

- [ ] **Step 1: Failing test schreiben**

```python
from file_followup_eval import BLOCK_MARKER, score_turn, summarize_runs


def _message(tools=(), outputs=(), content=""):
    output = [{"type": "function_call", "name": name} for name in tools]
    output += [{"type": "function_call_output", "output": text} for text in outputs]
    return {"content": content, "output": output}


def test_score_turn_counts_blocked_calls_and_finds_the_requested_file():
    message = _message(
        tools=["kahle_workflow_execute", "kahle_workflow_execute", "file_to_md_save"],
        outputs=[BLOCK_MARKER + ": nicht ausgeführt", BLOCK_MARKER + ": nicht ausgeführt",
                 '{"download_url": "http://x/files/d/abc", "filename": "ergebnis.md"}'],
        content="Hier ist die Datei: [ergebnis.md](http://x/files/d/abc)",
    )

    row = score_turn(message, expected_extension=".md", wall_ms=4200)

    assert row == {
        "tools": ["file_to_md_save", "kahle_workflow_execute"],
        "tool_calls": 3,
        "blocked_calls": 2,
        "file_delivered": True,
        "wall_ms": 4200,
    }


def test_score_turn_without_link_or_with_wrong_type_is_not_delivered():
    no_link = score_turn(_message(content="Erledigt."), expected_extension=".md", wall_ms=1)
    wrong = score_turn(
        _message(content="[ergebnis.pdf](http://x/files/d/abc)"), expected_extension=".md", wall_ms=1,
    )

    assert no_link["file_delivered"] is False and no_link["tool_calls"] == 0
    assert wrong["file_delivered"] is False


def test_summary_reports_rates_and_blocked_call_distribution_per_model():
    rows = [
        {"model": "m", "turn": 3, "tools": [], "tool_calls": 4, "blocked_calls": 3, "file_delivered": True, "wall_ms": 9000},
        {"model": "m", "turn": 3, "tools": [], "tool_calls": 1, "blocked_calls": 0, "file_delivered": True, "wall_ms": 3000},
        {"model": "m", "turn": 3, "tools": [], "tool_calls": 0, "blocked_calls": 0, "file_delivered": False, "wall_ms": 2000},
        {"model": "m", "turn": 2, "tools": [], "tool_calls": 1, "blocked_calls": 0, "file_delivered": True, "wall_ms": 5000},
        {"model": "m", "turn": 3, "error": "HTTPError"},
    ]

    summary = summarize_runs(rows)["m"]

    assert summary["turn2_delivered"] == "1/1"
    assert summary["turn3_delivered"] == "2/3"
    assert summary["turn3_blocked_max"] == 3
    assert summary["turn3_blocked_p50"] == 0
    assert summary["turn3_with_blocked"] == 1
    assert summary["turn3_wall_p50_ms"] == 3000
    assert summary["errors"] == 1
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run (aus `eval\harness`): `..\..\.venv-verify\Scripts\python.exe -m pytest tests\test_file_followup_eval.py -q -p no:cacheprovider`
Expected: FAIL mit `ModuleNotFoundError: No module named 'file_followup_eval'`

- [ ] **Step 3: Minimale Implementierung**

```python
"""Three-turn file conversation per model: knowledge answer, PDF from the result,
convert that PDF to Markdown. Counts tools, blocked calls, delivery and time only;
no question or answer text leaves this module.

Specialized Verification: needs a running local stack, IONOS models and
OPENWEBUI_API_KEY (JWT session token).
"""

from __future__ import annotations

import re
from typing import Any

from harness_eval import answer_text, nearest_rank

BLOCK_MARKER = "DATEIKONVERTIERUNG_TOOLCALL_BLOCKIERT"
_FILE_LINK = re.compile(r"\[([^\]]+)\]\((?:https?://[^)\s]+)?/files/(?:d/[A-Za-z0-9_-]+|download\?token=[^)\s]+)\)")


def score_turn(message: dict[str, Any], *, expected_extension: str, wall_ms: int) -> dict[str, Any]:
    output = [item for item in message.get("output") or () if isinstance(item, dict)]
    calls = [str(item.get("name") or "") for item in output if item.get("type") == "function_call"]
    results = [str(item.get("output") or "") for item in output if item.get("type") == "function_call_output"]
    delivered = any(
        name.strip().lower().endswith(expected_extension)
        for name in _FILE_LINK.findall(answer_text(message))
    )
    return {
        "tools": sorted(set(calls)),
        "tool_calls": len(calls),
        "blocked_calls": sum(BLOCK_MARKER in result for result in results),
        "file_delivered": delivered,
        "wall_ms": wall_ms,
    }


def summarize_runs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for model in sorted({str(row["model"]) for row in rows}):
        items = [row for row in rows if row["model"] == model]
        ok = [row for row in items if "error" not in row]
        turn2 = [row for row in ok if row["turn"] == 2]
        turn3 = [row for row in ok if row["turn"] == 3]
        blocked = [row["blocked_calls"] for row in turn3]
        summary[model] = {
            "turn2_delivered": f"{sum(row['file_delivered'] for row in turn2)}/{len(turn2)}",
            "turn3_delivered": f"{sum(row['file_delivered'] for row in turn3)}/{len(turn3)}",
            "turn3_blocked_p50": nearest_rank(blocked, 0.5),
            "turn3_blocked_max": max(blocked) if blocked else None,
            "turn3_with_blocked": sum(value > 0 for value in blocked),
            "turn3_wall_p50_ms": nearest_rank([row["wall_ms"] for row in turn3], 0.5),
            "errors": len(items) - len(ok),
        }
    return summary
```

- [ ] **Step 4: Test laufen lassen**

Run: `..\..\.venv-verify\Scripts\python.exe -m pytest tests\test_file_followup_eval.py -q -p no:cacheprovider`
Expected: `3 passed`. Liefert `nearest_rank` für die Liste `[3, 0, 0]` bei 0.5 nicht `0`, die Erwartung an die tatsächliche Definition von `nearest_rank` in `harness_eval.py` anpassen und im Commit begründen.

- [ ] **Step 5: Commit**

```bash
git add eval/harness/file_followup_eval.py eval/harness/tests/test_file_followup_eval.py
git commit -m "eval(harness): score the three-turn file conversation"
```

### Task 2: Laufzeit-Teil des Datei-Gesprächs

**Files:**
- Modify: `eval/harness/file_followup_eval.py`

Der Laufzeit-Teil folgt dem erprobten Probe-Skript vom 15.10.: erste Runde über `HarnessRuntimeClient.ask_messages`, Folgerunden im **selben Chat** mit `chat_id` und `parent_id` der vorigen Antwort (sonst meldet `kahle_workflow_execute` `previous_result_unavailable`).

- [ ] **Step 1: Laufzeitfunktionen und CLI anhängen**

```python
import argparse
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

from runtime_harness_eval import HarnessRuntimeClient, model_tool_ids

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rag"))
from run_runtime_eval import ConversationState  # noqa: E402

QUESTION = "Wer ist für die Garantieabwicklung zuständig?"
TURN2 = "Erstelle mir aus dem Ergebnis eine PDF"
TURN3 = "Wandle die eben erstellte PDF in eine Markdown-Datei um"


def _follow_up(client, chat_id: str, parent_id: str, messages: list[dict[str, str]], tool_ids: list[str]) -> dict:
    user_id, assistant_id = str(uuid4()), str(uuid4())
    body = {
        "model": client.model, "id": assistant_id, "parent_id": parent_id, "chat_id": chat_id,
        "session_id": str(uuid4()),
        "user_message": {"id": user_id, "parentId": parent_id, "childrenIds": [assistant_id],
                         "role": "user", "content": messages[-1]["content"], "timestamp": int(time.time())},
        "messages": messages, "tool_ids": list(tool_ids), "stream": True,
        "stream_options": {"include_usage": True},
    }
    message, _ = client._start_and_wait(body, assistant_id, ConversationState(chat_id, parent_id))
    return message


def run_conversation(client, tool_ids: list[str]) -> list[dict[str, Any]]:
    rows = []
    started = time.monotonic()
    first, chat_id = client.ask_messages([{"role": "user", "content": QUESTION}], tool_ids)
    history = [{"role": "user", "content": QUESTION}, {"role": "assistant", "content": answer_text(first)}]
    try:
        parent = first["id"]
        for turn, prompt, extension in ((2, TURN2, ".pdf"), (3, TURN3, ".md")):
            history.append({"role": "user", "content": prompt})
            started = time.monotonic()
            message = _follow_up(client, chat_id, parent, history, tool_ids)
            wall_ms = round((time.monotonic() - started) * 1000)
            rows.append({"model": client.model, "turn": turn,
                         **score_turn(message, expected_extension=extension, wall_ms=wall_ms)})
            history.append({"role": "assistant", "content": answer_text(message)})
            parent = message["id"]
    finally:
        try:
            client.delete_chat(chat_id)
        except Exception:
            pass
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:3004")
    parser.add_argument("--models", default="kahle-vinci-thinking,vinci-2-clone-clone-clone,kahle-vinci-max-thinking")
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--output-dir", type=Path, default=Path("eval/harness/results"))
    parser.add_argument("--api-key-env", default="OPENWEBUI_API_KEY")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args(argv)
    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        raise SystemExit(f"{args.api_key_env} fehlt")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    rows: list[dict[str, Any]] = []
    for model in [item.strip() for item in args.models.split(",") if item.strip()]:
        client = HarnessRuntimeClient(args.base_url, api_key, model, args.timeout, 1.0)
        tool_ids = model_tool_ids(client.model_info())
        for _ in range(args.repeat):
            try:
                rows.extend(run_conversation(client, tool_ids))
            except Exception as error:  # one failed conversation must not stop the matrix
                rows.append({"model": model, "turn": 3, "error": type(error).__name__})
    (args.output_dir / f"file-followup-{stamp}.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    summary = summarize_runs(rows)
    (args.output_dir / f"file-followup-{stamp}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Die Importe von `argparse`, `json`, `os`, `sys`, `time`, `Path`, `uuid4`, `HarnessRuntimeClient`, `model_tool_ids` und `ConversationState` an den Dateianfang zu den übrigen Importen verschieben.

- [ ] **Step 2: Tests und Import prüfen**

Run (aus `eval\harness`): `..\..\.venv-verify\Scripts\python.exe -m pytest tests -q -p no:cacheprovider`
Expected: alle bestanden

Run (Repository-Root): `.\.venv-verify\Scripts\python.exe eval\harness\file_followup_eval.py --help`
Expected: Hilfe ohne Fehler

- [ ] **Step 3: In `docs/VERIFICATION.md` im Abschnitt „Harness-Eval“ nach dem Laufzeit-Befehl ergänzen:**

```markdown
Das dreistufige Datei-Gespräch (Wissensantwort → PDF aus dem Ergebnis →
erzeugte PDF in Markdown) misst je Modell blockierte Toolaufrufe, Zustellung
und Dauer; die Ergebnisse enthalten keine Fragen oder Antworttexte:

```powershell
python eval\harness\file_followup_eval.py --repeat 5 --output-dir tmp\file-followup
```
```

- [ ] **Step 4: Commit**

```bash
git add eval/harness/file_followup_eval.py docs/VERIFICATION.md
git commit -m "eval(harness): run the three-turn file conversation against the stack"
```

### Task 3: Ausgangsmessung und Entscheidungspunkt

- [ ] **Step 1: Messvoraussetzungen prüfen.** `git status` ohne Änderungen außer `tmp/`; keine andere Sitzung arbeitet am Stack; `docker inspect open-webui --format '{{.State.StartedAt}}'` vor dem Lauf notieren. Token aus `%USERPROFILE%\.kahle-owui-token` nur im Prozess setzen, `/api/models` = `200`.

- [ ] **Step 2: Lauf**

```powershell
$env:OPENWEBUI_API_KEY = (Get-Content "$env:USERPROFILE\.kahle-owui-token" -Raw).Trim()
.\.venv-verify\Scripts\python.exe eval\harness\file_followup_eval.py --repeat 5 --output-dir tmp\file-followup-baseline
```

Nach dem Lauf `StartedAt` erneut prüfen. Hat sich der Wert geändert, ist der Lauf ungültig und wird wiederholt.

- [ ] **Step 3: Ergebnis in diesen Plan eintragen** (Tabelle je Modell: Zustellung Runde 2 und 3, blockierte Aufrufe Median/Maximum/Anzahl Läufe mit Blockierung, Dauer Runde 3) und committen:

```bash
git add docs/superpowers/plans/2026-10-20-harness-phase4c-workflow-retry-loop-and-no-preroute.md
git commit -m "eval(harness): phase 4c file conversation baseline"
```

**Ergebnis (20.10., `0e22e2c`, 5 Gespräche je Modell, kein Container-Neustart, 0 Fehler):**

| Modell | Runde 2 PDF zugestellt | Runde 3 Markdown zugestellt | Runde 3 blockiert: Median / Maximum / Gespräche mit Blockierung | Runde 3 Dauer Median |
| --- | --- | --- | --- | --- |
| Mistral (`vinci-2`) | 5/5 | 5/5 | 0 / 0 / 0 | 3,1 s |
| gpt-oss (`thinking`) | 5/5 | 4/5 | 0 / 1 / 1 | 6,1 s |
| `max-thinking` | 5/5 | 5/5 | 1 / 1 / 3 | 12,2 s (mit Blockierung 12–30 s) |

Ein erster Lauf (`9939f22`) zählte jede Datei als nicht zugestellt, weil der Guard den Namen in einer eigenen Zeile `Datei: <name>` nach `[Datei herunterladen](link)` ausgibt; behoben in `0e22e2c`, Blockierungen dort gleich (Maximum 1). gpt-oss ruft in Runde 3 meist kein Tool auf; dann wandelt der Guard die PDF selbst um (3 von 4 zugestellt).

**Folgerung:** Die Schleife mit 3–13 Blockierungen vom 19.10. tritt nicht mehr auf (behoben durch `e010432`/`8cd953c`). `turn3_blocked_max` ist bei keinem Modell ≥ 2; Task 4 entfällt nach Prüfregel.

- [ ] **Step 4: Entscheidungspunkt.** Task 4 wird nur umgesetzt, wenn bei mindestens einem Modell `turn3_blocked_max` ≥ 2 ist. Dem Nutzer werden dann die zwei Varianten aus Task 4 mit den gemessenen Zahlen vorgelegt; umgesetzt wird nur die gewählte.

### Task 4: Höchstens eine Blockierung je Antwort (eine Variante nach Nutzerentscheidung)

Beide Varianten wirken erst **nach** dem ersten blockierten Aufruf und leiten keine Anfrage vorab um; sie bleiben damit innerhalb der Nutzerentscheidung vom 19.10.

**Variante A: blockiertes Tool für den Rest der Antwort zurückziehen.** Nach einer Blockierung wird die Funktion aus der Tool-Liste der folgenden Schleifendurchläufe derselben Antwort entfernt. Das Modell kann sie nicht erneut wählen. Deterministisch, unabhängig vom Modell.

**Variante B: Blockiermeldung schärfen.** Die Meldung untersagt ausdrücklich jeden weiteren Aufruf dieses Tools in dieser Antwort und nennt den nächsten Schritt als einzigen zulässigen Aufruf. Keine Strukturänderung, aber modellabhängig.

**Files:**
- Modify: `stack/open-webui-overrides/open_webui/utils/middleware.py`
- Test: `stack/tests/test_generated_file_conversion_routing.py`

- [ ] **Step 1 (Variante A): Failing test anhängen**

```python
def test_blocked_conversion_tool_is_withdrawn_for_the_rest_of_the_answer():
    source = MIDDLEWARE.read_text(encoding="utf-8")
    block = source.index("if document_comparison_block_reason:")
    withdraw = "metadata.setdefault('_kahle_withdrawn_tools', set()).add(tool_function_name)"
    # The withdrawal is the first statement of the block branch.
    assert source[block:block + 200].split("\n")[1].strip() == withdraw
    assert "_without_withdrawn_tools(form_data.get('tools'), metadata)" in source


def test_without_withdrawn_tools_keeps_everything_else():
    source = MIDDLEWARE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_without_withdrawn_tools")
    namespace: dict = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "middleware", "exec"), namespace)
    strip = namespace["_without_withdrawn_tools"]
    tools = [{"type": "function", "function": {"name": "kahle_workflow_execute"}},
             {"type": "function", "function": {"name": "file_to_md_save"}}]

    assert strip(tools, {"_kahle_withdrawn_tools": {"kahle_workflow_execute"}}) == [tools[1]]
    assert strip(tools, {}) == tools
    assert strip(None, {"_kahle_withdrawn_tools": {"x"}}) is None
```

- [ ] **Step 1 (Variante B): Failing test anhängen**

```python
def test_conversion_block_forbids_another_call_of_the_same_tool():
    reason = load_block_reason()("kahle_workflow_execute", "Wandle die eben erstellte PDF in eine Markdown-Datei um")

    assert "Rufe kahle_workflow_execute in dieser Antwort nicht erneut auf" in reason
    assert "Dein einziger naechster Aufruf ist file_to_md_save" in reason
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `.\.venv-verify\Scripts\python.exe -m pytest stack\tests\test_generated_file_conversion_routing.py -q -p no:cacheprovider`
Expected: der neue Test schlägt fehl

- [ ] **Step 3 (Variante A): Implementierung**

Auf Modulebene neben `_with_generated_pdf_hint` einfügen:

```python
def _without_withdrawn_tools(tools: Any, metadata: dict) -> Any:
    """Drop tools blocked earlier in this answer from the next loop iteration."""
    withdrawn = metadata.get('_kahle_withdrawn_tools') or set()
    if not tools or not withdrawn:
        return tools
    return [
        tool for tool in tools
        if not (isinstance(tool, dict) and (tool.get('function') or {}).get('name') in withdrawn)
    ]
```

Im Blockierzweig des nativen Tool-Loops (`if document_comparison_block_reason:`, ca. Zeile 8053) als erste Zeile:

```python
                                    metadata.setdefault('_kahle_withdrawn_tools', set()).add(tool_function_name)
```

Beim Aufbau von `new_form_data` für den nächsten Durchlauf (der Block mit `*convert_output_to_messages(output, raw=True),`) nach `**form_data,` ergänzen:

```python
                                'tools': _without_withdrawn_tools(form_data.get('tools'), metadata),
```

- [ ] **Step 3 (Variante B): Implementierung**

In `_kahle_uploaded_conversion_block_reason` (ca. Zeile 819) genau diese eine Zeile

```python
                f'{name} wurde nicht ausgefuehrt. Rufe ausschliesslich {allowed} mit dem exakten Uploadpfad '
```

durch diese zwei Zeilen ersetzen:

```python
                f'{name} wurde nicht ausgefuehrt. Rufe {name} in dieser Antwort nicht erneut auf. '
                f'Dein einziger naechster Aufruf ist {allowed} mit dem exakten Uploadpfad '
```

- [ ] **Step 4: Tests laufen lassen**

Run: `.\.venv-verify\Scripts\python.exe -m pytest stack\tests -q -p no:cacheprovider -k "conversion or file or harness"`
Expected: alle bestanden

- [ ] **Step 5: Open WebUI neu starten, Messung wie Task 3 mit `--output-dir tmp\file-followup-after`, Ergebnis eintragen**

- [ ] **Step 6: Commit**

```bash
git add stack/open-webui-overrides/open_webui/utils/middleware.py stack/tests/test_generated_file_conversion_routing.py docs/superpowers/plans/2026-10-20-harness-phase4c-workflow-retry-loop-and-no-preroute.md
git commit -m "fix(files): at most one blocked conversion call per answer"
```

### Task 5: Messung ohne Vorabplanung

Reine Messung; nichts wird dauerhaft umgestellt.

- [ ] **Step 1: Messvoraussetzungen wie Task 3, Step 1.**

- [ ] **Step 2: Open WebUI mit abgeschalteter Vorabplanung für alle drei Modelle neu erstellen**

```powershell
$env:KAHLE_MODEL_LED_PREROUTE_OFF_MODELS = "kahle-vinci-thinking,vinci-2-clone-clone-clone,kahle-vinci-max-thinking"
.\scripts\start-stack.ps1 -NoBuild -ComposeArgs open-webui
docker exec open-webui printenv KAHLE_MODEL_LED_PREROUTE_OFF_MODELS
```

Expected: die drei Modell-IDs

- [ ] **Step 3: Laufzeit-Eval je Modell einzeln** (114 Fälle) mit `--output-dir tmp\runtime-phase4c-no-preroute`, wie in Phase 4b Task 3, Step 2.

- [ ] **Step 4: Zurückstellen und prüfen**

```powershell
Remove-Item Env:KAHLE_MODEL_LED_PREROUTE_OFF_MODELS
.\scripts\start-stack.ps1 -NoBuild -ComposeArgs open-webui
docker exec open-webui printenv KAHLE_MODEL_LED_PREROUTE_OFF_MODELS
```

Expected: leere Ausgabe

- [ ] **Step 5: Vergleich mit der 4b-Abnahme eintragen** (Routing korrekt je Modell und Kategorie, Verstöße, `retry_required`, Prompt-Tokens) und committen:

```bash
git add docs/superpowers/plans/2026-10-20-harness-phase4c-workflow-retry-loop-and-no-preroute.md
git commit -m "eval(harness): measure all models without pre-routing"
```

Ob Release B folgt, entscheidet der Nutzer anhand dieser Zahlen; dafür wird ein eigener Plan geschrieben.

### Task 6: Verify und Abnahme

- [ ] **Step 1: Full Verify**

Run: `.\scripts\run-local-tests.ps1 -Tier Full -Python .\.venv-verify\Scripts\python.exe -Npm npm.cmd`
Expected: `EXIT=0`

- [ ] **Step 2: Abnahme**

| Kriterium | Ziel |
| --- | --- |
| `turn3_blocked_max` je Modell nach Task 4 | ≤ 1 |
| `turn3_delivered` je Modell | mindestens wie Ausgangsmessung |
| `turn2_delivered` je Modell | unverändert 5/5 |
| Laufzeit-Eval nach Task 4 | Routing höchstens 2 Fälle unter 4b, 0 Verstöße |
| Messung ohne Vorabplanung | liegt vollständig vor (alle drei Modelle, 0 Container-Neustarts während der Läufe) |

- [ ] **Step 3: Ergebnis eintragen, committen, pushen**

```bash
git add docs/superpowers/plans/2026-10-20-harness-phase4c-workflow-retry-loop-and-no-preroute.md
git commit -m "eval(harness): phase 4c acceptance"
git push origin feat/harness-eval-foundation
```

## Nicht Teil dieses Plans (eigene Pläne)

- **Modellprofile** (gezielte Zusatzpflichten je Basismodell): Es gibt dafür noch keinen Mechanismus; Entwurf erst, wenn Task 4 oder 5 einen modellspezifischen Bedarf belegt.
- **Strukturierte Ausgabe prüfen.**
- **Release B** (Regex-Vorabplanung entfernen): nach Task 5 und Nutzerentscheidung.
- **Systemprompt-Kürzung:** Potenzial nach 4b-Vorabschätzung ca. 1–2 %.

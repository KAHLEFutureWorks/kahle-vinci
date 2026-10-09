# Harness Phase 4a: Vertrag nur einmal, Token-Ausgangswert Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Weniger Eingabe-Token pro interner Antwort bei gleicher oder besserer Auswertung, indem der Antwortvertrag genau einmal im Kontext steht und vor der Antwort nur noch eine kurze Pflichtenliste folgt.

**Architecture:** Die Auswertung misst künftig die Token aus `message.usage`. Die Methode `HarnessDecision.answer_duties()` erzeugt eine kurze Pflichtenliste ohne Evidenz, die statt der vollständigen Vertragswiederholung an die letzte Nutzernachricht gehängt wird. Die Vorabsuche setzt den Vertrag über `upsert_answer_contract_message`, damit eine spätere modellgeführte Aktualisierung ihn ersetzt statt einen zweiten anzulegen (R2, Befund K6).

**Tech Stack:** Python 3.11, pytest, Open WebUI v0.11.0 mit KAHLE-Overrides, Laufzeit-Eval gegen `localhost:3004`.

Grundlage: [Roadmap](2026-09-29-harness-quality-roadmap.md), Phase 4. Phase 4b (Modellprofile, Kürzung der Systemprompts, strukturierte Ausgabe, Messung ohne Vorabplanung für Release B) folgt als eigener Plan auf Basis der hier gemessenen Werte.

---

## Ausgangslage (gemessen 09.10.)

| Bestandteil pro Wissensantwort | Größe |
| --- | --- |
| Eingabe-Token, Antwort mit Evidenz | 16.700–21.800 |
| Eingabe-Token, freigegebene Vorabsuche ohne Evidenz | ca. 12.100 |
| Systemprompt je Modell (`params.system`) | 27.300–29.300 Zeichen, ca. 7.500 Token |
| Tool-Spezifikationen (ohne `server:doc-worker`) | ca. 13.000 Zeichen |

Der Antwortvertrag (`answer_prompt()`) steht bei Bauplan, Geltungsbereich oder Rückfrage **dreimal** im Kontext:

1. als Systemnachricht der Vorabsuche (`add_or_update_system_message(..., append=True)`, `middleware.py` ca. Zeile 5680);
2. noch einmal angehängt an die Systemnachricht (`_kahle_final_answer_prompt`, ca. Zeile 5881);
3. angehängt an die letzte Nutzernachricht (ca. Zeile 5886).

Bei einem modellgeführten Tool-Aufruf kommt die Vertragsnachricht von `upsert_answer_contract_message` hinzu. Damit können zwei Verträge mit unterschiedlicher Evidenz nebeneinander stehen (R2, K6).

## Dateien

| Datei | Änderung |
| --- | --- |
| `eval/harness/harness_eval.py` | `score_answer` liest `usage`; `summarize_answers` meldet Token-Perzentile |
| `eval/harness/tests/test_harness_eval.py` | Tests für Token-Felder |
| `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py` | neue Methode `HarnessDecision.answer_duties()` |
| `stack/open-webui-overrides/open_webui/utils/middleware.py` | `_high_salience_knowledge_answer_prompt` liefert die Pflichtenliste; der Schlussprompt geht nur an die Nutzernachricht; Vorabsuche nutzt `upsert_answer_contract_message` |
| `stack/tests/test_kahle_harness_phase4a.py` | neue Tests für Pflichtenliste, Platzierung und R2 |
| `stack/tests/test_kahle_harness_phase3c.py` | bisheriger Test „Vertrag wird vor der Antwort wiederholt“ wird auf die Pflichtenliste umgestellt |

---

### Task 1: Token-Verbrauch in der Auswertung

**Files:**
- Modify: `eval/harness/harness_eval.py` (`score_answer`, `summarize_answers`)
- Test: `eval/harness/tests/test_harness_eval.py`

- [ ] **Step 1: Write the failing test**

Am Ende von `eval/harness/tests/test_harness_eval.py` anfügen:

```python
def test_score_and_summary_report_token_usage():
    first = _message(text="Antwort [1].")
    first["usage"] = {"prompt_tokens": 20000, "completion_tokens": 400}
    second = _message(text="Antwort [1].")
    second["usage"] = {"prompt_tokens": 12000, "completion_tokens": 800}
    missing = _message(text="Antwort [1].")

    rows = [
        {"model": "m", **score_answer(_case(), message), "wall_ms": 10}
        for message in (first, second, missing)
    ]
    summary = summarize_answers(rows)["m"]

    assert (rows[0]["prompt_tokens"], rows[0]["completion_tokens"]) == (20000, 400)
    assert (rows[2]["prompt_tokens"], rows[2]["completion_tokens"]) == (None, None)
    assert summary["prompt_tokens_p50"] == 12000
    assert summary["prompt_tokens_p95"] == 20000
    assert summary["completion_tokens_p50"] == 400
```

Im bestehenden Test `test_score_answer_keeps_only_blocking_codes_and_no_text` das erwartete Dictionary um `"prompt_tokens": None, "completion_tokens": None,` ergänzen.

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv-verify\Scripts\python.exe -m pytest -q -p no:cacheprovider eval/harness/tests/test_harness_eval.py -k "token_usage or keeps_only_blocking"`
Expected: FAIL mit `KeyError: 'prompt_tokens'`

- [ ] **Step 3: Write minimal implementation**

In `harness_eval.py` vor `score_answer` ergänzen:

```python
def _token_count(message: dict[str, Any], field: str) -> int | None:
    value = (message.get("usage") or {}).get(field)
    return int(value) if isinstance(value, (int, float)) and value >= 0 else None
```

Im Rückgabe-Dictionary von `score_answer` nach `"evidence_probe"` ergänzen:

```python
        "prompt_tokens": _token_count(message, "prompt_tokens"),
        "completion_tokens": _token_count(message, "completion_tokens"),
```

In `summarize_answers` nach `walls = …` ergänzen:

```python
        prompt_tokens = [row["prompt_tokens"] for row in items if isinstance(row.get("prompt_tokens"), int)]
        completion_tokens = [
            row["completion_tokens"] for row in items if isinstance(row.get("completion_tokens"), int)
        ]
```

und im Ergebnis-Dictionary nach `"wall_p95_ms"`:

```python
            "prompt_tokens_p50": nearest_rank(prompt_tokens, 0.5),
            "prompt_tokens_p95": nearest_rank(prompt_tokens, 0.95),
            "completion_tokens_p50": nearest_rank(completion_tokens, 0.5),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv-verify\Scripts\python.exe -m pytest -q -p no:cacheprovider eval/harness/tests`
Expected: alle Tests PASS

- [ ] **Step 5: Commit**

```bash
git add eval/harness/harness_eval.py eval/harness/tests/test_harness_eval.py
git commit -m "eval(harness): report prompt and completion tokens per answer"
```

### Task 2: Ausgangsmessung

- [ ] **Step 1: Stack prüfen**

Run: `curl -s -o /dev/null -w "%{http_code}" http://localhost:3004/health`
Expected: `200`

- [ ] **Step 2: Je Modell einen Laufzeit-Eval starten** (Hintergrundlimit 30 Minuten, deshalb einzeln)

```bash
OPENWEBUI_API_KEY="$(cat ~/.kahle-owui-token)" ./.venv-verify/Scripts/python.exe eval/harness/runtime_harness_eval.py --models vinci-2-clone-clone-clone --output-dir tmp/runtime-phase4a-baseline
OPENWEBUI_API_KEY="$(cat ~/.kahle-owui-token)" ./.venv-verify/Scripts/python.exe eval/harness/runtime_harness_eval.py --models kahle-vinci-thinking --output-dir tmp/runtime-phase4a-baseline
OPENWEBUI_API_KEY="$(cat ~/.kahle-owui-token)" ./.venv-verify/Scripts/python.exe eval/harness/runtime_harness_eval.py --models kahle-vinci-max-thinking --output-dir tmp/runtime-phase4a-baseline
```

- [ ] **Step 3: Die drei Zusammenfassungen zu `eval/harness/results/<Datum>-runtime-phase4a-baseline.json` zusammenführen** (gleiches Vorgehen wie `2026-10-09-runtime-acceptance-fixes.json`: `models`, `routing` und `answers` je Modell übernehmen, `assembled_from` setzen) und prüfen, dass die Datei weder Fragen noch Namen enthält:

Run: `grep -c -iE "mustermann|beispiel|@kahle" eval/harness/results/<Datum>-runtime-phase4a-baseline.json`
Expected: `0`

- [ ] **Step 4: Commit**

```bash
git add eval/harness/results/<Datum>-runtime-phase4a-baseline.json
git commit -m "eval(harness): phase 4a token baseline"
```

### Task 3: Pflichtenliste statt Vertragswiederholung

**Files:**
- Modify: `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py` (`HarnessDecision`)
- Modify: `stack/open-webui-overrides/open_webui/utils/middleware.py` (`_high_salience_knowledge_answer_prompt`, Schlussprompt-Platzierung)
- Create: `stack/tests/test_kahle_harness_phase4a.py`
- Modify: `stack/tests/test_kahle_harness_phase3c.py` (`test_scope_contract_is_repeated_right_before_the_answer`)

- [ ] **Step 1: Write the failing test**

`stack/tests/test_kahle_harness_phase4a.py` anlegen:

```python
"""Phase 4a: the contract is in the context once; only a duty list precedes the answer."""

import ast
import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "kahle_knowledge_harness.py"
MIDDLEWARE = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "middleware.py"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_kahle_harness_phase3c import _model_led_decision, _scoped_rag_result  # noqa: E402


def load_harness():
    spec = importlib.util.spec_from_file_location("kahle_harness_phase4a", HARNESS)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_duties_name_scope_and_citations_but_carry_no_evidence():
    harness = load_harness()
    decision = _model_led_decision(harness, _scoped_rag_result())

    duties = decision.answer_duties()

    assert duties.startswith("KAHLE_KNOWLEDGE_ANSWER_DUTIES\n")
    assert "Er gilt nur für Hannover, Wunstorf und Wedemark." in duties
    assert "Quellen-ID" in duties
    assert "Kunden in Vaudis anhand der gemeldeten Kundennummer aufrufen" not in duties
    assert "EVIDENCE" not in duties and "evidence_bundle" not in duties
    assert len(duties) < len(decision.answer_prompt()) / 3


def test_high_salience_prompt_is_the_duty_list():
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_high_salience_knowledge_answer_prompt")
    namespace: dict[str, Any] = {"Any": Any}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(MIDDLEWARE), "exec"), namespace)
    decision = _model_led_decision(load_harness(), _scoped_rag_result())

    assert namespace["_high_salience_knowledge_answer_prompt"](decision) == decision.answer_duties()


def test_final_prompt_goes_only_to_the_user_turn():
    source = MIDDLEWARE.read_text(encoding="utf-8")
    block = source[source.index("    final_answer_prompt = metadata.pop('_kahle_final_answer_prompt', '')"):]
    block = block[: block.index("    # If there are citations")]

    assert "add_or_update_user_message(" in block
    assert "add_or_update_system_message(" not in block
```

In `stack/tests/test_kahle_harness_phase3c.py` im Test `test_scope_contract_is_repeated_right_before_the_answer` die letzte Zeile ersetzen durch:

```python
    assert namespace["_high_salience_knowledge_answer_prompt"](decision) == decision.answer_duties()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv-verify\Scripts\python.exe -m pytest -q -p no:cacheprovider stack/tests/test_kahle_harness_phase4a.py stack/tests/test_kahle_harness_phase3c.py -k "duties or high_salience or user_turn or repeated_right_before"`
Expected: FAIL mit `AttributeError: 'HarnessDecision' object has no attribute 'answer_duties'`

- [ ] **Step 3: Write minimal implementation**

In `kahle_knowledge_harness.py` in der Klasse `HarnessDecision` direkt nach `answer_prompt` einfügen:

```python
    def answer_duties(self) -> str:
        """Short duty list for the position right before the answer; no evidence."""
        if self.user_intent.clarification_required and self.user_intent.clarification_question.strip():
            # The clarification must be repeated word for word and is short.
            return self.answer_prompt()
        duties = []
        if self.answer_blueprint is not None:
            headings = [section.heading for section in self.answer_blueprint.sections]
            duties.append(
                "Gliedere die Antwort in genau diese nummerierten Abschnitte, in dieser "
                f"Reihenfolge: {'; '.join(headings)}."
            )
        scope = _scope_instruction(self.answer_contract.required_scope)
        if scope:
            duties.append(scope.removeprefix("KAHLE_KNOWLEDGE_SCOPE\n").strip())
        duties.append(
            "Belege jede interne Aussage mit einer Quellen-ID aus dem Antwortvertrag und nenne "
            "Kontaktwerte nur aus dem Antwortvertrag."
        )
        return "KAHLE_KNOWLEDGE_ANSWER_DUTIES\n" + "\n".join(f"- {duty}" for duty in duties)
```

In `middleware.py` die letzte Zeile von `_high_salience_knowledge_answer_prompt` ersetzen:

```python
    return str(decision.answer_duties() or '')
```

In `middleware.py` den Schlussprompt-Block (nach `final_answer_prompt = metadata.pop('_kahle_final_answer_prompt', '')`) ersetzen durch:

```python
    final_answer_prompt = metadata.pop('_kahle_final_answer_prompt', '')
    if final_answer_prompt:
        # The full contract is already a system message; next to the user turn
        # only the short duty list or release notice is repeated (phase 4a).
        form_data['messages'] = add_or_update_user_message(
            final_answer_prompt,
            form_data['messages'],
            append=True,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv-verify\Scripts\python.exe -m pytest -q -p no:cacheprovider stack/tests`
Expected: alle Tests PASS. Schlägt ein Test fehl, der den alten Schlussprompt an der Systemnachricht voraussetzt, wird er auf die Nutzernachricht umgestellt und die Änderung im Commit begründet.

- [ ] **Step 5: Commit**

```bash
git add stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py stack/open-webui-overrides/open_webui/utils/middleware.py stack/tests/test_kahle_harness_phase4a.py stack/tests/test_kahle_harness_phase3c.py
git commit -m "feat(harness): contract once, a short duty list before the answer"
```

### Task 4: Eine Vertragsnachricht pro Anfrage (R2, K6)

**Files:**
- Modify: `stack/open-webui-overrides/open_webui/utils/middleware.py` (Vorabsuche, ca. Zeile 5680)
- Test: `stack/tests/test_kahle_harness_phase4a.py`

- [ ] **Step 1: Write the failing test**

An `stack/tests/test_kahle_harness_phase4a.py` anfügen:

```python
def test_pre_route_installs_the_replaceable_contract_message():
    source = MIDDLEWARE.read_text(encoding="utf-8")
    start = source.index("knowledge_answer_prompt = harness_decision.answer_prompt()")
    block = source[start: start + 1200]

    assert "upsert_answer_contract_message(" in block
    assert "knowledge_answer_prompt,\n" not in block


def test_refresh_after_pre_route_leaves_exactly_one_contract():
    sys.path.insert(0, str(ROOT / "open-webui-overrides"))
    try:
        spec = importlib.util.spec_from_file_location(
            "kahle_internal_phase4a", ROOT / "open-webui-overrides" / "open_webui" / "utils" / "kahle_internal_knowledge.py"
        )
        internal = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(internal)
    finally:
        sys.path.remove(str(ROOT / "open-webui-overrides"))
    harness = load_harness()
    first = _model_led_decision(harness, _scoped_rag_result())
    messages = [{"role": "system", "content": "Basis"}, {"role": "user", "content": "Frage"}]

    messages = internal.upsert_answer_contract_message(messages, first)
    messages = internal.upsert_answer_contract_message(messages, first)

    contracts = [m for m in messages if str(m.get("content") or "").startswith("KAHLE_KNOWLEDGE_ANSWER_CONTRACT\n")]
    assert len(contracts) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv-verify\Scripts\python.exe -m pytest -q -p no:cacheprovider stack/tests/test_kahle_harness_phase4a.py -k "replaceable or exactly_one"`
Expected: `test_pre_route_installs_the_replaceable_contract_message` FAIL (die Vorabsuche hängt den Vertrag noch an die Systemnachricht an); `test_refresh_after_pre_route_leaves_exactly_one_contract` PASS (Bestandsverhalten von `upsert_answer_contract_message`).

- [ ] **Step 3: Write minimal implementation**

In `middleware.py` in der Vorabsuche ersetzen:

```python
                            form_data['messages'] = add_or_update_system_message(
                                knowledge_answer_prompt,
                                form_data.get('messages', []) or [],
                                append=True,
                            )
```

durch:

```python
                            # One replaceable contract message; a later model-led
                            # refresh replaces it instead of adding a second (R2).
                            form_data['messages'] = upsert_answer_contract_message(
                                form_data.get('messages', []) or [], harness_decision,
                            )
```

Die dann ungenutzte Variable `knowledge_answer_prompt` entfernen. Achtung: `_release_evidence_probe` entfernt Vertragsnachrichten bereits über das Präfix `KAHLE_KNOWLEDGE_ANSWER_CONTRACT\n`; das bleibt kompatibel.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv-verify\Scripts\python.exe -m pytest -q -p no:cacheprovider stack/tests`
Expected: alle Tests PASS

- [ ] **Step 5: Commit**

```bash
git add stack/open-webui-overrides/open_webui/utils/middleware.py stack/tests/test_kahle_harness_phase4a.py
git commit -m "feat(middleware): one replaceable contract message per request (R2)"
```

### Task 5: Verify, Messung und Abnahme

- [ ] **Step 1: Full Verify**

Run: `.\scripts\run-local-tests.ps1 -Tier Full -Python .\.venv-verify\Scripts\python.exe -Npm npm.cmd`
Expected: `EXIT=0`

- [ ] **Step 2: Open WebUI neu starten** (Middleware und Harness sind gemountet)

Run: `docker restart open-webui`, danach `/health` = `200`

- [ ] **Step 3: Laufzeit-Eval je Modell wie in Task 2** mit `--output-dir tmp/runtime-phase4a` und zu `eval/harness/results/<Datum>-runtime-phase4a.json` zusammenführen

- [ ] **Step 4: Abnahme gegen die Ausgangsmessung**

| Kriterium | Ziel |
| --- | --- |
| `prompt_tokens_p50` je Modell | spürbar niedriger als in Task 2 |
| Routing korrekt je Modell | mindestens wie Task 2 (±1 Fall Streuung) |
| ausgelieferte blockierende Verstöße | 0 |
| Korrekturquote je Modell | nicht mehr als 3 Prozentpunkte über Task 2 |

Steigt die Korrekturquote bei Mistral deutlicher, ist der Hinweis zu weit vom Antwortpunkt entfernt (Befund aus Phase 3b). Dann wird geprüft, welche Pflicht fehlt, und sie wird in `answer_duties()` ergänzt, nicht der ganze Vertrag zurückgeholt.

- [ ] **Step 5: Ergebnis im Plan eintragen, committen, pushen**

```bash
git add eval/harness/results/<Datum>-runtime-phase4a.json docs/superpowers/plans/2026-10-09-harness-phase4a-contract-once-and-token-baseline.md
git commit -m "eval(harness): phase 4a measurement"
git push origin feat/harness-eval-foundation
```

## Nicht Teil von 4a (folgt in 4b)

- **Modellprofile:** gezielte Zusatzpflichten je Basismodell, z. B. Quellenabgrenzung für Mistral und Zitatpflicht für gpt-oss.
- **Kürzung der Systemprompts:** Antwortregeln, die der Harness bereits erzwingt, aus `stack/open-webui-prompts/*.md` entfernen; das sind redaktionelle Inhalte und braucht deine Freigabe je Abschnitt.
- **Dokumentpassagen nur einmal:** RAG-Vorlage und Bauplan-Claims enthalten dieselben Textstellen; welche Fassung wegfallen kann, entscheidet die 4a-Messung.
- **Strukturierte Ausgabe prüfen.**
- **Messung ohne Vorabplanung** als Voraussetzung für Release B.

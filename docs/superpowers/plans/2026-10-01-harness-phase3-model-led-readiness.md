# Harness Phase 3 (neu zugeschnitten): modellgeführtes Routing tragfähig machen

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die drei Vinci-Modelle sollen interne Quellen ohne Regex-Vorplanung mindestens so treffsicher wählen wie heute mit Vorplanung. Die Vorplanung bleibt bis dahin als Sicherheitsnetz aktiv. Sie wird je Modell erst abgeschaltet, wenn der Laufzeit-Eval das belegt.

**Warum neu zugeschnitten (Prototyp 01.10., `eval/harness/results/2026-10-01-runtime-prototype-model-led-without-preroute.json`):**

| Modell | mit Vorplanung | ohne Vorplanung | typische Fehler |
| --- | --- | --- | --- |
| Qwen | 94/99 | 84/99 | Abteilungskontakte 1/8, Abkürzungen 1/4 |
| gpt-oss | 90/99 | 69/99 | Abteilungskontakte 0/8, Person + Prozess 0/4, kein Tool bei Anleitungen |
| Mistral | 91/99 | 40/68 (31 Fälle IONOS-502) | kein Tool in 11/59 Wissensfällen |

**Wahrscheinliche Ursachen (am Code belegt):**

- Die `rag_chat`-Beschreibung (`scripts/openwebui/register-kahle-workflow-tool.py`) schließt „Rollen, Teams, Abteilungen, Standorte“ pauschal aus.
- `query` hat keine Beschreibung.
- Das Personio-Tool ist englisch beschrieben und nennt weder Ausschlüsse noch den gemischten Fall.
- Nichts sagt dem Modell, dass Abteilungskontakte beide Tools brauchen oder dass Abkürzungen und Folgefragen Tool-Pflicht sind.

**Architecture:**

- Ein Schalter `KAHLE_MODEL_LED_PREROUTE_OFF_MODELS` (Komma-Liste von Modell-IDs) schaltet die Vorplanung im Modus `model_led` **je Modell** ab. Der Default ist leer, das entspricht dem heutigen Verhalten.
- Damit lässt sich das reine modellgeführte Routing jederzeit messen und später je Modell freigeben.
- Tool-Beschreibungen und Quellenregeln werden geschärft und gegen beide Betriebsarten gemessen.
- Der Rückbau des Werbewiderspruch-Sonderpfads ist **nicht** Teil dieses Plans. Er folgt als Phase 3b, sobald das Dokument einen Abschnitt „Suchbegriffe“ hat und die Suche die natürlichen Formulierungen besteht (Task 6).

**Tech Stack:** Python 3.11, pytest, Open WebUI v0.11.0-Overrides, Registrierungsskripte, Laufzeit-Eval `eval/harness`.

## Vorbereitung und Befehle

Branch `feat/harness-eval-foundation`. Edits an CRLF-Dateien nur mit dem Edit-Werkzeug oder mit Python-Skripten, die CRLF erhalten.

```bash
P=./.venv-verify/Scripts/python.exe
$P -m pytest stack/tests/test_kahle_harness_phase3.py -q -p no:cacheprovider
$P -m pytest stack/tests -q -p no:cacheprovider          # Ausgang: 1283 passed
$P -m pytest eval/harness/tests -q -p no:cacheprovider   # Ausgang: 40 passed
```

## Dateistruktur

| Datei | Änderung |
| --- | --- |
| `eval/harness/routing_cases.yml` | 3 neue Fälle (natürliche Werbewiderspruch-Formulierungen, Abteilungskontakt) |
| `stack/open-webui-overrides/open_webui/utils/middleware.py` | `_model_led_preroute_disabled`, `_routing_plan_for_execution(…, model_id)`, Aufrufstelle |
| `stack/docker-compose.local-edge.yml` | `KAHLE_MODEL_LED_PREROUTE_OFF_MODELS` |
| `scripts/openwebui/register-kahle-workflow-tool.py` | `rag_chat`-Beschreibung und `query`-Beschreibung |
| `scripts/openwebui/register-vinci-models.py` | `kahleKnowledgeNote` an die neue Quellenregel angleichen |
| `stack/open-webui-overrides/open_webui/utils/kahle_internal_knowledge.py` | Personio-Tool-Beschreibung (deutsch, Ausschlüsse, gemischter Fall) |
| `stack/open-webui-prompts/kahle-vinci-systemprompt.md`, `…-thinking-systemprompt.md` | Tool-Pflicht und gemischte Kontaktfragen in Abschnitt 3.3 |
| Create `stack/tests/test_kahle_harness_phase3.py` | neue Tests |
| `stack/tests/test_vinci_knowledge_source_prompt_contracts.py` | Erwartung an die `rag_chat`-Beschreibung anpassen |

---

### Task 1: Korpus um die gefundenen Lücken ergänzen

**Files:** `eval/harness/routing_cases.yml`; Test `eval/harness/tests/test_routing_corpus.py` (unverändert gültig)

- [ ] **Step 1:** Im Abschnitt `# --- RAG: Geltungsbereich nach Standort (U1) ---` anhängen:

```yaml
  - {id: scope_natural_hannover, category: scope_location, question: "Wie sperre ich einen Kunden für Werbung am Standort Hannover?", expected_tools: [rag_chat], findings: [U1, P3]}
  - {id: scope_natural_no_ads, category: scope_location, question: "Der Kunde will keine Werbung mehr bekommen, wie trage ich das ein?", expected_tools: [rag_chat], findings: [U1, P3]}
```

Im Abschnitt `# --- Beide: Abteilungskontakte ---` anhängen:

```yaml
  - {id: org_contact_service_neustadt, category: organization_contact, question: "Wen erreiche ich im Service in Neustadt und wie?", expected_tools: [personio_directory, rag_chat], findings: [P3]}
```

- [ ] **Step 2:** `$P -m pytest eval/harness/tests -q -p no:cacheprovider` → `40 passed`
- [ ] **Step 3:** Offline-Baseline neu erzeugen: `$P eval/harness/offline_routing_eval.py --output eval/harness/results/2026-10-01-offline-phase3-start.json`. Die Ausgabe notieren.
- [ ] **Step 4: Commit** `test(eval): cover natural opt-out phrasings and department contacts`

### Task 2: Schalter je Modell für die Vorplanung

**Files:** `middleware.py`, `docker-compose.local-edge.yml`; Test `stack/tests/test_kahle_harness_phase3.py`

- [ ] **Step 1: Failing tests**

`stack/tests/test_kahle_harness_phase3.py`:

```python
import ast
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
MIDDLEWARE = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "middleware.py"


def load_middleware_functions(*names):
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in nodes} == set(names)
    namespace = {"Any": Any, "os": __import__("os")}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(MIDDLEWARE), "exec"), namespace)
    return namespace


PLAN = object()


@pytest.mark.parametrize(
    "mode, off_models, model_id, expected",
    [
        ("model_led", "", "kahle-vinci-thinking", PLAN),
        ("model_led", "kahle-vinci-thinking", "kahle-vinci-thinking", None),
        ("model_led", "kahle-vinci-thinking, vinci-2-clone-clone-clone", "vinci-2-clone-clone-clone", None),
        ("model_led", "kahle-vinci-thinking", "kahle-vinci-max-thinking", PLAN),
        ("legacy", "kahle-vinci-thinking", "kahle-vinci-thinking", PLAN),
    ],
)
def test_preroute_can_be_disabled_per_model_only_in_model_led(monkeypatch, mode, off_models, model_id, expected):
    monkeypatch.setenv("KAHLE_MODEL_LED_PREROUTE_OFF_MODELS", off_models)
    select = load_middleware_functions(
        "_routing_plan_for_execution", "_model_led_preroute_disabled"
    )["_routing_plan_for_execution"]

    assert select(mode, PLAN, model_id) is expected


def test_call_site_passes_the_request_model():
    source = MIDDLEWARE.read_text(encoding="utf-8")

    assert re.search(
        r"retrieval_plan = _routing_plan_for_execution\(\s*routing_mode, legacy_retrieval_plan, "
        r"str\(form_data\.get\('model'\) or ''\)\s*\)",
        source,
    )


def test_local_edge_exposes_the_switch_with_an_empty_default():
    local = (ROOT / "docker-compose.local-edge.yml").read_text(encoding="utf-8")

    assert "KAHLE_MODEL_LED_PREROUTE_OFF_MODELS: ${KAHLE_MODEL_LED_PREROUTE_OFF_MODELS:-}" in local
```

- [ ] **Step 2:** Run → FAIL
- [ ] **Step 3: Implement.** `_routing_plan_for_execution` ersetzen:

```python
def _model_led_preroute_disabled(model_id: str) -> bool:
    """Per-model switch to measure and later release pure model-led routing."""
    raw = str(os.getenv('KAHLE_MODEL_LED_PREROUTE_OFF_MODELS') or '')
    return str(model_id or '') in {item.strip() for item in raw.split(',') if item.strip()}


def _routing_plan_for_execution(routing_mode: str, legacy_plan: Any, model_id: str = '') -> Any:
    if routing_mode == 'model_led' and _model_led_preroute_disabled(model_id):
        return None
    return legacy_plan if routing_mode in {'legacy', 'model_led'} else None
```

Aufrufstelle:

```python
        retrieval_plan = _routing_plan_for_execution(
            routing_mode, legacy_retrieval_plan, str(form_data.get('model') or '')
        )
```

`docker-compose.local-edge.yml` direkt unter `KAHLE_ANSWER_ENFORCEMENT: "enforce"`:

```yaml
      KAHLE_MODEL_LED_PREROUTE_OFF_MODELS: ${KAHLE_MODEL_LED_PREROUTE_OFF_MODELS:-}
```

- [ ] **Step 4:** Tests → PASS; den bestehenden Test `select_plan(...)` in `test_middleware_internal_rag_routing.py` unverändert lassen (Default-Argument); `stack/tests` vollständig; `compose_static_check.py`
- [ ] **Step 5: Commit** `feat(middleware): switch off pre-routing per model in model-led mode`

### Task 3: Tool-Beschreibungen schärfen

**Files:** Registrierungsskripte, `kahle_internal_knowledge.py`; Tests `test_kahle_harness_phase3.py`, `test_vinci_knowledge_source_prompt_contracts.py`

- [ ] **Step 1: Failing tests** (anhängen):

```python
import importlib.util

REGISTER = ROOT.parent / "scripts" / "openwebui" / "register-kahle-workflow-tool.py"
MODEL_REGISTER = ROOT.parent / "scripts" / "openwebui" / "register-vinci-models.py"
INTERNAL = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "kahle_internal_knowledge.py"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rag_description_covers_roles_locations_abbreviations_and_mixed_contacts():
    spec = _load(REGISTER, "reg_phase3").TOOL_DEFINITIONS["rag_chat"]["specs"][0]
    description = spec["description"]

    for phrase in (
        "Aufgaben von Rollen",
        "standortbezogene Abläufe",
        "Abkürzungen",
        "auch bei kurzen Begriffen, Abkürzungen und Folgefragen",
        "Nicht für aktuelle Personen, ihre Einzelkontakte oder Führungskräfte",
        "Bei Kontaktfragen zu einer Abteilung oder einem Bereich zusätzlich personio_directory aufrufen",
    ):
        assert phrase in description
    assert "Rollen, Teams, Abteilungen, Standorte" not in description
    assert "Bezug aus dem Verlauf" in spec["parameters"]["properties"]["query"]["description"]


def test_personio_description_is_german_and_names_the_mixed_case():
    source = INTERNAL.read_text(encoding="utf-8")

    assert "Durchsucht das aktuelle KAHLE-Mitarbeiterverzeichnis (Personio)" in source
    assert "Nicht für dokumentierte Prozesse, Zuständigkeiten oder Aufgabenbeschreibungen" in source
    assert "Bei Kontaktfragen zu einer Abteilung oder einem Bereich zusätzlich rag_chat aufrufen" in source
    assert "Search the current KAHLE employee directory" not in source


def test_model_note_matches_the_source_policy():
    models = _load(MODEL_REGISTER, "model_reg_phase3")
    note = models.make_meta(models.MODELS[0])["kahleKnowledgeNote"]

    assert "Abteilungs- und Bereichskontakte: beide Tools" in note
```

- [ ] **Step 2:** Run → FAIL
- [ ] **Step 3: Implement**

`rag_chat` in `TOOL_DEFINITIONS` (Registrierungsskript):

```python
                "description": (
                    "Durchsucht freigegebene KAHLE-Dokumente: Prozesse und Arbeitsanweisungen, "
                    "Zuständigkeiten und Aufgaben von Rollen, standortbezogene Abläufe, Systeme, "
                    "Abkürzungen, Öffnungszeiten, Funktionspostfächer, Ticketsysteme sowie "
                    "Einreichungs- und Kontaktwege. Für jede Frage zu internem KAHLE-Wissen aufrufen, "
                    "statt aus Modellwissen zu antworten – auch bei kurzen Begriffen, Abkürzungen und "
                    "Folgefragen. Nicht für aktuelle Personen, ihre Einzelkontakte oder Führungskräfte; "
                    "dafür personio_directory. Bei Kontaktfragen zu einer Abteilung oder einem Bereich "
                    "zusätzlich personio_directory aufrufen."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"query": {
                        "type": "string",
                        "description": (
                            "Eigenständige, vollständige Frage auf Deutsch. Bei Folgefragen den Bezug "
                            "aus dem Verlauf ausschreiben, zum Beispiel System, Prozess oder Standort."
                        ),
                    }},
                    "required": ["query"],
                },
```

Personio-Spec in `kahle_internal_knowledge.py`:

```python
            "description": (
                "Durchsucht das aktuelle KAHLE-Mitarbeiterverzeichnis (Personio): Personen, "
                "Positionen, Teams, Abteilungen, Standorte, Onboarding und Führungskräfte. "
                "Nicht für dokumentierte Prozesse, Zuständigkeiten oder Aufgabenbeschreibungen; "
                "dafür rag_chat. Bei Kontaktfragen zu einer Abteilung oder einem Bereich "
                "zusätzlich rag_chat aufrufen."
            ),
```

Die `query`-Beschreibung dort:

```python
                        "description": (
                            "Die unveränderte Verzeichnisfrage. Bei Folgefragen den Bezug "
                            "(Name, Bereich, Standort) aus dem Verlauf ausschreiben."
                        ),
```

`kahleKnowledgeNote` in `register-vinci-models.py`:

```python
        "kahleKnowledgeNote": "Quellenhoheit: aktuelle Personen, Einzelkontakte und Führungskräfte über personio_directory; dokumentierte Prozesse, Zuständigkeiten und Aufgaben von Rollen, standortbezogene Abläufe, Abkürzungen, Funktionspostfächer, Ticketsysteme sowie Einreichungs- und Kontaktwege über rag_chat. Abteilungs- und Bereichskontakte: beide Tools. OpenWebUI file context ist global deaktiviert.",
```

`test_vinci_knowledge_source_prompt_contracts.py`: die Assertion `"Nicht für aktuelle Personen" in rag_description` bleibt gültig. Weitere Assertions auf den alten Wortlaut auf die neuen Phrasen umstellen, ohne die Personio-/RAG-Trennung abzuschwächen.

- [ ] **Step 4:** Tests → PASS; `stack/tests` vollständig
- [ ] **Step 5: Commit** `feat(tools): sharpen internal knowledge tool descriptions for model-led routing`

### Task 4: Tool-Pflicht und gemischte Kontaktfragen im Prompt

**Files:** beide System-Prompts (Abschnitt 3.3); Test `test_kahle_harness_phase3.py`

- [ ] **Step 1: Failing test** (anhängen):

```python
PROMPTS = (
    ROOT / "open-webui-prompts" / "kahle-vinci-systemprompt.md",
    ROOT / "open-webui-prompts" / "kahle-vinci-thinking-systemprompt.md",
)
RULES = (
    "Beantworte KAHLE-interne Fragen nie ohne Tool-Evidenz. Das gilt auch für Abkürzungen, Systeme, Öffnungszeiten und Folgefragen; rufe dafür das passende Tool erneut auf.",
    "Kontaktfragen zu einer Abteilung oder einem Bereich brauchen beide Quellen: rufe rag_chat und personio_directory im selben Schritt auf.",
)


@pytest.mark.parametrize("prompt_path", PROMPTS, ids=lambda p: p.name)
def test_prompts_state_tool_duty_and_mixed_contacts(prompt_path):
    prompt = prompt_path.read_text(encoding="utf-8")
    for rule in RULES:
        assert rule in prompt
```

- [ ] **Step 2:** Run → FAIL
- [ ] **Step 3: Implement.** In beiden Prompts in Abschnitt 3.3 direkt nach der Zeile, die mit `- \`rag_chat\` liefert ausschließlich dokumentierte Prozess- und Kontaktweg-Evidenz.` beginnt, die zwei Regeln als eigene Zeilen einfügen. Sie beginnen jeweils mit `- `; die Zeichenketten stehen exakt so in `RULES`. Per Python-Skript mit CRLF-Erhalt.
- [ ] **Step 4:** Tests → PASS; `stack/tests` vollständig
- [ ] **Step 5: Commit** `fix(prompts): require tool evidence and both sources for department contacts`

**Abweichung bei der Umsetzung:**

- Die Quellenmatrix in Abschnitt 3.3 beider Prompts und die gemeinsame Function-Calling-Anweisung in `register-kahle-workflow-tool.py` wiesen „Rollen, Teams, Abteilungen, Standorte“ weiterhin allein `personio_directory` zu. Das widersprach den neuen Tool-Beschreibungen aus Task 3 und damit der Hauptursache des Prototyps.
- Beide Matrizen folgen jetzt der Modellnotiz:
  - Personio: Personen, Positionen, Teams, Abteilungs- und Standortzuordnung von Personen.
  - rag_chat: Aufgaben von Rollen, standortbezogene Abläufe, Abkürzungen.
  - Beide Tools: Abteilungs- und Bereichskontakte.
- Die Function-Calling-Anweisung enthält zusätzlich die Tool-Pflicht.
- Neue Tests: `test_prompt_source_matrix_matches_the_tool_descriptions`, `test_function_calling_prompt_matches_the_tool_descriptions`. Die Altverträge in `test_vinci_knowledge_source_prompt_contracts.py` wurden auf den neuen Wortlaut umgestellt.
- Die Personio-Führungshoheit und das Fallback-Verbot bleiben unverändert.
- Task 3: Der Personio-Test liest die String-Konstanten über den AST statt des Rohtexts, weil die Beschreibung über implizite Stringverkettung auf mehrere Zeilen verteilt ist.

### Task 5: Verify, Ausrollen, zweifache Laufzeitmessung

- [ ] Full Verify → Exit 0
- [ ] Ausrollen:
  1. Registrierung (Prompts, Tool-Spec): `MSYS_NO_PATHCONV=1 bash <scratchpad>/deploy_branch.sh`. Das Skript registriert und startet neu.
  2. Container neu erstellen, damit die neue Compose-Variable greift: `.\scripts\start-stack.ps1 -NoBuild -ComposeArgs @('--no-deps','open-webui')`
- [ ] **Messung A, mit Vorplanung (Regressionsschutz):** voller Laufzeit-Eval → `eval/harness/results/2026-10-01-runtime-phase3-hybrid.json`. Erwartung: Routing je Modell nicht schlechter als `2026-09-30-runtime-phase2-final.json` (±2 Rauschen); keine ausgelieferten blockierenden Verstöße.
- [ ] **Messung B, ohne Vorplanung:** in PowerShell `$env:KAHLE_MODEL_LED_PREROUTE_OFF_MODELS='vinci-2-clone-clone-clone,kahle-vinci-thinking,kahle-vinci-max-thinking'`, dann Container neu erstellen (wie oben), voller Laufzeit-Eval → `…-runtime-phase3-model-led.json`. Danach die Variable entfernen (`Remove-Item Env:KAHLE_MODEL_LED_PREROUTE_OFF_MODELS`) und den Container erneut erstellen. Mit `docker exec open-webui printenv KAHLE_MODEL_LED_PREROUTE_OFF_MODELS` prüfen, dass sie leer ist.
- [ ] Vergleich je Modell und Kategorie: A gegen Phase 2, B gegen Prototyp und gegen A. Fehlerzeilen (IONOS) getrennt ausweisen.
- [ ] Zusammenfassungen committen.

**Freigabe-Tor (Entscheidung des Nutzers):** Ein Modell kommt in `KAHLE_MODEL_LED_PREROUTE_OFF_MODELS`, wenn in Messung B gilt:

1. Routing ≥ Messung A − 2,
2. keine Kategorie mehr als 1 Fall schlechter,
3. Enthaltungen nicht höher.

Sonst bleibt die Vorplanung für dieses Modell aktiv, und die Fehlerkategorien gehen in Phase 4 (Modellführung).

### Task 6: Werbewiderspruch-Dokument auffindbar machen (Inhalt, Nutzer)

- [ ] **Nutzer:** In der Prozessbeschreibung „Temporäre Sperrung Hersteller-Zufriedenheitsbefragungen“ einen Abschnitt ergänzen:

```markdown
## Suchbegriffe

Werbewiderspruch, Werbesperre, Werbung sperren, Kunde möchte keine Werbung,
keine Werbung mehr, Werbeabmeldung, Zufriedenheitsbefragung abbestellen,
Herstellerbefragung sperren, DSE-Kontaktfreigaben, Kontaktfreigaben ändern,
Kundensperre Werbung, Werbewiderspruch in Vaudis
```

  Danach die Version über den Freigabeprozess veröffentlichen und die Indexierung abwarten.
- [ ] **Prüfung (Agent):** Die Werbewiderspruch-Prüfung im Container (`optout_generic_probe.py`) mit abgeschaltetem Sonderpfad wiederholen. Bestanden, wenn für alle vier natürlichen Formulierungen einschließlich „Standort Hannover“ die Prozessbeschreibung unter den Quellen ist.
- [ ] Bestanden → Plan „Phase 3b: Rückbau des Werbewiderspruch-Sonderpfads“ schreiben (Harness-Umschreibung, Standort-Vertrag, Tool-Anweisungen, Retrieval-Filter, Middleware-Gate und -Normalisierung, Portal-Retrieval-Metadaten), wieder mit Eval-Tor.

## Abnahme Phase 3

- Tool-Beschreibungen und Prompt-Regeln sind umgesetzt; Full Verify grün.
- Messung A zeigt keine Regression gegenüber Phase 2.
- Messung B ist dokumentiert. Die Freigabe je Modell ist entschieden und im Overlay umgesetzt oder begründet zurückgestellt.
- Task 6 ist erledigt oder als offener Inhaltsschritt dokumentiert.

## Ergebnis (01.10.)

Full Verify: 13/13 bestanden. Messungen über 102 Fälle (`eval/harness/results/2026-10-01-runtime-phase3-hybrid.json` und `…-phase3-model-led.json`):

| Modell | Messung A, mit Vorplanung | Messung B, ohne Vorplanung | Phase 2 (99 Fälle) |
| --- | --- | --- | --- |
| Mistral | 91/102 | 70/102 | 91/99 |
| gpt-oss | 95/102 | 73/102 | 90/99 |
| Qwen | 94/102 | 88/102 | 94/99 |

- Messung A zeigt keine Regression gegenüber Phase 2. Auf den 99 gemeinsamen Fällen: Mistral −3, gpt-oss +2, Qwen −3. Ein Qwen-Fall war ein DNS-Ausfall bei IONOS.
- In beiden Messungen gab es keine ausgelieferten blockierenden Verstöße.
- **Freigabe je Modell (Nutzerentscheidung 01.10.):** Die Vorplanung bleibt für alle drei Modelle aktiv, der Schalter `KAHLE_MODEL_LED_PREROUTE_OFF_MODELS` bleibt leer. Ohne Vorplanung verliert jedes Modell deutlich; besonders schwach sind Organisationskontakte (1/9, 0/9, 6/9), Folgefragen und Abkürzungen.
- Weiterführung in Phase 3b: Prozessfragen, die die Schlagwortsperre nicht erfasst, sollen über die evidenzgesteuerte Vorabsuche gebunden werden.
- **Nicht umgesetzt aus der Roadmap:**
  - „eine Vertragsnachricht“ (R2, Befund K6)
  - UI-Abnahme und Release B
  Beides bleibt offen. R2 wird mit Phase 4 (Modellführung) umgesetzt, weil der Vertrag dort ohnehin umgebaut wird (Nutzerentscheidung 07.10.).

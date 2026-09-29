# Harness Phase 0a: Routing-Korrekturen, Direktantworten, Validator-Schweregrade

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die in der Offline-Baseline gemessenen Harness-Fehler werden testgetrieben behoben:

- K1: Umlaut-Normalisierung.
- K3: geschlossene Verbliste bei Anleitungsfragen.
- K2: Zuständigkeitsfragen landen bei Personio.
- Tippfehler bei „Führungskraft“.

Außerdem werden die Legacy-Direktantworten vollständig entfernt, ohne ihre Sicherheitsregeln zu verlieren, und der Validator unterscheidet blockierende von beratenden Verstößen (K4).

**Architecture:** Alle Klassifikationskorrekturen bleiben im Harness-Modul und fügen **keine neuen Wortlisten** für Personen oder Rollen hinzu, nur allgemeinere Satzmuster und Stammformen.

- **Sicherheitsregeln:** Die zwei Regeln der Direktantworten (keine Rangliste von Führungskräften; Führungskraft nur aus Personio) wandern als Evidenzregeln in `build_decision`. Das Modell formuliert danach aus dem bestehenden Antwortvertrag.
- **Validator:** Er setzt pro Verstoß `severity`. Der Status `retry_required` entsteht nur noch aus blockierenden Codes.
- **Eval:** Er liest die `severity`.

**Tech Stack:** Python 3.11, pytest, bestehende Harness-Tests unter `stack/tests`, Offline-Eval `eval/harness`.

**Grundlage:**

- [Roadmap](2026-09-29-harness-quality-roadmap.md)
- [Eval-Grundlage](2026-09-29-harness-eval-foundation.md)
- Offline-Baseline `eval/harness/results/2026-09-29-offline-baseline.json`: 84/99, procedural 42,1 %

**Nicht Teil von 0a (folgt in Phase 0b):**

- Prompt-Korrekturen (Q5)
- einheitliches Zitierformat mit eindeutigen Quellen-IDs über mehrere `rag_chat`-Aufrufe (Q6 und K5)
- Entfernen des toten Guard-Codes. Der Guard enthält derzeit uncommittete Nutzeränderungen und wird erst angefasst, wenn diese committet sind.

---

## Vorbereitung

Weiter auf Branch `feat/harness-eval-foundation`. Uncommittete Änderungen an Guard und Orchestrator nicht stagen.

Die Harness-Datei hat im Arbeitsstand CRLF-Zeilenenden. Edits deshalb mit dem Edit-Werkzeug machen, nicht mit Shell-Heredocs, die Backslashes verändern.

Targeted-Befehle:

```bash
./.venv-verify/Scripts/python.exe -m pytest stack/tests/test_kahle_harness_phase0a.py -q -p no:cacheprovider
./.venv-verify/Scripts/python.exe -m pytest stack/tests/test_kahle_knowledge_harness.py stack/tests/test_kahle_internal_knowledge.py stack/tests/test_middleware_internal_rag_routing.py stack/tests/test_kahle_harness_reference_matrix.py -q -p no:cacheprovider
./.venv-verify/Scripts/python.exe -m pytest eval/harness/tests -q -p no:cacheprovider
```

Ausgangswert der vier Bestandssuiten: **635 passed**.

## Prototyp-Messung (29.09., vor Planerstellung, danach zurückgesetzt)

| Änderung | Offline-Routing | procedural | Bestandstests |
| --- | --- | --- | --- |
| Baseline | 84/99 | 8/19 | 635 grün |
| K1 + K3 (ohne Passiv-Muster) + K2 + Tippfehler | 87/99 (inklusive Korpuskorrektur Task 1: 89/99) | 17/19 | 635 grün |
| zusätzlich Passiv-Muster „Wie wird … durchgeführt?“ | – | 19/19 | **3 rot** (Werbewiderspruch-Sonderpfad) |

Das Passiv-Muster ist deshalb nicht Teil dieses Plans. Die zwei verbleibenden `procedural`-Abweichungen (`scope_opt_out_*`) entstehen, weil der Harness diese Anfragen selbst umschreibt (U1). Sie werden in Phase 3 mit den Geltungsbereichs-Metadaten gelöst.

## Dateistruktur

| Datei | Änderung |
| --- | --- |
| `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py` | Klassifikation, Evidenz-Sicherheitsregeln, Entfernen von `direct_answer`, Validator-Schweregrade, toter Code |
| `stack/open-webui-overrides/open_webui/utils/middleware.py` | `_knowledge_harness_direct_answer` und ihren Aufruf entfernen |
| Create `stack/tests/test_kahle_harness_phase0a.py` | Neue Verhaltenstests dieses Plans |
| `stack/tests/test_kahle_knowledge_harness.py`, `test_middleware_internal_rag_routing.py`, `test_kahle_harness_reference_matrix.py` | Direktantwort-Assertions durch Vertrags- und Evidenz-Assertions ersetzen |
| `eval/harness/routing_cases.yml`, `eval/harness/runtime_harness_eval.py`, `eval/harness/harness_eval.py` + Tests | Korpuskorrektur, echte Modell-ID, `severity` lesen |
| `docs/research/2026-09-29-vinci-harness-analyse.md` | Befund U4 korrigieren |

---

### Task 1: Eval-Korrekturen vor dem Umbau

Zwei Fehler im Eval selbst:

1. **Korpus:** ADR-008 und `ARCHITECTURE.md` definieren Kontaktfragen zu einem *dokumentierten Funktionsthema* (Bewerbung, Krankmeldung) ausdrücklich als gemischt. `functional_sick_note` und `functional_applications_submit` gehören deshalb in `organization_contact` mit beiden Quellen. Nur ausdrückliche Funktionspostfach-, Kontaktseiten- und Ticketfragen bleiben reine RAG-Fragen.
2. **Modell-ID:** Die Modell-ID von KAHLE-Vinci ist `vinci-2-clone-clone-clone` (`scripts/openwebui/register-kahle-workflow-tool.py`), nicht `kahle-vinci`.

**Files:**
- Modify: `eval/harness/routing_cases.yml`
- Modify: `eval/harness/runtime_harness_eval.py` (`DEFAULT_MODELS`)
- Test: `eval/harness/tests/test_runtime_harness_eval.py`
- Modify: `docs/research/2026-09-29-vinci-harness-analyse.md` (U4)

- [ ] **Step 1: Write the failing test**

An `eval/harness/tests/test_runtime_harness_eval.py` anhängen:

```python
def test_default_models_are_the_registered_vinci_model_ids():
    assert runtime_harness_eval.DEFAULT_MODELS == (
        "vinci-2-clone-clone-clone",
        "kahle-vinci-thinking",
        "kahle-vinci-max-thinking",
    )
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv-verify/Scripts/python.exe -m pytest eval/harness/tests -q -p no:cacheprovider`
Expected: 1 failed (`DEFAULT_MODELS` enthält `kahle-vinci`)

- [ ] **Step 3: Implement**

In `eval/harness/runtime_harness_eval.py`:

```python
DEFAULT_MODELS = ("vinci-2-clone-clone-clone", "kahle-vinci-thinking", "kahle-vinci-max-thinking")
```

In `eval/harness/routing_cases.yml` die zwei Zeilen ersetzen:

```yaml
  - {id: functional_sick_note, category: organization_contact, question: "Wohin schicke ich eine Krankmeldung?", expected_tools: [personio_directory, rag_chat]}
```

```yaml
  - {id: functional_applications_submit, category: organization_contact, question: "An wen reiche ich Bewerbungen ein?", expected_tools: [personio_directory, rag_chat]}
```

Beide Zeilen stehen weiter im Abschnitt `# --- RAG: Funktionspostfächer und Kontaktwege ---`. Den Kommentar dieses Abschnitts ändern in `# --- RAG: Funktionspostfächer; Funktionsthemen-Kontakte sind gemischt (ADR-008) ---`.

In `docs/research/2026-09-29-vinci-harness-analyse.md` den Punkt U4 ersetzen durch:

```markdown
- **U4 (korrigiert 29.09.):** `vinci-2-clone-clone-clone` ist die registrierte
  Modell-ID von KAHLE-Vinci (`scripts/openwebui/register-kahle-workflow-tool.py`),
  keine Altlast. Offen bleibt nur, dass die ID an vier Stellen dupliziert ist
  (Middleware, Evidenzsitzung, `owui_productivity.py`, Registrierungsskript).
```

- [ ] **Step 4: Run tests and regenerate the baseline**

Run: `./.venv-verify/Scripts/python.exe -m pytest eval/harness/tests -q -p no:cacheprovider`
Expected: `38 passed`

Run: `./.venv-verify/Scripts/python.exe eval/harness/offline_routing_eval.py --output eval/harness/results/2026-09-29-offline-baseline.json`
Expected: `legacy-planner: 86/99 korrekt (86.9%), procedural 42.1%`

- [ ] **Step 5: Commit**

```bash
git add eval/harness/routing_cases.yml eval/harness/runtime_harness_eval.py eval/harness/tests/test_runtime_harness_eval.py eval/harness/results/2026-09-29-offline-baseline.json docs/research/2026-09-29-vinci-harness-analyse.md
git commit -m "fix(eval): align functional-topic contacts with ADR-008 and real Vinci model id"
```

---

### Task 2: Umlaut- und ASCII-Stammformen (K1)

**Files:**
- Create: `stack/tests/test_kahle_harness_phase0a.py`
- Modify: `kahle_knowledge_harness.py` → `_is_procedural`, `_procedure_is_supported`

- [ ] **Step 1: Write the failing tests**

`stack/tests/test_kahle_harness_phase0a.py`:

```python
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "kahle_knowledge_harness.py"


def load_harness():
    spec = importlib.util.spec_from_file_location("kahle_harness_phase0a", HARNESS)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "umlaut, ascii_form",
    [
        ("Wie ändere ich eine Kundenadresse in Vaudis?", "Wie aendere ich eine Kundenadresse in Vaudis?"),
        ("Wie öffne ich einen Werkstattauftrag in WPS?", "Wie oeffne ich einen Werkstattauftrag in WPS?"),
        ("Wie läuft die Dialogannahme?", "Wie laeuft die Dialogannahme?"),
        ("Wie führe ich eine HU-Anmeldung durch?", "Wie fuehre ich eine HU-Anmeldung durch?"),
        ("Wie wähle ich im WPS einen freien Termin?", "Wie waehle ich im WPS einen freien Termin?"),
        ("Wie bestätige ich den Auftrag?", "Wie bestaetige ich den Auftrag?"),
    ],
)
def test_procedural_detection_is_independent_of_umlaut_spelling(umlaut, ascii_form):
    harness = load_harness()

    assert harness._is_procedural(umlaut) is True
    assert harness._is_procedural(ascii_form) is True


@pytest.mark.parametrize(
    "context",
    [
        "Öffnen Sie die Maske. Wählen Sie den Kunden. Bestätigen Sie mit OK.",
        "Oeffnen Sie die Maske. Waehlen Sie den Kunden. Bestaetigen Sie mit OK.",
    ],
)
def test_procedure_support_counts_umlaut_and_ascii_action_verbs(context):
    assert load_harness()._procedure_is_supported(context) is True
```

- [ ] **Step 2: Run to verify they fail**

Run: `./.venv-verify/Scripts/python.exe -m pytest stack/tests/test_kahle_harness_phase0a.py -q -p no:cacheprovider`
Expected: 8 failed. Die sechs Anfragepaare scheitern an der Umlautvariante. Beide Evidenztexte scheitern, weil heute nur zwei der drei Verben erkannt werden (`\bo?ffn` passt nicht auf „oeffnen“, `waehl`/`bestaetig` nicht auf „wählen“/„bestätigen“).

- [ ] **Step 3: Implement**

In `_is_procedural` die Verbalternativen ersetzen durch:

```python
            r"kann|muss|soll|darf|gehe|verfahre|funktioniert|lae?uft|"
            r"bedien|nutz|verwend|richt|beantrag|ae?nder|pfleg|meld|"
            r"fue?hr|oe?ffn|wae?hl|trag|gib|erfass|speicher|bestae?tig|"
            r"erstell|plan|buch|sperr"
```

In `_procedure_is_supported` drei Muster ersetzen:

```python
        r"\b(?:oe|o)?ffn\w*",
```
```python
        r"\bwae?hl\w*",
```
```python
        r"\bbestae?tig\w*",
```

- [ ] **Step 4: Run tests**

Run: `./.venv-verify/Scripts/python.exe -m pytest stack/tests/test_kahle_harness_phase0a.py -q -p no:cacheprovider`
Expected: `8 passed`

Run: die vier Bestandssuiten (siehe Vorbereitung)
Expected: `635 passed`

- [ ] **Step 5: Commit**

```bash
git add stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py stack/tests/test_kahle_harness_phase0a.py
git commit -m "fix(harness): recognize procedures regardless of umlaut spelling"
```

---

### Task 3: Anleitungsfragen ohne geschlossene Verbliste (K3)

**Files:**
- Modify: `kahle_knowledge_harness.py` → neue Konstante vor `_is_procedural`, Erweiterung des `return`
- Test: `stack/tests/test_kahle_harness_phase0a.py`

- [ ] **Step 1: Write the failing tests**

Anhängen:

```python
@pytest.mark.parametrize(
    "query",
    [
        "Wie lege ich einen Neukunden in Vaudis an?",
        "Wie storniere ich eine Rechnung?",
        "Wie reserviere ich einen Leihwagen für einen Werkstattkunden?",
        "Wie hinterlege ich einen Werbewiderspruch in Vaudis?",
        "Wie macht man eine Garantieanfrage?",
    ],
)
def test_first_person_how_to_questions_are_procedural(query):
    assert load_harness()._is_procedural(query) is True


@pytest.mark.parametrize(
    "query",
    [
        "Wie heißt der Serviceleiter in Wunstorf?",
        "Wie viele Serviceberater gibt es in Nienburg?",
        "Wie bin ich bei KAHLE versichert?",
        "Wie ist das Wetter heute?",
        "Was bedeutet TD?",
    ],
)
def test_non_procedural_how_questions_stay_non_procedural(query):
    assert load_harness()._is_procedural(query) is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `./.venv-verify/Scripts/python.exe -m pytest stack/tests/test_kahle_harness_phase0a.py -q -p no:cacheprovider`
Expected: 5 failed (`test_first_person_how_to_questions_are_procedural`), Negativfälle PASS

- [ ] **Step 3: Implement**

Direkt vor `def _is_procedural(query: str) -> bool:` einfügen:

```python
_FIRST_PERSON_HOW_TO = re.compile(
    r"\bwie\s+(?!(?:bin|ist|sind|war|waren|heit|heisst|heisse|viele?|lange|alt|oft)\b)"
    r"\w+\s+(?:ich|man|wir)\b"
)
```

`ß` fällt in `_fold` weg, deshalb steht `heit` für „heißt“.

Das abschließende `return bool(re.search(...))` in `_is_procedural` so erweitern, dass nach dem schließenden `)` des bisherigen `re.search(...)`-Aufrufs vor dem letzten `)` von `bool(` steht:

```python
        or _FIRST_PERSON_HOW_TO.search(intent_text)
```

- [ ] **Step 4: Run tests**

Run: `./.venv-verify/Scripts/python.exe -m pytest stack/tests/test_kahle_harness_phase0a.py -q -p no:cacheprovider`
Expected: `18 passed`

Run: die vier Bestandssuiten
Expected: `635 passed`

- [ ] **Step 5: Commit**

```bash
git add stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py stack/tests/test_kahle_harness_phase0a.py
git commit -m "fix(harness): treat first-person how-to questions as procedures"
```

---

### Task 4: Zuständigkeitsfragen gehen an RAG (K2)

Ursache laut Analyse: Das Namensmuster akzeptiert „für Garantieanträge“ als Vor- und Nachname. Außerdem fehlt eine allgemeine Erkennung von Zuständigkeitsfragen.

Mit ausdrücklich genanntem Personennamen bleibt die Frage gemischt, z. B. „Welche Aufgaben hat Anna Beispiel …“ (`person_process`).

**Files:**
- Modify: `kahle_knowledge_harness.py` → `_PERSON_NAME_WORD`, neue Funktion `_documented_responsibility_question`, `_directory_information_need`, `_rag_information_need`
- Test: `stack/tests/test_kahle_harness_phase0a.py`

- [ ] **Step 1: Write the failing tests**

Anhängen:

```python
def _tools(harness, query):
    return harness.plan_retrieval(query, query, [], "test-model", {"user_id": "u"}).required_tools


@pytest.mark.parametrize(
    "query",
    [
        "Wer ist für Garantieanträge zuständig?",
        "Welche Aufgaben hat ein Serviceberater?",
        "Wer kümmert sich um Leasingrückläufer?",
        "Wer ist für die Freigabe von Arbeitsanweisungen verantwortlich?",
    ],
)
def test_documented_responsibility_questions_use_rag_only(query):
    assert _tools(load_harness(), query) == ("rag_chat",)


@pytest.mark.parametrize(
    "query, tools",
    [
        ("Wer ist Max Mustermann?", ("personio_directory",)),
        ("Wer ist die Führungskraft von Anna Beispiel?", ("personio_directory",)),
        ("Wer sind die Serviceberater in Wunstorf?", ("personio_directory",)),
        (
            "Welche Rolle hat Anna Beispiel und welche Aufgaben gehören laut Arbeitsanweisung dazu?",
            ("personio_directory", "rag_chat"),
        ),
    ],
)
def test_person_questions_keep_their_directory_route(query, tools):
    assert _tools(load_harness(), query) == tools
```

- [ ] **Step 2: Run to verify they fail**

Run: `./.venv-verify/Scripts/python.exe -m pytest stack/tests/test_kahle_harness_phase0a.py -q -p no:cacheprovider`
Expected: FAIL für „Garantieanträge“ (`personio_directory`) und „Welche Aufgaben hat ein Serviceberater?“ (`personio_directory`); die übrigen Fälle PASS

- [ ] **Step 3: Implement**

In `_PERSON_NAME_WORD` nach der ersten Zeile `r"(?!(?:der|die|das|den|dem|ein|eine|einen|einem|einer|"` einfügen:

```python
    r"f(?:ü|ue|u)r|bei|mit|von|im|in|an|am|auf|zu|zum|zur|(?:ü|ue|u)ber|"
```

Direkt vor `def _directory_information_need(query: str) -> bool:` einfügen:

```python
def _documented_responsibility_question(folded_query: str) -> bool:
    """Responsibilities and role duties are documented process knowledge."""
    return bool(re.search(
        r"\b(?:zustandig\w*|verantwortlich\w*|kummer\w*\s+sich|"
        r"welche\s+aufgaben|aufgaben\s+(?:hat|haben))\b",
        folded_query,
    ))
```

In `_directory_information_need` direkt nach dem ersten `if _functional_responsibility_question(folded): return False` einfügen:

```python
    if _documented_responsibility_question(folded) and not _has_named_person_reference(query):
        return False
```

In `_rag_information_need` direkt vor `relation = bool(` einfügen:

```python
    if _documented_responsibility_question(folded):
        return True
```

- [ ] **Step 4: Run tests**

Run: `./.venv-verify/Scripts/python.exe -m pytest stack/tests/test_kahle_harness_phase0a.py -q -p no:cacheprovider`
Expected: `26 passed`

Run: die vier Bestandssuiten
Expected: `635 passed`

- [ ] **Step 5: Commit**

```bash
git add stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py stack/tests/test_kahle_harness_phase0a.py
git commit -m "fix(harness): route documented responsibility questions to RAG"
```

---

### Task 5: Vertauschte Buchstaben in „Führungskraft“

**Files:**
- Modify: `kahle_knowledge_harness.py` → `_has_supervisor_reference`, neue Funktion `_one_edit_apart`
- Test: `stack/tests/test_kahle_harness_phase0a.py`

- [ ] **Step 1: Write the failing tests**

Anhängen:

```python
@pytest.mark.parametrize(
    "query",
    [
        "Wer ist die Fürhungskraft von Anna Beispiel?",
        "Wer ist die Führungskrfat von Anna Beispiel?",
        "Wer ist die Führungskrft von Anna Beispiel?",
    ],
)
def test_supervisor_reference_tolerates_one_typo_or_transposition(query):
    assert load_harness()._has_supervisor_reference(query) is True


def test_unrelated_words_are_not_supervisor_references():
    harness = load_harness()

    assert harness._has_supervisor_reference("Wie funktioniert die Fahrzeugführung?") is False
    assert harness._has_supervisor_reference("Wer macht die Fuhrparkplanung?") is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `./.venv-verify/Scripts/python.exe -m pytest stack/tests/test_kahle_harness_phase0a.py -q -p no:cacheprovider`
Expected: 2 failed („Fürhungskraft“ und „Führungskrfat“, beides Buchstabenvertauschungen). Die Auslassung „Führungskrft“ und die Negativfälle PASS.

- [ ] **Step 3: Implement**

Direkt vor `def _one_character_apart(left: str, right: str) -> bool:` einfügen:

```python
def _one_edit_apart(left: str, right: str) -> bool:
    """One insertion, deletion, substitution or adjacent transposition."""
    if len(left) == len(right):
        diffs = [index for index, (a, b) in enumerate(zip(left, right)) if a != b]
        if len(diffs) == 2 and diffs[1] == diffs[0] + 1:
            return left[diffs[0]] == right[diffs[1]] and left[diffs[1]] == right[diffs[0]]
    return _one_character_apart(left, right)
```

In `_has_supervisor_reference` die Bedingung ersetzen:

```python
        token.startswith("fu") and _one_edit_apart(token, "fuhrungskraft")
```

- [ ] **Step 4: Run tests**

Run: `./.venv-verify/Scripts/python.exe -m pytest stack/tests/test_kahle_harness_phase0a.py -q -p no:cacheprovider`
Expected: `30 passed`

Run: die vier Bestandssuiten
Expected: `635 passed`

- [ ] **Step 5: Commit**

```bash
git add stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py stack/tests/test_kahle_harness_phase0a.py
git commit -m "fix(harness): accept transposed letters in supervisor wording"
```

---

### Task 6: Sicherheitsregeln der Direktantworten in die Evidenz verlagern

`_knowledge_harness_direct_answer` (Middleware) setzt heute zwei Sicherheitsregeln als feste Texte um. Beide wandern als Evidenzregeln in `build_decision`, den Legacy-Pfad, in dem die Direktantworten liefen. `build_result_driven_decision` bleibt unverändert.

1. Fragen nach Rangliste oder Auswahl wichtiger Führungskräfte: `unsupported`, keine Claims.
2. Supervisor-Fragen: nur Personio-Claims (`P…`) zählen, und genau ein Name. Sonst `unsupported`.

**Files:**
- Modify: `kahle_knowledge_harness.py` → neue Funktion `_apply_directory_safety_rules`, Aufruf in `build_decision`
- Test: `stack/tests/test_kahle_harness_phase0a.py`

- [ ] **Step 1: Write the failing tests**

Anhängen:

```python
def _personio(*names):
    return {
        "status": "ok",
        "claims": [
            {"display_name": name, "position": "Leitung", "source_id": f"P{index}"}
            for index, name in enumerate(names, 1)
        ],
        "sources": [{"id": f"P{index}", "kind": "personio_directory"} for index in range(1, len(names) + 1)],
        "sync_completed_at": "2026-09-29T08:00:00Z",
        "stale": False,
    }


def _decide(harness, query, personio=None, rag=""):
    return harness.build_decision(
        query=query,
        resolved_query=query,
        messages=[{"role": "user", "content": query}],
        model_id="test-model",
        permission_scope={"user_id": "u", "role": "user", "groups": []},
        rag_result=rag,
        personio_result=personio,
    )


def test_leadership_ranking_has_no_supported_evidence():
    decision = _decide(load_harness(), "Wer sind die wichtigsten Führungskräfte?", _personio("Erika Beispiel"))

    assert decision.evidence_bundle.status == "unsupported"
    assert decision.evidence_bundle.supported_claims == ()
    assert "Erika Beispiel" not in decision.answer_prompt()


def test_named_supervisor_with_one_personio_claim_stays_supported():
    decision = _decide(load_harness(), "Wer ist die Führungskraft von Erika Beispiel?", _personio("Max Leitung"))

    assert decision.evidence_bundle.status == "supported"
    assert "Max Leitung" in decision.answer_prompt()


def test_ambiguous_supervisor_candidates_are_unsupported():
    decision = _decide(
        load_harness(), "Wer ist die Führungskraft von Erika Beispiel?", _personio("Max Leitung", "Mia Leitung")
    )

    assert decision.evidence_bundle.status == "unsupported"
    assert "Mia Leitung" not in decision.answer_prompt()


def test_supervisor_typo_without_personio_evidence_has_no_person_claim():
    decision = _decide(load_harness(), "Wer ist die Führungskrft von Erika Beispiel?")

    assert decision.evidence_bundle.status == "unsupported"
    assert decision.evidence_bundle.supported_claims == ()
```

- [ ] **Step 2: Run to verify they fail**

Run: `./.venv-verify/Scripts/python.exe -m pytest stack/tests/test_kahle_harness_phase0a.py -q -p no:cacheprovider`
Expected: FAIL für `test_leadership_ranking_has_no_supported_evidence` und `test_ambiguous_supervisor_candidates_are_unsupported`

> **Abweichung bei der Umsetzung (29.09.):** „Wer sind die wichtigsten Führungskräfte?“ ohne Bereich wird nur an RAG geroutet. Der Test war dadurch schon vorher grün und prüfte die Regel nicht. Der umgesetzte Test ist deshalb parametrisiert mit „… im Verkauf?“ und „Gib mir eine Rangliste der Führungskräfte im Service“. Beide laufen über Personio (per Assertion abgesichert) und waren ohne die Regel `supported`.

- [ ] **Step 3: Implement**

Direkt vor `def build_decision(` einfügen:

```python
_LEADERSHIP_RANKING = re.compile(
    r"\b(?:wichtig\w*|rangliste|auswahl)\b.*\bfuhrungskraft\w*\b"
)


def _apply_directory_safety_rules(
    query: str, evidence: EvidenceBundle
) -> EvidenceBundle:
    """Keep supervisor answers bound to exactly one Personio record."""
    if _LEADERSHIP_RANKING.search(_fold(query)):
        return EvidenceBundle(
            status="unsupported",
            missing_information=(
                "Eine Rangliste oder Auswahl wichtiger Führungskräfte ist durch "
                "Personio nicht belegt.",
            ),
            sync_completed_at=evidence.sync_completed_at,
            stale=evidence.stale,
        )
    if classify_personio_directory_intent(query) != "supervisor_lookup":
        return evidence
    personio_claims = tuple(
        claim
        for claim in evidence.supported_claims
        if isinstance(claim, dict)
        and _citation_identifier(str(claim.get("source_id") or "")).startswith("P")
    )
    names = {
        str(claim.get("display_name") or "").strip()
        for claim in personio_claims
        if str(claim.get("display_name") or "").strip()
    }
    if len(names) != 1:
        return EvidenceBundle(
            status="unsupported",
            missing_information=(
                "Dazu finde ich im aktuellen Personio-Mitarbeiterverzeichnis keine "
                "eindeutige Supervisor-Evidenz.",
            ),
            sync_completed_at=evidence.sync_completed_at,
            stale=evidence.stale,
        )
    return replace(
        evidence,
        supported_claims=personio_claims,
        sources=tuple(
            source
            for source in evidence.sources
            if _source_identifier(source).startswith("P")
        ),
    )
```

In `build_decision` direkt vor `evidence, allowed_contact_values = _apply_contact_evidence_requirement(` einfügen:

```python
    evidence = _apply_directory_safety_rules(retrieval_query, evidence)
```

- [ ] **Step 4: Run tests**

Run: `./.venv-verify/Scripts/python.exe -m pytest stack/tests/test_kahle_harness_phase0a.py -q -p no:cacheprovider`
Expected: `34 passed`

Run: die vier Bestandssuiten
Expected: `635 passed`. Schlägt ein Bestandstest fehl, prüfen, ob er eine Supervisor- oder Ranglistenfrage mit RAG- oder Mehrfach-Claims erwartet. Nur dann an die neue, strengere Evidenzregel anpassen, sonst STOP und nachfragen.

- [ ] **Step 5: Commit**

```bash
git add stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py stack/tests/test_kahle_harness_phase0a.py
git commit -m "fix(harness): enforce supervisor and ranking safety in evidence"
```

---

### Task 7: Legacy-Direktantworten entfernen

**Files:**
- Modify: `kahle_knowledge_harness.py` → `HarnessDecision.direct_answer` und `_organization_contact_answer` löschen
- Modify: `middleware.py` → `_knowledge_harness_direct_answer` löschen, Aufrufblock im Zweig `if harness_mode == 'active':` löschen
- Modify: `stack/tests/test_kahle_knowledge_harness.py`, `stack/tests/test_middleware_internal_rag_routing.py`, `stack/tests/test_kahle_harness_reference_matrix.py`
- Test: `stack/tests/test_kahle_harness_phase0a.py`

- [ ] **Step 1: Write the failing tests**

An `stack/tests/test_kahle_harness_phase0a.py` anhängen:

```python
MIDDLEWARE = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "middleware.py"


def test_harness_decision_has_no_direct_answer_renderer():
    harness = load_harness()

    assert not hasattr(harness.HarnessDecision, "direct_answer")
    assert not hasattr(harness, "_organization_contact_answer")


def test_middleware_never_sets_final_content_from_the_knowledge_harness():
    source = MIDDLEWARE.read_text(encoding="utf-8")

    assert "_knowledge_harness_direct_answer" not in source
    active_block = source[
        source.index("if harness_mode == 'active':"):
        source.index(
            "if harness_mode != 'active' and pre_routed_internal_rag",
            source.index("if harness_mode == 'active':"),
        )
    ]
    assert "kahle_direct_final_content" not in active_block
```

- [ ] **Step 2: Run to verify they fail**

Run: `./.venv-verify/Scripts/python.exe -m pytest stack/tests/test_kahle_harness_phase0a.py -q -p no:cacheprovider`
Expected: 2 failed

- [ ] **Step 3: Remove the code**

1. `kahle_knowledge_harness.py`: Die Methode `def direct_answer(self) -> str:` samt Rumpf aus `HarnessDecision` löschen, ebenso die Funktion `def _organization_contact_answer(...)`.
2. `middleware.py`: Die Funktion `def _knowledge_harness_direct_answer(...)` samt Rumpf löschen, bis vor `def _knowledge_harness_tool_called`.
3. `middleware.py`: Im Zweig `if harness_mode == 'active':` diesen Block löschen:

```python
                            if routing_mode != 'model_led':
                                direct_answer = _knowledge_harness_direct_answer(
                                    harness_decision, harness_payload
                                )
                                if direct_answer:
                                    metadata['kahle_direct_final_content'] = direct_answer
```

- [ ] **Step 4: Bestandstests auf den Vertrag umstellen**

Run: die vier Bestandssuiten. Erwartet rot sind genau diese Tests; sie werden wie folgt geändert.

`stack/tests/test_kahle_knowledge_harness.py`:

| Test | Änderung |
| --- | --- |
| `test_personio_organization_contact_uses_only_structured_business_contacts` | `direct_answer`-Assertion ersetzen durch `assert decision.evidence_bundle.status == "supported"` |
| `test_mixed_organization_contact_keeps_documented_channel_and_current_people_separate` | `direct_answer`-Assertion ersetzen durch die Codeblöcke unter dieser Tabelle |
| `test_general_area_contact_accepts_a_cited_non_literal_contact_path` | letzte Assertion ersetzen durch `assert "Ticketsystem im Intranet" in decision.answer_prompt()` |
| `test_personio_organization_contact_requires_the_requested_contact_channel`, `test_rag_organization_contact_without_literal_contact_evidence_is_unsupported`, `test_rag_organization_contact_uses_only_an_exact_cited_contact_literal` | nur die `direct_answer`-Assertion löschen |
| `test_unsupported_decision_provides_one_stable_pre_answer_result` | umbenennen in `test_unsupported_decision_forbids_model_knowledge_in_contract`, Assertion ersetzen durch den Codeblock unter dieser Tabelle |

Assertion für `test_mixed_organization_contact_keeps_documented_channel_and_current_people_separate`:

```python
    assert decision.answer_contract.allowed_contact_values == (
        "person@example.invalid",
        "team@example.invalid",
    )
    prompt = decision.answer_prompt()
    assert "team@example.invalid" in prompt and "person@example.invalid" in prompt
```

Assertion für `test_unsupported_decision_forbids_model_knowledge_in_contract`:

```python
    assert decision.evidence_bundle.status == "unsupported"
    assert "Bei unsupported nutze kein allgemeines Modellwissen" in decision.answer_prompt()
```

`stack/tests/test_kahle_harness_reference_matrix.py`: die Assertion `assert lock.direct_answer().startswith(...)` ersetzen durch

```python
    prompt = lock.answer_prompt()
    assert prompt.startswith("KAHLE_KNOWLEDGE_CLARIFICATION")
    assert "Geht es um Werbewiderspruch" in prompt
```

`stack/tests/test_middleware_internal_rag_routing.py`:

| Test | Änderung |
| --- | --- |
| `test_pure_person_query_calls_personio_once_and_never_falls_back_to_rag` | die `direct_answer`-Zeilen ersetzen durch `assert decision.evidence_bundle.status == "unsupported"` |
| `test_supported_onboarding_directory_evidence_is_rendered_without_model_synthesis` | umbenennen in `test_supported_onboarding_directory_evidence_reaches_the_answer_contract`, `direct_answer`-Teil ersetzen durch den Codeblock unter dieser Tabelle |
| `test_supported_person_lookup_…` und `test_supported_person_contact_…` | nur die Zeilen mit `direct_answer` sowie `assert answer == ""` löschen |
| `test_general_leadership_ranking_is_fail_closed_even_with_directory_evidence` | `direct_answer`-Teil ersetzen durch `assert decision.evidence_bundle.status == "unsupported"` und `assert "Erika Beispiel" not in decision.answer_prompt()` |
| `test_named_supervisor_evidence_is_not_blocked_as_a_leadership_ranking` | `direct_answer`-Zeilen ersetzen durch `assert decision.evidence_bundle.status == "supported"`; die Assertion `"Max Leitung" in decision.answer_prompt()` bleibt |
| `test_supervisor_typo_blocks_rag_person_claim_as_defense_in_depth` | vollständig durch den Test in Task 6 ersetzt (`test_supervisor_typo_without_personio_evidence_has_no_person_claim`) → löschen |
| `test_model_led_preroute_supplies_evidence_but_never_owns_final_content` | durch `test_middleware_never_sets_final_content_from_the_knowledge_harness` ersetzt → löschen |

Ersatz für den `direct_answer`-Teil in `test_supported_onboarding_directory_evidence_reaches_the_answer_contract`:

```python
    assert decision.evidence_bundle.status == "supported"
    prompt = decision.answer_prompt()
    assert "Nora Neu" in prompt and "Erik Einstieg" in prompt
```

- [ ] **Step 5: Run tests**

Run: `./.venv-verify/Scripts/python.exe -m pytest stack/tests/test_kahle_harness_phase0a.py -q -p no:cacheprovider`
Expected: `36 passed`

Run: die vier Bestandssuiten
Expected: `633 passed` (635 minus zwei gelöschte Tests)

Run: `./.venv-verify/Scripts/python.exe -m pytest stack/tests -q -p no:cacheprovider`
Expected: alle PASS; kein anderer Test referenziert die gelöschten Funktionen.

- [ ] **Step 6: Commit**

```bash
git add stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py stack/open-webui-overrides/open_webui/utils/middleware.py stack/tests/test_kahle_harness_phase0a.py stack/tests/test_kahle_knowledge_harness.py stack/tests/test_middleware_internal_rag_routing.py stack/tests/test_kahle_harness_reference_matrix.py
git commit -m "refactor(harness): remove legacy direct answers in favour of the answer contract"
```

---

### Task 8: Validator-Schweregrade und Fehlalarme (K4)

**Files:**
- Modify: `kahle_knowledge_harness.py` → Konstante `BLOCKING_VIOLATION_CODES`, `validate_answer`
- Modify: `eval/harness/harness_eval.py` → `score_answer` liest `severity`
- Test: `stack/tests/test_kahle_harness_phase0a.py`, `eval/harness/tests/test_harness_eval.py`

- [ ] **Step 1: Write the failing tests**

An `stack/tests/test_kahle_harness_phase0a.py` anhängen:

```python
def _validation_decision():
    return {
        "evidence_bundle": {
            "status": "supported",
            "supported_claims": [{"text": "Die Rechnung liegt im Archiv.", "source_id": "#1"}],
            "sources": [{"number": 1}],
        },
        "answer_contract": {},
        "retrieval_plan": {"permission_scope": {"user_id": "u"}},
        "resolved_context": {"retrieval_query": "Wo liegt die Rechnung?"},
    }


@pytest.mark.parametrize(
    "answer",
    [
        "Die Rechnung liegt im Archiv [#1]. Eine Suche ist dort möglich.",
        "Die Rechnung liegt im Archiv [#1]. Ohne Freigabe darfst du sie nicht löschen.",
    ],
)
def test_ordinary_wording_is_not_flagged_as_an_approval(answer):
    result = load_harness().validate_answer(answer, _validation_decision())

    assert result.status == "accepted"
    assert result.violations == ()


@pytest.mark.parametrize(
    "answer, code",
    [
        ("Die Rechnung liegt im Archiv [#1]. Das ist technisch möglich.", "unsupported_technical_approval"),
        ("Die Rechnung liegt im Archiv [#1]. Eine Datenschutzprüfung ist nicht erforderlich.", "unsupported_privacy_approval"),
        ("Die Rechnung liegt im Archiv [#1]. Es bestehen keine datenschutzrechtlichen Bedenken.", "unsupported_privacy_approval"),
    ],
)
def test_heuristic_findings_are_advisory_and_do_not_require_retry(answer, code):
    result = load_harness().validate_answer(answer, _validation_decision())

    assert result.status == "accepted"
    assert [(item["code"], item["severity"]) for item in result.violations] == [(code, "advisory")]


def test_unknown_source_is_blocking_and_requires_retry():
    result = load_harness().validate_answer("Die Rechnung liegt im Archiv [#7].", _validation_decision())

    assert result.status == "retry_required"
    assert {"code": "unknown_source_id", "severity": "blocking"}.items() <= result.violations[0].items()
```

An `eval/harness/tests/test_harness_eval.py` anhängen:

```python
def test_score_answer_prefers_recorded_severity():
    message = {
        "content": "Antwort",
        "kahle_answer_validation": {"attempts": [{"status": "accepted", "violations": [
            {"code": "unsupported_privacy_approval", "severity": "advisory"},
            {"code": "future_code", "severity": "blocking"},
        ]}]},
    }

    assert score_answer(_case(), message)["blocking_violations"] == ["future_code"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `./.venv-verify/Scripts/python.exe -m pytest stack/tests/test_kahle_harness_phase0a.py eval/harness/tests -q -p no:cacheprovider` (die zwei Verzeichnisse getrennt aufrufen, da `eval/harness` eine eigene `conftest.py` hat)
Expected: FAIL für die Tests zu Fehlalarmen, `severity` und `score_answer_prefers_recorded_severity`

- [ ] **Step 3: Implement**

In `kahle_knowledge_harness.py` direkt nach `SCHEMA_VERSION = ...` einfügen:

```python
# Codes that prove a false statement or a missing proof. All other validator
# codes are heuristics and stay advisory.
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
```

In `validate_answer` die innere Funktion `add` ersetzen:

```python
    def add(code: str, message: str, **details: Any) -> None:
        violation = {
            "code": code,
            "severity": "blocking" if code in BLOCKING_VIOLATION_CODES else "advisory",
            "message": message,
        }
        violation.update(details)
        if violation not in violations:
            violations.append(violation)
```

Das Muster `technical_approval = re.search(...)` ersetzen:

```python
    technical_approval = re.search(
        r"\btechnisch\w*\s+(?:problemlos|machbar|umsetzbar|realisierbar|moglich)\b"
        r"|\b(?:problemlos|machbar|umsetzbar|realisierbar)\b",
        folded_text,
    )
```

`privacy_clearance_pattern` ersetzen:

```python
    privacy_clearance_pattern = (
        r"(?:\b(?:keine|ohne)\s+(?:weitere\s+)?(?:datenschutz(?:rechtliche)?\w*\s+)?"
        r"(?:prufung|freigabe|bedenken)\w*\s+(?:erforderlich|notwendig|notig|noetig)"
        r"|\bdatenschutz\w*\s+(?:ist\s+)?(?:nicht|kein\w*)\s+"
        r"(?:erforderlich|notwendig|problematisch|bedenklich)"
        r"|\bkeine\s+datenschutz\w*\s+bedenken)"
    )
```

Den Rückgabewert ersetzen:

```python
    return AnswerValidation(
        schema_version="kahle.answer-validation.v1",
        status=(
            "retry_required"
            if any(item["severity"] == "blocking" for item in violations)
            else "accepted"
        ),
        violations=tuple(violations),
    )
```

In `eval/harness/harness_eval.py` in `score_answer` die Code-Auswertung ersetzen:

```python
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
```

Im zurückgegebenen Dict `"blocking_violations": blocking,` setzen.

- [ ] **Step 4: Run tests and adjust existing expectations**

Run: `./.venv-verify/Scripts/python.exe -m pytest stack/tests/test_kahle_harness_phase0a.py -q -p no:cacheprovider`
Expected: `42 passed`

Run: `./.venv-verify/Scripts/python.exe -m pytest eval/harness/tests -q -p no:cacheprovider`
Expected: `39 passed`

Run: die vier Bestandssuiten. Bestandstests, die `retry_required` nur wegen eines Codes außerhalb von `BLOCKING_VIOLATION_CODES` erwarten, schlagen jetzt fehl. Für jeden davon genau diese Änderung:

- `status == "retry_required"` wird zu `status == "accepted"`.
- Der erwartete Verstoß bleibt und bekommt `"severity": "advisory"`.
- `retry_prompt()`-Assertions an diesen Ergebnissen bleiben unverändert gültig.

Tests, die einen Vergleich des ganzen Verstoß-Dicts erwarten, bekommen das Feld `severity` ergänzt. Jede andere Art von Fehlschlag: STOP und nachfragen.
Expected danach: `633 passed`

- [ ] **Step 5: Commit**

```bash
git add stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py stack/tests eval/harness/harness_eval.py eval/harness/tests/test_harness_eval.py
git commit -m "fix(harness): classify validator findings as blocking or advisory"
```

Vorher `git status --short stack/tests` prüfen: `test_kahle_toolcall_guard.py` und `test_kahle_workflow_orchestrator.py` (Nutzeränderungen) dürfen **nicht** mitgestagt werden. Stattdessen die geänderten Testdateien einzeln angeben.

---

### Task 9: Toter Code im Harness

**Files:**
- Modify: `kahle_knowledge_harness.py` → `_opt_out_location`

- [ ] **Step 1: Remove unreachable code**

In `_opt_out_location` alles nach dem `return next((name for name in _SUPPORTED_OPT_OUT_LOCATIONS ...), "")` löschen: die vier Zeilen ab `folded = _fold(query)` bis `return max(matches)[1] if matches else ""`.

- [ ] **Step 2: Run tests**

Run: die vier Bestandssuiten und `stack/tests/test_kahle_harness_phase0a.py`
Expected: `633 passed`, `42 passed`

- [ ] **Step 3: Commit**

```bash
git add stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py
git commit -m "refactor(harness): drop unreachable opt-out location fallback"
```

---

### Task 10: Messen, Full Verify, Abschluss

- [ ] **Step 1: Offline-Eval nach Phase 0a**

Run: `./.venv-verify/Scripts/python.exe eval/harness/offline_routing_eval.py --output eval/harness/results/2026-09-29-offline-phase0a.json`
Expected: mindestens `89/99`, procedural mindestens `89.5%` (17/19). Die verbleibenden Routingabweichungen sind nur Planer-Default-Fälle (`none_*`), Nominalphrasen, `supervisor_team_lead_beispiel`, `person_process_handover` und Folgefragen. Sie gehören ins modellgeführte Zielbild (Phase 3) und bekommen keine neuen Wortlisten.

- [ ] **Step 2: Full Verify** (Middleware ist High-Risk)

Run:
```powershell
.\scripts\run-local-tests.ps1 -Tier Full -Python .\.venv-verify\Scripts\python.exe -Npm npm.cmd
```
Expected: Exit-Code 0

- [ ] **Step 3: Commit**

```bash
git add eval/harness/results/2026-09-29-offline-phase0a.json
git commit -m "test(eval): record offline routing after harness phase 0a"
```

## Abnahme Phase 0a

- Alle neuen Verhaltenstests grün; Bestandssuiten grün (633 nach zwei ersetzten Tests); Full Verify Exit 0.
- Offline-Eval ≥ 89/99 und procedural ≥ 17/19, gegenüber 86/99 und 8/19 der korrigierten Baseline.
- Keine Stelle im Harness oder in der Middleware setzt noch eine feste Wissensantwort.
- Die Laufzeit-Eval-Messung folgt, sobald IONOS antwortet (Task 12 der Eval-Grundlage). Bis dahin ist die Laufzeitwirkung der entfernten Direktantworten ungemessen.

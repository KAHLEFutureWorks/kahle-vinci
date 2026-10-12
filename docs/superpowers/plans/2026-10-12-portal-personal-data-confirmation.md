# Portal: Kundendaten beim Hochladen erkennen und bestätigen lassen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein hochgeladenes Dokument mit personenbezogenen Kundendaten wird erst nach ausdrücklicher Bestätigung der hochladenden Person weiterbearbeitet; die Bestätigung erzwingt das Backend.

**Architecture:** Das neue Modul `personal_data.py` erkennt Kategorien (Fahrgestellnummer, Kennzeichen, Handynummer, private Telefonnummer, IBAN, Geburtsdatum, Postanschrift, E-Mail außerhalb KAHLE) und speichert nur Kategorien und Anzahlen, nie Werte. Ein starkes Merkmal oder zwei schwache führen in den bestehenden Schritt `pending_employee_decision`. `choose_action` verlangt dort für `create`, `replace` und `publish_existing` das Feld `personal_data_confirmed=true` und protokolliert die Bestätigung als Ereignis. Das Portal zeigt die Kategorien und eine Bestätigungs-Checkbox.

**Tech Stack:** Python 3.11, FastAPI, SQLite (kb-admin-api), React/TypeScript (admin-dashboard), pytest.

Anlass: Am 09.10. wurde eine ausgefüllte Termin-Checkliste mit Kundendaten ohne Rückfrage aufgenommen und indexiert. Nutzerentscheidung 12.10.: Kundendaten sind im Portal erlaubt, aber nur nach ausdrücklicher Freigabe beim Hochladen.

Hochrisikobereich (Secure Ingest, Portal-Lifecycle): Full Verify ist Pflicht; Testdaten sind ausschließlich synthetisch.

---

## Messung vor der Umsetzung (12.10., lokaler Bestand)

| Regel | aktive Dokumente mit Bestätigungspflicht | bekanntes Kundendaten-Formular |
| --- | --- | --- |
| jede Kategorie | 9 von 26 (Firmenanschriften, Hersteller-E-Mails) | erkannt |
| **ein starkes Merkmal oder zwei schwache** | **0 von 26** | erkannt (6 Kategorien) |

Starke Merkmale: `vin`, `licence_plate`, `mobile_phone`, `private_phone`, `iban`, `birth_date`. Schwache Merkmale: `postal_address`, `external_email`.

## Dateien

| Datei | Änderung |
| --- | --- |
| `stack/kb-admin-api/app/personal_data.py` | neu: Erkennung |
| `stack/kb-admin-api/tests/test_personal_data.py` | neu |
| `stack/kb-admin-api/app/document_lifecycle.py` | `Analysis.personal_data_categories`, Routing, Bestätigung in `choose_action` |
| `stack/kb-admin-api/app/main.py` | Upload ruft die Erkennung auf; Antwort und Aufgabenliste melden Kategorien; `PortalCaseActionRequest.personal_data_confirmed` |
| `stack/kb-admin-api/tests/test_document_lifecycle.py` | Routing- und Bestätigungstests |
| `stack/kb-admin-api/tests/test_portal_api.py` | API-Test Upload bis Bestätigung |
| `admin-dashboard/components/KnowledgePortal.tsx` | Hinweis und Checkbox im Upload-Ergebnis und in „Meine Aufgaben“ |
| `SECURITY.md`, `DECISIONS.md` | Regel dokumentieren |

---

### Task 1: Erkennung von Kundendaten

**Files:**
- Create: `stack/kb-admin-api/app/personal_data.py`
- Test: `stack/kb-admin-api/tests/test_personal_data.py`

- [ ] **Step 1: Write the failing test**

```python
"""Personal customer data is detected by category; values are never returned."""

import pytest

from app.personal_data import detect

FORM = (
    "Kunden-Nr.: 100001\n"
    "Name: Muster, Max\n"
    "Anschrift: Beispielweg 12, 30159 Hannover\n"
    "Telefon privat: 0511 1234567\n"
    "Telefon mobil: 0171 2345678\n"
    "E-Mail Privat: max.muster@example.org\n"
    "Kennzeichen: H AB 1234\n"
    "Fahrg.-Nr.: WVWZZZ1KZAW000001\n"
)


def test_customer_form_requires_confirmation_and_reports_only_categories():
    result = detect(FORM)

    assert result.requires_confirmation is True
    assert set(result.categories) == {
        "postal_address", "private_phone", "mobile_phone", "external_email", "licence_plate", "vin",
    }
    assert "Muster" not in repr(result) and "0171" not in repr(result)


@pytest.mark.parametrize("text", [
    "Autohaus KAHLE, Kabelkamp 1, 30179 Hannover",
    "Support des Herstellers: support@hersteller.example",
    "Bei Fragen: datenschutz@kahle.de oder https://ticket.kahle.de/login.php",
    "Rufnummer Zentrale: 0511 27999-0",
])
def test_business_contacts_alone_need_no_confirmation(text):
    assert detect(text).requires_confirmation is False


def test_two_weak_signals_together_need_confirmation():
    text = "Kunde wohnt Beispielweg 12, 30159 Hannover, E-Mail max@example.org"

    assert detect(text).requires_confirmation is True


@pytest.mark.parametrize(("text", "category"), [
    ("IBAN DE89 3704 0044 0532 0130 00", "iban"),
    ("geb. 01.02.1980", "birth_date"),
    ("Kennzeichen HAN-XY 123", "licence_plate"),
    ("Mobil +49 171 2345678", "mobile_phone"),
])
def test_each_strong_signal_alone_needs_confirmation(text, category):
    result = detect(text)

    assert result.requires_confirmation is True
    assert category in result.categories
```

- [ ] **Step 2: Run test to verify it fails**

Run (aus `stack/kb-admin-api`): `..\..\.venv-verify\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_personal_data.py`
Expected: FAIL mit `ModuleNotFoundError: No module named 'app.personal_data'`

- [ ] **Step 3: Write minimal implementation**

`stack/kb-admin-api/app/personal_data.py`:

```python
"""Detect personal customer data in an uploaded document by category.

Only categories and counts leave this module, never the matched values.
One strong signal or two different weak signals require an explicit
confirmation by the uploader (user decision 2026-10-12).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PATTERNS = {
    "external_email": re.compile(r"\b[\w.+-]+@(?![\w.-]*kahle\.)[\w-]+(?:\.[\w-]+)+\b", re.I),
    "mobile_phone": re.compile(r"(?<!\d)(?:\+49[\s/-]?|0)1[5-7]\d[\s/-]?\d{3,4}[\s/-]?\d{3,5}(?!\d)"),
    "private_phone": re.compile(r"(?i)\b(?:telefon|tel\.?)\s*privat\b[^\n]{0,20}\d{4,}"),
    "postal_address": re.compile(
        r"(?i)\b[\wäöüß.-]+(?:stra(?:ss|ß)e|str\.|weg|allee|platz|ring|damm|gasse)\s+\d+\s*[a-z]?\b"
        r"[,\s]+\d{5}\s+[A-ZÄÖÜ][a-zäöüß]+"
    ),
    "vin": re.compile(
        r"\b(?=[A-HJ-NPR-Z0-9]{17}\b)(?=[A-HJ-NPR-Z0-9]*\d)(?=[A-HJ-NPR-Z0-9]*[A-HJ-NPR-Z])"
        r"[A-HJ-NPR-Z0-9]{17}\b"
    ),
    "licence_plate": re.compile(r"\b[A-ZÄÖÜ]{1,3}[\s-][A-Z]{1,2}[\s-]?\d{1,4}[EH]?\b"),
    "iban": re.compile(r"\bDE\d{2}(?:\s?\d{4}){4}\s?\d{2}\b"),
    "birth_date": re.compile(r"(?i)\bgeb(?:\.|oren|urtsdatum)\s*(?:am\s*)?:?\s*\d{1,2}\.\d{1,2}\.\d{2,4}"),
}
STRONG_CATEGORIES = frozenset({"vin", "licence_plate", "mobile_phone", "private_phone", "iban", "birth_date"})


@dataclass(frozen=True)
class PersonalDataFindings:
    categories: dict[str, int]
    requires_confirmation: bool


def detect(markdown: str) -> PersonalDataFindings:
    text = str(markdown or "")
    categories = {
        name: len(pattern.findall(text))
        for name, pattern in _PATTERNS.items()
        if pattern.search(text)
    }
    requires = bool(STRONG_CATEGORIES & set(categories)) or len(categories) >= 2
    return PersonalDataFindings(categories=categories, requires_confirmation=requires)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\..\.venv-verify\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_personal_data.py`
Expected: PASS. Schlägt der Zentrale-Rufnummern-Fall an, ist das Muster `mobile_phone` zu weit und wird auf `01[5-7]` nach Vorwahlbeginn begrenzt.

- [ ] **Step 5: Commit**

```bash
git add stack/kb-admin-api/app/personal_data.py stack/kb-admin-api/tests/test_personal_data.py
git commit -m "feat(portal): detect personal customer data by category"
```

### Task 2: Routing und erzwungene Bestätigung im Lifecycle

**Files:**
- Modify: `stack/kb-admin-api/app/document_lifecycle.py` (`Analysis`, `record_analysis`, `choose_action`)
- Test: `stack/kb-admin-api/tests/test_document_lifecycle.py`

- [ ] **Step 1: Write the failing test**

An `tests/test_document_lifecycle.py` anfügen (nutzt das vorhandene `setup()` dieser Datei; dessen Rückgabewerte vorher mit `grep -n "def setup" -A30 tests/test_document_lifecycle.py` prüfen und die Namen unten anpassen, falls sie abweichen):

```python
def test_personal_data_waits_for_the_uploaders_explicit_confirmation():
    lifecycle, kb, uploader = setup()
    case = lifecycle.submit(
        uploaded_by_user_id=uploader, owner_user_id=uploader,
        target_knowledgebase_id=kb, title="Formular", original_filename="f.md",
        original_file_id="f", original_sha256="7" * 64, valid_workdays=30, confidentiality="internal",
    )

    case = lifecycle.record_analysis(
        case_id=case.case_id, normalized_sha256="n", markdown_sha256="m",
        analysis=Analysis(personal_data_categories=("vin", "licence_plate")),
    )
    assert case.status == "pending_employee_decision"

    with pytest.raises(LifecycleError, match="personal_data_confirmation_required"):
        lifecycle.choose_action(case_id=case.case_id, actor_user_id=uploader, action="create")

    case = lifecycle.choose_action(
        case_id=case.case_id, actor_user_id=uploader, action="create", personal_data_confirmed=True,
    )
    assert case.status in {"pending_manager_approval", "pending_admin_approval"}


def test_discard_needs_no_personal_data_confirmation():
    lifecycle, kb, uploader = setup()
    case = lifecycle.submit(
        uploaded_by_user_id=uploader, owner_user_id=uploader,
        target_knowledgebase_id=kb, title="Formular", original_filename="f.md",
        original_file_id="f", original_sha256="6" * 64, valid_workdays=30, confidentiality="internal",
    )
    case = lifecycle.record_analysis(
        case_id=case.case_id, normalized_sha256="n", markdown_sha256="m",
        analysis=Analysis(personal_data_categories=("iban",)),
    )

    assert lifecycle.choose_action(case_id=case.case_id, actor_user_id=uploader, action="discard").status == "withdrawn"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\..\.venv-verify\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_document_lifecycle.py -k personal_data`
Expected: FAIL mit `TypeError: Analysis.__init__() got an unexpected keyword argument 'personal_data_categories'`

- [ ] **Step 3: Write minimal implementation**

In `Analysis` nach `restricted_terms` ergänzen:

```python
    personal_data_categories: tuple[str, ...] = ()
```

In `record_analysis`:
- im Tupel für `clean` den Eintrag `analysis.personal_data_categories,` nach `analysis.restricted_terms,` ergänzen;
- `needs_uploader_action` um `or analysis.personal_data_categories` erweitern;
- im `payload`-Dictionary ergänzen: `"personal_data_categories": list(analysis.personal_data_categories),`.

`choose_action` erhält den Parameter `personal_data_confirmed: bool = False` und prüft nach der Aktionsvalidierung:

```python
        if action != "discard":
            with self.store.connect() as db:
                row = db.execute("SELECT analysis_json FROM document_cases WHERE case_id=?", (case_id,)).fetchone()
            categories = (json.loads(row["analysis_json"] or "{}") if row else {}).get("personal_data_categories") or []
            if categories and not personal_data_confirmed:
                raise LifecycleError("personal_data_confirmation_required")
```

und protokolliert im bestehenden `with self.store.connect() as db:`-Block vor `action_chosen`:

```python
            if personal_data_confirmed:
                self._event(db, case_id, actor_user_id, "personal_data_confirmed", {"action": action})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `..\..\.venv-verify\Scripts\python.exe -m pytest -q -p no:cacheprovider tests`
Expected: alle Tests PASS

- [ ] **Step 5: Commit**

```bash
git add stack/kb-admin-api/app/document_lifecycle.py stack/kb-admin-api/tests/test_document_lifecycle.py
git commit -m "feat(portal): personal data waits for the uploader's explicit confirmation"
```

### Task 3: Upload-API, Aufgabenliste und Aktions-Endpunkt

**Files:**
- Modify: `stack/kb-admin-api/app/main.py` (Upload ca. Zeile 1526, `PortalUploadResponse`, Aufgabenliste ca. Zeile 2360, `PortalCaseActionRequest`, `portal_case_action`)
- Test: `stack/kb-admin-api/tests/test_portal_api.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_portal_api.py` einen Test nach dem Muster der vorhandenen Upload-Tests anlegen (vorher `grep -n "def test_.*upload" tests/test_portal_api.py` und den Helfer für Uploads übernehmen). Er lädt eine Markdown-Datei mit dem synthetischen `FORM` aus Task 1 hoch und prüft:

```python
    assert response.json()["status"] == "pending_employee_decision"
    assert set(response.json()["personal_data_categories"]) >= {"vin", "licence_plate"}
    case_id = response.json()["case_id"]
    denied = client.post(f"/portal/cases/{case_id}/action", json={"action": "create"})
    assert denied.status_code == 409 and denied.json()["detail"] == "personal_data_confirmation_required"
    accepted = client.post(f"/portal/cases/{case_id}/action", json={"action": "create", "personal_data_confirmed": True})
    assert accepted.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL mit `KeyError: 'personal_data_categories'`

- [ ] **Step 3: Write minimal implementation**

- Import neben den anderen App-Imports (beide Varianten, wie bei `restricted_terms`): `from .personal_data import detect as detect_personal_data` bzw. `from personal_data import detect as detect_personal_data`.
- Nach `restricted_terms = RESTRICTED_TERMS.matches(markdown)`:

```python
        personal_data = detect_personal_data(markdown)
```

- In `Analysis(...)` ergänzen: `personal_data_categories=tuple(personal_data.categories) if personal_data.requires_confirmation else (),`
- `PortalUploadResponse`: Feld `personal_data_categories: list[str] = Field(default_factory=list)` und in der Rückgabe `personal_data_categories=list(personal_data.categories) if personal_data.requires_confirmation else [],`
- In der Aufgabenliste neben `item["restricted_terms"] = …`: `item["personal_data_categories"] = analysis.get("personal_data_categories", [])`
- `PortalCaseActionRequest`: Feld `personal_data_confirmed: bool = False`; in `portal_case_action` an `DOCUMENT_LIFECYCLE.choose_action(...)` übergeben: `personal_data_confirmed=payload.personal_data_confirmed`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `..\..\.venv-verify\Scripts\python.exe -m pytest -q -p no:cacheprovider tests`
Expected: alle Tests PASS

- [ ] **Step 5: Commit**

```bash
git add stack/kb-admin-api/app/main.py stack/kb-admin-api/tests/test_portal_api.py
git commit -m "feat(portal): report personal data and require confirmation via the API"
```

### Task 4: Hinweis und Bestätigung im Portal

**Files:**
- Modify: `admin-dashboard/components/KnowledgePortal.tsx` (Upload-Ergebnis ca. Zeile 2036, Funktion `action` ca. Zeile 1625, „Meine Aufgaben“ ca. Zeile 2575, `chooseAction` ca. Zeile 2101)

- [ ] **Step 1: Kategorien-Beschriftungen ergänzen** (neben den bestehenden Textkonstanten):

```tsx
const personalDataLabels: Record<string, string> = {
  vin: "Fahrgestellnummer",
  licence_plate: "Kennzeichen",
  mobile_phone: "Mobilnummer",
  private_phone: "private Telefonnummer",
  iban: "IBAN",
  birth_date: "Geburtsdatum",
  postal_address: "Postanschrift",
  external_email: "E-Mail-Adresse außerhalb KAHLE",
};
```

- [ ] **Step 2: Upload-Ergebnis:** einen State `const [personalDataConfirmed, setPersonalDataConfirmed] = useState(false);` anlegen; ist `result.personal_data_categories?.length`, vor den Aktionsknöpfen anzeigen:

```tsx
<div className="wp-quality warn" role="alert">
  <AlertTriangle />
  <div>
    <strong>Kundendaten erkannt</strong>
    <span>
      Das Dokument enthält: {result.personal_data_categories.map((c) => personalDataLabels[c] || c).join(", ")}.
      Es wird erst nach deiner ausdrücklichen Bestätigung weiterbearbeitet.
    </span>
    <label>
      <input type="checkbox" checked={personalDataConfirmed}
        onChange={(e) => setPersonalDataConfirmed(e.target.checked)} />
      Ich bestätige, dass diese Kundendaten in das Wissensportal hochgeladen werden dürfen.
    </label>
  </div>
</div>
```

Die Knöpfe „Als neues Dokument vorschlagen“, „Vorhandenes zusätzlich veröffentlichen“ und „Als neue Version … vorschlagen“ erhalten `disabled={Boolean(result.personal_data_categories?.length) && !personalDataConfirmed}`. In `action()` den Body um `personal_data_confirmed: personalDataConfirmed` ergänzen und den State nach Abschluss zurücksetzen.

- [ ] **Step 3: „Meine Aufgaben“:** denselben Hinweis je Aufgabe anzeigen, wenn `task.personal_data_categories?.length`; die Bestätigung als State je `case_id` (`Record<string, boolean>`) führen und in `chooseAction` als `personal_data_confirmed` mitsenden.

- [ ] **Step 4: Build und Smoke-Test**

Run (aus `admin-dashboard`): `npm.cmd test`
Expected: Build erfolgreich, `rendered-html.test.mjs` PASS

- [ ] **Step 5: Commit**

```bash
git add admin-dashboard/components/KnowledgePortal.tsx
git commit -m "feat(portal): show detected customer data and ask for confirmation"
```

### Task 5: Dokumentation, Verify, Ausrollen lokal

- [ ] **Step 1:** In `SECURITY.md` (Abschnitt Secure Ingest) und als Implication in `DECISIONS.md` (ADR zum Portal-Ingest) ergänzen: „Erkannte Kundendaten (starkes Merkmal oder zwei schwache) führen zu `pending_employee_decision`; weiter geht es nur mit `personal_data_confirmed`. Gespeichert werden nur Kategorien, keine Werte (Nutzerentscheidung 2026-10-12).“
- [ ] **Step 2:** Full Verify: `.\scripts\run-local-tests.ps1 -Tier Full -Python .\.venv-verify\Scripts\python.exe -Npm npm.cmd`, Erwartung `EXIT=0`
- [ ] **Step 3:** Images neu bauen: `.\scripts\start-stack.ps1 -ComposeArgs kb-admin-api,kb-maintenance,kb-upload-worker,kb-admin-dashboard`
- [ ] **Step 4:** Messung am Bestand wiederholen: Bestätigungspflicht 0 von 26 aktiven Dokumenten erwartet.
- [ ] **Step 5:** UI-Prüfung durch den Nutzer: eine synthetische Kundendaten-Datei hochladen, Hinweis und gesperrte Knöpfe sehen, bestätigen, Freigabeweg läuft weiter.
- [ ] **Step 6:** Commit und Push.

## Nicht Teil dieses Plans

- Eine Datenschutz-Sofortlöschung vor Ablauf der 30 Tage (Nutzerentscheidung 12.10.: Frist abwarten).
- Bestehende Dokumente nachträglich prüfen; die Messung zeigt 0 Treffer im aktiven Bestand.

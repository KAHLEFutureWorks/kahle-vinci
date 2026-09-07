# Supervisor Consensus and Request Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** KAHLE-Vinci beantwortet direkte und bereichsbezogene Führungskraftfragen aus expliziter Personio-Evidenz, löst verkürzte Folgefragen strukturiert auf und verwendet Systemprompts ohne konkurrierende Fachantworten.

**Architecture:** Der Personio-Dienst berechnet den 90-Prozent-Konsens innerhalb seiner bestehenden read-only Suchgrenze und liefert ausschließlich evidenzsichere Aggregatfelder. Der bestehende `ResolvedContext` im Knowledge Harness wird zur strukturierten Anfrageauflösung vertieft; die Middleware verwendet dessen Retrieval-Anfrage anstelle wachsender Sonderfallumschreibungen. Beide Core-Prompts beschreiben nur noch Quellenhoheit, Evidenzvertrag und Ausgabegrenzen.

**Tech Stack:** Python 3.11, dataclasses, FastAPI/Pydantic, pytest, Open-WebUI-Override, Markdown-Systemprompts, PowerShell Verification Runner

**Spec:** `docs/superpowers/specs/2026-09-04-supervisor-consensus-and-request-resolution-design.md`

## Global Constraints

- Personio ist die einzige Quelle für aktuelle Personen, organisatorische Zuordnungen und Führungskräfte.
- Supervisoren werden nur aus expliziten, eindeutig auflösbaren Personio-IDs abgeleitet.
- Der Bereichskonsens gilt bei exakt 90 Prozent oder mehr aller gefundenen aktiven Beschäftigten; fehlende und unauflösbare Zuordnungen bleiben im Nenner.
- Die Regel gilt ab einer gefundenen Person; eine Ein-Personen-Gruppe wird in der Evidenz gekennzeichnet.
- `original_query` bleibt unverändert; nur `resolved_query` wird für Routing und Retrieval verwendet.
- Der Resolver erzeugt weder Antworten noch neue Fakten und verwendet kein zusätzliches Modell.
- Fachliche Kontakte und feste Weiterleitungen stehen nicht im Systemprompt.
- Keine realen Personendaten in Tests, Logs, Plänen oder technischen Ausgaben.
- Bestehende Änderungen im Worktree bleiben erhalten. Commits und Pushes erfolgen nur nach gesonderter Freigabe.

---

### Task 1: Personio-Supervisor-Konsens testgetrieben implementieren

**Files:**
- Modify: `stack/personio-directory/tests/test_search.py`
- Modify: `stack/personio-directory/app/search.py`

**Interfaces:**
- Consumes: `DirectorySearch._directory_candidates(text, people)` und `PersonRecord.supervisor_personio_id`
- Produces: `DirectorySearch._supervisor_consensus(candidate_query, people) -> tuple[tuple[PersonRecord, ...], dict[str, object]]`
- Produces: Supervisor-Claims mit optionalen Feldern `supervisor_scope`, `candidate_count`, `support_count`, `support_ratio`, `single_candidate_basis`

- [ ] **Step 1: Failing tests für Schwelle und Nenner schreiben**

Ergänze synthetische Testdaten für diese getrennten Fälle:

```python
def test_department_supervisor_accepts_exactly_ninety_percent_consensus():
    # 9 von 10 ACTIVE-Kandidaten referenzieren dieselbe auflösbare Supervisor-ID.
    # Erwartung: ok, eine Führungskraft, candidate_count=10, support_count=9,
    # support_ratio=0.9.

def test_department_supervisor_rejects_eight_of_nine_consensus():
    # 8 / 9 < 0.9.
    # Erwartung: not_found und keine Claims.

def test_missing_supervisor_counts_against_department_consensus():
    # Neun gleiche IDs plus eine fehlende ID ergeben exakt 90 Prozent.
    # Erwartung: gültiger Claim.

def test_unresolvable_supervisor_counts_against_department_consensus():
    # Eine unbekannte ID bleibt im Nenner und darf nicht selbst ausgegeben werden.

def test_department_supervisor_ignores_non_active_candidates():
    # LEAVE und ONBOARDING verändern den Bereichsnenner nicht.

def test_single_person_department_marks_its_evidence_basis():
    # Erwartung: single_candidate_basis=True und support_ratio=1.0.
```

- [ ] **Step 2: RED nachweisen**

Run:

```powershell
& .\.venv-verify\Scripts\python.exe -m pytest stack\personio-directory\tests\test_search.py -q -p no:cacheprovider
```

Expected: Die neuen Konsens- und Metadatenassertionen schlagen fehl, weil die aktuelle Implementierung nur genau eine unterschiedliche Supervisor-ID akzeptiert und keine Aggregatfelder erzeugt.

- [ ] **Step 3: Minimale Konsensfunktion implementieren**

Implementiere in `DirectorySearch` eine fokussierte Funktion nach diesem Vertrag:

```python
def _supervisor_consensus(
    self, candidate_query: str, people: Iterable[PersonRecord]
) -> tuple[tuple[PersonRecord, ...], dict[str, object]]:
    active_people = tuple(
        person for person in people if person.employment_status == "ACTIVE"
    )
    candidates = self._directory_candidates(candidate_query, active_people)
    # Häufigkeiten nur für vorhandene IDs zählen, alle candidates bleiben Nenner.
    # Dominante ID muss zu genau einer Person aus active_people auflösbar sein.
    # support_count * 10 >= len(candidates) * 9 vermeidet Rundungsfehler.
```

Der benannte Personenpfad `_supervisor_for_named_person()` bleibt unverändert fail-closed. Ersetze nur den Bereichspfad in `_supervisors_from_candidate_query()` durch die neue Konsensauswertung.

- [ ] **Step 4: Aggregatmetadaten evidenzsicher anreichern**

Erweitere `_evidence()` um ein optionales `claim_metadata: dict[str, object] | None`. Kopiere ausschließlich die freigegebenen Aggregatwerte in den einzelnen Supervisor-Claim. Gib keine Kandidatennamen und keine Personio-IDs aus.

- [ ] **Step 5: GREEN und Regressionen nachweisen**

Run:

```powershell
& .\.venv-verify\Scripts\python.exe -m pytest stack\personio-directory\tests\test_search.py -q -p no:cacheprovider
```

Expected: Alle bisherigen direkten Supervisor- und neuen Konsenstests bestehen.

- [ ] **Step 6: Review checkpoint**

Prüfe, dass ausschließlich `ACTIVE` in die Bereichsquote eingeht, die direkte Personenfrage weiterhin exakt auflöst und kein neuer Logpfad Rohdaten ausgibt. Kein Commit ohne ausdrückliche Freigabe.

---

### Task 2: Personio-API- und Harness-Vertrag für Konsensevidenz absichern

**Files:**
- Modify: `stack/personio-directory/tests/test_api.py`
- Modify: `stack/tests/test_kahle_knowledge_harness.py`
- Modify only if required by the failing contract: `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py`

**Interfaces:**
- Consumes: bestehende `SearchResponse.claims`
- Produces: unveränderte API-Struktur mit erlaubten Supervisor-Aggregatfeldern
- Produces: `_personio_evidence()` erhält diese Felder ohne IDs oder Kandidatenlisten

- [ ] **Step 1: Failing API-Vertragstest ergänzen**

Erzeuge eine synthetische `DirectoryEvidence` mit einem Supervisor-Claim und prüfe:

```python
assert response.status_code == 200
claim = response.json()["claims"][0]
assert claim["candidate_count"] == 10
assert claim["support_count"] == 9
assert claim["support_ratio"] == 0.9
assert "supervisor_personio_id" not in repr(response.json())
assert "candidate_names" not in repr(response.json())
```

- [ ] **Step 2: Failing Harness-Vertragstest ergänzen**

Prüfe mit synthetischen Namen, dass `_personio_evidence()` die Aggregatfelder im belegten Claim erhält und die Quelle `P1` bindet. Ein `not_found`-Ergebnis darf keinen Supervisor-Claim erzeugen.

- [ ] **Step 3: RED nachweisen**

Run:

```powershell
& .\.venv-verify\Scripts\python.exe -m pytest stack\personio-directory\tests\test_api.py -q -p no:cacheprovider
& .\.venv-verify\Scripts\python.exe -m pytest stack\tests\test_kahle_knowledge_harness.py -q -p no:cacheprovider
```

Expected: Mindestens der neue Aggregatvertrag schlägt vor der Implementierung aus Task 1 fehl.

- [ ] **Step 4: Minimalen Vertrag anpassen**

Behalte die bestehende offene Claim-Struktur, sofern sie die neuen Felder bereits sicher durchreicht. Ändere Produktionscode nur, wenn der RED-Test eine tatsächliche Filterung oder Validierungslücke belegt. Füge keine zweite Supervisor-Auswertung im Harness hinzu.

- [ ] **Step 5: GREEN nachweisen**

Run beide Befehle aus Step 3 erneut. Expected: PASS.

- [ ] **Step 6: Review checkpoint**

Prüfe API-Ausgabe und Harness-Payload auf interne IDs, Kandidatenlisten und reale Daten. Kein Commit ohne ausdrückliche Freigabe.

---

### Task 3: Core-Systemprompts an den Harness-Vertrag anpassen

**Files:**
- Modify: `stack/tests/test_vinci_starter_prompt_contracts.py`
- Modify: `stack/open-webui-prompts/kahle-vinci-systemprompt.md`
- Modify: `stack/open-webui-prompts/kahle-vinci-thinking-systemprompt.md`

**Interfaces:**
- Consumes: `EvidenceBundle`, `AnswerContract` und Harness-Quellenplan
- Produces: identischer Wissens- und Quellenvertrag für Standard, Thinking und Max Thinking

- [ ] **Step 1: Failing Prompt-Vertragstests schreiben**

Ersetze die bisherige positive Assertion für `datenschutz@kahle.de` durch negative und positive Vertragsprüfungen:

```python
assert "datenschutz@kahle.de" not in prompt
assert "PFLICHT-WEITERLEITUNGEN" not in prompt
assert "ausschließlich aus" in prompt.lower()
assert "EvidenceBundle" in prompt
assert "Personio" in prompt
assert "RAG" in prompt
assert "keine Kontakte" in prompt
```

Prüfe zusätzlich, dass der Prompt den Harness für Anfrageauflösung,
Quellenplanung und Evidenzbereitstellung verantwortlich macht und keine
allgemeine Kundensperre mit einer festen Fachantwort verknüpft.

- [ ] **Step 2: RED nachweisen**

Run:

```powershell
& .\.venv-verify\Scripts\python.exe -m pytest stack\tests\test_vinci_starter_prompt_contracts.py -q -p no:cacheprovider
```

Expected: FAIL wegen vorhandener E-Mail-Adresse und Pflicht-Weiterleitungen.

- [ ] **Step 3: Standardprompt bereinigen**

Entferne die doppelten statischen Sperr- und Datenschutzregeln. Formuliere den internen Wissensvertrag kompakt:

```text
Der KAHLE Knowledge Harness löst Kontext auf, plant interne Quellen und stellt
das EvidenceBundle bereit. Antworte ausschließlich aus diesem EvidenceBundle.
Personio belegt aktuelle Personen und Führungskräfte. RAG belegt dokumentierte
Prozesse, Zuständigkeiten und Funktionskontakte. Ergänze keine Kontakte,
Personen, Zuständigkeiten oder Arbeitsschritte außerhalb der Evidenz.
```

Belasse Datei-, Sicherheits-, Kalender-, Aufgaben- und Webregeln unverändert, soweit sie nicht mit diesem Vertrag kollidieren.

- [ ] **Step 4: Thinking-Prompt gleichwertig bereinigen**

Übernehme denselben fachlichen Vertrag. Erlaube nur ausführlichere Struktur und Analyse, keine zusätzliche Evidenz oder andere Kontaktwege.

- [ ] **Step 5: GREEN nachweisen**

Run Step 2 erneut. Expected: PASS.

- [ ] **Step 6: Registrierungszuordnung statisch prüfen**

Run:

```powershell
rg -n 'vinci-2-clone-clone-clone|kahle-vinci-thinking|kahle-vinci-max-thinking' scripts/openwebui/register-kahle-workflow-tool.py
```

Expected: Standardmodell nutzt den Standardprompt; Thinking und Max Thinking nutzen denselben bereinigten Thinking-Prompt.

- [ ] **Step 7: Review checkpoint**

Prüfe, dass keine fachliche E-Mail-Adresse oder pauschale Weiterleitung in beiden Core-Prompts verblieben ist. Kein Commit ohne ausdrückliche Freigabe.

---

### Task 4: Strukturierte Anfrageauflösung testgetrieben in den Harness integrieren

**Files:**
- Modify: `stack/tests/test_kahle_knowledge_harness.py`
- Modify: `stack/tests/test_middleware_internal_rag_routing.py`
- Modify: `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py`
- Modify: `stack/open-webui-overrides/open_webui/utils/middleware.py`

**Interfaces:**
- Extends: `ResolvedContext`
- Produces: `resolve_request(query: str, messages: list[dict[str, Any]]) -> ResolvedContext`
- Consumes: `ResolvedContext.retrieval_query` in `plan_retrieval()` and Middleware-Retrieval

- [ ] **Step 1: Failing Harness-Tests für den strukturierten Vertrag schreiben**

Erweitere `ResolvedContext` in den Tests um den gewünschten Vertrag und prüfe getrennt:

```python
resolved = resolve_request(
    "Und wie geht es dann, wenn ich in Hannover bin?",
    messages_with_prior_vaudis_advertising_process,
)
assert resolved.original_query == "Und wie geht es dann, wenn ich in Hannover bin?"
assert "Werbewiderspruch" in resolved.retrieval_query
assert "Vaudis" in resolved.retrieval_query
assert "Hannover" in resolved.retrieval_query
assert resolved.entities["locations"] == ("Hannover",)
assert resolved.conversation_reference is True
assert resolved.required_clarification is False
```

Weitere Tests:

- eine eigenständige Frage bleibt semantisch unverändert;
- ein neuer Standort ersetzt den alten Standort;
- ein neuer Personenname übernimmt niemals den vorherigen Namen;
- ein Supervisor-Pronomen darf die unmittelbar vorherige eindeutige Person referenzieren;
- zwei plausible Prozessbezüge setzen `required_clarification=True` und eine kurze Rückfrage;
- fachfremder älterer Kontext wird nicht übernommen.

- [ ] **Step 2: RED nachweisen**

Run:

```powershell
& .\.venv-verify\Scripts\python.exe -m pytest stack\tests\test_kahle_knowledge_harness.py -q -p no:cacheprovider
```

Expected: FAIL, weil `resolve_request()` und die erweiterten Kontextfelder noch fehlen.

- [ ] **Step 3: `ResolvedContext` fokussiert erweitern**

Ergänze rückwärtskompatible Standardwerte:

```python
@dataclass(frozen=True)
class ResolvedContext:
    original_query: str
    retrieval_query: str
    aliases: dict[str, str] = field(default_factory=dict)
    conversation_reference: bool = False
    intent: str = ""
    information_needs: tuple[str, ...] = ()
    entities: dict[str, tuple[str, ...]] = field(default_factory=dict)
    context_references: tuple[str, ...] = ()
    ambiguities: tuple[str, ...] = ()
    required_clarification: bool = False
    clarification_question: str = ""
```

- [ ] **Step 4: Deterministischen Resolver implementieren**

Baue auf `_fold()`, `resolve_query_aliases()`, vorhandener Intent-Erkennung und dem unmittelbar vorherigen Nutzer- und Assistant-Turn auf. Zerlege die Logik in kleine private Helfer für letzten relevanten Turn, explizite Entitäten, Referenzmarker und eigenständige Retrieval-Anfrage. Übernimm nur kontrollierte Entitäten, die wörtlich oder über bestehende kanonische Aliase belegt sind.

- [ ] **Step 5: Entscheidungserzeugung auf `resolve_request()` umstellen**

`build_decision()` und `build_result_driven_decision()` sollen denselben aufgelösten Kontext verwenden. `plan_retrieval()` erhält ausschließlich `resolved.retrieval_query`. Das EvidenceBundle bleibt die einzige Fachfaktenquelle.

- [ ] **Step 6: GREEN im Harness nachweisen**

Run Step 2 erneut. Expected: PASS.

- [ ] **Step 7: Failing Middleware-Integrationstests schreiben**

Ersetze beziehungsweise ergänze Tests um diese beobachtbaren Eigenschaften:

```python
resolved = resolve_internal_request(messages, current_user_text)
assert resolved.original_query == current_user_text
assert resolved.retrieval_query == expected_standalone_query
```

Prüfe den Vaudis-Hannover-Fall, Standortwechsel, neuen Personennamen und eine unveränderte eigenständige Anfrage.

- [ ] **Step 8: Middleware an den Harness-Resolver anbinden**

Ersetze den Aufruf von `_expanded_internal_rag_query()` im aktiven Wissenspfad durch den neuen Harness-Resolver. Entferne nur die nun nachweislich ersetzten Sonderfälle; behalte nicht betroffene Öffnungszeiten- oder technische Clarification-Pfade, bis deren Tests eine sichere Migration belegen.

- [ ] **Step 9: Middleware GREEN nachweisen**

Run:

```powershell
& .\.venv-verify\Scripts\python.exe -m pytest stack\tests\test_middleware_internal_rag_routing.py -q -p no:cacheprovider
```

Expected: PASS, einschließlich bestehender Modell-, Quellen- und Direct-Final-Content-Grenzen.

- [ ] **Step 10: Review checkpoint**

Prüfe, dass `original_query` unverändert bleibt, keine Antwort im Resolver entsteht und keine neue globale Formulierungswortliste eingeführt wurde. Kein Commit ohne ausdrückliche Freigabe.

---

### Task 5: Akzeptanzmatrix, Bundle-Synchronität und vollständige Verifikation

**Files:**
- Modify: `scripts/openwebui/kahle-harness-acceptance-matrix.json`
- Modify: `stack/tests/test_kahle_harness_reference_matrix.py`
- Modify only if generated sources require it: synchronized files under `stack/open-webui-tools/dist/`

**Interfaces:**
- Consumes: neue Supervisor- und Folgefragenverträge
- Produces: reproduzierbare Regressionen für alle drei Vinci-Modelle

- [ ] **Step 1: Failing Akzeptanzfälle ergänzen**

Ergänze synthetische beziehungsweise datenunabhängige Fälle für:

- konkrete Person plus Führungskraft;
- Bereich mit mindestens 90 Prozent Konsens;
- Bereich unter 90 Prozent;
- Mahnung ohne belegten Ansprechpartner;
- Werbewiderspruch ohne Standort;
- Folgefrage „Und wie geht es dann, wenn ich in Hannover bin?“;
- Standortwechsel im selben Chat;
- neuer Personenname nach einer Supervisor-Folgefrage.

- [ ] **Step 2: RED für Matrixvertrag nachweisen**

Run:

```powershell
& .\.venv-verify\Scripts\python.exe -m pytest stack\tests\test_kahle_harness_reference_matrix.py -q -p no:cacheprovider
```

Expected: Neue Matrixanforderungen schlagen fehl, bis alle vorherigen Tasks integriert sind.

- [ ] **Step 3: Matrix und Verträge auf den neuen Pfad ausrichten**

Lege für jeden Fall erlaubte Tools, Evidenzstatus, Quellenpflicht und verbotene Kontaktwerte fest. Verwende keine realen Namen oder E-Mail-Adressen.

- [ ] **Step 4: Tool-Bundles prüfen und nur bei geänderter Quelle bauen**

Run:

```powershell
& .\.venv-verify\Scripts\python.exe stack\open-webui-tools\build_tools.py --check
```

Wenn der Check wegen einer tatsächlich geänderten Toolquelle fehlschlägt:

```powershell
& .\.venv-verify\Scripts\python.exe stack\open-webui-tools\build_tools.py
& .\.venv-verify\Scripts\python.exe stack\open-webui-tools\build_tools.py --check
```

Expected: Source und `dist` sind synchron. Dist wird niemals isoliert bearbeitet.

- [ ] **Step 5: Gezielte Gesamttests ausführen**

Run:

```powershell
& .\.venv-verify\Scripts\python.exe -m pytest stack\personio-directory\tests -q -p no:cacheprovider
& .\.venv-verify\Scripts\python.exe -m pytest stack\tests\test_kahle_knowledge_harness.py stack\tests\test_middleware_internal_rag_routing.py stack\tests\test_vinci_starter_prompt_contracts.py stack\tests\test_kahle_harness_reference_matrix.py -q -p no:cacheprovider
```

Expected: PASS. Die Personio-Suite bleibt wegen des gleichnamigen `app`-Pakets in einem eigenen Prozess.

- [ ] **Step 6: Kanonischen Full Verify ausführen**

Run:

```powershell
.\scripts\run-local-tests.ps1 -Tier Full -Python .\.venv-verify\Scripts\python.exe -Npm npm.cmd
```

Expected: Full Verify endet erfolgreich ohne `TESTFEHLER`. Einen möglichen `SETUPFEHLER` separat diagnostizieren und nicht als Produkterfolg ausgeben.

- [ ] **Step 7: Abschlussreview**

Prüfe `git diff --check`, den vollständigen Diff der betroffenen Dateien und `git status --short`. Stelle sicher, dass bestehende fremde Änderungen erhalten blieben, keine Secrets enthalten sind und kein Produktionsrollout, Push oder Commit ausgeführt wurde.

- [ ] **Step 8: Manuelle UI-Abnahme vorbereiten**

Liefere kurze Testprompts für KAHLE-Vinci, Thinking und Max Thinking mit erwarteter Toolwahl, Evidenzgrenze und Antwortinhalt. Die eigentliche UI-Abnahme oder Produktionsaktivierung erfolgt nur nach separatem Auftrag.

---

### Task 6: Live gefundene Bereichs- und Clientvertragslücken schließen

**Files:**
- Modify: `stack/personio-directory/app/search.py`
- Modify: `stack/personio-directory/tests/test_search.py`
- Modify: `stack/open-webui-overrides/open_webui/utils/personio_directory_client.py`
- Modify: `stack/tests/test_middleware_internal_rag_routing.py`

- [ ] Ergänze zuerst fehlschlagende Tests dafür, dass Bereichsmetadaten den Open-WebUI-Client passieren und die dominante Führungskraft selbst nicht zum Konsensnenner zählt.
- [ ] Weise beide Fehler separat als RED nach.
- [ ] Erweitere den Client ausschließlich um die freigegebenen Aggregatfelder und berechne den Konsens über die übrigen Bereichsmitglieder, wenn die dominante Supervisor-Person selbst Kandidat ist.
- [ ] Weise Personio- und Open-WebUI-Tests als GREEN nach.

### Task 7: Themenanker über mehrere Folgefragen erhalten

**Files:**
- Modify: `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py`
- Modify: `stack/tests/test_kahle_knowledge_harness.py`

- [ ] Ergänze einen fehlschlagenden Drei-Turn-Test für Vaudis, Hannover und anschließend Nienburg.
- [ ] Suche rückwärts nur innerhalb des aktuellen zusammenhängenden Referenzdialogs nach dem letzten eigenständigen Themenanker; neue explizite Personen oder Themen überschreiben den Anker.
- [ ] Weise bestehende und neue Resolver-Regressionen als GREEN nach.

### Task 8: Fachfremde Kontakte und unvollständige Prozessgeltung verhindern

**Files:**
- Modify: `stack/open-webui-tools/hybrid_retrieval.py`
- Modify: `stack/open-webui-tools/dist/rag_chat_hybrid_tool.py` through `build_tools.py`
- Modify: `stack/tests/test_hybrid_retrieval_security.py`

- [ ] Ergänze fehlschlagende Retrievaltests: Ein allgemeiner Kontakt aus einem fachfremden Dokument darf keine Mahnungszuständigkeit belegen; ein Prozessdokument mit explizitem Geltungsbereich muss die Geltungspassage zusammen mit den Schritten liefern.
- [ ] Binde Kontaktbelege an passenden Zweck bzw. Dokumentkontext und vervollständige fokussierte Prozessdokumente um vorhandene Geltungs- und Ausnahmeabschnitte.
- [ ] Generiere `dist` aus der Quelle und weise Bundle-Synchronität sowie Retrievaltests als GREEN nach.

### Task 9: Vorgeroutetes Personio sichtbar machen

**Files:**
- Modify: `stack/open-webui-overrides/open_webui/utils/middleware.py`
- Modify: `stack/tests/test_middleware_internal_rag_routing.py`

- [ ] Ergänze zuerst einen fehlschlagenden Test für sichtbare `personio_directory`-Start- und Fertigereignisse bei einem Personio-only-Plan.
- [ ] Verallgemeinere die bestehende native RAG-Fortschrittsdarstellung für tatsächlich vorgeroutete interne Tools, ohne Toolaufrufe vorzutäuschen.
- [ ] Weise Middleware-Regressionen als GREEN nach.

### Task 10: Abschlussprüfung und lokaler Live-Retest

- [ ] Führe die getrennten betroffenen Dienstsuiten aus.
- [ ] Führe den kanonischen Full Verify aus.
- [ ] Aktualisiere ausschließlich die betroffenen lokalen Container und prüfe Quell-/Container-Synchronität.
- [ ] Wiederhole die freigegebenen Live-Prompts datensparsam; kein Commit, Branch, Push oder Produktionsrollout.

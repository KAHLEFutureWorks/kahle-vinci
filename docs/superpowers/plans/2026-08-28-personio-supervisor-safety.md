# Personio Supervisor Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Personio-Verzeichnisfragen zuverlässig ohne RAG beantworten, Bereichsführungskräfte ausschließlich aus Supervisor-Evidenz auflösen und Führungskräftefragen auch bei kontrollierten Tippfehlern fail-closed halten.

**Architecture:** Der Knowledge Harness bleibt die einzige Quelle für die Retrieval-Planung. Ein gemeinsamer, kontrollierter Supervisor-Begriffserkenner wird von Harness und Middleware verwendet; der Personio-Dienst spiegelt dieselbe enge Erkennung an seiner Servicegrenze. Bereichsfragen verwenden die vorhandenen strukturierten Directory-Filter und lösen nur explizite Supervisor-Personio-IDs auf.

**Tech Stack:** Python 3.11, pytest, Open-WebUI-Overrides, FastAPI-Personio-Dienst, Docker Compose, PowerShell und Bash-Rollout.

**Spec:** Freigegebenes Design im Chat vom 28.08.2026; verbindliche Regeln in `ARCHITECTURE.md`, `SECURITY.md` und ADR-008 in `DECISIONS.md`.

## Global Constraints

- Personio bleibt für aktuelle Mitarbeiterstammdaten autoritativ und lesend.
- RAG darf keine Führungskraft, aktuelle Person oder aktuelle Kontaktdaten liefern.
- Supervisoren werden ausschließlich über stabile Personio-IDs aufgelöst.
- Mehrdeutige, fehlende oder nicht auflösbare Supervisor-Evidenz bleibt fail-closed.
- Tests, Logs und Rollout-Nachweise enthalten keine Mitarbeiterdaten oder Secrets.
- Der Rollout ersetzt nur betroffene Dateien, sichert sie vorab und lädt Open WebUI nach Bind-Mount-Änderungen ausdrücklich neu.

---

### Task 1: Kontrollierte Supervisor-Tippfehler sicher routen

**Files:**
- Modify: `stack/tests/test_kahle_knowledge_harness.py`
- Modify: `stack/tests/test_middleware_internal_rag_routing.py`
- Modify: `stack/personio-directory/tests/test_search.py`
- Modify: `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py`
- Modify: `stack/personio-directory/app/search.py`

**Interfaces:**
- Produces: `_has_supervisor_reference(query: str) -> bool` im Harness.
- Consumes: normalisierte Query-Tokens; akzeptiert exakte Supervisorbegriffe und genau einen Zeichenfehler in `fuhrungskraft`, ansonsten keine unscharfe Semantik.

- [ ] **Step 1: Failing Harness- und Middleware-Tests ergänzen**

```python
def test_supervisor_typo_stays_personio_only():
    query = "Wer ist die Führungskrft von Erika Beispiel?"
    plan = harness.plan_retrieval(query, query, [], "kahle-vinci", {})
    assert plan.required_tools == ("personio_directory",)
    assert harness.classify_personio_directory_intent(query) == "supervisor_lookup"
```

- [ ] **Step 2: Failing Directory-Test ergänzen**

```python
def test_supervisor_typo_uses_fail_closed_supervisor_intent():
    assert classify_directory_query(
        "Wer ist die Führungskrft von Erika Beispiel?"
    ) == "supervisor_lookup"
```

- [ ] **Step 3: RED verifizieren**

Run:

```powershell
& .\.venv-verify\Scripts\python.exe -m pytest stack\tests\test_kahle_knowledge_harness.py stack\tests\test_middleware_internal_rag_routing.py -q -p no:cacheprovider -k "supervisor_typo"
& .\.venv-verify\Scripts\python.exe -m pytest stack\personio-directory\tests\test_search.py -q -p no:cacheprovider -k "supervisor_typo"
```

Expected: Beide Aufrufe schlagen fehl, weil `Führungskrft` derzeit als Directory-/RAG-Frage statt `supervisor_lookup` erkannt wird.

- [ ] **Step 4: Minimale kontrollierte Erkennung implementieren**

Im Harness einen Tokenvergleich ergänzen, der nur `fuhrungskraft` und einen Abstand von genau einem Zeichen akzeptiert. `_directory_information_need`, `classify_personio_directory_intent` und die Führungsfrage-Schutzlogik verwenden denselben Helper. Die Servicegrenze in `search.py` erhält die gleiche enge Regel.

- [ ] **Step 5: GREEN verifizieren**

Run: dieselben beiden pytest-Aufrufe.

Expected: PASS; die Tippfehlerfrage plant ausschließlich `personio_directory`.

### Task 2: Bereichs- und Abteilungsführungskräfte aus Supervisor-Evidenz auflösen

**Files:**
- Modify: `stack/personio-directory/tests/test_search.py`
- Modify: `stack/personio-directory/app/search.py`
- Modify: `stack/tests/test_middleware_internal_rag_routing.py`

**Interfaces:**
- Produces: `_supervisors_for_group_query(text: str, people: Iterable[PersonRecord]) -> tuple[PersonRecord, ...]`.
- Consumes: vorhandene `_directory_candidates`-Filter und `supervisor_personio_id`.

- [ ] **Step 1: Failing Tests für eindeutige und mehrdeutige Bereiche ergänzen**

```python
def test_department_supervisor_resolves_only_explicit_personio_relationship():
    leader = person("1", name="Erika Beispiel", department="Disposition")
    report = person("2", name="Anna Adler", department="Disposition", supervisor_personio_id="1")
    evidence = search([leader, report]).search(
        query("Wer ist die Führungskraft der Disposition?")
    )
    assert [claim["display_name"] for claim in evidence.claims] == ["Erika Beispiel"]

def test_department_supervisor_with_multiple_explicit_leaders_stays_fail_closed():
    # Zwei unterschiedliche Supervisor-IDs dürfen keine Auswahl erzeugen.
    assert evidence.status == "not_found"
    assert evidence.claims == ()
```

- [ ] **Step 2: RED verifizieren**

Run:

```powershell
& .\.venv-verify\Scripts\python.exe -m pytest stack\personio-directory\tests\test_search.py -q -p no:cacheprovider -k "department_supervisor"
```

Expected: Der eindeutige Fall schlägt mit `not_found` fehl.

- [ ] **Step 3: Minimale Gruppenauflösung implementieren**

Bei `supervisor_lookup` zuerst eine exakte benannte Person auflösen. Enthält die Frage stattdessen einen expliziten strukturierten Bereich, werden die vorhandenen Directory-Kandidaten ermittelt. Eine intern referenzierte Supervisor-ID hat nur dann Evidenz, wenn sie eindeutig ist. Existiert keine interne Führungskraft, darf genau eine gemeinsame externe Supervisor-ID aufgelöst werden. Mehrere, fehlende oder unbekannte IDs liefern keine Claims.

- [ ] **Step 4: GREEN und bestehende Supervisorfälle verifizieren**

Run:

```powershell
& .\.venv-verify\Scripts\python.exe -m pytest stack\personio-directory\tests\test_search.py -q -p no:cacheprovider -k "supervisor"
```

Expected: PASS für benannte Personen, Folgefragen, Bereiche und Fail-closed-Fälle.

### Task 3: RAG-Halluzinationen bei Supervisorfragen defensiv blockieren

**Files:**
- Modify: `stack/tests/test_middleware_internal_rag_routing.py`
- Modify: `stack/open-webui-overrides/open_webui/utils/middleware.py`
- Modify: `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py`

**Interfaces:**
- Consumes: `classify_personio_directory_intent(query)` und Retrieval-Plan.
- Produces: Direkte fail-closed-Antwort, falls eine Supervisorfrage wider Erwarten nicht ausschließlich mit Personio-Evidenz beantwortet werden kann.

- [ ] **Step 1: Failing Defense-in-depth-Test ergänzen**

Der Test übergibt eine Tippfehler-Supervisorfrage zusammen mit einer angeblichen RAG-Personenbehauptung und prüft, dass weder der Name noch eine Personio-Quellenbehauptung in der Antwort erscheint.

- [ ] **Step 2: RED verifizieren**

Run:

```powershell
& .\.venv-verify\Scripts\python.exe -m pytest stack\tests\test_middleware_internal_rag_routing.py -q -p no:cacheprovider -k "supervisor and rag"
```

Expected: FAIL, solange der RAG-Text die Antwortgrenze passieren kann.

- [ ] **Step 3: Minimalen Guard implementieren**

Die Middleware verwendet den gemeinsamen Supervisor-Intent. Jede Supervisorfrage ohne unterstützte Personio-Evidenz erhält die vorhandene Nicht-verfügbar-Antwort. RAG-Inhalte und RAG-Quellen werden dafür nicht gerendert.

- [ ] **Step 4: GREEN verifizieren**

Run: derselbe Middleware-pytest-Aufruf.

Expected: PASS; kein RAG-Personenname und keine erfundene Personio-Quelle erreichen die Antwort.

### Task 4: Dokumentation, Gesamtverifikation und Rollout

**Files:**
- Modify: `docs/operations/personio-directory.md`
- Create: `deploy/personio-supervisor-safety-20260828-v1.tar.gz` (ignoriertes Rollout-Artefakt)

**Interfaces:**
- Rollout ersetzt Harness, Middleware und Personio-Suche.
- Open WebUI wird mit `--force-recreate --no-deps` neu erstellt, damit Python die aktualisierte Bind-Mount-Datei importiert.

- [ ] **Step 1: Betriebsdokumentation um Reload-Regel und Abnahmefälle ergänzen**

- [ ] **Step 2: Targeted Suiten ausführen**

```powershell
& .\.venv-verify\Scripts\python.exe -m pytest stack\personio-directory\tests -q -p no:cacheprovider
& .\.venv-verify\Scripts\python.exe -m pytest stack\tests\test_kahle_knowledge_harness.py stack\tests\test_middleware_internal_rag_routing.py -q -p no:cacheprovider
```

- [ ] **Step 3: Kanonischen Full Verify ausführen**

```powershell
.\scripts\run-local-tests.ps1 -Tier Full -Python .\.venv-verify\Scripts\python.exe -Npm npm.cmd -Node node.exe
```

- [ ] **Step 4: Zusätzliche statische Prüfungen ausführen**

```powershell
& .\.venv-verify\Scripts\python.exe stack\open-webui-tools\build_tools.py --check
& .\.venv-verify\Scripts\python.exe -m compileall -q stack\personio-directory\app stack\open-webui-overrides\open_webui\utils
git diff --check
```

- [ ] **Step 5: Kleine fachliche Commits erstellen**

```powershell
git add AGENTS.md stack/AGENTS.md ARCHITECTURE.md SECURITY.md DECISIONS.md docs/superpowers/plans/2026-08-28-personio-supervisor-safety.md
git commit -m "docs: refresh Personio authority context"
git add stack/personio-directory stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py stack/open-webui-overrides/open_webui/utils/middleware.py stack/tests docs/operations/personio-directory.md
git commit -m "fix(personio): keep supervisor queries evidence-bound"
```

- [ ] **Step 6: Schmales Rollout-Paket mit Backup, Rollback und Health-Wartezeit erstellen**

Das Paket enthält nur die drei Laufzeitdateien, `README.txt` und `install.sh`. Der Installer prüft Personio-Variablennamen ohne Werte, sichert die Ziele, kompiliert Python, baut `personio-directory`, erstellt `open-webui` ausdrücklich neu und prüft beide Health-Zustände. Beim Fehler werden Dateien wiederhergestellt und Open WebUI erneut geladen.

- [ ] **Step 7: Manuellen Produktionsrollout über PowerShell übergeben**

SCP und SSH verwenden den vorhandenen Schlüsselpfad. Der Benutzer gibt SSH- und sudo-Passphrase selbst ein. Nach dem Rollout werden ausschließlich Prüfsumme, Container-Health und aggregierte Abnahmeergebnisse dokumentiert.

# Upload FIFO Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dokument-Uploads werden global, persistent und strikt in FIFO-Reihenfolge verarbeitet; Fehler werden eindeutig einem Upload zugeordnet und an Uploader sowie abweichenden Owner gemeldet.

**Architecture:** Der bestehende `UploadJobService` wird zu einer SQLite-gestützten Single-Consumer-Queue mit Lease und persistentem Dateispool erweitert. Ein eigener `kb-upload-worker` beansprucht atomar genau einen Auftrag, führt den bestehenden sicheren Ingest-Pfad aus und setzt die Queue nach Erfolg oder Fehler fort. API und Portal verwalten nur Einreihung, Status, Queue-Position und verständliche Fehlerzuordnung.

**Tech Stack:** Python 3.11, FastAPI, SQLite, pypdf, Docker Compose, React 19, TypeScript.

## Global Constraints

- Keine bestehenden Änderungen in `global_analysis.py`, `main.py`, `test_global_analysis.py`, `.vendor/` oder `deploy/` überschreiben.
- Keine `.env`-Dateien, Schlüssel oder Zugangsdaten ausgeben.
- Global höchstens ein Upload mit gültigem Status `processing`.
- Ein fehlgeschlagener oder unterbrochener Auftrag darf den nächsten Auftrag nicht blockieren.
- Uploader immer benachrichtigen; abweichenden aktiven vorgesehenen Owner zusätzlich benachrichtigen.
- Wartende Aufträge überleben Neustarts; abgelaufene aktive Aufträge werden als `upload_worker_interrupted` abgeschlossen und nicht automatisch erneut ausgeführt.
- Keine Commits und kein Push ohne ausdrücklichen Auftrag.
- Rollout sichert veränderte Dateien unter `/opt/kahle-vinci/.rollout-backups/` und stellt sie bei Fehlern wieder her.

---

## File Map

- `stack/kb-admin-api/app/upload_jobs.py`: Persistente Queue, additive Schema-Migration, FIFO-Claim, Lease, Sichtbarkeit, Metadaten und Spool-Speicher.
- `stack/kb-admin-api/app/main.py`: HTTP-Enqueue, Queue-Verarbeitung, Fehlerkontext, Qualitätsfall-Fingerprint und Benutzerbenachrichtigungen.
- `stack/kb-admin-api/app/upload_worker.py`: Einziger Polling-Consumer und Recovery abgelaufener Leases.
- `stack/docker-compose.yml`: Neuer Dienst `kb-upload-worker` mit identischer API-Konfiguration und gemeinsamem Dateivolume.
- `stack/docker-compose.prod.yml`: Produktionslimits für `kb-upload-worker` mit 750 MiB RAM, 1 CPU und 192 PIDs.
- `admin-dashboard/components/KnowledgePortal.tsx`: Aktive Upload-Liste, Queue-Position und vollständige Qualitätsfall-Zuordnung.
- `stack/kb-admin-api/tests/test_upload_jobs.py`: Queue-, Lease-, Persistenz- und Spool-Tests.
- `stack/kb-admin-api/tests/test_portal_upload_api.py`: Enqueue-, Worker-, FIFO-, Fehlerkontext- und Benachrichtigungstests.
- `admin-dashboard/tests/rendered-html.test.mjs`: Sichtbare Upload- und Qualitätsfallinformationen im gebauten Portal.

---

### Task 1: Persistente Queue und geschützter Spool

**Files:**
- Modify: `stack/kb-admin-api/app/upload_jobs.py`
- Test: `stack/kb-admin-api/tests/test_upload_jobs.py`

**Interfaces:**
- Produces: `UploadSpool(root: Path)`, `UploadJobService.enqueue(...)`, `claim_next()`, `heartbeat(...)`, `expire_interrupted()`, `list_active(...)`, `set_incident(...)`.
- Consumes: `SQLiteGovernanceStore.connect()` mit SQLite-Transaktionen.

- [ ] **Step 1: Failing Queue-Schema- und Metadatentest schreiben**

Erweitere `test_upload_jobs.py` um zwei vollständige Aufträge. Nach einer neuen Service-Instanz müssen Titel, Dateiname, Owner, Wissensbereiche, Gültigkeit, Dateigröße und staged Pfad unverändert lesbar sein.

```python
first = service.enqueue(
    job_id="job-1", user_id="uploader-1", original_filename="gross.pdf", title="Großes Handbuch",
    knowledgebase_ids=("kb-service",), valid_workdays=60,
    confidentiality="internal", owner_user_id="owner-1",
    security_review_requested=False, staged_path="job-1.upload", file_size_bytes=17_000_000,
)
reopened = UploadJobService(store, now=clock.now)
assert reopened.get(first["job_id"], "uploader-1")["title"] == "Großes Handbuch"
assert reopened.get(first["job_id"], "uploader-1")["knowledgebase_ids"] == ["kb-service"]
```

- [ ] **Step 2: Roten Test ausführen**

Run: Backend-Testcontainer mit `pytest stack/kb-admin-api/tests/test_upload_jobs.py -q`.

Expected: FAIL, weil `enqueue` und die Metadatenspalten fehlen.

- [ ] **Step 3: Additive Schema-Migration und `enqueue` minimal implementieren**

Ergänze vorhandene Datenbanken über `PRAGMA table_info(upload_jobs)` plus `ALTER TABLE` um:

```text
original_filename TEXT
title TEXT
knowledgebase_ids_json TEXT NOT NULL DEFAULT '[]'
valid_workdays INTEGER
confidentiality TEXT
owner_user_id TEXT
security_review_requested INTEGER NOT NULL DEFAULT 0
staged_path TEXT
file_size_bytes INTEGER NOT NULL DEFAULT 0
lease_expires_at TEXT
incident_id TEXT
```

`enqueue` übernimmt eine bereits erzeugte und validierte `job_id`, schreibt alle Metadaten mit `status='queued'`, `step='uploaded'`, `progress=5`. `get` dekodiert `knowledgebase_ids_json` zu `knowledgebase_ids`.

- [ ] **Step 4: Queue-Position und global exklusiven Claim rot testen**

```python
assert service.get(first_id, "uploader-1")["position"] == 1
assert service.get(second_id, "uploader-2")["position"] == 2
assert service.claim_next()["job_id"] == first_id
assert service.claim_next() is None
```

Expected: FAIL, weil `position` und `claim_next` fehlen.

- [ ] **Step 5: Atomaren FIFO-Claim und Lease implementieren**

`claim_next()` verwendet `BEGIN IMMEDIATE`, verweigert einen Claim bei gültigem `processing`-Job und beansprucht den ältesten `queued`-Datensatz über `ORDER BY created_at, job_id`. Lease-Dauer: 15 Minuten. `heartbeat(job_id, step, progress)` aktualisiert Fortschritt und Lease.

- [ ] **Step 6: Abgelaufene Lease rot testen und implementieren**

```python
expired = service.expire_interrupted()
assert [item["job_id"] for item in expired] == [first_id]
assert service.get(first_id, "uploader-1")["error_code"] == "upload_worker_interrupted"
assert service.claim_next()["job_id"] == second_id
```

`expire_interrupted()` markiert abgelaufene Jobs atomar als `failed`, löscht die Lease und gibt deren vorherige vollständige Datensätze zurück. Ergänze `list_active` und `set_incident`.

- [ ] **Step 7: Spool-Tests rot schreiben und `UploadSpool` implementieren**

Prüfe atomisches Speichern, ungültige Job-IDs, Lesen und idempotentes Entfernen. `stage(job_id, data)` schreibt über `tempfile.mkstemp` plus `os.replace` nach `<root>/<job_id>.upload`. Ursprüngliche Dateinamen werden nie als Pfad verwendet.

- [ ] **Step 8: Task-Tests grün ausführen**

Expected: alle Tests in `test_upload_jobs.py` PASS.

---

### Task 2: API reiht nur noch ein und liefert aktive Jobs

**Files:**
- Modify: `stack/kb-admin-api/app/main.py:1634-1675`
- Test: `stack/kb-admin-api/tests/test_portal_upload_api.py`

**Interfaces:**
- Consumes: `UPLOAD_JOBS.enqueue(...)`, `UPLOAD_SPOOL.stage(...)`, `UPLOAD_JOBS.list_active(...)`.
- Produces: `POST /portal/upload-jobs`, `GET /portal/upload-jobs`, unverändertes `GET /portal/upload-jobs/{job_id}`.

- [ ] **Step 1: Failing API-Test schreiben, der Background-Verarbeitung verbietet**

Nach `POST /portal/upload-jobs` muss der Job `queued` bleiben und ein absichtlich protokollierender Converter darf nicht aufgerufen worden sein.

```python
assert response.status_code == 202
assert response.json()["status"] == "queued"
assert response.json()["position"] == 1
assert converter_calls == []
```

- [ ] **Step 2: Roten API-Test ausführen**

Expected: FAIL, weil der vorhandene FastAPI-Background-Task den Job sofort verarbeitet.

- [ ] **Step 3: HTTP-Enqueue minimal implementieren**

Entferne `BackgroundTasks` aus dem Upload-Endpunkt. Prüfe Berechtigungen und Größe, erzeuge eine UUID-Job-ID, stage die Datei atomar unter dieser Job-ID, speichere den Queue-Datensatz mit exakt derselben ID und gib das Jobobjekt mit `202` zurück. Scheitert das Enqueue nach erfolgreichem Stage, entferne die staged Datei.

- [ ] **Step 4: Active-List-Autorisierung rot testen und implementieren**

`GET /portal/upload-jobs` zeigt Mitarbeitern nur eigene `queued`- und `processing`-Jobs. Portal-Admins sehen alle aktiven Jobs. Abgeschlossene Jobs erscheinen nicht.

- [ ] **Step 5: Bestehende Endpunkt-Strukturprüfung anpassen**

Ersetze die Quelltextprüfung des Background-Aufrufs durch die fachliche Assertion, dass der POST-Endpunkt keine Konvertierung startet. Tests, die sofort `completed` erwarten, werden in Task 3 gemeinsam mit dem dort eingeführten Worker-Seam umgestellt.

- [ ] **Step 6: Task-Tests grün ausführen**

Expected: Enqueue-, Sichtbarkeits- und vorhandene Validierungstests PASS.

---

### Task 3: Single-Consumer-Worker und Queue-Fortsetzung

**Files:**
- Create: `stack/kb-admin-api/app/upload_worker.py`
- Modify: `stack/kb-admin-api/app/main.py:1595-1631`
- Modify: `stack/docker-compose.yml`
- Modify: `stack/docker-compose.prod.yml`
- Test: `stack/kb-admin-api/tests/test_portal_upload_api.py`

**Interfaces:**
- Consumes: Queue- und Spool-Methoden aus Task 1.
- Produces: `_process_portal_upload_job(job)`, `drain_one_upload_job() -> bool`, `recover_interrupted_upload_jobs()`, `app.upload_worker.run_forever()`.

- [ ] **Step 1: FIFO-Verarbeitungstest rot schreiben**

Reihe zwei Jobs ein, protokolliere Converter-Dateinamen und rufe `drain_one_upload_job()` zweimal auf.

```python
assert module.drain_one_upload_job() is True
assert module.drain_one_upload_job() is True
assert converted_filenames == ["gross.pdf", "klein.pdf"]
```

Expected: FAIL, weil der Worker-Seam fehlt.

- [ ] **Step 2: Queue-Verarbeitung minimal implementieren**

Lade staged Datei und aktuelle Uploader-Identität. Setze `UPLOAD_CONVERSION_PROGRESS`, führe `portal_upload_document` mit gespeicherten Metadaten aus und speichere Ergebnis oder Fehler. Fortschrittsupdates verwenden `heartbeat`. Entferne staged Dateien nur bei terminalem Status.

- [ ] **Step 3: Fehler-fährt-fort-Test rot schreiben und implementieren**

Der erste Converter-Aufruf wirft `IngestError`, der zweite liefert Markdown. Nach zwei Drains muss der erste Job `failed`, der zweite `completed` sein. Jobfehler dürfen nicht aus `drain_one_upload_job` entweichen.

- [ ] **Step 4: Interrupted-Recovery der Queue testen und implementieren**

`recover_interrupted_upload_jobs()` verarbeitet die Rückgabe von `expire_interrupted()`, entfernt die staged Datei und gibt die Queue frei. Die Qualitätsfälle und Meldungen werden in Task 4 an diesen bestehenden Seam angeschlossen.

- [ ] **Step 5: Worker-Loop erstellen**

```python
def run_forever(poll_seconds: float = 2.0) -> None:
    recover_interrupted_upload_jobs()
    while True:
        if drain_one_upload_job():
            continue
        time.sleep(poll_seconds)
```

- [ ] **Step 6: Compose-Service ergänzen**

`kb-upload-worker` verwendet dasselbe API-Image, `command: ["python", "-m", "app.upload_worker"]`, die API-Werte für Datenbank, Portaldateien, Document-Worker, ClamAV, Embeddings, KB-Sync und Mail sowie das persistente `/portal-data`-Volume, `restart: unless-stopped` und genau eine Replik. Der Produktions-Override setzt 750 MiB RAM, 1 CPU und 192 PIDs.

- [ ] **Step 7: Sofort-Abschluss-Tests auf den Worker-Seam umstellen**

Bestehende Tests für erfolgreiche Upload-Jobs rufen nach dem POST ausdrücklich `drain_one_upload_job()` auf und erwarten erst danach `completed`.

- [ ] **Step 8: Task-Tests und Compose-Konfiguration prüfen**

Expected: FIFO-, Fortsetzungs- und Recovery-Tests PASS; Compose enthält genau einen `kb-upload-worker`.

---

### Task 4: Eindeutige Qualitätsfälle und Benachrichtigungen

**Files:**
- Modify: `stack/kb-admin-api/app/main.py:1526-1550, 2669-2677`
- Modify only if update semantics require it: `stack/kb-admin-api/app/quality_cases.py:73-95`
- Test: `stack/kb-admin-api/tests/test_portal_upload_api.py`
- Test: `stack/kb-admin-api/tests/test_quality_cases.py`

**Interfaces:**
- Produces: `UPLOAD_JOB_CONTEXT`, `_upload_failure_diagnostic(...)`, `_notify_upload_failure(...)`.
- Consumes: `QUALITY_CASES.system_incident(..., fingerprint=...)`, `portal_notifications`, `MAINTENANCE.enqueue_notification`.

- [ ] **Step 1: Vollständigen Diagnosekontext rot testen**

`diagnostic_json` muss Job-ID, Fehlercode, Titel, Dateiname, Uploader-ID, Owner-ID, Wissensbereich-IDs, Dateigröße und Seitenbereich enthalten.

- [ ] **Step 2: Zwei-Jobs-zwei-Fälle rot testen**

Zwei Jobs mit demselben Fehler erhalten verschiedene Incident-IDs. Derselbe Job und Fehler verwendet dieselbe Incident-ID und öffnet einen gelösten Fall wieder.

- [ ] **Step 3: Jobbezogenen Fingerprint minimal implementieren**

Setze beim Worker `UPLOAD_JOB_CONTEXT`. Erweitere `_notify_system_error` um `fingerprint` und verwende:

```python
fingerprint = f"upload_job:{job['job_id']}:{stable_error_code}"
incident_id = _notify_system_error(
    "required_ingest_check", diagnostic, fingerprint=fingerprint,
)
```

- [ ] **Step 4: Benachrichtigungstests rot schreiben**

Prüfe Uploader, abweichenden aktiven Owner, Deduplizierung bei identischem Owner, Überspringen inaktiver Owner sowie Abwesenheit von Dokumentinhalt.

- [ ] **Step 5: `_notify_upload_failure` implementieren**

Bilde Empfänger über `dict.fromkeys([uploader_id, owner_id])`, validiere aktive Portal-Identitäten, schreibe `portal_notifications` mit `subject_type='upload_job'` und plane E-Mail über die Outbox. Dedupe-Key: `upload-failed:<job_id>:<recipient_user_id>`.

- [ ] **Step 6: Incident-ID am Job speichern**

Speichere `incident_id` über `UPLOAD_JOBS.set_incident`. Der Job-Fehlercode bleibt mit `friendlyError` kompatibel.

- [ ] **Step 7: Task-Tests grün ausführen**

Expected: Qualitätsfall- und Benachrichtigungstests PASS.

---

### Task 5: Portal zeigt alle aktiven Uploads und vollständige Fallzuordnung

**Files:**
- Modify: `admin-dashboard/components/KnowledgePortal.tsx:200-220, 1260-1640, 4587-4721`
- Modify: `admin-dashboard/tests/rendered-html.test.mjs`

**Interfaces:**
- Consumes: `GET /portal/upload-jobs` mit `position`, `title`, `original_filename`, `status`, `step`, `progress`.
- Produces: Liste „Meine laufenden Uploads“ und zusätzliche Qualitätsfallfelder.

- [ ] **Step 1: Gerenderten UI-Test rot schreiben**

Assertiere sichtbare Texte: `Meine laufenden Uploads`, `Wartet · Position`, `Wird verarbeitet`, `Auftrags-ID`, `Hochgeladen von`, `Vorgesehener Owner`, `Betroffener Seitenbereich`.

- [ ] **Step 2: Roten UI-Test ausführen**

Expected: FAIL, weil aktive Liste und zusätzliche Fallfelder fehlen.

- [ ] **Step 3: Typen und aktive Job-Abfrage implementieren**

Ergänze `UploadJob` um `position`, `title`, `original_filename`, `incident_id`. Beim Mount lädt die Komponente alle aktiven Jobs; solange mindestens einer aktiv ist, pollt sie im bestehenden 700-ms-Rhythmus. Timer wird beim Unmount beendet.

- [ ] **Step 4: Aktive Jobs darstellen**

Zeige Titel, Dateiname und entweder `Wartet · Position X` oder Verarbeitungsschritt plus Fortschritt. Der gerade eingereichte Job bleibt prominent. `sessionStorage` bleibt nur ein schneller Wiedereinstieg und ist nicht mehr die Quelle der Vollständigkeit.

- [ ] **Step 5: Qualitätsfallfelder darstellen**

Ergänze verständliche Texte für `document_conversion_failed` und `upload_worker_interrupted`. Karte und Dialog zeigen Titel, Dateiname, Job-ID, Uploader, Owner, Wissensbereiche, formatierte Dateigröße und Seitenbereich.

- [ ] **Step 6: UI-Tests und Build ausführen**

Run: `npm test` in `admin-dashboard`. Neue Fehler in veränderten Zeilen sind nicht zulässig; bereits bekannte unabhängige Cloudflare-Typfehler werden separat dokumentiert.

---

### Task 6: Gesamttest, Rollout-Paket und Betriebsprüfung

**Files:**
- Test: `test_upload_jobs.py`, `test_portal_upload_api.py`, `test_quality_cases.py`, `test_secure_ingest.py`, `test_global_analysis.py`
- Create: `deploy/wissen-upload-fifo-queue-20260817/install.sh`
- Create mechanically: minimales Payload und `deploy/wissen-upload-fifo-queue-20260817.tar.gz`

- [ ] **Step 1: Relevante Backend-Suite vollständig ausführen**

Expected: alle genannten Tests PASS.

- [ ] **Step 2: Syntax und statische Konsistenz prüfen**

Nutze `PYTHONDONTWRITEBYTECODE=1` oder AST-Parsing, `git diff --check` und eine Suche nach temporärer Instrumentierung.

- [ ] **Step 3: Rollout-Installer erstellen**

Der Installer sichert jede veränderte Laufzeitdatei, installiert nur Payload-Dateien, prüft Syntax, baut und startet nur `kb-admin-api`, `kb-upload-worker`, `kb-admin-dashboard`, wartet auf Status und Health und stellt bei Fehlern Dateien sowie Dienste wieder her.

- [ ] **Step 4: Installer und Payload lokal verifizieren**

Prüfe `bash -n`, Datei-SHA-256 und Tar-Inhalt. Keine `.env`, Tests, `.vendor` oder fremden Deploy-Dateien dürfen enthalten sein.

- [ ] **Step 5: Hand-off erzeugen**

Liefere Paketpfad, kleingeschriebene SHA-256, PowerShell-SCP-Befehl, Installationsblock und Prüfkommandos.

- [ ] **Step 6: Abschluss ohne Commit oder Push**

Zeige `git status --short`, trenne Voränderungen von dieser Umsetzung und bestätige, dass nichts committed oder gepusht wurde.


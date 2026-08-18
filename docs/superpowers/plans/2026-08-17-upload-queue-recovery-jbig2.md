# Upload Queue Recovery and JBIG2 Tolerance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verwaiste Upload-Jobs geben die persistente FIFO-Queue automatisch frei und nicht dekodierbare JBIG2-Bilder brechen die PDF-Konvertierung nicht mehr ab.

**Architecture:** Der Queue-Claim erkennt verwaiste Jobs atomar und gibt ihre Metadaten für nachgelagerte Incidents zurück. Der Worker führt Recovery bei jedem Poll aus. Der Dokument-Worker isoliert die Bilddekodierung pro Bildindex.

**Tech Stack:** Python 3.11, SQLite, FastAPI, pypdf, Docker Compose, pytest.

## Global Constraints

- Bestehende lokale Änderungen bleiben erhalten.
- Keine neue native JBIG2-Abhängigkeit.
- Global höchstens ein aktiver Upload.
- Keine Commits und kein Push.
- Rollout mit Sicherung und automatischer Rückstellung.

---

### Task 1: Atomare Recovery der Queue

**Files:**
- Modify: `stack/kb-admin-api/app/upload_jobs.py`
- Test: `stack/kb-admin-api/tests/test_upload_jobs.py`

**Interfaces:**
- Produces: `claim_next() -> tuple[dict[str, Any] | None, list[dict[str, Any]]]`
- Consumes: SQLite `BEGIN IMMEDIATE`.

- [ ] Test schreiben: Ein `processing`-Job mit `lease_expires_at=NULL` wird `upload_worker_interrupted`, danach wird der älteste wartende Job beansprucht.
- [ ] Test rot ausführen.
- [ ] Recovery innerhalb `claim_next()` implementieren und vollständige Recovery-Datensätze zurückgeben.
- [ ] Test grün ausführen.
- [ ] Test schreiben: Eine zunächst gültige Lease wird nach Zeitfortschritt beim nächsten Claim abgeschlossen.
- [ ] Rot und anschließend grün ausführen.

### Task 2: Recovery-Folgen im Worker

**Files:**
- Modify: `stack/kb-admin-api/app/main.py`
- Modify: `stack/kb-admin-api/app/upload_worker.py`
- Test: `stack/kb-admin-api/tests/test_portal_upload_api.py`

**Interfaces:**
- Consumes: Recovery-Datensätze aus `claim_next()`.
- Produces: Incident, `incident_id`, Portalnachricht, E-Mail-Outbox und Spool-Bereinigung.

- [ ] Integrationstest schreiben: Recovery eines Altjobs legt Incident und Meldung an und verarbeitet danach den nächsten Job.
- [ ] Test rot ausführen.
- [ ] Recovery-Nachbearbeitung in eine idempotente Funktion ziehen und bei jedem Drain ausführen.
- [ ] Test grün ausführen.

### Task 3: JBIG2-Bilder isolieren

**Files:**
- Modify: `stack/document-worker/app/main.py`
- Test: `stack/tests/test_document_worker_markdown_cleanup.py`

**Interfaces:**
- Consumes: `page.images` mit potenziell fehlerhaften Elementen.
- Produces: OCR-Text dekodierbarer Bilder; Fehler eines Bildes bleiben lokal.

- [ ] Test schreiben: Bildsammlung mit einem beim Zugriff fehlschlagenden Element und vorhandenem Seitentext konvertiert ohne Ausnahme.
- [ ] Test rot ausführen und `NotImplementedError` bestätigen.
- [ ] `page.images` indexweise mit Fehlergrenze je Bild lesen.
- [ ] Test grün ausführen.

### Task 4: Gesamttest und Rollout

**Files:**
- Create: `deploy/wissen-upload-queue-recovery-jbig2-20260817/install.sh`
- Create mechanically: minimales Payload und `.tar.gz`.

**Interfaces:**
- Produces: rückrollbares Installationspaket für `kb-admin-api`, `kb-upload-worker` und `document-worker`.

- [ ] Relevante und vollständige Testsuiten ausführen.
- [ ] Compose, Python-Syntax, `git diff --check` und Installer mit `bash -n` prüfen.
- [ ] Laufzeitdateien sichern, installieren, betroffene Images bauen und Container prüfen.
- [ ] Tar-Inhalt, Payload-Hashes und SHA-256 prüfen.
- [ ] Paketpfad und Installationsblock ohne Commit oder Push übergeben.

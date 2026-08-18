# Deutsche Mitteilungen und Aufbereitungsfreigabe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nutzer sehen ausschließlich verständliche deutsche Mitteilungen und können Fälle mit Status `needs_correction` verbindlich freigeben, ablehnen oder weiterleiten.

**Architecture:** Technische Status- und Fehlerwerte bleiben intern stabil, werden aber vor der Anzeige vollständig übersetzt. `DocumentLifecycle.decide` erhält einen ausdrücklich autorisierten Statusübergang für `needs_correction`; die UI verwendet dieselbe Entscheidungsfähigkeit statt einer Zeichenfolgenprüfung auf `approval`.

**Tech Stack:** Python 3.11, FastAPI, SQLite, React 19, TypeScript, pytest, Node Test Runner.

## Global Constraints

- Keine technischen IDs oder Fehlercodes in Nutzertexten.
- Fehlende Titel alter Uploads werden neutral und deutsch benannt.
- Ablehnung und Weiterleitung benötigen eine Begründung.
- Keine Commits und kein Push.

---

### Task 1: Deutsche Upload-Mitteilungen

**Files:**
- Modify: `stack/kb-admin-api/app/main.py`
- Modify: `admin-dashboard/components/KnowledgePortal.tsx`
- Test: `stack/kb-admin-api/tests/test_portal_upload_api.py`
- Test: `admin-dashboard/tests/rendered-html.test.mjs`

**Interfaces:**
- Produces: deutsche `statusText`- und Fehlertexte; nutzerfreundliche `portal_notifications.reason`.

- [ ] Fehlende Übersetzung und sichtbaren technischen Fehlercode rot testen.
- [ ] Backend-Mitteilung mit Dokumenttitel oder neutralem Altauftragstext implementieren.
- [ ] Status- und Fehlerübersetzung im Portal ergänzen.
- [ ] Backend- und UI-Tests grün ausführen.

### Task 2: Entscheidungen für Aufbereitungsprüfung

**Files:**
- Modify: `stack/kb-admin-api/app/document_lifecycle.py`
- Modify: `admin-dashboard/components/KnowledgePortal.tsx`
- Test: `stack/kb-admin-api/tests/test_document_lifecycle.py`
- Test: `admin-dashboard/tests/rendered-html.test.mjs`

**Interfaces:**
- Consumes: `decision in {'approve','reject','escalate'}`.
- Produces: erlaubte Übergänge von `needs_correction` nach `ready_to_activate`, `rejected` oder `pending_admin_approval`.

- [ ] Statusübergänge und Berechtigungen rot testen.
- [ ] Backend-Entscheidungszweig minimal implementieren.
- [ ] UI-Aktionsbedingung für `needs_correction` ergänzen.
- [ ] Backend- und UI-Tests grün ausführen.

### Task 3: Gesamttest und Rollout

**Files:**
- Create: `deploy/wissen-deutsche-mitteilungen-aufbereitungsfreigabe-20260817/install.sh`
- Create mechanically: minimales Payload und `.tar.gz`.

**Interfaces:**
- Produces: rückrollbares Rollout für API und Dashboard.

- [ ] Vollständige Backend- und Dashboard-Suiten ausführen.
- [ ] Syntax, Installer, Payload und Tar-Inhalt prüfen.
- [ ] Paketpfad und SHA-256 ohne Commit oder Push übergeben.

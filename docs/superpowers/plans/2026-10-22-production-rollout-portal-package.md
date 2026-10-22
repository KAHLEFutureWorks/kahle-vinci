# Produktions-Rollout Paket 1: Wissensportal-Stand Oktober

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Nichts in diesem Plan läuft auf dem Server; der Serverlauf ist ausschließlich Aufgabe des Nutzers nach ausdrücklicher Freigabe.

**Goal:** Ein geprüftes, sich selbst sicherndes Rollout-Paket bauen, das alle Wissensportal-Änderungen seit dem letzten Produktions-Rollout (21.08., `66db7ba`) auf `vinci-prod-01` bringt, ohne Open WebUI, Harness, Tools, Prompts oder Personio zu berühren.

**Architecture:** Gleiches Verfahren wie `wissen-versionsarchiv-20260821`: Das Paket legt die geänderten Dateien über `/opt/kahle-vinci`, sichert vorher jede Zieldatei nach `/opt/kahle-vinci/.rollout-backups/<name>-before-<Zeitstempel>`, prüft Syntax und Compose, baut nur die Portaldienste, belegt neuen Code und neues Schema im Container und rollt bei jedem Fehler automatisch zurück. Paket 2 (Open WebUI mit Harness) folgt erst nach erfolgreichem Paket 1 in einem eigenen Plan.

**Tech Stack:** Bash, Docker Compose, Python 3.11, Node/Vinext (Dashboard-Build im Container).

---

## Ausgangslage (22.10.)

- Letzter Produktions-Rollout: 21.08., Paket `wissen-versionsarchiv-20260821`, Commits `dd50ac3`, `66db7ba` (`docs/operations/netcup-production-deployment.md`, Abschnitt „Rollout History“). Seitdem 230 Commits.
- Nutzerentscheidung 22.10.: zwei getrennte Rollouts. **Paket 1 = Portaldienste**, Paket 2 = Open WebUI mit Harness, Overrides, Guard, Tools, Prompts, Registrierungsskript, Datei-Proxy und `personio-directory`.
- Portaländerungen seit `66db7ba` (17 Dateien, keine gelöschten, keine neuen Abhängigkeiten):
  - `stack/kb-admin-api/app/`: `document_lifecycle.py`, `main.py`, `maintenance.py` geändert; `personal_data.py`, `retrieval_metadata.py` neu.
  - `admin-dashboard/`: `app/header-actions.css`, `app/portal.css`, `components/KnowledgePortal.tsx` geändert; `build/sites-vite-plugin.ts`, `AGENTS.md` neu.
  - Tests unter `stack/kb-admin-api/tests/` und `admin-dashboard/tests/`.
- Darin enthalten u. a.: Kundendaten-Erkennung mit Bestätigungspflicht (`eaa4f62`–`94cd7ac`), endgültiges Löschen räumt Mitteilungen auf (`6654ae6`), Retrieval-Metadaten (`fca773c`, `254aef0`).
- Schema: `kb-admin-api` legt beim Start an: Tabellen `document_retrieval_metadata` und `document_evidence_relations`, Spalten `document_evidence_relations.document_id`, `document_retrieval_metadata.confirmed_by_user_id`, `document_retrieval_metadata.confirmed_at`. Alle über `CREATE TABLE IF NOT EXISTS` bzw. `ALTER TABLE … ADD COLUMN`; vom alten Code ignoriert.
- Compose und `env.production.template` haben seit August nur Änderungen für Open WebUI und `personio-directory` (Paket 2). Paket 1 braucht keine Konfigurationsänderung.
- Offene Frage: `kb-sync` liest Retrieval-Metadaten (`stack/kb-sync/app/canonical_inventory.py`) und hat selbst 7 geänderte Dateien. Ob `kb-sync` mit in Paket 1 muss, klärt Task 1.

## Dateien

| Datei | Zweck |
| --- | --- |
| `deploy/wissen-portal-oktober-<Datum>/files/…` | Kopien der geänderten Dateien in Repository-Struktur (`deploy/` ist git-ignoriert) |
| `deploy/wissen-portal-oktober-<Datum>/install.sh` | Rollout mit Sicherung, Prüfung, Belegen und automatischer Rückabwicklung |
| `deploy/wissen-portal-oktober-<Datum>/README.txt` | Inhalt, Nachweis, manuelle Abnahme, manueller Rollback |
| `docs/operations/netcup-production-deployment.md` | Eintrag in „Rollout History“ erst nach erfolgreichem Serverlauf |

---

### Task 1: Kopplung Portal-API ↔ kb-sync klären

- [ ] **Step 1: Prüfen, ob der Portal-Code Dateien schreibt, die kb-sync liest.**

Run (Repository-Root):

```bash
git diff 66db7ba..HEAD -- stack/kb-admin-api/app | grep -nE "^\+.*(rag\.md|write_text|frontmatter|RAGMetadataWriter)"
grep -rn "class RAGMetadataWriter" stack/kb-admin-api/app
git diff --stat 66db7ba..HEAD -- stack/kb-sync
```

- [ ] **Step 2: Prüfen, ob der alte kb-sync-Stand mit den neuen Tabellen und Dateien umgehen kann.** `git show 66db7ba:stack/kb-sync/app/canonical_inventory.py` lesen und feststellen, ob er `document_retrieval_metadata` oder ein geändertes `rag.md`-Format liest.

- [ ] **Step 3: Entscheidungsregel anwenden und im Plan festhalten.**
  - Ändert der neue Portal-Code das Format von `rag.md` oder liest der neue kb-sync-Stand Daten, die erst der neue Portal-Code schreibt (oder umgekehrt) → **kb-sync kommt in Paket 1**: alle seit `66db7ba` geänderten Dateien unter `stack/kb-sync/` aufnehmen, `kb-sync` in `SERVICES` ergänzen; zusätzlich prüfen, dass der neue kb-sync keine Open-WebUI- oder Harness-Dateien voraussetzt (`grep -rn "open_webui\|kahle_knowledge_harness" stack/kb-sync/app`), sonst Abbruch und Rücksprache.
  - Sonst bleibt kb-sync in Paket 2.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/2026-10-22-production-rollout-portal-package.md
git commit -m "docs(plan): decide whether kb-sync joins the portal package"
```

### Task 2: Lokaler Nachweis auf dem Paketstand

- [ ] **Step 1: Arbeitsbaum sauber, Stand festhalten**

Run: `git status --short` (nur `tmp/`), `git rev-parse --short HEAD` → als `<Commit>` in README übernehmen.

- [ ] **Step 2: Full Verify**

Run: `.\scripts\run-local-tests.ps1 -Tier Full -Python .\.venv-verify\Scripts\python.exe -Npm npm.cmd`
Expected: `EXIT=0`. Die Testzahlen je Check für das README notieren.

- [ ] **Step 3: Lokaler Portal-Neubau und Smoke-Test**

Run: `.\scripts\start-stack.ps1 -ComposeArgs kb-admin-api,kb-maintenance,kb-upload-worker,kb-admin-dashboard`
Danach: `/wissen/` unter `http://localhost:3004` lädt; synthetischer Upload mit `tmp/ui-check/kundendaten-testformular.txt` zeigt den Kundendaten-Hinweis (wie am 12.10. abgenommen).

### Task 3: Paket bauen

**Files:**
- Create: `deploy/wissen-portal-oktober-<YYYYMMDD>/files/…`, `install.sh`, `README.txt`

- [ ] **Step 1: Dateien kopieren** (PowerShell, Repository-Root; `<YYYYMMDD>` = Bautag)

```powershell
$name = "wissen-portal-oktober-<YYYYMMDD>"
$files = git diff --name-only --diff-filter=AM 66db7ba..HEAD -- stack/kb-admin-api admin-dashboard
# Bei Entscheidung "kb-sync in Paket 1" (Task 1) zusätzlich:
# $files += git diff --name-only --diff-filter=AM 66db7ba..HEAD -- stack/kb-sync
foreach ($f in $files) { New-Item -ItemType Directory -Force (Split-Path "deploy/$name/files/$f") | Out-Null; Copy-Item $f "deploy/$name/files/$f" }
(Get-ChildItem -Recurse -File "deploy/$name/files").Count
```

Expected: 17 (bzw. 17 + kb-sync-Dateien). `git diff --name-only --diff-filter=D 66db7ba..HEAD -- stack/kb-admin-api admin-dashboard` muss leer sein; sonst fehlt dem Paket eine Löschung → Abbruch und Plan ergänzen.

- [ ] **Step 2: `install.sh` aus `deploy/wissen-versionsarchiv-20260821/install.sh` übernehmen** und genau diese Stellen ändern:

```bash
BACKUP="${ROOT}/.rollout-backups/wissen-portal-oktober-before-$(date -u +%Y%m%dT%H%M%SZ)"
SERVICES=(kb-admin-api kb-maintenance kb-upload-worker kb-admin-dashboard)   # + kb-sync nach Task 1
```

Den Block `=== NEUEN CODE IM CONTAINER BELEGEN ===` ersetzen durch:

```bash
echo "=== NEUEN CODE IM CONTAINER BELEGEN ==="
sudo docker exec kb-admin-api sh -c "test -f /app/app/personal_data.py"
sudo docker exec kb-admin-api sh -c "grep -q 'require_personal_data_confirmation' /app/app/main.py"
sudo docker exec kb-admin-api sh -c "grep -q 'personal_data_confirmation_required' /app/app/document_lifecycle.py"
sudo docker exec kb-admin-api sh -c "test -f /app/app/retrieval_metadata.py"
sudo docker exec kb-admin-dashboard sh -c "grep -rlq 'Kundendaten erkannt' /app/dist/client/assets"
```

Den Block `=== SCHEMA-ERGÄNZUNGEN BELEGEN ===` ersetzen durch (nur lesend):

```bash
echo "=== SCHEMA-ERGÄNZUNGEN BELEGEN ==="
sudo docker exec kb-admin-api python -c "
import os, sqlite3, sys
path = os.getenv('KB_PORTAL_DB_PATH', '/portal-data/wissensportal.sqlite3')
db = sqlite3.connect('file:' + path + '?mode=ro', uri=True)
def cols(table): return {row[1] for row in db.execute('PRAGMA table_info(' + table + ')')}
missing = ({'confirmed_by_user_id', 'confirmed_at'} - cols('document_retrieval_metadata')) | ({'document_id'} - cols('document_evidence_relations'))
missing |= ({'superseded_at', 'purged_at', 'previous_version_id'} - cols('document_versions'))
if missing:
    sys.exit('Fehlende Spalten oder Tabellen: ' + ', '.join(sorted(missing)))
print('Schema vollstaendig.')
"
```

Die Abschlusszeile ändern in:

```bash
echo "Offen: manuelle Abnahme laut README (Kundendaten-Upload, Standard-Upload, endgültiges Löschen)."
```

- [ ] **Step 3: Klären, wann die Metadaten-Tabellen entstehen.** `grep -n "RetrievalMetadataStore(" stack/kb-admin-api/app/main.py` und `_initialize` lesen. Entstehen sie beim Start von `kb-admin-api`, bleibt Step 2 so. Entstehen sie erst später, die Prüfung auf `document_versions` beschränken und das im README unter „Datenbank“ vermerken.

- [ ] **Step 4: README.txt schreiben** im Aufbau von `deploy/wissen-versionsarchiv-20260821/README.txt`: INHALT (Commit-Bereich `66db7ba..<Commit>`, ausdrücklich: Open WebUI, Middleware, Guard, Tools, Prompts, Datei-Proxy, `personio-directory` sind NICHT enthalten), WAS SICH ÄNDERT (Kundendaten-Erkennung mit Bestätigung; endgültiges Löschen räumt Mitteilungen und abgeleitete Zeilen auf; Retrieval-Metadaten), DATENBANK (Tabellen und Spalten aus der Ausgangslage, alle additiv), BETROFFENE DIENSTE, LOKALER NACHWEIS (Zahlen aus Task 2), ROLLOUT, MANUELLE ABNAHME, MANUELLER ROLLBACK (wie im Vorgänger, mit neuem Namen und Dienstliste).

MANUELLE ABNAHME nach dem Rollout:
1. Ein Dokument mit synthetischen Kundendaten hochladen: Hinweis „Kundendaten erkannt“, Weiterleiten gesperrt bis zur Bestätigung, danach Freigabeweg.
2. Ein reguläres Dokument hochladen und freigeben (Standardweg unverändert).
3. Ein Dokument endgültig löschen: keine verwaisten Mitteilungen in „Mitteilungen“.
4. Eine bekannte Wissensfrage in Vinci stellen: Quelle wird weiter gefunden (Index unverändert erreichbar).

- [ ] **Step 5: Skript prüfen**

Run (Git Bash): `bash -n deploy/<name>/install.sh` → keine Ausgabe. Falls `shellcheck` vorhanden: `shellcheck deploy/<name>/install.sh` ohne Fehler der Stufe error.

- [ ] **Step 6: Archiv und Prüfsumme**

```bash
cd deploy && tar -czf <name>.tar.gz <name> && sha256sum <name>.tar.gz
```

Die Prüfsumme im README des Rollout-Eintrags (Task 5) notieren.

### Task 4: Übergabe an den Nutzer

- [ ] **Step 1:** Dem Nutzer Paketname, SHA-256, Commit-Bereich, Dienstliste, die Befehle für den Serverlauf und die manuelle Abnahme vorlegen. Serverlauf (vom Nutzer, auf `vinci-prod-01`):

```bash
sha256sum wissen-portal-oktober-<YYYYMMDD>.tar.gz
tar -xzf wissen-portal-oktober-<YYYYMMDD>.tar.gz
sudo bash wissen-portal-oktober-<YYYYMMDD>/install.sh
```

- [ ] **Step 2:** Nichts auf dem Server ausführen. Der Rollout startet nur nach ausdrücklicher Freigabe durch den Nutzer und wird von ihm ausgeführt.

### Task 5: Nach erfolgreichem Serverlauf dokumentieren

- [ ] **Step 1:** In `docs/operations/netcup-production-deployment.md` unter „Rollout History“ einen Eintrag im Stil von 2026-08-21 ergänzen: Datum, Paket, SHA-256, Commit-Bereich, gebaute Dienste, unberührte Dienste, Inhalt, Schema, „Nicht enthalten: Paket 2“, Ergebnis der manuellen Abnahme.

- [ ] **Step 2: Commit und Push**

```bash
git add docs/operations/netcup-production-deployment.md
git commit -m "docs(ops): record the October portal rollout"
git push origin feat/harness-eval-foundation
```

## Paket 2: Vorbedingungen (eigener Plan nach Paket 1)

Paket 2 wird erst geplant, wenn Paket 1 live und abgenommen ist. Vorher zu klären:

- **Produktionskonfiguration:** Lokal gemessen ist `KAHLE_KNOWLEDGE_ROUTING_MODE=model_led` und `KAHLE_ANSWER_ENFORCEMENT=enforce`; `stack/env.production.template` steht auf `legacy`/`observe`. Nutzerentscheidung nötig, welche Kombination live geht; ungemessene Kombinationen werden vorher lokal gemessen.
- **Personio:** `personio-directory` braucht `PERSONIO_CLIENT_ID` und `PERSONIO_API` in `stack/.env.production` (nur vom Nutzer/IT einzutragen).
- **Umfang:** Overrides (`stack/open-webui-overrides`, neue Mounts in `docker-compose.yml`), Guard, Tools (in `webui.db`, über `scripts/openwebui/register-kahle-workflow-tool.py`), Systemprompts, `owui-file-proxy`-Image, `kb-sync` (falls nicht in Paket 1), neuer Dienst `personio-directory`.
- **Serverabnahme** laut „Mandatory Server Tests“, insbesondere die 21-Fragen-Laufzeit-Eval und Rollenprüfungen mit echten Konten.

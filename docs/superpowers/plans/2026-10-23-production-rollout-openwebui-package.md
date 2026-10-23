# Produktions-Rollout Paket 2: Open WebUI, Harness, Tools, Datei-Proxy

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Nichts in diesem Plan läuft auf dem Server; Übertragung, Installation und Passworteingaben führt der Nutzer aus.

**Goal:** Den Open-WebUI-Teil von `vinci-prod-01` (Harness, Middleware, Router, Guard, Tools, Haupt-Systemprompts, Datei-Proxy, kb-sync-Inventar) auf den Stand des Branches bringen, mit `KAHLE_ANSWER_ENFORCEMENT=observe`, ohne die Spezial-Vincis oder das Portal zu berühren.

**Architecture:** Gleiches Verfahren wie Paket 1 (`wissen-portal-oktober-20261022`), erweitert um die Open-WebUI-Registrierung: Der Installer prüft Paketdateien (`SHA256SUMS`) und den Serverstand (`BASELINE.sha256` = die am 23.10. inventarisierten Prüfsummen), sichert Dateien und die Registrierungstabellen der Open-WebUI-Datenbank, tauscht die Dateien, baut `owui-file-proxy` und `kb-sync`, registriert Tools, Guard und die drei Haupt-Vinci-Modelle über `register-kahle-workflow-tool.py` und erstellt `open-webui` neu. Bei jedem Fehler werden Dateien, Datenbankzeilen und Dienste zurückgesetzt.

**Tech Stack:** Bash, Docker Compose, Python 3.11 (im Container), SQLite.

---

## Ausgangslage (Inventur 23.10., `tmp/inventar-paket2-20261023T094112Z.txt`)

- 126 Dateien in den Paket-2-Bereichen erfasst; 73 entsprechen HEAD (LF oder CRLF). Abweichende Stände: Harness und Middleware = Rollout 24.09. (`ddf1643`); Router `openai.py`, Datei-Proxy `main.py`, `kb-sync/canonical_inventory.py` = 06.08. (`feb85a7`); `docker-compose.yml` = 07.09. (`819630f`); Guard, Haupt-Prompts, Tool-Bundles = Stand des Rollouts 24.09. (`cc610b1`).
- Drei Dateien passten zu keinem Commit: `document-worker/app/main.py` und `kb-sync/app/kb_sync.py` sind inhaltsgleich mit HEAD (nur Zeilenenden); `open-webui-tools/build_tools.py` ist der Generator des Reparaturpakets vom 18.09., dessen Einbettung von `functional_contact_contract` im HEAD-Generator enthalten ist (Bundles synchron, kein externer Import).
- Konfiguration: `KAHLE_KNOWLEDGE_ROUTING_MODE=model_led`, `KAHLE_ANSWER_ENFORCEMENT` nicht gesetzt (Code-Default `observe`), Personio-Zugangsdaten gesetzt, `ENABLE_PERSISTENT_CONFIG=False` (Tool-Server-Verbindung wird bei jedem Start aus der Umgebung gelesen).
- Registrierung: Guard und die Prompts der drei Haupt-Modelle = Rollout 24.09.; Tool-Inhalte setzt das Registrierungsskript aus mehreren Dateien zusammen, Datei-Prüfsummen passen daher nicht direkt.

## Nutzerentscheidungen (23.10.)

1. **Vollständiger Angleich** aller Paket-2-Bereiche an den Branch (keine Teilmenge).
2. **`observe` bleibt** in der Produktion (Phase-2-Entscheidung). Weil alle Messungen seit Phase 3 mit `enforce` liefen, wird die Kombination HEAD + `observe` vorher lokal gemessen (Task 1).

## Paketzuschnitt

- Nur Laufzeitdateien, die vom Serverstand abweichen (Ausgangsliste 51; ohne 21 Tests, ohne lokale Hilfsskripte `kahle-harness-acceptance*`, `provision-local-*`, `update-local-rag-tools.ps1`, ohne Spezial-Vinci-Dateien `register-vinci-models.py` und `vincis/kahle-email-vinci-systemprompt.md`).
- Inhalt: `scripts/openwebui/register-kahle-workflow-tool.py`, `stack/docker-compose.yml`, `stack/env.production.template`, `stack/kb-sync/app/canonical_inventory.py`, `stack/open-webui-functions/kahle_toolcall_guard.py`, 5 Overrides (`routers/openai.py`, `utils/kahle_internal_knowledge.py`, `utils/kahle_knowledge_harness.py`, `utils/kahle_locations.py` neu, `utils/middleware.py`), 2 Haupt-Prompts, 7 Tool-Dateien (Generator, Quellen, `dist`-Bundles, `kahle_locations.py` neu), 4 Datei-Proxy-Module (`main.py`, `chat_scope.py` neu, `generated_links.py` neu, `kahle_document_theme.py`).
- Compose ändert nur `open-webui`: `KAHLE_ANSWER_ENFORCEMENT` (Default `observe`), `KAHLE_ANSWER_RETRY_TIMEOUTS`, Mount `kahle_locations.py`, Doc-Worker-Kopfzeilen `X-Kahle-Chat-Id`/`X-Kahle-User-Id` (vom neuen Datei-Proxy ausgewertet).
- Dienste: Build `owui-file-proxy`, `kb-sync`; `open-webui` neu erstellen (neue Mounts und Umgebung); `personio-directory`, `document-worker`, `academy-provisioner`, Portal, Caddy, Qdrant, n8n unberührt.

---

### Task 1: Lokale Messung HEAD + `observe`

- [ ] **Step 1:** `stack/docker-compose.local-edge.yml` liest `KAHLE_LOCAL_ANSWER_ENFORCEMENT` (Default `enforce`, `e020927`). Open WebUI mit `$env:KAHLE_LOCAL_ANSWER_ENFORCEMENT="observe"` und `start-stack.ps1 -NoBuild -ComposeArgs --no-deps,open-webui` neu erstellen; `printenv KAHLE_ANSWER_ENFORCEMENT` = `observe`.
- [ ] **Step 2:** Gültiges Token in `%USERPROFILE%\.kahle-owui-token` (`/api/models` = 200), Laufzeit-Eval je Modell nach `tmp\runtime-pkg2-observe`; `StartedAt` vor/nach vergleichen.
- [ ] **Step 3:** Vergleich mit der 4b-Abnahme (`enforce`). Abnahme: Routing je Modell höchstens 2 Fälle unter 4b; ausgelieferte Verstöße werden bei `observe` nicht verhindert, deshalb werden `attempt_blocking_violations` je Modell berichtet und dem Nutzer vorgelegt.
- [ ] **Step 4:** Lokal zurück auf `enforce` (Variable entfernen, Open WebUI neu erstellen, `printenv` prüfen).

### Task 2: Paket bauen

- [ ] **Step 1:** Build-Skript nach dem Muster von Paket 1: Dateien per `git show HEAD:<pfad>` (LF), `SHA256SUMS`, `BASELINE.sha256` aus der Inventur (exakte Serverprüfsumme je Datei, `ABSENT` für neue Dateien).
- [ ] **Step 2:** `install.sh` mit den Schritten: (1) `SHA256SUMS`, (2) Serverstand gegen `BASELINE.sha256` und `compose config` mit der neuen Compose-Datei, `--check` endet hier; (3) Sicherung der Dateien und der Tabellen `tool`, `function`, `model`, `config`, `access_grant` aus `webui.db` (zeilengenau als JSON) plus vollständige SQLite-Sicherungskopie; (4) Dateien tauschen; (5) Syntax, `build_tools.py --check`, `compose config`; (6) Build `owui-file-proxy`, `kb-sync`; (7) Registrierung über Staging im Container mit `KAHLE_REPO_ROOT` wie am 24.09.; (8) `up -d --no-deps owui-file-proxy kb-sync open-webui`; (9) Healthchecks; (10) Belege: Mounts und Code im Container (`document_tools_needed`, `prompt_composition`, `kahle_locations`), Umgebung `KAHLE_ANSWER_ENFORCEMENT=observe`, Registrierung (Guard aktiv, `builtinTools` notes/tasks/automations/time aus bei den drei Haupt-Modellen), Datei-Proxy-Module; (11) HTTPS `/healthz` 200, `/wissen/` 401.
- [ ] **Step 3:** Rückabwicklung ab Schritt 3: Dateien zurück, Tabellen aus der JSON-Sicherung in einer Transaktion zurückschreiben, `owui-file-proxy`/`kb-sync` neu bauen, `open-webui` neu erstellen.
- [ ] **Step 4:** Lokal simulieren (Stubs wie Paket 1): Serverstand laut Inventur → `--check` ok; abweichende Datei → Abbruch ohne Änderung; Fehler bei Registrierung → Dateien und Tabellen zurück; vollständiger Lauf → „ROLLOUT ERFOLGREICH“. Zusätzlich die Tabellen-Sicherung und -Wiederherstellung gegen eine Kopie der lokalen `webui.db` prüfen.
- [ ] **Step 5:** Archiv entpacken, `bash -n`, `SHA256SUMS`, 0 CR; Prüfsumme festhalten.

### Task 3: Übergabe, Serverlauf, Abnahme

- [ ] **Step 1:** Befehle für Übertragung, `--check` und Installation an den Nutzer. Installation erst nach `--check` ohne Abweichung.
- [ ] **Step 2:** Fachliche Abnahme durch den Nutzer in neuen Chats: Wissensfrage mit Quelle (`rag_chat`), Personenfrage (`personio_directory`), Zuständigkeit mit beiden Quellen, „Erstelle mir aus dem Ergebnis eine PDF“ und Folgefrage zur erzeugten Datei, ein Upload einer Datei mit Bearbeitung (Doc-Worker erscheint nur mit Datei).
- [ ] **Step 3:** Rollout-Historie in `docs/operations/netcup-production-deployment.md` ergänzen; Commit und Push.

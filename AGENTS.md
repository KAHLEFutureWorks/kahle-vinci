# Project Instructions

## Project Overview

KAHLE-Vinci ist ein Compose-zentriertes KI- und Wissensportal. Open WebUI ist
der zentrale Chat-Einstieg. Das rollenbasierte Wissensportal läuft unter
`/wissen/`. Eigenständige Python-Dienste übernehmen Portal-Governance,
Dokumentenverarbeitung, Retrieval, Academy-Provisionierung und das interne
Personio-Verzeichnis.

Der aktuelle technische Aufbau ist in [ARCHITECTURE.md](ARCHITECTURE.md), das
Sicherheitsmodell in [SECURITY.md](SECURITY.md) und die belegten Entscheidungen
in [DECISIONS.md](DECISIONS.md) dokumentiert.

## Technology Stack

- Docker Compose mit Caddy als Edge-Komponente
- Open WebUI `v0.11.0` mit eingecheckten KAHLE-Overrides
- Python 3.11 für die meisten Dienste und die lokale Verification; `kb-sync`
  verwendet im Container Python 3.12.11
- FastAPI, SQLite und Qdrant
- React 19, Next.js 16, Vinext/Vite und TypeScript im Admin-Dashboard
- n8n und SearxNG für freigegebene Automations- und Websuchpfade
- IONOS für Chat-, Embedding- und Rerank-Modelle

## Repository Map

- `stack/`: Compose, Python-Dienste, Open-WebUI-Anpassungen und Stack-Tests.
  Lokale Regeln stehen in [stack/AGENTS.md](stack/AGENTS.md).
- `admin-dashboard/`: Wissensportal-Frontend. Lokale Regeln stehen in
  [admin-dashboard/AGENTS.md](admin-dashboard/AGENTS.md).
- `scripts/`: lokaler Verification-Runner und betriebliche Hilfsskripte.
- `docs/operations/`: aktuelle Betriebsdokumentation.
- `docs/superpowers/plans/`: historische Pläne, keine aktuelle
  Architektur-Source-of-Truth.
- `eval/rag/`: Retrieval-Evaluation und spezialisierte Laufzeitprüfungen.
- `n8n/`: kanonischer Workflow-Export und lokale n8n-Artefakte.
- `use-cases/`: fachliche Beispiele und Szenarien.

## Architecture Boundaries

- Browserzugriffe auf das Portal laufen über Caddy und `/wissen/`.
- Das Frontend zeigt Berechtigungen an, entscheidet sie aber nicht. Die
  Portal-API prüft Identität, Status, Rolle und Knowledge-Base-Rechte.
- Portalmetadaten und Portaldateien unter `kb-portal-data` sind führend.
  Qdrant ist ein abgeleiteter Suchindex.
- Klassische Quellen unter `knowledgebases` bleiben vom Portal-Datenmodell
  getrennt.
- Externe Systeme werden über ihre vorhandenen Adapter oder Dienste
  angesprochen. Neue Direktzugriffe aus UI oder fachfremden Diensten sind nicht
  zulässig.
- Die Python-Dienste besitzen jeweils ein eigenes Paket namens `app`. Ihre
  Tests und Imports müssen pro Dienst isoliert bleiben.

## Implementation Rules

- Verwende vorhandene Module, Clients, Services und Verträge, bevor neue
  Abstraktionen angelegt werden.
- Ergänze Portal-Endpunkte über die bestehende Governance-, Lifecycle-,
  Ingest- und Job-Struktur. Umgehe keine vorhandenen Prüfpfade.
- Halte Portalrechte `can_read` und `can_upload` getrennt.
- Behandle Qdrant niemals als alleinige oder führende Dokumentquelle.
- Bearbeite Quellen unter `stack/open-webui-tools/` und erzeuge danach die
  synchronisierten Bundles. Ändere `dist/` nicht isoliert.
- Verändere Runtime-Requirements der einzelnen Dienste nicht über
  `stack/requirements-dev.txt`. Diese Datei ist nur die gemeinsame lokale
  Verification-Kombination.
- Bewahre bestehende Mount-Modi, Container-Härtung und Servicegrenzen bei
  Compose-Änderungen.

## Development Commands

Verification-Umgebung aus dem Repository-Root anlegen:

```powershell
py -3.11 -m venv .venv-verify
.\.venv-verify\Scripts\python.exe -m pip install -r stack\requirements-dev.txt
.\.venv-verify\Scripts\python.exe -m pip check

Push-Location admin-dashboard
npm.cmd ci
Pop-Location
```

Lokalen Stack mit den dafür vorgesehenen Secrets und Overlays starten:

```powershell
.\scripts\start-stack.ps1
```

Produktionswerte werden ausschließlich aus einer geschützten, nicht
versionierten `stack/.env.production` geladen. Die einzige kanonische Vorlage
ist `stack/env.production.template`.

## Verification

[docs/VERIFICATION.md](docs/VERIFICATION.md) ist der kanonische Einstiegspunkt.

- Targeted Checks laufen während der Implementierung für den kleinsten
  betroffenen Dienst, Vertrag oder statischen Bereich.
- Fast ist für kleinere bis mittlere, lokal begrenzte Änderungen vorgesehen.
- Full ist vor Abschluss substantieller Änderungen erforderlich. Full ist
  außerdem Pflicht bei bereichsübergreifenden, Security-, Datenmodell-,
  Integrations- oder Infrastrukturänderungen.
- Specialized wird nur für betroffene Bereiche zusätzlich ausgeführt, wenn ein
  laufender Stack, externe APIs, reale Konfigurationen, Secrets oder Testkorpora
  erforderlich sind.

Kanonischer Fast Verify:

```powershell
.\scripts\run-local-tests.ps1 -Tier Fast -Python .\.venv-verify\Scripts\python.exe -Npm npm.cmd
```

Kanonischer Full Verify:

```powershell
.\scripts\run-local-tests.ps1 -Tier Full -Python .\.venv-verify\Scripts\python.exe -Npm npm.cmd
```

Ohne `-Tier` läuft Full. Targeted und Specialized ersetzen den erforderlichen
Fast oder Full Verify nicht.

## High-Risk Areas

Zusätzliche Sorgfalt ist erforderlich bei Portalrollen und ACLs, klassischer
Vector-Freigabe, Secure Ingest, Personio-Daten, Academy-Provisionierung,
Produktions-Env, Compose-Mounts, Backups und externen Integrationen.

## Never Do

- Keine Secrets, realen Produktions-Env-Dateien oder Mitarbeiterdaten
  einchecken oder in Testausgaben übernehmen.
- Keine Authentifizierungs-, Rollen-, ACL-, Bestätigungs- oder Unlock-Prüfung
  im Client nachbilden oder serverseitig umgehen.
- Keine ignorierten Runtime- und Übergabeordner wie `deploy/`, `backups/`,
  `kb-portal-data/`, `knowledgebases/`, `openwebui_data/`, `kb-sync-state/` oder
  `qdrant-snapshots/` als Architektur-Evidence behandeln.
- Keine Python-Tests mehrerer Dienste mit gleichnamigem `app`-Paket in einem
  gemeinsamen pytest-Prozess ausführen.
- Keine Produktionsaktivierung, externen Live-Probes oder Rollouts ohne
  ausdrücklichen Auftrag ableiten oder durchführen.

## Documentation Map

- [ARCHITECTURE.md](ARCHITECTURE.md): Laufzeit, Datenflüsse und Grenzen
- [SECURITY.md](SECURITY.md): Sicherheitsmodell und Coding-Regeln
- [DECISIONS.md](DECISIONS.md): bestätigte Policies und beobachtete Konventionen
- [docs/VERIFICATION.md](docs/VERIFICATION.md): Verification-Tiers und Befehle
- [docs/operations/data-paths.md](docs/operations/data-paths.md): Persistenz und Mounts
- [docs/operations/kb-admin-dashboard.md](docs/operations/kb-admin-dashboard.md): Portal und klassische Vector-Administration
- [docs/operations/netcup-production-deployment.md](docs/operations/netcup-production-deployment.md): Produktionsbetrieb

# Stack Instructions

## Scope

Diese Regeln gelten für `stack/`: Compose-Dateien, Python-Dienste,
Open-WebUI-Overrides, Tool-Bundles und Stack-Tests. Die allgemeinen Regeln aus
[`../AGENTS.md`](../AGENTS.md) gelten zusätzlich.

## Local Architecture

- `docker-compose.yml` ist die Basisdefinition. Overlays ergänzen lokale Edge-,
  Produktions-, Maintenance- und UI-Konfiguration.
- `kb-admin-api` stellt Portal- und klassische Vector-Endpunkte bereit. Dasselbe
  Image versorgt auch Maintenance-, Upload- und optional Backup-Worker.
- `kb-sync` liest klassische und Portalquellen und erzeugt abgeleitete Qdrant-
  und BM25-Indizes.
- `owui-file-proxy` und `document-worker` bilden die interne
  Dokumentverarbeitungsgrenze.
- `personio-directory` ist ein interner, lesender Verzeichnisdienst.
- `academy-provisioner` liest Open-WebUI-Benutzer nur lesend und hält eigenen
  idempotenten Zustand.
- `open-webui-overrides` enthält versionsgebundene KAHLE-Anpassungen.
- `open-webui-tools` enthält wartbare Quellen und daraus erzeugte
  eigenständige Bundles.

## Local Implementation Rules

- Jeder Python-Dienst besitzt sein eigenes Paket `app`. Importiere keinen
  Dienst direkt über den Repository-Root in einen anderen Dienst. Verwende die
  vorhandene HTTP-, Volume- oder Jobgrenze.
- Ergänze Portal-Fachlogik in den bestehenden Governance-, Lifecycle-, Ingest-,
  Decision-, Maintenance- oder Backupmodulen. Halte Routen in `main.py` so
  schmal, wie es die bestehende Struktur erlaubt.
- Neue Portal-Endpunkte verwenden die bestehende Open-WebUI-Identität und die
  passenden serverseitigen Rollen- oder ACL-Prüfungen.
- `can_read` und `can_upload` bleiben getrennt. Klassische Vector-Adminrechte
  werden nicht aus Portalrollen abgeleitet.
- Schreibe Portalmetadaten und Portaldateien in den etablierten Portalbestand.
  Qdrant bleibt abgeleitet.
- Behandle `knowledgebases` als getrennten klassischen Bestand. Prüfe vor
  Mount-Änderungen die tatsächlichen Read-/Write-Modi in allen Compose-Dateien.
- Personio-Aufrufe bleiben lesend und im `personio-directory`-Adapter. Rohdaten,
  Namen und Providerantworten gehören nicht in Fehlerlogs.
- Academy-Provisionierung bleibt auf Open-WebUI-Rollen `user` und `admin`
  begrenzt. `pending` darf keine Provisionierung auslösen.
- Bearbeite Tool-Quellen, führe danach `build_tools.py` aus und prüfe den Sync.
  Ändere die Bundles unter `dist/` nicht allein.
- `stack/env.production.template` ist die einzige Produktionsvorlage. Echte
  Werte und `stack/.env.production` bleiben unversioniert.
- Bewahre `read_only`, `no-new-privileges`, `cap_drop`, interne API-Keys,
  Healthchecks und restriktive Mounts, sofern die Aufgabe keine ausdrücklich
  geprüfte Änderung verlangt.

## Local Commands

Alle Befehle werden aus dem Repository-Root ausgeführt:

```powershell
$py = ".\.venv-verify\Scripts\python.exe"

& $py -m pytest stack\tests -q -p no:cacheprovider
& $py -m pytest stack\kb-admin-api\tests -q -p no:cacheprovider
& $py -m pytest stack\kb-sync\tests -q -p no:cacheprovider
& $py -m pytest stack\academy-provisioner\tests -q -p no:cacheprovider
& $py -m pytest stack\personio-directory\tests -q -p no:cacheprovider

& $py stack\tests\compose_static_check.py
& $py stack\tests\n8n_workflow_static_check.py
& $py stack\open-webui-tools\build_tools.py --check
```

Führe nur die betroffenen Targeted Checks während der Implementierung aus.
Danach gilt weiterhin der erforderliche Fast oder Full Verify aus
[`../docs/VERIFICATION.md`](../docs/VERIFICATION.md).

Die Python-Suiten dürfen nicht zu einem gemeinsamen pytest-Aufruf verbunden
werden. Der kanonische Runner startet sie mit getrennten Modulpfaden.

## Local High-Risk Areas

- `kb-admin-api/app/main.py` und `portal_governance.py`
- Secure Ingest, Quarantäne, Malwareprüfung und Dokumentkonvertierung
- Portal-Lifecycle, Freigaben, Löschung, Restore und Backups
- Open-WebUI-Middleware und Toolcall-Guard
- Personio- und Academy-Integrationen
- Compose-Mounts, Netzwerke, Ports, Profile und Container-Härtung
- Caddy-Routen, Sessionweitergabe und Security-Header
- Produktions-Env und Secret-Namen

Security-, Datenmodell-, Integrations- oder Infrastrukturänderungen verlangen
Full Verify und die betroffene Specialized Verification. Produktive
Compose-Prüfungen dürfen keine aufgelösten Secrets ausgeben.

## Parent and Deeper Documentation

- [`../ARCHITECTURE.md`](../ARCHITECTURE.md)
- [`../SECURITY.md`](../SECURITY.md)
- [`../DECISIONS.md`](../DECISIONS.md)
- [`../docs/VERIFICATION.md`](../docs/VERIFICATION.md)
- [`../docs/operations/data-paths.md`](../docs/operations/data-paths.md)
- [`../docs/operations/kb-admin-dashboard.md`](../docs/operations/kb-admin-dashboard.md)
- [`../docs/operations/netcup-production-deployment.md`](../docs/operations/netcup-production-deployment.md)
- [`tests/README.md`](tests/README.md)

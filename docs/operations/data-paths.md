# Datenpfade

Der Stack nutzt Docker-Volumes für containerverwaltete Daten und kontrollierte
Host-Mounts für betriebliche Daten, Konfigurationen und lokale Overrides. Die
folgenden Tabellen bilden die aktuell eingecheckten Compose-Dateien ab. Ein
Mount ohne `:ro` ist aus Docker-Sicht read/write, auch wenn der jeweilige Dienst
ihn fachlich nur lesend verwendet.

## Docker-Volumes

| Volume | Gültigkeitsbereich | Eingebundene Dienste und Modus | Zweck |
| --- | --- | --- | --- |
| `open-webui` | Basis-Stack | `open-webui` rw, `owui-file-proxy` rw, `academy-provisioner` ro, `n8n` rw | Open-WebUI-Datenbank, Uploads und generierte Dateien. |
| `academy_provisioner_state` | Basis-Stack | `academy-provisioner` rw | Persistenter Provisionierungsstatus der Academy-Anbindung. |
| `personio_directory_state` | Basis-Stack | `personio-directory` rw | Lokale Personio-Synchronisationsdatenbank. |
| `qdrant_data` | Basis-Stack | `qdrant` rw | Persistente Qdrant-Vector-Daten. Nach einem Embedding-Wechsel ist ein Reindex erforderlich. |
| `document_worker_data` | Basis-Stack | `document-worker` rw, `n8n` rw | Temporäre, durch den Document Worker bereinigte Arbeitsdateien. |
| `clamav_data` | Basis-Stack | `clamav` rw | Virensignaturen und weitere persistente ClamAV-Daten. |
| `caddy_data` | Produktion und Maintenance-Edge | `caddy` rw | Von Caddy verwaltete Laufzeitdaten, insbesondere Zertifikatsdaten. |
| `caddy_config` | Produktion und Maintenance-Edge | `caddy` rw | Von Caddy verwaltete Konfigurationsdaten. |
| `caddy_local_data` | lokaler Edge-Stack | `caddy-local` rw | Lokale Caddy-Laufzeitdaten. |
| `caddy_local_config` | lokaler Edge-Stack | `caddy-local` rw | Lokale Caddy-Konfigurationsdaten. |

## Persistente Host-Mounts

| Hostpfad | Eingebundene Dienste und Modus | Zweck |
| --- | --- | --- |
| `${KAHLE_ROOT}/n8n` | `n8n` rw | n8n-Konfiguration, Datenbank und importierte Workflows. |
| `${KAHLE_ROOT}/knowledgebases` | `open-webui` ro, `owui-file-proxy` ro, `n8n` ro, `kb-sync` ro, `kb-admin-api` rw, `kb-upload-worker` rw | Klassische dateibasierte Knowledgebase-Quellen und Migrationsquelle für das Wissensportal. |
| `${KAHLE_ROOT}/kb-sync-state` | `open-webui` ro, `kb-admin-api` ro, `kb-upload-worker` ro, `kb-backup` ro, `kb-sync` rw | Synchronisationsstatus und hybrider BM25-Snapshot. |
| `${KAHLE_ROOT}/kb-portal-data` | `kb-admin-api` rw, `kb-maintenance` rw, `kb-upload-worker` rw, `kb-sync` ro, `kb-backup` ro | Kanonische Portal-SQLite-Datenbank, Portaldateien, Upload-Spool und lokale Mail-Capture-Datei. |
| `${KAHLE_ROOT}/assets` | `owui-file-proxy` ro | KAHLE-Vorlagen, Markenwerte und Logos für erzeugte Dateien. |
| `${KAHLE_ROOT}/stack/retention-reports` | `owui-file-proxy` ro | Reportablage für Retention-Status. |
| `${KAHLE_ROOT}/backups` | `kb-backup` rw | Primäres Ziel für verschlüsselte Portal-Backups. |
| `${KAHLE_BACKUP_SECONDARY_ROOT}` | `kb-backup` rw | Getrennt konfigurierbares sekundäres Backupziel; Standard ist `C:/kahle-vinci-backups`. |
| `${KAHLE_ROOT}/searxng` | `searxng` rw | SearxNG-Konfiguration. |

## Konfigurations- und Code-Bind-Mounts

Diese Mounts sind keine eigenständigen Datenablagen:

| Hostpfad | Ziel und Modus | Gültigkeitsbereich |
| --- | --- | --- |
| `${KAHLE_ROOT}/stack/open-webui-overrides/open_webui/routers/openai.py` | `open-webui`, ro | Basis-Stack |
| `${KAHLE_ROOT}/stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py` | `open-webui`, ro | Basis-Stack |
| `${KAHLE_ROOT}/stack/open-webui-overrides/open_webui/utils/personio_directory_client.py` | `open-webui`, ro | Basis-Stack |
| `${KAHLE_ROOT}/stack/open-webui-overrides/open_webui/utils/middleware.py` | `open-webui`, ro | Basis-Stack |
| `${KAHLE_ROOT}/stack/open-webui-overrides/open_webui/utils/misc.py` | `open-webui`, ro | Basis-Stack |
| `./caddy/Caddyfile` | `/etc/caddy/Caddyfile`, ro | Produktion und lokaler Edge-Stack |
| `./caddy/Caddyfile.maintenance` | `/etc/caddy/Caddyfile`, ro | Maintenance-Edge |
| `./caddy/Caddyfile.bootstrap` | `/etc/caddy/Caddyfile`, ro | OAuth-Bootstrap zusätzlich zum Produktions-Stack |

## `knowledgebases` und Portal-Persistenz

`knowledgebases/` ist nicht generell read-only. Die klassischen
Vector-Admin-Funktionen und der Upload-Worker besitzen dort Schreibzugriff.
Open WebUI, File-Proxy, n8n und `kb-sync` lesen die Quellen dagegen nur.

Das rollenbasierte Wissensportal speichert seine kanonischen Metadaten in
`kb-portal-data/wissensportal.sqlite3` und die zugehörigen Original- und
Markdown-Dateien unter `kb-portal-data/files/`. `kb-sync` liest diese Daten und
erzeugt daraus den Suchindex in Qdrant. Qdrant bleibt damit ein abgeleiteter
Index und nicht die führende Quelle.

## Legacy-Ordner

Historisch verwendete lokale Ordner wie `C:/kahle-vinci/ollama`, alte
Open-WebUI-Kopien oder projektnahe Datenordner außerhalb der offiziellen
Mounts sind keine Zielpfade für neue Persistenzlogik.

Diese Ordner werden nicht automatisch gelöscht. Sie sind nur:

- Archivbestand,
- Quelle für eine kontrollierte Migration,
- oder manuell zu prüfender Altbestand.

Vor jeder Bereinigung muss klar sein, welcher Dienst den Pfad noch nutzt und
ob ein Backup existiert.

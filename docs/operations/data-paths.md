# Datenpfade

Der Stack nutzt eine Mischung aus Docker Volumes und kontrollierten Host-Mounts. Diese Pfade sind bewusst festgelegt; lokale Altordner ausserhalb dieser Liste gelten nur als Legacy-Bestand, Archiv oder Migrationsquelle.

## Offizielle Docker Volumes

| Volume | Zweck |
| --- | --- |
| `open-webui` | Persistente Open-WebUI-Daten, Uploads, generierte Dateien und Datenbank. |
| `qdrant_data` | Persistente Qdrant-Vector-Daten. Nach Embedding-Wechsel ist ein Reindex erforderlich. |
| `document_worker_data` | Temporaere bzw. persistente Arbeitsdaten des Document Workers. |

## Offizielle Host-Mounts

| Pfad unter `KAHLE_ROOT` | Zweck |
| --- | --- |
| `n8n/` | n8n-Konfiguration, Datenbank und importierte Workflows. |
| `knowledgebases/` | Read-only Knowledgebase-Quelle fuer n8n-Reindex und RAG-Pipelines. |
| `searxng/` | SearxNG-Konfiguration. |
| `stack/retention-reports/` | Read-only Reportablage fuer Retention-Status im File-Proxy. |

## Legacy-Ordner

Historisch verwendete lokale Ordner wie `C:/kahle-vinci/ollama`, alte Open-WebUI-Kopien oder projektnahe Datenordner ausserhalb der offiziellen Mounts sind keine Zielpfade fuer neue Persistenzlogik.

Diese Ordner werden nicht automatisch geloescht. Sie sind nur:

- Archivbestand,
- Quelle fuer eine kontrollierte Migration,
- oder manuell zu pruefender Altbestand.

Vor jeder Bereinigung muss klar sein, welcher Dienst den Pfad noch nutzt und ob ein Backup existiert.

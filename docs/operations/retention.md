# Retention und Cleanup

Diese Betriebsnotiz beschreibt die vorhandenen n8n-Cleanup-Workflows. Beide Workflows sind exportiert, aber aktuell nicht aktiv geschaltet. Vor Aktivierung immer zuerst mit Dry-Run bzw. kontrollierter Testausfuehrung gegen eine Kopie oder einen klar begrenzten Datenbestand pruefen.

## Vorhandene Workflows

| Workflow | Zweck | Schedule | Aktueller Export-Status |
| --- | --- | --- | --- |
| `Cleanup Uploaded+Generated Files (15d)` | Loescht alte Uploads, generierte Ausgabedateien und temporaere Worker-Dateien. | Alle 15 Tage um 03:15 Uhr. | In `n8n/all-workflows.json` vorhanden, `active: false`. |
| `Retention Cleanup: OWUI Logs 180d + Chats 60d` | Entfernt alte Open-WebUI-Logs nach 180 Tagen und Chatdaten nach 60 Tagen. | Taeglich um 03:30 Uhr. | In `n8n/all-workflows.json`, `n8n/retention-workflow-export.json` und `n8n/scripts/workflow_retention_cleanup.json` vorhanden, `active: false`. |

## Dry-Run und Aktivierung

- Vor dem ersten produktiven Lauf die Workflow-Logik im n8n-Editor importieren und deaktiviert lassen.
- Wenn der Workflow einen Dry-Run-Parameter oder eine Deaktivierung der Schreib-/Loeschschritte anbietet, zuerst damit ausfuehren und das Report-Ergebnis pruefen.
- Wenn kein expliziter Dry-Run-Schalter vorhanden ist, die loeschenden Nodes voruebergehend deaktivieren oder gegen eine Testkopie der Volumes ausfuehren.
- Erst nach erfolgreicher Sichtpruefung der betroffenen Pfade/Datensaetze den Workflow aktivieren.

## Importhinweise

- n8n-Import ueber die UI verwenden und danach Credentials, Pfade und Mounts pruefen.
- Die Workflows duerfen keine echten Secrets enthalten. Zugangsdaten werden ausserhalb des Repos gepflegt.
- Nach Import nicht automatisch aktivieren, sondern Schedule, Zeitzone `Europe/Berlin` und Zielpfade gegen die aktuelle Compose-Umgebung pruefen.

## Betriebsrisiken

- Alte Downloadlinks auf generierte Dateien koennen nach Cleanup nicht mehr funktionieren. Benutzer sollten relevante Ergebnisse rechtzeitig lokal sichern.
- Retention-Laeufe koennen Daten dauerhaft entfernen. Vor Aenderungen an Fristen oder Pfaden ein Backup der betroffenen Docker Volumes erstellen.
- Lokale Legacy-Ordner sind nur Archiv- oder Migrationskandidaten und werden nicht automatisch geloescht.

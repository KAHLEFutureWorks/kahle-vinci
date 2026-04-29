# n8n Flow: Cleanup aller Uploads/Generates alle 15 Tage

## Ziel
- Alle Dateien aelter als 15 Tage loeschen aus:
  - `/mnt/open-webui-data/uploads` (hochgeladen)
  - `/mnt/open-webui-data/edited` (erzeugt durch `*_save`)
  - `/mnt/document-worker-data` (temporaere Worker-Artefakte)

## Voraussetzungen
- `n8n` muss diese Volumes gemountet haben (bereits in `stack/docker-compose.yml` ergaenzt):
  - `open-webui:/mnt/open-webui-data`
  - `document_worker_data:/mnt/document-worker-data`
- Cleanup-Skript liegt auf dem `n8n`-Mount:
  - `/home/node/.n8n/scripts/cleanup_file_artifacts.sh`

## Workflow-Aufbau (UI)

1. Node `Schedule Trigger`
- Name: `Every 15 Days`
- Intervall: alle 15 Tage
- Uhrzeit: z. B. 03:15 (nachts)

2. Node `Execute Command` (Dry-Run, optional fuer Startphase)
- Name: `Cleanup Dry Run`
- Command:
```bash
sh /home/node/.n8n/scripts/cleanup_file_artifacts.sh 15 dry-run
```

3. Node `Execute Command` (Produktivloeschung)
- Name: `Cleanup Delete`
- Command:
```bash
sh /home/node/.n8n/scripts/cleanup_file_artifacts.sh 15 delete
```

4. (Optional) Node `IF` + Benachrichtigung (Mail/Slack/Teams)
- Wenn Exit-Code ungleich 0: Fehler-Benachrichtigung.
- Sonst: Erfolg mit Anzahl/Listing aus `stdout`.

## Empfohlene Inbetriebnahme
1. Workflow zuerst manuell mit `dry-run` ausfuehren und Output pruefen.
2. Danach `Cleanup Delete` aktiv schalten.
3. Workflow veroeffentlichen (`Publish`), damit der Trigger produktiv laeuft.

## Hinweis
- Das Loeschen entfernt nur Dateien, keine Chat-/DB-Eintraege.
- Wenn alte Chat-Nachrichten noch auf Dateien verlinken, koennen Download-Links danach ins Leere zeigen.

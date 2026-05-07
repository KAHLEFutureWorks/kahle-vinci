# Knowledgebase Sync

`kb-sync` ersetzt die alten n8n-VectorDB-Watcher fuer die laufende Indizierung der lokalen Knowledgebase-Ordner.

## Ziel

Dateien unter `knowledgebases/` sollen direkt und automatisch nach Qdrant gespiegelt werden:

- `knowledgebases/kahleallgemein` -> Qdrant Collection `kahleallgemein`
- `knowledgebases/kahlekontext` -> Qdrant Collection `kahlekontext`
- `knowledgebases/kahlerichtlinien` -> Qdrant Collection `kahlerichtlinien`

Der Dienst laeuft als interner Docker-Container, liest die Dateien read-only, erzeugt Embeddings ueber IONOS und schreibt die Vektoren nach Qdrant.

## Unterstuetzte Dateien

- `.md`
- `.txt`
- `.csv`
- `.pdf`
- `.docx`

Temporaere Office-Dateien wie `~$datei.docx` und versteckte Dateien werden ignoriert.

## Verhalten

- Beim Start wird jede Collection mit dem Dateisystem abgeglichen.
- Neue oder geaenderte Dateien werden neu indiziert.
- Geloeschte Dateien werden anhand ihrer `doc_id` aus Qdrant entfernt.
- Der lokale Status liegt in `kb-sync-state/` und wird nicht nach GitHub gepusht.
- Wenn Qdrant leer ist, aber ein alter Status vorhanden ist, erzwingt der Dienst beim Start eine Neuindizierung.

## Force Reindex

Wenn du sicher komplett neu indizieren willst:

1. Container stoppen.
2. Qdrant Collections loeschen oder leeren.
3. Ordner `kb-sync-state/` im Projektordner loeschen.
4. Stack wieder starten.

Danach behandelt `kb-sync` alle Dateien als neu.

## Betrieb

Start erfolgt ueber das bestehende Script:

```powershell
powershell -ExecutionPolicy Bypass -File C:\kahle-vinci\scripts\start-stack.ps1
```

Logs pruefen:

```powershell
docker logs kb-sync --tail 100
```

Qdrant Count pruefen:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:6333/collections/kahleallgemein/points/count" `
  -ContentType "application/json" `
  -Body '{"exact":true}'
```

## Hinweis zu n8n

n8n bleibt fuer RAG-Chat und andere Automationen erhalten. Die Dateisystem-Synchronisierung der Knowledgebase-Dateien sollte aber nicht mehr ueber die alten PowerShell-Watcher und VectorDB-Flows laufen, damit keine doppelten oder fehlerhaften Indizierungen entstehen.

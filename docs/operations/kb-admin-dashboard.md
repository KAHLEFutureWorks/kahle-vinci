# KAHLE Vector Admin-Dashboard

## Zweck

Das Dashboard verwaltet die serverseitigen KAHLE-Vinci-Knowledgebases und
zeigt den zugehörigen Qdrant-Indexstatus. Die Quelldateien bleiben die
führende Datenquelle; Qdrant enthält ausschließlich den daraus erzeugten
Suchindex.

Zugriff nach dem Server-Rollout:

```text
https://vinci.kahle.de/admin/vector/
```

Die Admin-API prüft jede Anfrage über die bestehende Open-WebUI-Sitzung und
akzeptiert ausschließlich Nutzer mit der Rolle `admin`.

Zusätzlich erzwingt die API eine zweite Code-Freigabe. Der Code wird nie im Klartext
gespeichert, sondern als PBKDF2-SHA256-Hash in der nicht versionierten
`/opt/kahle-vinci/stack/.env.production` hinterlegt. Die Freigabe gilt standardmäßig
acht Stunden und wird in einem signierten, `HttpOnly`, `Secure` und `SameSite=Strict`
Cookie an den jeweiligen Open-WebUI-Admin gebunden.

Konfiguration oder Codewechsel auf dem Server:

```bash
sudo python3 /opt/kahle-vinci/stack/scripts/configure-kb-admin-unlock.py
sudo /opt/kahle-vinci/stack/scripts/start-production.sh \
  /opt/kahle-vinci/stack/.env.production
```

Nach fünf Fehlversuchen wird die Codeeingabe für 15 Minuten blockiert. Erfolgreiche
Freigaben, manuelle Sperren und Fehlversuche werden ohne den Code im Audit-Log
protokolliert.

## Funktionen des MVP

- Knowledgebases und Dateianzahlen anzeigen
- neue Knowledgebases samt Qdrant-Collection anlegen
- neue Bases automatisch für `kb-sync` und Vinci-RAG entdecken
- Markdown, TXT, CSV, PDF und DOCX auflisten
- Metadaten, Gültigkeit, Owner, Standorte und Tags anzeigen
- Markdown-, TXT- und CSV-Dateien direkt bearbeiten
- PDF- und DOCX-Inhalte als extrahierte Vorschau anzeigen
- Dateien per Dateiauswahl oder Drag-and-Drop hochladen oder ersetzen
- Ablaufdaten permanent in der Dateiliste anzeigen; gelb ab 30 Tagen und rot im `notify_before_days`-Fenster
- Dateien zwischen bestehenden Knowledgebases verschieben
- Dateien wiederherstellbar löschen
- Vor Änderungen automatische Dateiversionen anlegen
- Qdrant-Chunks eines Dokuments anzeigen
- Semantisch über alle verwalteten Collections suchen
- Indexstatus aus `kb-sync-state.json` anzeigen

## Sicherheitsmodell

- Keine Qdrant- oder IONOS-Zugangsdaten im Browser
- Server-seitige Rollenprüfung über Open WebUI
- Schreibzugriff nur über die getrennte `kb-admin-api`
- Pfadvalidierung verhindert absolute Pfade und `..`-Traversal
- Dateitypen und Uploadgröße sind begrenzt
- Speichern erfolgt atomar
- Löschen verschiebt nach `/knowledgebases/.trash`
- Versionen liegen unter `/knowledgebases/.versions`
- Audit-Ereignisse liegen unter `/knowledgebases/.admin/audit.jsonl`
- Beide neuen Container laufen ohne Linux-Capabilities und mit read-only
  Root-Dateisystem

## Indexierungsverhalten

Speichern, Upload, Verschieben und Löschen verändern die Quelldateien. Der
vorhandene `kb-sync` erkennt diese Änderungen und aktualisiert Qdrant. Der
Button „Speichern & neu indexieren“ schreibt daher nicht direkt aus dem Browser
in Qdrant.

Der angezeigte Status bedeutet:

- `current`: Datei-Hash und letzter Indexstand stimmen überein
- `pending`: Änderung wartet auf den nächsten `kb-sync`-Lauf
- `excluded`: `rag_index: false`
- `error`: Status konnte nicht bestimmt werden

## Rollout

Der Rollout erfolgt wie die bisherigen KAHLE-Vinci-Änderungen:

1. Dateien lokal bauen und prüfen.
2. Paket nach `/home/joltmanns/<stage>` übertragen.
3. Prüfsummen und Syntax auf dem Server prüfen.
4. Verschlüsseltes Produktionsbackup prüfen oder neu erstellen.
5. Dateien mit `sudo install` nach `/opt/kahle-vinci` übernehmen.
6. `kb-admin-api` und `kb-admin-dashboard` bauen.
7. Caddy neu laden.
8. Admin-Anmeldung, Lesen, Speichern, Versionierung und Qdrant-Status prüfen.


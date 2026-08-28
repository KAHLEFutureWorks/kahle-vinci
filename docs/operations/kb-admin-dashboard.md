# KAHLE-Vinci Wissensportal und klassische Vector-Administration

## Aktueller Einstiegspunkt

Das aktuelle rollenbasierte Wissensportal wird unter diesem Pfad bereitgestellt:

```text
https://vinci.kahle.de/wissen/
```

`/wissen` wird auf `/wissen/` normalisiert. Die früheren Pfade
`/admin/vector` und `/admin/vector/*` leitet Caddy mit HTTP 308 auf
`/wissen/` um. Die geroutete Dashboard-Seite lädt `KnowledgePortal`. Die im
Repository weiterhin vorhandene Komponente `VectorAdmin` ist nicht der
aktuelle Seiten-Einstieg.

Das Wissensportal und die klassischen Vector-Admin-Funktionen verwenden zwei
getrennte Sicherheitsmodelle. Der zusätzliche Freigabecode der klassischen
Funktionen ist kein allgemeiner Portalzugang.

## Sicherheitsmodell des Wissensportals

Für das Portal ist eine gültige Open-WebUI-Sitzung erforderlich. Die Portal-API
übernimmt daraus die stabile Benutzer-ID, E-Mail-Adresse und den Anzeigenamen.
In Produktion werden nur konfigurierte KAHLE-E-Mail-Domains akzeptiert.
Deaktivierte Portalidentitäten werden abgewiesen.

Die Portalrollen werden getrennt von der Open-WebUI-Rolle in der
Portal-Governance gespeichert:

| Rolle | Aktueller Zugriff |
| --- | --- |
| `employee` | Standardrolle für neue Portalidentitäten. Lesen und Upload erfolgen nur für Wissensbereiche mit der jeweils ausdrücklich gesetzten Berechtigung. |
| `manager` | Besitzt ebenfalls nur die ausdrücklich gesetzten Lese- und Uploadrechte. Die Rolle kann zusätzlich Freigaben für zugeordnete Mitarbeiter oder gültige Vertretungen bearbeiten. |
| `admin` | Darf alle aktiven Wissensbereiche lesen und dort hochladen, Portalverwaltung ausführen und Knowledge-Base-Änderungen zur Freigabe vorbereiten. |
| `portal_admin` | Darf alle aktiven Wissensbereiche lesen und dort hochladen, Adminrollen verwalten, geschützte Portaleinstellungen ändern und Knowledge-Base-Änderungen direkt ausführen oder entscheiden. Mindestens ein aktiver Portal-Admin bleibt technisch erzwungen. |

`can_read` und `can_upload` sind für `employee` und `manager` getrennte Rechte.
Ein Leserecht erteilt nicht automatisch ein Uploadrecht. `admin` und
`portal_admin` erhalten über ihre Rolle Zugriff auf alle aktiven
Wissensbereiche.

Kritische Rollen- und Knowledge-Base-Änderungen verlangen die im Portal
vorgesehene ausdrückliche Bestätigung. Für die `/portal/*`-Endpunkte ist kein
zusätzlicher Vector-Freigabecode erforderlich.

## Persistenz des Wissensportals

Die kanonischen Portalmetadaten liegen unter
`kb-portal-data/wissensportal.sqlite3`. Originaldateien, aufbereitete
Markdown-Dateien, Quarantäne- und Upload-Arbeitsdaten liegen unter
`kb-portal-data/files/`. `kb-sync` liest diese Portalquelle und aktualisiert
den abgeleiteten Qdrant-Index.

Die klassischen dateibasierten Quellen unter `knowledgebases/` bleiben davon
getrennt. Sie dienen weiterhin den klassischen Vector-Funktionen und als
kontrollierte Migrationsquelle. Qdrant ist in beiden Fällen ein abgeleiteter
Suchindex und keine führende Datenquelle.

## Klassische Vector-Admin-Funktionen

Die klassischen Endpunkte für Collections, direkte Dateiverwaltung, Chunks,
Versionen und semantische Suche sind weiterhin in `kb-admin-api` vorhanden.
Sie verlangen zuerst eine Open-WebUI-Sitzung mit der Open-WebUI-Rolle `admin`
und anschließend den zusätzlichen Vector-Freigabecode. Portalrollen oder
Portal-Lese- und Uploadrechte ersetzen diese beiden Prüfungen nicht.

Der Code wird nie im Klartext gespeichert, sondern als PBKDF2-SHA256-Hash in
der nicht versionierten `/opt/kahle-vinci/stack/.env.production` hinterlegt.
Die Freigabe gilt standardmäßig acht Stunden und wird in einem signierten,
`HttpOnly`, `Secure` und `SameSite=Strict` Cookie an den jeweiligen
Open-WebUI-Admin gebunden.

Konfiguration oder Codewechsel auf dem Server:

```bash
sudo python3 /opt/kahle-vinci/stack/scripts/configure-kb-admin-unlock.py
sudo /opt/kahle-vinci/stack/scripts/start-production.sh \
  /opt/kahle-vinci/stack/.env.production
```

Nach fünf Fehlversuchen wird die Codeeingabe für 15 Minuten blockiert.
Erfolgreiche Freigaben, manuelle Sperren und Fehlversuche werden ohne den Code
im klassischen Audit-Log protokolliert.

### Funktionsumfang

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

### Technische Schutzmaßnahmen

- Keine Qdrant- oder IONOS-Zugangsdaten im Browser
- Serverseitige Open-WebUI-Adminprüfung und zusätzlicher Freigabecode
- Schreibzugriff nur über die getrennte `kb-admin-api`
- Pfadvalidierung gegen absolute Pfade und `..`-Traversal
- Begrenzte Dateitypen und Uploadgröße
- Atomares Speichern
- Wiederherstellbares Löschen nach `/knowledgebases/.trash`
- Versionen unter `/knowledgebases/.versions`
- Klassische Audit-Ereignisse unter `/knowledgebases/.admin/audit.jsonl`
- `kb-admin-api` und `kb-admin-dashboard` ohne Linux-Capabilities und mit read-only Root-Dateisystem

## Indexierungsverhalten der klassischen Quellen

Speichern, Upload, Verschieben und Löschen verändern die Quelldateien unter
`knowledgebases/`. `kb-sync` erkennt diese Änderungen und aktualisiert Qdrant.
Die Browseranwendung schreibt daher nicht direkt in Qdrant.

Der klassische Indexstatus bedeutet:

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
8. `/wissen/`, Portalrollen, Lese- und Uploadrechte sowie den Qdrant-Status prüfen.
9. Falls klassische Vector-Funktionen betroffen sind, Open-WebUI-Adminprüfung und zusätzlichen Freigabecode getrennt prüfen.

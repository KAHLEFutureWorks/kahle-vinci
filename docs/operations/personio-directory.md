# Personio-Mitarbeiterverzeichnis betreiben und abnehmen

Stand: 26. August 2026

## Aktueller Abnahmestand

Die Implementierung und die Offline-Vertragstests sind vorbereitet. Der reale
read-only API-Probe, der lokale Vollabgleich und die interaktive Abnahme unter
`http://localhost:3004` sind noch offen. Sie wurden in diesem Arbeitsschritt
bewusst nicht ausgeführt, weil der laufende Codex-Prozess die erst später
gesetzten Windows-Variablen zuvor nicht geerbt hatte. Die folgenden Schritte
müssen deshalb in einer frisch geöffneten PowerShell ausgeführt werden.

Die Prüfung verändert keine Daten in Personio. Der spätere lokale Sync schreibt
ausschließlich in den lokalen Zustand und in die getrennte Qdrant-Collection
`vinci_personio_directory`.

## Datenschutzregeln für die Abnahme

- Secrets niemals ausgeben, kopieren, protokollieren oder in Dateien schreiben.
- Reale Namen und Kontaktdaten nur in der angemeldeten Vinci-Oberfläche prüfen.
- Keine Screenshots, Chat-Exporte oder Akzeptanzdateien mit realen Namen,
  Fragen, Antworten, Kontaktdaten, Personio-IDs oder Rohbelegen speichern.
- In technischen Berichten nur Fall-ID, Modell-ID, erwartete und tatsächlich
  verwendete Werkzeuge, Intent, Evidenzstatus, Quellenarten,
  Validierungsstatus, Laufzeit und boolesche Prüfergebnisse erfassen.
- Sofort abbrechen, wenn Namen, E-Mail-Adressen, Telefonnummern, Secrets oder
  vollständige Personio-Antworten in technischen Logs erscheinen.

## 1. Frische PowerShell und Variablen prüfen

Nach dem Setzen der Windows-Umgebungsvariablen alle alten PowerShell- und
Codex-Prozesse schließen. Anschließend eine neue PowerShell öffnen und die
Anwesenheit prüfen, ohne die Werte auszugeben:

```powershell
@('PERSONIO_CLIENT_ID','PERSONIO_API') | ForEach-Object {
  [pscustomobject]@{ Name = $_; Present = -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_)) }
}
```

Beide Zeilen müssen `Present=True` zeigen. Bei `False` Codex und PowerShell
erneut vollständig schließen und frisch starten. Nicht mit dem Probe oder dem
Stack fortfahren, solange eine Variable fehlt.

## 2. Read-only API-Probe ausführen

Im Repository-Stamm ausführen:

```powershell
Set-Location C:\kahle-vinci
C:\kahle-vinci\.venv-test\Scripts\python.exe scripts/personio/probe.py
```

Der erfolgreiche Probe zeigt ausschließlich:

- `personio_probe_ok=true`
- `selected_api=v1` oder `selected_api=v2`
- verfügbare Attributbezeichnungen, aber keine Attributwerte
- die aufgelösten kanonischen Feldnamen
- aggregierte Anzahlen geeigneter und ausgeschlossener Datensätze

Erwartet werden die API-Mappings `personio_id`, `display_name`, `position`,
`department`, `team`, `office`, `business_email`, `business_phone`,
`employment_status` und `source_updated_at`. `display_name` muss ausschließlich
auf das Personio-Feld mit der Bezeichnung `Name (preferred)` zeigen;
`source_updated_at` bleibt für den Delta-Sync über `Last modified at`,
`Last modified` beziehungsweise `Letzte Änderung` verpflichtend. Vor- und
Nachname werden intern aus dem normalisierten Preferred Name abgeleitet und
sind keine eigenen API-Mappings.
Position, Abteilung, Team, Standort, geschäftliche E-Mail und geschäftliche
Telefonnummer dürfen bei einzelnen Personen leer sein. E-Mail-Adressen werden
vor der Indexierung normalisiert; ausschließlich die exakte Domain
`@kahle.de` wird übernommen. Private oder andersartige E-Mail-Domains werden
verworfen, ohne die Person selbst aus dem Verzeichnis zu entfernen.
Die Beschäftigungsart wird nicht gelesen oder ausgewertet. Wenn der Probe
fehlschlägt oder ein benötigtes
Geschäftsfeld nicht eindeutig aufgelöst wird, hier stoppen. Das Mapping wird
dann anhand der Personio-Attributbezeichnung explizit korrigiert. Dafür niemals
Beispielwerte oder vollständige API-Antworten protokollieren.

## 3. Lokalen Stack kontrolliert starten

Die frische PowerShell enthält die beiden Personio-Werte bereits im
Prozessspeicher. Das vorhandene Startskript reicht sie an Compose weiter, ohne
sie in eine Datei zu schreiben:

```powershell
Set-Location C:\kahle-vinci
.\scripts\start-stack.ps1
```

Danach den Zustand mit denselben lokalen Compose-Dateien prüfen:

```powershell
$composeArgs = @(
  '-f', 'stack/docker-compose.yml',
  '-f', 'stack/docker-compose.kahle-ui.yml',
  '-f', 'stack/docker-compose.local-edge.yml'
)

docker compose @composeArgs ps personio-directory open-webui caddy-local
docker compose @composeArgs logs --tail=100 personio-directory
```

`personio-directory` muss nach dem ersten erfolgreichen Sync `healthy` sein.
Die Logs dürfen nur technische, sanitierte Fehlercodes enthalten. Der erste
Sync kann abhängig von Datenmenge und API-Limits länger als die Startfrist
dauern. Bei einem Fehler bleibt der letzte gültige Index erhalten und der
Dienst versucht den vollständigen Bootstrap erneut.

## 4. Sync-Zustand nur aggregiert prüfen

Der folgende Befehl zeigt lediglich letzten Laufstatus, letzten erfolgreichen
Zeitpunkt und Anzahl indexierter Personen. Er gibt keine Personen-ID aus:

```powershell
@'
import os
import sqlite3

path = os.environ['PERSONIO_DIRECTORY_STATE_DB_PATH']
with sqlite3.connect(path) as connection:
    last_status = connection.execute(
        'SELECT status FROM sync_run ORDER BY id DESC LIMIT 1'
    ).fetchone()
    last_success = connection.execute(
        "SELECT MAX(value) FROM sync_state WHERE key IN ('last_successful_delta_at','last_successful_full_at')"
    ).fetchone()
    indexed_count = connection.execute(
        'SELECT COUNT(*) FROM indexed_person'
    ).fetchone()
print({
    'last_run_status': last_status[0] if last_status else None,
    'last_successful_at': last_success[0] if last_success else None,
    'indexed_count': int(indexed_count[0]) if indexed_count else 0,
})
'@ | docker compose @composeArgs exec -T personio-directory python -
```

Erwartet sind `last_run_status: completed`, ein UTC-Zeitstempel und eine
plausible Anzahl. Die Anzahl in Qdrant wird separat und ohne Payload geprüft:

```powershell
@'
import requests

response = requests.post(
    'http://qdrant:6333/collections/vinci_personio_directory/points/count',
    json={'exact': True},
    timeout=10,
)
response.raise_for_status()
print({
    'collection': 'vinci_personio_directory',
    'count': int(response.json()['result']['count']),
})
'@ | docker compose @composeArgs exec -T personio-directory python -
```

Beide Anzahlen müssen übereinstimmen. Nicht die Scroll- oder Suchendpunkte von
Qdrant im Terminal ausgeben.

## 5. Interaktive Abnahme unter localhost:3004

Die Prüfung erfolgt angemeldet unter `http://localhost:3004`. Mindestens ein
Konto mit Rolle `user`, ein Konto mit Rolle `admin` und ein Konto mit Rolle
`pending` werden benötigt. Reale Personennamen dürfen nur direkt in der
Oberfläche eingesetzt und nicht in Berichte übernommen werden.

Für jedes verfügbare Vinci-Modell sind diese 14 fachlichen Prüfungen nötig:

1. Eine aktive Person exakt nach vollständigem Namen, Rolle, Standort,
   geschäftlicher Telefonnummer und geschäftlicher E-Mail finden.
2. Personen nach Position, Abteilung, Team und Standort filtern.
3. Einen geeigneten `LEAVE`-Fall in der normalen Suche finden.
4. Sicherstellen, dass `ONBOARDING` in einer normalen Rollen- oder
   Standortfrage unsichtbar bleibt.
5. Mit einer ausdrücklichen Onboarding-Frage ausschließlich Name, zukünftige
   Position, Abteilung, Team und Standort erhalten.
6. Sicherstellen, dass `INACTIVE` nicht erscheint und ein geeigneter externer
   Testfall wie eine interne Person erscheint, ohne Kennzeichnung oder Filterung
   nach Beschäftigungsart.
7. Die Zusammenarbeitskaskade für Team, anschließend Position plus Standort
   und anschließend Abteilung plus Standort prüfen. Die Antwort muss ihre
   Grundlage nennen und darf keine tatsächliche Zusammenarbeit behaupten.
8. Eine reine aktuelle Personenfrage stellen. Tatsächlich verwendet werden darf
   nur `personio_directory`.
9. Eine reine Prozess- oder Arbeitsanweisungsfrage stellen. Tatsächlich
   verwendet werden darf nur `rag_chat`.
10. Eine Mischfrage zu aktueller Person und dokumentiertem Projektbezug stellen.
    Tatsächlich verwendet werden müssen `personio_directory` und `rag_chat`.
    Personio ist für aktuelle Stammdaten führend, RAG für den belegten Bezug.
11. Eine garantiert nicht vorhandene Person suchen. Es darf keinen Rückfall auf
    RAG oder Modellwissen geben.
12. Dieselbe Verzeichnisfrage mit dem `pending`-Konto stellen. Es darf kein
    Verzeichnisergebnis und keinen Adapteraufruf geben.
13. In einem kontrolliert mehr als 24 Stunden alten Testzustand die sichtbare
    Veraltet-Kennzeichnung prüfen.
14. Containerlogs und den sanitisierten Akzeptanzbericht auf Secrets,
    Personennamen, Kontaktdaten, Personio-IDs und Rohbelege prüfen.

Wenn der Personio-Bestand keinen passenden Status- oder Kaskadenfall enthält,
wird der Fall als `pending` dokumentiert. Es werden keine Personio-Daten nur für
einen Test verändert.

In den technischen Harness-Metadaten werden pro Fall ausschließlich
`required_tools`, die tatsächlich verwendeten Werkzeuge, Intent,
Evidenzstatus, Quellenarten `personio_directory` oder `rag_chat`,
Validierungsstatus, Laufzeit sowie die vorgesehenen booleschen Assertions
übernommen. Rohantwort und Rohbelege bleiben im interaktiven Lauf.

## 6. Automatisierte Abnahme und Bericht

```powershell
Set-Location C:\kahle-vinci
C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest stack/personio-directory/tests -q -p no:cacheprovider
C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest stack/tests -q -p no:cacheprovider
C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest stack/kb-admin-api/tests -q -p no:cacheprovider
C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest stack/kb-sync/tests -q -p no:cacheprovider
```

Der Reporter liest normalisierte, bereits datensparsame Laufdaten:

```powershell
C:\kahle-vinci\.venv-test\Scripts\python.exe scripts/openwebui/kahle-harness-acceptance.py <privacy-safe-runs.json>
```

Erwartete Modelle, erlaubte Profile und sämtliche Pflichtfälle stammen
ausschließlich aus der versionierten Matrix
`scripts/openwebui/kahle-harness-acceptance-matrix.json`. Gleichnamige Felder
in der Laufdatei werden ignoriert und können die Abdeckung weder verkleinern
noch erweitern. Die Laufdatei liefert nur die datensparsamen Läufe und den
tatsächlichen Autorisierungsstatus der in der Matrix erlaubten Profile.

Nur wenn jede Modell-Profil-Kombination der Matrix alle für sie geltenden Fälle
besteht, liefert der Reporter Exitcode `0`. `failed`, `unavailable`,
`not_authorized`, eine leere Laufdatei und ein Bericht ohne bestandenen Fall
liefern einen Exitcode ungleich null. Die Status bleiben im Bericht getrennt
sichtbar.

## 7. Produktionskonfiguration

Auf dem Server werden ausschließlich die folgenden Personio-Werte in
`/opt/kahle-vinci/stack/.env.production` gesetzt:

```text
PERSONIO_CLIENT_ID=<client-id>
PERSONIO_API=<secret>
PERSONIO_DIRECTORY_SYNC_INTERVAL_SECONDS=900
```

`PERSONIO_API` ist das Client-Secret. Es wird nicht mit einem API-Basis-URL-Wert
verwechselt. OpenWebUI erhält keine Personio-Credentials. Compose setzt intern
`PERSONIO_DIRECTORY_URL` und verwendet den bestehenden internen API-Key. Der
Dienst veröffentlicht keinen Host-Port.

Vor dem Produktionsstart werden die Werte nur auf Anwesenheit und Nicht-Leere
geprüft. Sie dürfen nicht mit `cat`, `grep`, `docker compose config` ohne
Ausgabefilter oder `docker inspect` ausgegeben werden. Der Produktionsrollout
bleibt gesperrt, bis API-Probe, lokaler Sync, alle automatisierten Suites und
die interaktive Abnahme vollständig nachgewiesen sind.

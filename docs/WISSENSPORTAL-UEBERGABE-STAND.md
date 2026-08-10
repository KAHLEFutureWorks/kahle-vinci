# Übergabe: Stand des Vinci Wissensportals

Stand: 8. August 2026 · 37 Commits auf `main`, noch nicht gepusht

Dieses Dokument fasst zusammen, was seit dem Commit `1c6cea0` entstanden ist, und richtet sich an jeden, der die Arbeit fortsetzt. Die vorherigen acht Commits (`feb85a7` bis `1c6cea0`) bilden die Portal-Grundlage; sie sind hier nicht wiederholt.

Das PRD liegt unverändert unter `docs/superpowers/specs/2026-08-06-kahle-vinci-wissensportal-prd.md`. Die fortlaufende Nachweisakte ist `docs/WISSENSPORTAL-LOKALE-ABNAHME.md`.

## 1. Wo das Projekt steht

Die lokale Umsetzung läuft und ist bedienbar. Der Stack startet reproduzierbar, das Portal ist erreichbar, der Dokumentlebenszyklus lässt sich vollständig durchspielen, und das Hybrid Retrieval liefert nachweislich Treffer mit Quellenlinks.

| Bereich | Stand |
|---|---|
| Portal-Backend | 113 Tests |
| Stack, Verträge, Sicherheit | 243 Tests |
| Hybridindex | 10 Tests |
| Portal-UI | Build, Lint und 3 Tests |
| Retrieval-Evaluation | 100 % Dokumenttreffer, 100 % Quellenlinks |
| RTO | 36,85 s gemessen, Budget 4 Stunden |

Testlauf über einen Befehl:

```
./scripts/run-local-tests.ps1 -Python <interpreter>
```

Abhängigkeiten in `stack/requirements-dev.txt`. Auf dem Entwicklungsrechner steht nur Windows PowerShell 5.1 zur Verfügung, kein `pwsh`.

## 2. Architekturentscheidungen, die den Code prägen

**Reranking läuft auf IONOS, nicht lokal.** Der lokale CPU-Cross-Encoder brauchte rund zwei Sekunden je Kandidat; bei den von PRD 19.2 erzwungenen 30 bis 50 Kandidaten lief jede Anfrage in einen Timeout, und das Retrieval ist fail-closed. Das Zielsystem ist ein netcup VPS ohne GPU. `IonosReranker` mit `Qwen/Qwen3-VL-Reranker-8B` antwortet im Median in 3,24 s bei besserer Trennschärfe. Der lokale `reranker`-Dienst ist aus `docker-compose.yml` entfernt; ein Test verhindert seine Rückkehr.

**Der IONOS-Token wird unter zwei Namen akzeptiert.** Lokal ist er als `IONOS_API_TOKEN` gesetzt, die Produktionsvorlage nennt ihn `IONOS_API_KEY`. Code und Compose lesen beide, `IONOS_API_TOKEN` hat Vorrang. Beim Rollout ist nur zu prüfen, welcher Name gesetzt ist.

**Die OpenWebUI-Tools werden gebaut, nicht direkt verteilt.** `rag_chat_hybrid_tool.py` und `kahle_workflow_orchestrator.py` teilen sich `hybrid_retrieval.py` und `hybrid_retrieval_adapters.py`. OpenWebUI nimmt aber genau eine Datei je Tool und stellt keinen Modulsuchpfad bereit. `stack/open-webui-tools/build_tools.py` erzeugt daraus eigenständige Fassungen unter `dist/`. **Nur die aus `dist/` sind lauffähig**; die Quelldateien tragen einen Warnhinweis. Ein Test baut im `--check`-Modus und importiert beide Bundles.

**Der lokale Step-up ersetzt nur den Microsoft-Rückkanal.** Vier Adminfunktionen verlangen eine frische Microsoft-Anmeldung, die lokal nicht konfiguriert ist. `LocalStepUpAdapter` hängt hinter dem vorhandenen `OIDCAdapter`-Protokoll: Challenge, State, PKCE, Ablauf, Nonce- und E-Mail-Abgleich, Cookie und Audit laufen unverändert. Er aktiviert sich ausschließlich, wenn `KB_PORTAL_LOCAL_STEP_UP=true` gesetzt ist, ein Signaturgeheimnis existiert und **keine einzige** Entra-Variable gesetzt ist. Tests decken jedes Entra-Feld einzeln ab.

**Caddy läuft lokal mit der Produktionskonfiguration.** `stack/docker-compose.local-edge.yml` mountet dieselbe Caddyfile und setzt `PUBLIC_HOSTNAME` auf `:3004`, wodurch TLS und ACME entfallen. Die Abnahme prüft damit das echte Routing samt `forward_auth`. Beide Stack-Skripte binden das Overlay standardmäßig ein, `-NoEdge` schaltet es ab.

## 3. Behobene Fehler, nach Ursache gruppiert

### Fehler, die im laufenden Betrieb sichtbar waren

- **Jeder Upload scheiterte** an `valid_workdays_or_valid_until_required`. Der Hintergrundjob rief die Endpunktfunktion direkt auf, ohne `valid_until` zu übergeben; der Parameter erhielt seinen `Form(None)`-Default, ein FieldInfo-Objekt statt `None`. Ein Wächter vergleicht jetzt die Form-Parameter der Endpunktfunktion mit den Argumenten des Jobs.
- **Jede Vinci-Anfrage scheiterte** mit `RetrievalError`. `build_tools.py` schnitt jeden `@dataclass`-Dekorator ab, weil die Zeilennummer einer Klasse auf `class` zeigt, nicht auf ihre Dekoratoren.
- **Gelöschte Dokumente galten weiter als ähnlich.** Der Analysekorpus führt eine eigene Statusspalte, die außerhalb des Vorgangsablaufs niemand pflegte. Der Zustand wird jetzt aus der Version abgeleitet, und ein Eintrag ohne existierende Version zählt nicht mehr.
- **Knowledge Bases waren nicht löschbar.** Ein Bereich muss erst archiviert werden, aber Archivieren entfernte ihn aus der Auswahlliste. Die Auswahl liest jetzt die Verwaltungsübersicht.
- **Admins fanden ihre eigenen Uploads nicht.** `tasks_for` lieferte für Admins nur die Eskalationsliste.
- **Verworfene Vorgänge ließen Entwürfe zurück.** Der Status hängt an der Version, ein verworfener Vorgang hat aber keine aktive Version.
- **Dokumente im Papierkorb blieben in allen Listen sichtbar.**
- **Aktionen am Dokument brachen wortlos ab**, wenn die Begründung fehlte; zwei hatten gar keine Fehlerbehandlung.
- **Das Portal war lokal nicht erreichbar.** Ein handgestarteter Caddy-Container mit veralteter Konfiguration kannte nur die alten `/admin/vector`-Pfade und antwortete auf `/wissen/` mit einem leeren 200er.

### Kalibrierung

Die automatische Vertraulichkeitseinstufung stufte praktisch jede KAHLE-Richtlinie als „bereichsbeschränkt" ein: Jede E-Mail-Adresse zählte, auch interne im Verantwortlichkeitsblock, ebenso jede Telefonnummer und jede Erwähnung des Wortes „vertraulich". Jetzt zählen nur Adressen außerhalb von `kahle.de`, keine Servicenummern, und „vertraulich" nur als ausdrückliche Kennzeichnung. Bank-, Zugangs-, Gesundheits- und Kundendaten lösen unverändert aus.

### Oberfläche

Sieben Abweichungen gegen PRD 12.3, 16.1, 21.1, 26.2 und 26.3 wurden behoben: fehlende Fokuszustände, fehlender Tastaturpfad, Fachbegriffe und rohe Statuscodes für Mitarbeitende, fehlende dreistufige Bewertung der Aufbereitung, technische Fehlercodes in der Oberfläche, unvollständige Fortschrittsanzeige ohne Wiederaufnahme, fehlende Datumsauswahl für die Gültigkeit.

Später kamen hinzu: unsichtbare Formularfelder ohne Rahmen, rohes JSON im Qualitätsdashboard, Benutzer-IDs statt Klarnamen im Audit, fehlender Grund der Prüfung an Vorgängen, nicht schließbare Kacheln, Titel muss abgetippt werden, und die Trennung eigener Uploads von fremden Freigaben.

## 4. Neue Funktionen

- **Gültigkeit als geprüftes Datum** (PRD 17.1). `workdays_until` als Umkehrung von `add_workdays`; die Umrechnung bleibt serverseitig, damit Feiertage und die 60-Arbeitstage-Grenze verbindlich sind. Ein Datum auf Wochenende oder Feiertag verkürzt, verlängert nie.
- **Verwaltungsübersicht der Wissensbereiche** mit Dokumentanzahl und aufklappbarer Tabelle. Bewusst getrennt von `/portal/documents`, das nach Leserechten filtert; die Verwaltung braucht auch Bereiche, in die der Admin nicht hineinlesen darf. Liefert ausschließlich Metadaten.
- **Zuordnung bestehender Dokumente zu Wissensbereichen** (PRD 9.3). Eine Zuordnung entstand bisher nur beiläufig aus einem Uploadfall; ein Dokument ohne Bereich ließ sich nicht mehr zuordnen.
- **Warnung vor Archivierung und Löschung**, die die Zahl betroffener Dokumente nennt und eine zweite Bestätigung verlangt.
- **Endgültiges Löschen aus dem Papierkorb** für Portal-Admins, zweistufig bestätigt. Ein Legal Hold bleibt bindend.
- **Screenshots an Wissensfehlermeldungen.** Typprüfung am Dateiinhalt statt an der Endung, kein SVG, Erkennung aktiver Inhalte hinter gültigem Header, ClamAV-Scan, max. 5 MB. Nur der Meldende darf anhängen, nur Admins abrufen.
- **Eigene Vorgänge aus der Aufgabenliste weiterschicken.** Die Aktionen gab es zuvor nur auf dem Ergebnisbildschirm direkt nach dem Upload.

## 5. Neue Dateien

| Datei | Zweck |
|---|---|
| `scripts/run-local-tests.ps1` | Fährt die drei Suiten in getrennten Prozessen |
| `scripts/stop-stack.ps1` | Gegenstück zu `start-stack.ps1` |
| `stack/requirements-dev.txt` | Verifizierte Testabhängigkeiten |
| `stack/docker-compose.local-edge.yml` | Lokaler Caddy und lokaler Step-up |
| `stack/open-webui-tools/build_tools.py` | Baut die installierbaren Tool-Bundles |
| `stack/tests/measure_restore_rto.py` | Zeitmessung für den RTO-Nachweis |
| `docs/WISSENSPORTAL-UX-TESTPROTOKOLL.md` | Moderiertes Testskript für PRD 29.4 |
| `eval/rag/results/2026-08-07-hybrid-ionos.json` | Bericht der Retrieval-Evaluation |
| drei `conftest.py` | Modulsuchpfade je Testverzeichnis |

## 6. Offene Punkte

**Technisch offen:**

- Die Negativfragen aus PRD 29.2 sind offline bestanden, die Laufzeitprüfung im Vinci-Chat steht aus.
- Die Restore-Zeitmessung nutzt deterministische lokale Embeddings statt IONOS; die Teilmessung mit echten Embeddings über 6000 Chunks fehlt.
- Die Migration der Altbestände nach PRD 28 wurde nicht ausgeführt. Der Hybridindex enthält ausschließlich, was über das Portal freigegeben wurde.
- Mailversand ist lokal nicht konfiguriert. Benachrichtigungen erscheinen nur im Portal, die E-Mail-Wege nach PRD 22 sind ungeprüft.
- Latenz: 12,4 s Median je Frage in der Offline-Evaluation, 23,8 s im 95. Perzentil. Kein PRD-Grenzwert, aber im Chat spürbar.

**Organisatorisch offen:**

- Die UX-Praxistests nach PRD 29.4 brauchen echte Testpersonen. Das Protokoll liegt vor.

**Bewusst nicht umgesetzt:**

- Mitarbeitende können nach dem Upload keine Herabstufung mit Begründung beantragen (PRD 10.1) und keinen Konvertierungsfehler kommentieren (PRD 13.2). Der Endpunkt für die Herabstufung verlangt eine `document_id`, die zum Uploadzeitpunkt noch nicht existiert; der Vorgang selbst kann keinen Text mitnehmen. Ein Durchstich durch mehrere Schichten, in `WISSENSPORTAL-LOKALE-ABNAHME.md` als offene Lücke geführt.

## 7. Fallstricke

**Die Bundles unter `dist/` müssen nach jeder Änderung an den Tool-Quellen neu gebaut werden.** `.gitignore` enthält eine generische `dist/`-Regel; für dieses Verzeichnis gibt es eine ausdrückliche Ausnahme. Der Bundle-Test schlägt fehl, sobald `dist/` veraltet ist.

**Endpunktfunktionen nie direkt aufrufen, ohne alle Form-Parameter zu übergeben.** Sie erhalten sonst FastAPI-Defaults, also FieldInfo-Objekte statt Werte. Genau das hat jeden Upload lahmgelegt.

**Hintergrundjobs melden Fehler still in ihren Jobdatensatz.** Ein Test, der nur den HTTP-Statuscode prüft, bleibt grün, während der Job scheitert. Immer das Jobergebnis prüfen.

**`kb-admin-api` und `kb-sync` haben beide ein Paket `app`.** Sie können nicht in einem Python-Prozess koexistieren; der Testrunner fährt die Suiten deshalb getrennt.

**Große Downloads brechen auf diesem Rechner sporadisch ab.** Kein Proxy, keine TLS-Interception, Path-MTU in Ordnung. `docker pull` braucht Retry-Schleifen.

## 8. Kein Push, keine Produktion

Alle 37 Commits liegen lokal auf `main` und sind nicht gepusht. Eine Produktionsbereitstellung hat nicht stattgefunden und ist bis zum vollständigen Abschluss der lokalen Abnahme ausgeschlossen. Das Go-live-Gate in `WISSENSPORTAL-LOKALE-ABNAHME.md` ist geschlossen.

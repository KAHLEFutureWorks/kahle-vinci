# Übergabe: Stand des Vinci Wissensportals

Stand: 12. August 2026 · lokaler Release-Candidate vor dem kontrollierten Server-Test

Dieses Dokument fasst zusammen, was seit dem Commit `1c6cea0` entstanden ist, und richtet sich an jeden, der die Arbeit fortsetzt. Die vorherigen acht Commits (`feb85a7` bis `1c6cea0`) bilden die Portal-Grundlage; sie sind hier nicht wiederholt.

Das PRD liegt unverändert unter `docs/superpowers/specs/2026-08-06-kahle-vinci-wissensportal-prd.md`. Die fortlaufende Nachweisakte ist `docs/WISSENSPORTAL-LOKALE-ABNAHME.md`.

## 1. Wo das Projekt steht

Die lokale Umsetzung läuft und ist bedienbar. Der Stack startet reproduzierbar, das Portal ist erreichbar, der Dokumentlebenszyklus lässt sich vollständig durchspielen, und das Hybrid Retrieval liefert nachweislich Treffer mit Quellenlinks.

| Bereich | Stand |
|---|---|
| Portal-Backend | 147 Tests |
| Stack, Verträge, Sicherheit | 263 Tests |
| Hybridindex | 12 Tests |
| RAG-Auswertungswerkzeuge | 7 Tests |
| Portal-UI | Produktionsbuild, 9 Renderingtests und Lint |
| Retrieval-Evaluation | 100 % Dokumenttreffer, 100 % Quellenlinks |
| RTO | 517,39 s mit 6.000 echten IONOS-Embeddings, Budget 4 Stunden |

Testlauf über einen Befehl:

```
./scripts/run-local-tests.ps1 -Python <interpreter> -Npm <npm-command>
```

Abhängigkeiten in `stack/requirements-dev.txt`. Auf dem Entwicklungsrechner steht nur Windows PowerShell 5.1 zur Verfügung, kein `pwsh`.

## 2. Architekturentscheidungen, die den Code prägen

**Reranking läuft auf IONOS, nicht lokal.** Der lokale CPU-Cross-Encoder brauchte rund zwei Sekunden je Kandidat; bei den von PRD 19.2 erzwungenen 30 bis 50 Kandidaten lief jede Anfrage in einen Timeout, und das Retrieval ist fail-closed. Das Zielsystem ist ein netcup VPS ohne GPU. `IonosReranker` mit `Qwen/Qwen3-VL-Reranker-8B` antwortet im Median in 3,24 s bei besserer Trennschärfe. Der lokale `reranker`-Dienst ist aus `docker-compose.yml` entfernt; ein Test verhindert seine Rückkehr.

**Der IONOS-Token wird unter zwei Namen akzeptiert.** Die Produktionsvorlage nennt `IONOS_API_KEY`; Code und Compose lesen zusätzlich `IONOS_API_TOKEN`, das Vorrang hat. Die zwischenzeitliche HTTP-401-Diagnose betraf irrtümlich nur den älteren Credential-Manager-Eintrag. Der Stack verwendet die gültige Windows-Benutzervariable `IONOS_API_TOKEN`. Modellliste, beide Chatmodelle und BGE-M3 antworten damit mit HTTP 200.

**Rerank-Treffer brauchen eine Mindest-Relevanz von 0,25.** Der Reranker liefert auch für fachfremde Fragen immer eine Rangliste; ohne Schwelle konnte Vinci deshalb einen formal besten, aber sachlich unpassenden Richtlinienabschnitt als Quelle verwenden. Die Schwelle wurde am aktiven lokalen Korpus kalibriert: eine fachfremde Leistungsfrage erreichte höchstens 0,193, eine erfundene Kennung 0,128 und eine belegte Eskalationsfrage 0,517. Kandidaten unter 0,25 werden jetzt verworfen. Das Verhalten ist in beiden OpenWebUI-Tools ausgerollt und fail-closed getestet.

**Die OpenWebUI-Tools werden gebaut, nicht direkt verteilt.** `rag_chat_hybrid_tool.py` und `kahle_workflow_orchestrator.py` teilen sich `hybrid_retrieval.py` und `hybrid_retrieval_adapters.py`. OpenWebUI nimmt aber genau eine Datei je Tool und stellt keinen Modulsuchpfad bereit. `stack/open-webui-tools/build_tools.py` erzeugt daraus eigenständige Fassungen unter `dist/`. **Nur die aus `dist/` sind lauffähig**; die Quelldateien tragen einen Warnhinweis. Ein Test baut im `--check`-Modus und importiert beide Bundles.

**Die lokale Tool-Aktualisierung benötigt keinen OpenWebUI-API-Key.** `scripts/openwebui/update-local-rag-tools.ps1` kopiert die beiden gebauten `dist`-Tools und das vorhandene SQLite-Registrierungsskript in den lokalen OpenWebUI-Container, aktualisiert ausschließlich `rag_chat` und `kahle_workflow` in der persistenten `webui.db` und startet danach nur OpenWebUI neu.

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

Die Migrationsmaske verlangte außerdem technische Autoritätscodes und einen Geltungsbereich als JSON. Sie verwendet jetzt die sechs verständlichen Autoritätsstufen aus dem PRD, schlägt den anhand des Ordners erkannten Ziel-Wissensbereich vor und erlaubt dessen fachliche Korrektur. Dateien auf der obersten Ebene müssen ausdrücklich einem Wissensbereich zugeordnet werden. Der fachliche Geltungsbereich wird optional als Klartext aufgenommen; Suche und Statusfilter erschließen die 57 erfassten Altbestände. Original und Markdown können vor der Entscheidung über einen rollen- und pfadgesicherten Endpunkt geöffnet werden. Owner, Einstufung und Verbindlichkeit bleiben für die nächste Datei vorausgewählt, ohne die Einzelprüfung oder den regulären Freigabeprozess zu umgehen. Nicht zu übernehmende Altbestände lassen sich mit Begründung reversibel in den eigenen Bereich „Nicht übernehmen“ verschieben. Die Quelldateien bleiben erhalten, die Entscheidung wird protokolliert und der Eintrag kann später wieder in die Prüfliste zurückgeholt werden.

Die technische Vertraulichkeitseinstufung wird in der Oberfläche als konkrete Zugriffsfrage dargestellt: „Unternehmensweit intern“, „Nur freigegebene Bereiche“ oder „Nur ausdrücklich berechtigte Personen“. Die Produktentscheidung vom 11. August 2026 ersetzt die pauschale Freigabekette durch drei Stufen: Saubere Uploads in genau eine Bereichs-Knowledgebase dürfen direkt aktiviert werden. KAHLE-Allgemein sowie Dubletten, Versionskandidaten und unklare Dokumentenprioritäten benötigen die Freigabe der Führungskraft. Kritische Fälle benötigen zuerst die Führungskraft und anschließend einen Admin. Nicht sicher untersuchbare Dateien und Malware bleiben ohne Override in Quarantäne. Diese Matrix ist im Backend umgesetzt und durch die vollständige Portal-Backend-Suite abgedeckt. Der zentrale Schalter ist lokal standardmäßig aktiv und in Produktion bis zur Abnahme standardmäßig aus.

Jede automatische Aktivierung und jede menschliche Entscheidung muss außerdem an die betroffenen Personen zurückgemeldet werden. Nach einer Führungskraftentscheidung erhält der Uploader den Status und die Begründung. Nach einer Adminentscheidung erhalten Führungskraft und Uploader dieselben verständlichen Abschlussinformationen. „Veröffentlicht und abrufbar“, „abgelehnt“, „zur Korrektur zurückgegeben“ und „weitere Prüfung erforderlich“ dürfen in UI und E-Mail nicht verwechselt werden. Die drei bestätigten Testgrenzen sind Upload-/Entscheidungs-API, sichtbare Portalaufgaben und Vorgangsstatus sowie der E-Mail-Ausgang mit sicheren Vorgangslinks.

Die lokale Umgebung enthält nur drei technische Testnutzer, für die keine getrennten interaktiven Anmeldungen verfügbar sind. Der echte Rollen- und Benachrichtigungstest mit unterschiedlichen Mitarbeitern, Führungskräften und Admins ist deshalb ein verpflichtender Produktionsvorbereitungstest auf dem Server und kein lokal als bestanden zu wertender Nachweis. Vor diesem Test werden die Knowledgebases planmäßig geleert und der Wissensbestand kontrolliert von Grund auf neu aufgebaut.

Die Benutzer- und Rechteverwaltung verwendet jetzt eine übersichtliche Master-Detail-Ansicht: Benutzer stehen kompakt links, die bearbeitbaren Zuordnungen und Knowledgebase-Rechte direkt rechts. Diese Änderungen werden bewusst gesammelt und über „Änderungen speichern“ übernommen; ein sichtbarer Status weist auf gespeicherte oder noch ungespeicherte Änderungen hin. Abwesenheit und Vertretung sind ein gemeinsamer Vorgang mit Zeitraum und Grund. Beim Entfernen endet auch die gekoppelte Vertretung. Rollenänderungen bleiben wegen der erneuten Microsoft-Bestätigung ein separater Sofortvorgang.

Admins besitzen einen eigenen Bereich „Sperrwörter“. Die initialen Regeln `TPI` und `Reparaturleitfaden` werden serverseitig im aufbereiteten Dokumentinhalt geprüft. Treffer gehen zuerst zur Führungskraft und bei Zustimmung anschließend zur Adminprüfung; die gefundenen Begriffe sind im Upload-Ergebnis und in beiden Prüfaufgaben sichtbar. Groß- und Kleinschreibung wird ignoriert, kurze Begriffe treffen nur als vollständiges Wort. Hinzufügen und Entfernen von Regeln ist auf Adminrollen beschränkt und vollständig auditiert; Korrekturversionen und kontrollierte Legacy-Übernahmen durchlaufen dieselbe Prüfung erneut.

Normale Admins benötigen einen Portal-Admin als Führungskraft. Portal-Admins benötigen keine Führungskraft und dürfen Vorgänge ohne zweite Freigabe abschließend entscheiden. Reine Freigaben benötigen keine Begründung; Ablehnungen, Weiterleitungen und Overrides bleiben begründungspflichtig. Während eine Entscheidung verarbeitet wird, sperrt ein zentraler Ladehinweis den gesamten Aufgabenbereich gegen Mehrfachklicks und parallele Freigaben, nennt das betroffene Dokument und zeigt anschließend den aktualisierten Stand oder einen verständlichen Fehler an. Das Portal zeigt Vorgangsänderungen zusätzlich im neuen Bereich „Mitteilungen“ an; Uploader, Führungskraft und Admin erhalten abhängig vom jeweiligen Schritt dieselben verständlichen Statusinformationen per E-Mail.

Die persistente serverseitige `decision_jobs`-Warteschlange serialisiert Aktivierung und Indexänderung auch über mehrere Nutzer, Browser und API-Prozesse hinweg. Gleichzeitige Entscheidungen werden FIFO eingereiht, doppelte aktive Jobs für denselben Fall verhindert und mit einer Lease gegen dauerhaft hängenbleibende Worker abgesichert. Die UI wartet nicht mehr blockierend: Nach dauerhafter Annahme erscheint der Vorgang unter „Veröffentlichung läuft“, die Seite darf geschlossen werden und der Abschluss wird über die Mitteilungen gemeldet.

Reguläre Freigaben und Dokumentänderungen lösen keinen vollständigen Hybridindex-Neuaufbau mehr aus. `kb-sync` bettet nur die Chunks des betroffenen Dokuments ein und schaltet alte/neue Punkte fehlersicher über das `published`-Merkmal um. Die Sparse-Suche nutzt Qdrants serverseitig gepflegte IDF-Statistik. Vor Nutzung der inkrementellen Schnittstelle ist einmalig ein vollständiger Schema-v3-Neuaufbau erforderlich; danach bleibt `reindex-all` Restore, Migration und bewussten Schema-/Modellwechseln vorbehalten.

Für eindeutig benannte Dokumente kann das Retrieval nun die vollständigen, weiterhin hart berechtigungsgefilterten Parent-Abschnitte nachladen. Gesamtfragen wie „Was steht in unserer KI-Compliance?“ erhalten je nummeriertem Hauptkapitel einen Quellenblock in Dokumentreihenfolge. Alle Unterabschnitte desselben Hauptkapitels werden innerhalb dieses Blocks zusammengeführt, sofern das vollständige Dokument in das Kontextbudget passt. Dadurch umfasst beispielsweise „Incident-Management“ nicht nur die Definition, sondern auch Meldewege, Eindämmung, Wiederherstellung und Nachbereitung. YAML-Frontmatter wird bereits beim Chunking entfernt und zusätzlich beim Retrieval abgefangen. Der lokale Bestand wurde nach dieser Änderung vollständig neu indexiert; die Kontrolle über 306 Punkte ergab 0 verbliebene Frontmatter-Chunks.

Kurze eindeutige Titelanfragen wie „KAHLE KI-Compliance“ lösen ebenfalls die vollständige Dokumentübersicht aus. Für normale normative Fragen berücksichtigt die Auswahl zusätzlich die hinterlegte Autoritätsstufe: Höherrangige Quellen erhalten bei ähnlicher semantischer Relevanz Vorrang, Stufe-6-Schulungsunterlagen werden bei ausreichender fachlicher Abdeckung zurückgestellt und nahezu identische Abschnitte dokumentübergreifend reduziert. Konfliktmarkierte Quellen sind von dieser Reduktion ausgenommen. Im lokalen Kontrolllauf verschwand dadurch der KI-Richtlinien-Fragebogen aus der allgemeinen Vorgabenfrage. Die KI-Anwendungsübersicht bleibt erwartungsgemäß auffindbar, weil sie aktuell als Stufe 5 „Prozess- oder Arbeitsanweisung“ klassifiziert ist; eine fachliche Umstufung auf Stufe 6 ist eine bewusste Adminentscheidung und keine Retrievalkorrektur.

Nach dem ersten Praxiseinsatz wurde ein Darstellungsfehler behoben: Das Metadatenformular stand unterhalb der vollständigen Liste und war bei 57 Einträgen praktisch unsichtbar. Ein Klick auf eine Dokumentkarte wählt sie jetzt eindeutig aus und zeigt Ziel-Wissensbereich, Owner, Vertraulichkeit, Verbindlichkeit und Geltungsbereich direkt innerhalb dieser Karte. Original und Markdown sind klar als unveränderliche Vorschau gekennzeichnet. Eine eigene responsive Styleschicht vereinheitlicht Aktionshöhen, Abstände, Eingabefelder, Auswahlzustand und mobile Anordnung; ein vierter Renderingtest verhindert die Rückkehr des Fehlers.

## 4. Neue Funktionen

- **Gültigkeit als geprüftes Datum** (PRD 17.1). `workdays_until` als Umkehrung von `add_workdays`; die Umrechnung bleibt serverseitig, damit Feiertage und die 60-Arbeitstage-Grenze verbindlich sind. Ein Datum auf Wochenende oder Feiertag verkürzt, verlängert nie.
- **Verwaltungsübersicht der Wissensbereiche** mit Dokumentanzahl und aufklappbarer Tabelle. Bewusst getrennt von `/portal/documents`, das nach Leserechten filtert; die Verwaltung braucht auch Bereiche, in die der Admin nicht hineinlesen darf. Liefert ausschließlich Metadaten.
- **Zuordnung bestehender Dokumente zu Wissensbereichen** (PRD 9.3). Eine Zuordnung entstand bisher nur beiläufig aus einem Uploadfall; ein Dokument ohne Bereich ließ sich nicht mehr zuordnen.
- **Warnung vor Archivierung und Löschung**, die die Zahl betroffener Dokumente nennt und eine zweite Bestätigung verlangt.
- **Endgültiges Löschen aus dem Papierkorb** ist während der ersten 30 Tage technisch gesperrt. Ab Tag 30 erscheint der zweistufige Löschbutton für Admins und Portal-Admins. Ein Legal Hold bleibt bindend.
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

- Der echte 21-Fragen-Lauf über OpenWebUI-Hintergrundaufgaben und `rag_chat` ist technisch ausführbar. Die Negativfrage blieb ohne Quelle. Der frühere Gesamtlauf mit dem unvollständigen lokalen Legacy-Korpus ist nicht als Serverabnahme verwertbar. Nach der Produktentscheidung für einen frischen Wissensaufbau wird der Lauf auf dem Server mit einem repräsentativen, regulär über das Portal freigegebenen Abnahmekorpus wiederholt.
- Das Admin-Qualitätsdashboard deckt jetzt die vollständigen PRD-27-Gruppen ab: Dokumentstatus, Freigaben und Bearbeitungszeit, Eskalationen, Dubletten, Versions- und Konflikttreffer, Konvertierungs- und Sicherheitsfunde, Wissensfehler, Verantwortlichkeiten, Backup/Index sowie Retrievaltreffer, Quellenabdeckung, unbeantwortete Fragen, Latenzen und Fehlerrate. `rag_chat` übermittelt dafür nur Hash, Ergebnis, Quellenanzahl, Dauer und Fehlercode; Fragetext und Dokumentinhalt werden nicht in der Telemetrie gespeichert. Retrievalfehler erzeugen zusätzlich automatisch einen deduplizierten Admin-Incident.
- Der vollständige RTO-Lauf mit 500 Dokumenten, 1.001 Dateien, 392,2 MB und 6.000 echten IONOS-Embeddings benötigt 517,39 Sekunden. Das sind 3,59 Prozent des Vier-Stunden-Budgets.
- Die technische Migration nach PRD 28 ist umgesetzt und bleibt testbar. Die 51 offenen lokalen Legacy-Aufgaben sind nach der Entscheidung für einen frischen Serverbestand keine Rollout-Voraussetzung mehr; sie werden nicht ungeprüft auf den Server kopiert.
- Der lokale Versandweg ist über `kb-portal-data/mail-capture.jsonl` geprüft; ein echter Wartungslauf hat ausstehende Freigabebenachrichtigungen ausgeliefert. Microsoft Graph bleibt erst im Produktionsprofil zu prüfen.
- Die Konvertierungsmessung gegen den echten lokalen Document Worker umfasst 12 Dateien bis 10 MB aus PDF, DOCX und XLSX: 100 Prozent erfolgreich, maximal 0,923 Sekunden. Der Bericht liegt unter `eval/rag/results/2026-08-10-conversion-quality.json`.
- Latenz: 12,4 s Median je Frage in der Offline-Evaluation, 23,8 s im 95. Perzentil. Kein PRD-Grenzwert, aber im Chat spürbar.

**Organisatorisch offen:**

- Die UX-Praxistests nach PRD 29.4 brauchen echte Testpersonen. Das Protokoll liegt vor.

**Nachträglich geschlossen:**

- Dokumente entstehen bereits vor der Nutzerentscheidung mit einer stabilen `document_id` und erscheinen auch als Entwurf in der Dokumentliste. Owner und Führungskräfte können dort eine Herabstufung mit schriftlicher Begründung beantragen; Admins entscheiden darüber. Fehlgeschlagene Konvertierungen erscheinen jetzt zusätzlich beim Mitarbeiter. Er kann Original und Markdown vergleichen, den Fehler in Alltagssprache beschreiben und die automatische Korrektur ausdrücklich per Checkbox freigeben. Jede Korrektur erzeugt eine neue Version und durchläuft Prüfung und Freigabe erneut.

## 7. Fallstricke

**Die Bundles unter `dist/` müssen nach jeder Änderung an den Tool-Quellen neu gebaut werden.** `.gitignore` enthält eine generische `dist/`-Regel; für dieses Verzeichnis gibt es eine ausdrückliche Ausnahme. Der Bundle-Test schlägt fehl, sobald `dist/` veraltet ist.

**Endpunktfunktionen nie direkt aufrufen, ohne alle Form-Parameter zu übergeben.** Sie erhalten sonst FastAPI-Defaults, also FieldInfo-Objekte statt Werte. Genau das hat jeden Upload lahmgelegt.

**Hintergrundjobs melden Fehler still in ihren Jobdatensatz.** Ein Test, der nur den HTTP-Statuscode prüft, bleibt grün, während der Job scheitert. Immer das Jobergebnis prüfen.

**`kb-admin-api` und `kb-sync` haben beide ein Paket `app`.** Sie können nicht in einem Python-Prozess koexistieren; der Testrunner fährt die Suiten deshalb getrennt.

**Große Downloads brechen auf diesem Rechner sporadisch ab.** Kein Proxy, keine TLS-Interception, Path-MTU in Ordnung. `docker pull` braucht Retry-Schleifen.

## 8. Release-Candidate, keine Produktionsfreigabe

Der aktuelle Stand wird als nachvollziehbarer Release-Candidate auf `main` gesichert. Eine Produktionsfreigabe ist damit nicht verbunden. Das Go-live-Gate bleibt geschlossen, bis Microsoft-Anmeldung und Step-up, Graph-Mail, echte Rollenabläufe, der 21-Fragen-Lauf, UX-Praxistests sowie Backup und Restore auf dem Server dokumentiert bestanden sind.

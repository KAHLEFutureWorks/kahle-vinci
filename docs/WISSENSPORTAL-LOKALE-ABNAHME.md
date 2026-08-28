# Lokale Abnahme des KAHLE-Vinci Wissensportals

Stand: 11. August 2026

> Dieses Dokument ist ein historischer Abnahmenachweis. Die aktuellen
> Verification-Tiers und Befehle stehen in [VERIFICATION.md](VERIFICATION.md).

Dieses Protokoll ist die fortlaufende Nachweisakte zur lokalen Umsetzung des PRD. Eine Produktionsfreigabe ist damit ausdrücklich nicht verbunden.

## Testumgebung

Die drei Python-Suiten laufen über einen dokumentierten Befehl:

```
./scripts/run-local-tests.ps1
```

Auf dem Entwicklungsrechner steht nur Windows PowerShell 5.1 zur Verfügung,
kein `pwsh`. Beide Skripte sind für diese Edition geeignet und werden aus einer
laufenden PowerShell-Sitzung direkt aufgerufen.

Die Testabhängigkeiten stehen in `stack/requirements-dev.txt` und müssen
einmalig installiert werden, sinnvollerweise in einer eigenen Umgebung:

```
python -m venv .venv-test
./.venv-test/Scripts/python.exe -m pip install -r stack/requirements-dev.txt
./scripts/run-local-tests.ps1 -Python ./.venv-test/Scripts/python.exe
```

Die Suiten laufen bewusst in getrennten Prozessen, weil `kb-admin-api` und
`kb-sync` jeweils ein eigenes Paket `app` besitzen. Die Modulsuchpfade setzt je
eine `conftest.py` im Testverzeichnis; ein `PYTHONPATH` von außen ist nicht
nötig.

## Automatisierte Nachweise

| Bereich | Nachweis | Ergebnis |
|---|---|---|
| Portal-Backend | `stack/kb-admin-api/tests` | 147 Tests bestanden |
| Stack, Verträge und Sicherheit | `stack/tests` | 263 Tests bestanden |
| Hybridindex und Synchronisierung | `stack/kb-sync/tests` | 12 Tests bestanden |
| RAG-Auswertungswerkzeuge | `eval/rag/tests` | 7 Tests bestanden |
| Portal-UI | `npm test` in `admin-dashboard` | 9 Rendering-, UX- und Sicherheitstests sowie Produktionsbuild bestanden |
| Portal-UI-Lint | `npm run lint` in `admin-dashboard` | ohne Fehler bestanden |
| Routing | `caddy validate` mit lokalen Platzhalterwerten | gültig |
| Orchestrierung | `docker compose config --quiet` mit lokalen Platzhalterwerten | gültig |
| Backup, Restore und Reindex | `stack/tests/test_portal_restore_reindex_e2e.py` | im Stack-Testlauf bestanden |

## Nachgewiesene Kerninvarianten

- Rollen, Knowledgebase-Rechte, Freigaben und Originaldateizugriff werden serverseitig geprüft.
- Der globale Dokumentvergleich ist unabhängig von den sichtbaren Knowledgebases des Uploaders.
- Exakte Dubletten werden gegen eine doppelte Veröffentlichung blockiert und der Führungskraft zur Aktionsentscheidung vorgelegt. Knowledgebase-übergreifende Ähnlichkeitstreffer benötigen mindestens die Führungskraft; Widersprüche und Veröffentlichungen in mehreren Wissensbereichen benötigen anschließend zusätzlich einen Admin.
- Uploads laufen als persistente Hintergrundjobs und zeigen einen verständlichen Verarbeitungsstatus.
- Ein abweichender Dokument-Owner benötigt ein gesondertes Recht und muss die Übernahme ausdrücklich bestätigen.
- Führungskräfte, Vertretungen, Abwesenheiten sowie Eskalationen nach zwei, vier und sechs Arbeitstagen sind abgebildet.
- Gleichzeitige Freigaben verschiedener Nutzer werden persistent eingereiht und global nacheinander verarbeitet; doppelte aktive Jobs desselben Falls und parallele Indexwechsel sind ausgeschlossen.
- Malwareprüfung, Dateitypprüfung, Makro-/Verschlüsselungsblockade, Prompt-Injection-Prüfung und Konvertierungsprüfung laufen vor der Freigabe.
- PDF- und Office-Dokumente oberhalb der Grenze von 200 Seiten beziehungsweise geschätzten Druckseiten werden abgewiesen.
- Kontrolliertes RAG-Frontmatter ersetzt nicht vertrauenswürdige Upload-Metadaten.
- Die Legacy-Migration erfasst Original und Markdown rekursiv, erzeugt stabile IDs und konkrete Klärungsaufgaben, prüft Konvertierung und Prompt Injection und übergibt bestandene Dateien an den Owner- und risikobasierten Freigabeprozess. Die lokale Inventur vom 10. August 2026 erfasste 57 Dateien. Davon sind inzwischen 2 nach dem bisherigen Prozess freigegeben und aktiv, 1 begründet zurückgestellt, 51 benötigen Metadaten beziehungsweise Zuständigkeiten und 3 liegen in Quarantäne.
- Autorität und strukturierte Beziehungen wie `supersedes` und `overrides` können ausschließlich administrativ mit Begründung gepflegt werden.
- Abgelaufene, zurückgezogene, gelöschte oder nicht aktive Versionen werden nicht an das Retrieval freigegeben.
- Erinnerungen, Papierkorb, Legal Hold, physische Löschung, Audit und verschlüsseltes Backup sind automatisiert abgedeckt.
- Der Produktionsstart aktiviert das verschlüsselte Backup-Profil zwingend und verweigert den Start ohne Schlüssel oder absolutes zweites Backup-Ziel.
- Ablauf-Sammelmails werden werktäglich ab 10:30 Uhr Europe/Berlin erzeugt; Produktion verlangt eine vollständige Microsoft-Graph-Mailkonfiguration und einen KAHLE-Absender.
- Der lokale Wartungsdienst liefert Nachrichten ohne Graph-Konfiguration in `kb-portal-data/mail-capture.jsonl` aus. Ein realer Lauf vom 10. August 2026 hat Freigabebenachrichtigungen mit Empfänger, Betreff, Inhalt, Typ und UTC-Zeitstempel erfasst.

## Konvertierungsqualität

Die reproduzierbare Messung `stack/tests/measure_conversion_quality.py` lief am 10. August 2026 gegen den echten lokalen Document Worker. Bericht: `eval/rag/results/2026-08-10-conversion-quality.json`.

| Dateien bis 10 MB | Erfolgreich | Erfolgsquote | Langsamste Datei |
|---:|---:|---:|---:|
| 12 | 12 | **100 %** | **0,923 s** |

Der Korpus enthielt PDF, DOCX und neun XLSX-Dateien einschließlich KAHLE-Compliance-Unterlagen und lokaler Vorlagen. Die vorhandene PPTX-Vorlage ist 10.599.005 Bytes groß und liegt damit knapp oberhalb des für dieses Abnahmekriterium definierten Bereichs von höchstens 10 MB. Das PRD-Ziel von mindestens 95 Prozent erfolgreichen Konvertierungen und höchstens fünf Minuten für typische Dateien bis 10 MB ist in dieser lokalen Stichprobe erfüllt.

## Noch offene Go-live-Nachweise

| Nachweis | Status | Nächster Schritt |
|---|---|---|
| Höchstens 5 Prozent unbelegte Antworten ohne freigegebene Quelle | Laufzeitprüfung bestanden: 0 Prozent unbelegte Antworten bei Negativfragen | Auf dem Server mit dem frisch aufgebauten repräsentativen Abnahmekorpus im vollständigen 21-Fragen-Lauf erneut bestätigen |
| 80 Prozent der Testmitarbeiter schaffen den Upload ohne Erklärung | organisatorischer Praxistest offen, Protokoll liegt vor | Testrunde nach `WISSENSPORTAL-UX-TESTPROTOKOLL.md` durchführen |
| Führungskräfte entscheiden Normalfälle durchschnittlich unter drei Minuten | organisatorischer Praxistest offen, Protokoll liegt vor | Zeitmessung in derselben Testrunde durchführen |

## Kalibrierung der automatischen Einstufung

Erster Praxisbefund vom 7. August 2026 mit der KAHLE-KI-Richtlinie. Das Dokument wurde als „bereichsbeschränkt" eingestuft und damit zur Adminprüfung eskaliert, obwohl es eine unternehmensweite Richtlinie ist.

Ursache war keine inhaltliche Erkennung, sondern drei zu grob gefasste Muster:

- Jede E-Mail-Adresse zählte als personenbezogenes Merkmal, auch interne wie `oltmanns@kahle.de` im Verantwortlichkeitsblock.
- Jede Telefonnummer zählte, auch die Servicenummer der Datenschutzbeauftragten.
- Das Wort „vertraulich" zählte, obwohl es in Richtlinien fast immer nur einen Begriff erklärt.

Praktisch wäre damit nahezu jede KAHLE-Richtlinie bereichsbeschränkt geworden und über den Admin gelaufen; die Einstufung hätte ihre Aussagekraft verloren. PRD 15.2 sieht genau diese Kalibrierung anhand echter Dokumente vor.

Nachgezogen wurde:

| Merkmal | Vorher | Jetzt |
|---|---|---|
| E-Mail-Adresse | jede | nur außerhalb von `kahle.de` |
| Telefonnummer | jede | Servicenummern 0800, 0180 und 0900 zählen nicht |
| „vertraulich" | jede Erwähnung | nur als ausdrückliche Kennzeichnung, etwa „Klassifizierung: vertraulich" |

Bank-, Zugangs-, Gesundheits- und Kundendaten sowie Marge, Einkaufspreis und Personalakte lösen unverändert aus. Fünf Tests decken die Abgrenzung ab, darunter der reale Kontaktblock der Richtlinie.

## Begründung und Korrektur durch Mitarbeitende

Mitarbeitende und Führungskräfte können eine Herabstufung mit schriftlicher Begründung beantragen; Admins entscheiden darüber. Admins und Portal-Admins können die Einstufung mit eigener Begründung direkt ändern. Fehler in der Aufbereitung werden in einer eigenen Ansicht anhand von Original und erzeugtem Markdown kommentiert. Erst die ausdrückliche Freigabe per Checkbox erzeugt eine neue, erneut geprüfte Version. Mitarbeitende sehen ihre eigenen Korrekturaufgaben in der Aufgabenliste. Backend- und UI-Tests decken diese Wege ab.

## Benutzeroberfläche und UX

Die Benutzer- und Rechteverwaltung wurde als Master-Detail-Ansicht neu aufgebaut. Admins wählen den Benutzer in einer kompakten Liste links und bearbeiten Führungskraft, Owner-Berechtigung und Wissensbereichsrechte direkt daneben. Anders als zuvor werden diese Felder nicht mehr unbemerkt automatisch gespeichert: Ein sichtbarer Speichern-Button übernimmt alle Änderungen gemeinsam und zeigt den Speicherstatus an. Abwesenheit und Vertretung werden in einem einzigen Formular erfasst und beim Entfernen gemeinsam beendet. Backendtest, Renderingtest, Produktionsbuild und Lint sichern diesen Ablauf ab.

Die Portal-UI wurde am 7. August 2026 gegen die Abschnitte 12.3, 16.1, 21.1, 26.2 und 26.3 des PRD geprüft. Sieben Abweichungen wurden gefunden und behoben:

- `portal.css` besaß keine einzige `:focus-visible`-Regel; Fokuszustände waren nicht erkennbar.
- Benutzer- und Dokumentauswahl waren klickbare `<article>`-Elemente ohne Tastaturpfad und damit ohne Maus nicht erreichbar.
- Mitarbeitende sahen den Fachbegriff „RAG-Markdown" sowie die rohen Einstufungscodes `internal`, `restricted` und `confidential`.
- Die vom PRD geforderte dreistufige Bewertung der Aufbereitung fehlte in der Oberfläche, obwohl das Backend `conversion_quality` bereits lieferte.
- Technische Fehlercodes wie `kahle_microsoft_tenant_required` erreichten den Nutzer unverändert.
- Der Uploadfortschritt wurde nur bei geöffneter Seite verfolgt und zeigte vier statt fünf Stufen.
- Die Gültigkeit war nur als Anzahl Arbeitstage wählbar; die vom PRD gleichrangig vorgesehene Auswahl eines geprüften Datums fehlte.

Alle sieben Punkte sind umgesetzt und durch Zusicherungen im Portaltest gegen Rückschritte gesichert. Die Datumsauswahl rechnet ausschließlich serverseitig um, damit die niedersächsischen Feiertage und die Grenze von 60 Arbeitstagen verbindlich bleiben; ein Datum auf einem Wochenende oder Feiertag verkürzt die Gültigkeit auf den davorliegenden Arbeitstag und verlängert sie nie.

Die Ampel der Aufbereitungsqualität, die Fehlermeldungen und die Begriffe sind damit technisch nachgewiesen. Ob sie für Mitarbeitende tatsächlich verständlich sind, entscheidet ausschließlich der moderierte Praxistest.

Die Formatgrenze entspricht jetzt wieder exakt PRD 12.1: PDF, DOCX, XLSX, PPTX, TXT und Markdown. CSV wird sowohl im Browser bei Auswahl oder Drag-and-drop als auch verbindlich im sicheren Backend-Inspector abgewiesen. Der CSV-Auditexport bleibt davon unberührt, da er kein Dokumentupload ist.

Das Admin-Qualitätsdashboard bildet jetzt alle in PRD 27 geforderten Kennzahlengruppen sichtbar ab. Neu ist eine datensparsame 30-Tage-Retrievaltelemetrie für Anfragezahl, Dokumenttreffer, Quellenabdeckung, unbeantwortete interne Fragen, durchschnittliche und P95-Latenz sowie Fehlerrate. Gespeichert werden ausschließlich Nutzer-ID, SHA-256-Hash der Frage, Trefferstatus, Quellenanzahl, Dauer und technischer Fehlercode – niemals Fragetext, Antwort oder Dokumentinhalt. Technische Retrievalfehler erzeugen außerdem automatisch einen deduplizierten Admin-Incident. Die aktuellen Gesamtzahlen stehen in der Nachweistabelle am Anfang dieser Datei.

## RPO und RTO

**RTO vier Stunden: eingehalten.** Gemessen am 7. August 2026 mit `stack/tests/measure_restore_rto.py` über 500 Dokumente, 1001 Dateien und 392 MB nicht komprimierbarer Originaldaten:

| Schritt | Dauer |
|---|---|
| Verschlüsseltes Backup | 22,43 s |
| Restore | 14,09 s |
| Validierung | 0,03 s |
| Inventar laden | 0,09 s |
| Hybridindex neu aufbauen | 0,20 s |
| **Wiederherstellung gesamt** | **36,85 s** |

Das entspricht 0,26 Prozent des Vier-Stunden-Budgets. 6000 Chunks wurden neu indexiert.

Die ursprüngliche Messung verwendete deterministische lokale Embeddings. Am 10. August 2026 wurde deshalb ein zweiter vollständiger Lauf mit echten IONOS-Embeddings (`BAAI/bge-m3`, Batchgröße 64) über 6.000 Chunks durchgeführt:

| Schritt | Dauer mit echten IONOS-Embeddings |
|---|---:|
| Verschlüsseltes Backup | 8,24 s |
| Restore | 1,59 s |
| Validierung | 0,01 s |
| Inventar laden | 0,01 s |
| Hybridindex neu aufbauen | 507,54 s |
| **Wiederherstellung gesamt** | **517,39 s** |

Damit werden 3,59 Prozent des Vier-Stunden-Budgets ausgeschöpft. Das RTO ist auch unter Einbeziehung des realen externen Embedding-Endpunkts nachgewiesen.

**RPO 24 Stunden: eingehalten, ohne Puffer.** `backup_worker.py` prüft stündlich und erzeugt genau eine Sicherung je Kalendertag. Der größtmögliche Abstand zwischen zwei erfolgreichen Sicherungen beträgt damit 24 Stunden, der maximale Datenverlust entsprechend knapp 24 Stunden. Ein einzelner fehlgeschlagener Backupzyklus verletzt den RPO deshalb unmittelbar. Der Worker meldet jeden Fehlschlag sofort als Admin-Incident; ein zeitlicher Puffer besteht nicht.

## Retrieval-Evaluation

Ausgeführt am 7. August 2026 mit den vier Document-Worker-Ausgaben und den 21 Fragen aus `eval/rag/kahle-document-worker-questions.yml`. Bericht: `eval/rag/results/2026-08-07-hybrid-ionos.json`. Korpus: 121 Chunks, Embeddings `BAAI/bge-m3`, Reranker `Qwen/Qwen3-VL-Reranker-8B`, beide auf IONOS.

| Konfiguration | Richtige Dokumenttreffer | Korrekte Quellenlinks |
|---|---:|---:|
| Dense-only (Ausgangswert) | 90,5 % | 100 % |
| Sparse/BM25-only | 95,2 % | 100 % |
| Hybrid mit RRF | **100 %** | 100 % |
| Hybrid mit RRF und Reranker | **100 %** | 100 % |

Damit sind die Kriterien aus PRD 29.2 erfüllt: mindestens 90 Prozent Dokumenttreffer und mindestens 95 Prozent korrekt verlinkte Originalquellen. Die Negativfrage nach der frei erfundenen Anwendung `ZX-999-NICHT-VORHANDEN` wird in allen vier Konfigurationen korrekt nicht belegt.

Die vom PRD 30 geforderte Vergleichsreihe zeigt den erwarteten Verlauf: Die reine Dense-Suche verfehlt zwei Fragen, darunter eine rein lexikalische nach dem Eskalationsprozess. Die deutsche BM25-Suche fängt diese ab, und erst die Fusion beider erreicht die volle Trefferquote.

Einschränkungen, die noch offen sind:

- **Latenz.** Der Median liegt bei 12,4 Sekunden je Frage, das 95. Perzentil bei 23,8 Sekunden. Gemessen wird dabei Query-Embedding plus Reranking über 50 Kandidaten; die Laufzeit ersetzt die lokale Kosinusberechnung durch Qdrant. Das PRD setzt für das Retrieval keine harte Zeitgrenze, aber für einen Chat ist das spürbar und gehört vor dem Rollout genauer untersucht.
- **Kein Vergleich gegen den lokalen Reranker.** Der Baseline-Lauf mit `gte-multilingual-reranker-base` wurde abgebrochen, als der Testcontainer entfernt wurde. Da dieses Modell wegen seiner Laufzeit ohnehin ausscheidet, wurde er nicht wiederholt.
- **Offline-Charakter.** Die Evaluation arbeitet direkt auf den Chunks und umgeht Qdrant, die Berechtigungsfilter und das Antwortmodell. Die Rechteprüfung ist getrennt durch die Sicherheitstests belegt.

## Reranking läuft auf IONOS

Das Reranking war auf einen lokal betriebenen CPU-Cross-Encoder verdrahtet (`Alibaba-NLP/gte-multilingual-reranker-base` in einem TEI-Container). Auf reiner CPU braucht dieses Modell rund zwei Sekunden je Kandidat. Gemessen am 7. August 2026:

| Kandidaten | lokal (CPU) | IONOS |
|---:|---|---|
| 8 | 17,0 s | – |
| 32 | 62,2 s | – |
| 50 | 101,7 s | 3,24 s Median, 9,17 s schlechtester von zwölf Läufen |

PRD 19.2 erzwingt 30 bis 50 Kandidaten je Anfrage, und `QdrantHybridRetriever` setzt diese Grenzen hart durch. Da das Retrieval fail-closed arbeitet, hätte jede Anfrage oberhalb von etwa 30 Kandidaten **gar keine Antwort** geliefert. Das Zielsystem ist ein netcup VPS 2000 G12 ohne GPU; die Laufzeit ließ sich deshalb nicht durch Konfiguration retten.

Reranking läuft jetzt über `Qwen/Qwen3-VL-Reranker-8B` auf den freigegebenen IONOS-Endpunkten. PRD Prinzip 10 lässt alle drei Vertraulichkeitsstufen dort ausdrücklich zu, und die Embeddings nutzen denselben Weg bereits. Die Trennschärfe ist zusätzlich besser: 0,96 gegen 0,02 bei einem deutschen Beispiel, lokal waren es 0,45 gegen 0,04.

Der lokale `reranker`-Dienst ist vollständig aus `docker-compose.yml` entfernt, ebenso sein Volume und die nicht mehr gelesene Variable `RERANKER_URL`. Zwei Tests sichern, dass er nicht zurückkehrt und dass das IONOS-Antwortformat korrekt gelesen wird.

Nebenbefund: `hybrid_retrieval.py` enthielt bereits eine korrekte `IonosReranker`-Klasse, die nie verdrahtet worden war.

## Offene Punkte für den Serverrollout

| Punkt | Was zu tun ist |
|---|---|
| Name des IONOS-Tokens | Lokal ist der Token als Umgebungsvariable `IONOS_API_TOKEN` gesetzt, die Produktionsvorlage führt ihn als `IONOS_API_KEY`. Code und Compose akzeptieren jetzt **beide** Namen, `IONOS_API_TOKEN` hat Vorrang. Beim Rollout ist zu prüfen, unter welchem Namen der Token auf dem Server tatsächlich hinterlegt ist; ein Umbenennen ist nicht mehr nötig, aber genau einer der beiden muss gesetzt sein. |
| Reranker-Erreichbarkeit | Der Produktionsserver muss die IONOS-Endpunkte erreichen. Fällt IONOS aus, liefert Vinci fail-closed keine Wissensantwort mehr — es gibt bewusst keinen lokalen Rückfall auf ein schwächeres Modell. |
| Freigewordene Ressourcen | Der entfernte Reranker-Container belegte auf dem VPS dauerhaft Arbeitsspeicher. Nach dem Rollout ist zu prüfen, ob das Speicherbudget entsprechend angepasst werden kann. |

## Aktueller externer Prüfblocker

Die frühere HTTP-401-Diagnose beruhte auf dem falschen lokalen Secret: Direkt geprüft worden war der ältere Credential-Manager-Eintrag `IONOS_API_KEY`. Der laufende Stack verwendet entsprechend der Compose-Priorität die Windows-Benutzervariable `IONOS_API_TOKEN`. Mit genau diesem, auch von OpenWebUI verwendeten Token wurden am 10. August 2026 Modellliste, Mistral Small 24B, GPT-OSS 120B und BGE-M3 erfolgreich mit HTTP 200 geprüft. BGE-M3 liefert die erwarteten 1.024 Dimensionen. Ein Tokenwechsel ist nicht erforderlich.

Der Laufzeit-Evaluationssatz umfasst 21 Fragen. `eval/rag/run_runtime_eval.py` bildet den echten OpenWebUI-Browserablauf nach: temporären Chat anlegen, Hintergrundaufgabe starten, persistierte Assistentennachricht samt Toolausgabe und Quellen abfragen, Folgefragen im selben Chat senden und den Testchat anschließend löschen. Sieben Tests sichern Runner und Auswertung.

Der vollständige Lauf vom 10. August 2026 liegt unter `eval/rag/results/rag-runtime-eval-20260810-120045.jsonl`, die Auswertung unter `eval/rag/results/2026-08-10-runtime-eval-report.json`. Alle 21 Anfragen wurden gestartet; 20 wurden fachlich abgeschlossen, bei einer Abfrage lief ein 30-Sekunden-Polling-Request in einen Timeout. Der Runner wiederholt solche Polling-Timeouts jetzt bis zum Gesamtzeitlimit. Jede abgeschlossene Frage durchlief `rag_chat`; die erfundene Kennung ZX-999 blieb ohne Quelle und die Quote unbelegter Antworten bei Negativfragen beträgt 0 Prozent.

Der bisherige Gesamtlauf ist bewusst **nicht bestanden**. Zum Zeitpunkt dieser Messung lag im aktiven Portalindex nur die regulär freigegebene `KAHLE KI Policy v1.4`; entsprechend betrug die Dokumenttrefferquote des auf drei Wissensbereiche ausgelegten Satzes 4,76 Prozent. Inzwischen sind zwei weitere Altbestände nach dem bisherigen Prozess freigegeben und aktiv. Der Lauf muss nach Abschluss der fachlichen Migration mit dem dann maßgeblichen Korpus vollständig wiederholt werden. Die noch offenen Altbestände dürfen erst nach der neu festgelegten risikobasierten Freigabematrix aktiviert werden.

Der zuvor testweise verwendete lokale TEI-Reranker ist aus dem aktiven Stack entfernt. Offline-Evaluation und Vinci-Laufzeit verwenden jetzt beide den IONOS-Reranker `Qwen/Qwen3-VL-Reranker-8B` und brechen bei dessen Ausfall geschlossen ab.

Ein zusätzlicher Laufzeittest zeigte, dass ein Reranker ohne Mindestwert auch bei einer fachfremden Frage einen formal besten Treffer liefert. Deshalb gilt nun eine Mindest-Relevanz von 0,25. Die Kalibrierung am aktiven lokalen Korpus ergab 0,193 für eine fachfremde Leistungsfrage, 0,128 für eine erfundene Kennung und 0,517 für eine belegte Eskalationsfrage. Nach dem Ausrollen lieferten fachfremde Fragen keine Quelle mehr, die belegte Frage weiterhin eine freigegebene Quelle mit sicherem `/wissen/api/portal/sources/...`-Link. Zwei Tests sichern Grenzwert und Konfiguration.

Der Laufzeitnachweis deckte drei weitere Sicherheitslücken auf und schloss sie: Native Function Calling darf eine interne Wissensfrage nicht mehr ohne `rag_chat` beantworten; unterschiedliche relevante Abschnitte desselben Dokuments bleiben bis zum Reranking erhalten; explizit genannte Quellenkennungen wie `KB_KAHLE_Hannover` müssen den Dokumenttitel tatsächlich treffen. Außerdem entfernt der Server vom Modell erfundene Quelldomains und hängt ausschließlich die kanonischen relativen Original-Links aus `SOURCES_JSON` an. Der positive Kontrollfall nennt nach der Korrektur alle vier Whitelist-Systeme und verlinkt die Originaldatei; die nicht vorhandene Hannover-Quelle bleibt ohne Treffer.

Für die fachliche Bearbeitung der Legacy-Aufgaben wurde die Migrationsansicht vereinfacht. Admins wählen Owner, konkrete Zugriffsgruppe und eine der sechs ausgeschriebenen Autoritätsstufen. Der erkannte Ziel-Wissensbereich wird vorausgewählt und kann fachlich korrigiert werden; Dateien auf der obersten Ebene verlangen eine ausdrückliche Zuordnung. Diese Auswahl bleibt auch bei erneuter Inventur stabil. Der optionale Geltungsbereich wird in Alltagssprache beschrieben statt als JSON. Suche und Statusfilter machen die 57 Einträge bearbeitbar. Original und aufbereitete Fassung lassen sich vor der Einstufung in einem neuen Tab öffnen. Die Owner-Auswahl enthält nur aktive Benutzer mit zugeordneter Führungskraft. Nach der Produktentscheidung vom 11. August 2026 richtet sich die erforderliche Freigabe nach Ziel-Wissensbereich und Prüfbefund. Diese Matrix ist inzwischen serverseitig umgesetzt: saubere Bereichsdokumente können bei aktivem Schalter automatisch aktiviert werden, KAHLE-Allgemein und normale Dubletten-/Versionsfälle gehen an die Führungskraft, kritische Fälle anschließend zusätzlich an einen Admin. Portal-Admins dürfen eigene kritische Fälle mit schriftlicher Begründung abschließend entscheiden. Der Dateiendpunkt akzeptiert ausschließlich bereits inventarisierte Pfade innerhalb des Knowledge-Roots und bleibt Adminrollen vorbehalten. Der echte lokale Abruf einer inventarisierten Markdown-Datei lieferte HTTP 200 und `text/markdown`; das aktualisierte Dashboard läuft lokal unter `/wissen`.

Nicht zu übernehmende Altbestände können Admins mit einer kurzen Begründung in den separaten Bereich „Nicht übernehmen“ verschieben. Die Original- und Markdown-Dateien werden nicht gelöscht. Die Entscheidung wird mit Benutzer und Zeitpunkt protokolliert und kann mit erneuter Begründung rückgängig gemacht werden; dann öffnet das System die erforderlichen Migrationsaufgaben wieder. Die normale Ansicht „Noch zu bearbeiten“ bleibt dadurch auf die tatsächlich zu prüfenden Dokumente begrenzt.

Für den Go-live offen sind damit der frische fachliche Wissensaufbau auf dem Server, die anschließende Wiederholung des vollständigen Laufzeitsatzes sowie die organisatorischen Mehrbenutzer- und UX-Praxistests. Die verbleibenden lokalen Legacy-Aufgaben werden nicht als produktiver Bestand übernommen und blockieren den Server-Test deshalb nicht.

Das Go-live-Gate bleibt geschlossen, bis alle offenen Nachweise erbracht und in dieser Datei dokumentiert sind.

Der vollständige Mehrbenutzertest kann lokal nicht realistisch durchgeführt werden, weil nur drei technische Testidentitäten vorhanden sind und keine getrennte interaktive Anmeldung möglich ist. Der Server-Test startet deshalb mit leeren Knowledgebases und einem kontrolliert über das Portal aufgebauten Abnahmekorpus. Danach müssen echte Mitarbeiter-, Führungskraft- und Admin-Konten das Aufgabenrouting, die sichtbaren Statusänderungen und die E-Mail-Empfänger prüfen. Dieser organisatorische Nachweis bleibt bis dahin offen.

## Nachweismatrix der PRD-Abnahmeszenarien

Die folgende Matrix ordnet die automatisierten Nachweise der risikobasierten Produktentscheidung vom 11. August 2026 zu. Sie belegt die technische Zustands- und Rechteprüfung; die separat verlangten Praxistests mit echten Mitarbeitenden und Führungskräften bleiben davon unberührt.

| Nr. | Szenario | Nachweis | Stand |
|---:|---|---|---|
| 1 | Sauberes DOCX in einer Bereichs-Knowledgebase automatisch aktivieren und Originalquelle öffnen | `test_clean_area_docx_is_automatically_active_and_exposes_original_only_to_read_authorized_user` | automatisierter HTTP-Gesamtablauf bestanden |
| 2 | Sauberes Dokument für KAHLE-Allgemein durch Führungskraft freigeben | `test_clean_general_upload_uses_account_owner_and_is_activated_by_manager` | automatisierter HTTP-Gesamtablauf bestanden |
| 3 | Identische Datei gegen doppelte Veröffentlichung blockieren und der Führungskraft vorlegen | `test_exact_duplicate_is_blocked_and_only_publish_or_discard_is_allowed` | automatisiert bestanden |
| 4 | Identisches Dokument nach Führungskraft und Admin in weiterer Knowledgebase veröffentlichen | `test_cross_kb_exact_duplicate_publishes_existing_canonical_document_only`, `test_cross_kb_or_contradiction_requires_admin_and_cannot_be_manager_approved` | automatisiert bestanden |
| 5 | Neue Version atomar ersetzen und zurückrollen | `test_real_upload_is_bound_to_selected_version_candidate_before_replacement`, `test_new_version_atomically_supersedes_previous_active_version`, `test_failed_index_activation_restores_previous_active_version` | automatisiert bestanden |
| 6 | Ähnliche Dokumente verständlich vergleichen | `test_semantic_and_lexical_signals_are_combined_and_version_is_suggested`, `test_real_upload_is_bound_to_selected_version_candidate_before_replacement` sowie Portal-Renderingtest | technisch automatisiert; Praxistest bleibt offen |
| 7 | Knowledgebase-übergreifenden Ähnlichkeitstreffer mindestens der Führungskraft vorlegen | `test_cross_kb_or_contradiction_requires_admin_and_cannot_be_manager_approved` | automatisiert bestanden |
| 8 | Widersprüchliche Richtlinien erst nach Führungskraft und Admin veröffentlichen | `test_cross_kb_or_contradiction_requires_admin_and_cannot_be_manager_approved` | automatisiert bestanden |
| 9 | Kritischen Prompt-Injection-Befund durch Führungskraft und Admin prüfen; Malware nicht übersteuerbar blockieren | `test_any_prompt_injection_signal_requires_manager_then_admin`, `test_required_scanner_outage_fails_closed_and_creates_admin_incident` sowie Malwaretests in `test_secure_ingest.py` | automatisiert bestanden |
| 10 | Fehlerhafte Tabellen-/Excel-Konvertierung zeilen- und spaltenbezogen anzeigen und korrigieren | `test_conversion_quality_blocks_mojibake_and_flags_broken_tables`, `test_confirmed_employee_comment_creates_new_checked_draft_version`, Portal-Renderingtest | automatisiert bestanden |
| 11 | Owner bestätigt Aktualität; Führungskraft verlängert | `test_single_knowledgebase_renewal_requires_owner_confirmation_then_manager_only` | automatisiert bestanden |
| 12 | Mehrfach veröffentlichtes Dokument durch Führungskraft und Admin verlängern | `test_multi_knowledgebase_renewal_requires_manager_then_admin` | automatisiert bestanden |
| 13 | Abgelaufenes Dokument automatisch aus RAG entfernen | `test_expired_versions_are_removed_from_all_active_publications`, `test_expired_or_nonactive_document_can_never_be_activated` | automatisiert bestanden |
| 14 | Ohne Leserecht weder Antwortinhalt noch Originalquelle erhalten | `test_internal_scope_is_authenticated_and_derived_from_persisted_read_rights`, `test_hybrid_request_repeats_acl_in_both_prefetches_and_rejects_leak`, DOCX-HTTP-Test | automatisiert bestanden |
| 15 | Falsche Vinci-Antwort als Korrekturfall erfassen | `test_permission_feedback_is_critical_and_captures_effective_rights`, Portal-Feedbacktest | automatisiert bestanden |
| 16 | Deaktivierter Owner erzeugt Neuzuordnungsaufgabe | `test_deactivated_owner_creates_task_and_new_owner_must_confirm` | automatisiert bestanden |
| 17 | Admin bereitet Knowledgebase vor; Portal-Admin entscheidet | `test_admin_prepares_knowledgebase_change_portal_admin_decides` | automatisiert bestanden |
| 18 | Portal-Admin legt Knowledgebase direkt an | derselbe Governance-Test und HTTP-Vertrag | automatisiert bestanden |
| 19 | Dokument innerhalb von 30 Tagen wiederherstellen | `test_employee_removal_request_requires_admin_and_restore_reactivates_valid_version` | automatisiert bestanden |
| 20 | Nach 90 Tagen physisch löschen und Audit behalten | `test_trash_reminders_and_physical_deletion_at_day_90` | automatisiert bestanden |
| 21 | Vollständiger Restore und Indexneuaufbau | `test_encrypted_restore_rebuilds_authoritative_hybrid_index` | automatisiert bestanden |

Die drei Freigabestufen sind technisch implementiert und automatisiert geprüft. Das Go-live-Gate bleibt dennoch geschlossen, bis die fachliche Legacy-Migration, der Laufzeitsatz mit dem maßgeblichen Korpus und die Praxistests mit Mitarbeitenden, Führungskräften und Admins bestanden sind.

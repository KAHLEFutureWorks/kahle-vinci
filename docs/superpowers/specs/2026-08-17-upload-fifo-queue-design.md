# Persistente FIFO-Warteschlange für Dokument-Uploads

## Ziel

Alle Dokument-Uploads werden unabhängig vom hochladenden Mitarbeiter in einer gemeinsamen, persistenten FIFO-Warteschlange verarbeitet. Es ist global höchstens ein Upload aktiv. Ein fehlgeschlagener Auftrag beendet nur sich selbst; anschließend wird automatisch der nächste Auftrag bearbeitet.

Die Zuordnung technischer Fehler muss eindeutig sein. Uploader und ein abweichender vorgesehener Dokument-Owner werden über das Portal und per E-Mail informiert.

## Ausgangslage

Der API-Endpunkt `/portal/upload-jobs` erzeugt aktuell einen Datensatz in `upload_jobs` und startet anschließend pro HTTP-Anfrage einen eigenen FastAPI-Background-Task. Background-Tasks verschiedener Anfragen laufen parallel. Die hochgeladene Datei und ihre Metadaten existieren für den Auftrag nur im Arbeitsspeicher des jeweiligen Requests.

Konvertierungsfehler erzeugen einen technischen Qualitätsfall mit Fehlercode und gegebenenfalls Seitenbereich. Job-ID, Titel, Dateiname, Uploader, vorgesehener Owner und Wissensbereiche werden nicht übergeben. Gleiche Diagnosen erhalten denselben Fingerprint und werden dadurch uploadübergreifend zusammengeführt.

## Architektur

### UploadJobQueue

`UploadJobService` wird zu einer persistenten Single-Consumer-Queue erweitert. Die Tabelle `upload_jobs` speichert zusätzlich:

- ursprünglicher Dateiname,
- Dokumenttitel,
- Ziel-Wissensbereiche als JSON,
- Gültigkeit in Arbeitstagen,
- Vertraulichkeitsstufe,
- vorgesehene Owner-ID,
- ID des Uploaders; aktuelle, nicht geheime Identitätsfelder werden erst bei der Verarbeitung aus der Portal-Benutzerverwaltung geladen,
- Anforderung einer PDF-Sicherheitsprüfung,
- relativer Pfad zur staged Datei,
- Dateigröße,
- Queue-Lease mit Ablaufzeit,
- optional die ID des erzeugten technischen Falls.

Neue Spalten werden bei bestehenden Datenbanken additiv ergänzt. Vorhandene abgeschlossene oder fehlgeschlagene Aufträge bleiben lesbar.

`enqueue` schreibt Metadaten und staged Dateipfad gemeinsam mit Status `queued`. `claim_next` verwendet `BEGIN IMMEDIATE`, verweigert einen Claim bei einem noch gültigen aktiven Auftrag und beansprucht danach atomar den ältesten Auftrag nach `created_at, job_id`.

`get` berechnet für wartende Aufträge die Position innerhalb der globalen Queue. `list_active` liefert einem Benutzer alle eigenen wartenden und laufenden Aufträge. Administratoren können alle aktiven Aufträge sehen.

### Geschützter Dateispeicher

Die Request-Verarbeitung speichert die hochgeladene Datei vor dem Enqueue atomar in einem persistenten Spool-Verzeichnis unter dem bestehenden Portal-Dateispeicher. Dateinamen werden nicht als Speicherpfade verwendet. Der Pfad basiert ausschließlich auf der validierten Job-ID.

Die staged Datei ist noch nicht freigegeben und wird ausschließlich vom Upload-Worker gelesen. Nach `completed` oder `failed` wird sie entfernt. Bei einem Abbruch bleibt sie erhalten, bis der Worker die abgelaufene Lease als `upload_worker_interrupted` abschließt und die Datei kontrolliert entfernt. Verwaiste Dateien ohne aktiven Queue-Datensatz werden durch die Wartungslogik nach sieben Tagen entfernt.

Scheitert das atomare Speichern, wird kein Queue-Datensatz erzeugt. Scheitert das Enqueue nach erfolgreichem Speichern, wird die staged Datei unmittelbar entfernt.

### Dedizierter Upload-Worker

Ein neuer Dienst `kb-upload-worker` verwendet dasselbe Image und dieselben produktiven Volumes sowie Umgebungsvariablen wie `kb-admin-api`. Er startet ein fokussiertes Worker-Modul und verarbeitet mit einem einzigen Consumer:

1. ältesten Auftrag atomar beanspruchen,
2. staged Datei und gespeicherte Metadaten laden,
3. bestehenden sicheren Ingest- und Analysepfad ausführen,
4. Fortschritt und Lease während langer PDF-Blockkonvertierungen aktualisieren,
5. Auftrag als `completed` oder `failed` abschließen,
6. staged Datei bei einem terminalen Zustand entfernen,
7. ohne Verzögerung den nächsten Auftrag beanspruchen.

Wenn keine Arbeit vorliegt, wartet der Worker kurz und fragt erneut ab. Ein Fehler in einem Auftrag beendet den Worker-Prozess nicht. Unerwartete Worker-Fehler werden dem Auftrag zugeordnet und danach wird die Queue fortgesetzt.

Der API-Endpunkt startet keine eigene Dokumentverarbeitung mehr. Er validiert Berechtigung und maximale Dateigröße, speichert die Datei, reiht den Auftrag ein und antwortet mit `202` sowie Job-ID, Status, Fortschritt und Queue-Position.

### Verhalten nach Neustart

Ein beanspruchter Auftrag besitzt eine zeitlich begrenzte Lease. Der Worker verlängert sie bei jedem Fortschrittsupdate. Wartende Aufträge bleiben bei einem Neustart vollständig erhalten und werden anschließend in ihrer ursprünglichen Reihenfolge weiterbearbeitet.

Ein beim Prozessabbruch bereits aktiver Auftrag wird nach Ablauf seiner Lease nicht automatisch ein zweites Mal ausgeführt. Der sichere Ingest-Pfad besitzt noch keine durchgängigen, persistenten Checkpoints und könnte sonst nach einem Abbruch doppelte Entwürfe oder Veröffentlichungsversuche erzeugen. Der abgelaufene Auftrag wird mit `upload_worker_interrupted` als fehlgeschlagen abgeschlossen, den zuständigen Benutzern zugeordnet gemeldet und aus der aktiven Queue entfernt. Danach verarbeitet der Worker sofort den nächsten wartenden Auftrag. Der Benutzer kann die betroffene Datei anschließend bewusst erneut einreichen.

## Fehler- und Qualitätsfälle

Bei einem uploadbezogenen Fehler wird die Diagnose mindestens mit folgenden Feldern erzeugt:

- `job_id`,
- `error_code`,
- `title`,
- `original_filename`,
- `uploaded_by_user_id`,
- `intended_owner_user_id`,
- `knowledgebase_ids`,
- `file_size_bytes`,
- `page_range`, sofern bekannt.

Der Fingerprint lautet fachlich `upload_job:<job_id>:<error_code>`. Damit erhält jeder fehlgeschlagene Upload einen eigenen Qualitätsfall. Wiederholt sich derselbe Fehler beim selben Job, wird der vorhandene Fall wieder geöffnet beziehungsweise aktualisiert.

Der Qualitätsfall zeigt Titel, Dateiname, Job-ID, Uploader, vorgesehenen Owner, Wissensbereiche, Dateigröße und Seitenbereich in verständlicher Form. Technische Rohdaten bleiben auf die für Diagnose und Zuordnung erforderlichen Werte begrenzt. Dokumentinhalt, Zugangsdaten und Schlüssel werden nie gespeichert oder angezeigt.

## Benachrichtigungen

Bei einem terminal fehlgeschlagenen Upload werden die Empfänger als eindeutige Menge gebildet:

1. immer der Uploader,
2. zusätzlich der vorgesehene Dokument-Owner, wenn er vom Uploader abweicht und als aktiver Portal-Benutzer eindeutig vorhanden ist.

Für jeden Empfänger wird eine Portalnachricht in `portal_notifications` angelegt und eine E-Mail über die bestehende Notification-Outbox eingeplant. Betreff und Nachricht nennen Dokumenttitel, Dateiname und Job-ID sowie den verständlichen Hinweis, dass die Aufbereitung nicht abgeschlossen werden konnte. Die technische Fall-ID wird als Referenz ergänzt. Die Nachricht enthält keinen Dokumentinhalt.

Die Benachrichtigung verwendet eine deduplizierte ID aus Job-ID, Empfänger und Status. Ein Retry desselben fehlgeschlagenen Zustands erzeugt keine doppelte Nachricht. Ein späterer, eigenständiger Upload erzeugt eine neue Nachricht.

## Portal-Oberfläche

Der Upload-Bereich fragt beim Öffnen alle eigenen Aufträge mit Status `queued` oder `processing` ab. Dadurch hängt die Darstellung nicht mehr von einer einzelnen `sessionStorage`-Job-ID ab.

Für jeden aktiven Auftrag werden angezeigt:

- Titel und Dateiname,
- Status `Wartet` oder `Wird verarbeitet`,
- globale Queue-Position bei `queued`,
- Verarbeitungsschritt und Fortschritt bei `processing`.

Der gerade eingereichte Auftrag bleibt prominent sichtbar. Weitere eigene Aufträge erscheinen in einer kompakten Liste. Ein Seitenwechsel, Reload oder zusätzlicher Upload überschreibt keinen bestehenden Status. Terminale Fehler erscheinen über die Portalbenachrichtigung und beim direkt beobachteten Auftrag zusätzlich als verständliche Fehlermeldung.

Die Qualitätsfall-Ansicht zeigt die gespeicherten Upload-Metadaten sowohl auf der Karte als auch im Bearbeitungsdialog.

## Datenfluss

1. Benutzer lädt eine Datei hoch.
2. API validiert Dateigröße und Upload-Berechtigungen.
3. API erzeugt eine Job-ID und speichert die Datei atomar im geschützten Spool.
4. API speichert den vollständigen Queue-Datensatz und antwortet `202` mit Queue-Position.
5. Der einzelne Upload-Worker beansprucht den ältesten Auftrag.
6. Der bestehende Sicherheits-, Konvertierungs- und Analysepfad verarbeitet die Datei.
7. Bei Erfolg werden Ergebnis und Status gespeichert und die staged Datei entfernt.
8. Bei Fehler werden Qualitätsfall und Benachrichtigungen erzeugt, der Auftrag wird als `failed` gespeichert und die staged Datei entfernt.
9. Der Worker beansprucht sofort den nächsten Auftrag.

## Tests

### Queue und Persistenz

- Zwei gleichzeitig eingereichte Uploads werden in Erstellungsreihenfolge beansprucht.
- Es kann global höchstens einen Auftrag mit gültigem Status `processing` geben.
- Ein zweiter Claim während einer gültigen Lease liefert keinen Auftrag.
- Eine abgelaufene Lease schließt den unterbrochenen Auftrag eindeutig als `failed` ab und gibt die Queue für den nächsten Auftrag frei.
- Die Queue-Position entspricht der globalen FIFO-Reihenfolge.
- Aktive Aufträge sind nur für ihren Benutzer beziehungsweise Administratoren sichtbar.
- Metadaten und staged Pfad überleben eine neue Service-Instanz.

### Verarbeitung

- Der API-Endpunkt führt keine Konvertierung im Request-Background-Task aus.
- Der Worker verarbeitet wartende Aufträge exakt in FIFO-Reihenfolge.
- Nach einem Fehler wird der nächste Auftrag bearbeitet.
- Fortschrittsupdates verlängern die Lease.
- Staged Dateien bleiben bei einem Prozessabbruch bestehen und werden bei terminalem Erfolg oder Fehler entfernt.
- Die vorhandenen PDF-Blocktests bleiben erfolgreich.

### Qualitätsfälle und Benachrichtigungen

- Ein Konvertierungsfehler enthält Job-ID, Titel, Dateiname, Benutzer, Owner, Wissensbereiche, Dateigröße und Seitenbereich.
- Zwei verschiedene fehlgeschlagene Uploads erhalten zwei verschiedene Qualitätsfälle.
- Derselbe Job und Fehler verwenden denselben Fall erneut.
- Uploader erhält Portalnachricht und E-Mail.
- Ein abweichender aktiver Owner erhält beide Benachrichtigungen zusätzlich.
- Ein identischer Uploader und Owner erhält keine doppelte Nachricht.

### Oberfläche

- Wartende Aufträge zeigen ihre Position.
- Mehrere eigene Uploads bleiben nach einem Reload sichtbar.
- Qualitätsfälle zeigen die Upload-Zuordnung verständlich an.
- Die bestehende direkte Fehlerdarstellung bleibt funktionsfähig.

## Rollout

Der Rollout enthält nur tatsächlich veränderte Laufzeitdateien und notwendige Tests nicht. Vor jeder Installation werden die betroffenen Dateien unter `/opt/kahle-vinci/.rollout-backups/` gesichert. Bei einem Fehler werden Dateien und betroffene Dienste auf den vorherigen Stand zurückgesetzt.

Betroffen sind `kb-admin-api`, der neue `kb-upload-worker` auf Basis desselben Images und `kb-admin-dashboard`. Der Document-Worker wird nicht geändert oder neu gebaut.

Der Installationsablauf prüft Python-Syntax ohne schreibbare `__pycache__`-Dateien in den Zielordnern, baut nur die betroffenen Dienste, wartet auf ihre Healthchecks und prüft Queue-Semantik, Worker-Status sowie die sichtbaren Qualitätsfall-Metadaten.

Es wird weder committed noch gepusht, solange dies nicht ausdrücklich beauftragt wird.

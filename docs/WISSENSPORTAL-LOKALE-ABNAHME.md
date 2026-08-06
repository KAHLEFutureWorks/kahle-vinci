# Lokale Abnahme des KAHLE-Vinci Wissensportals

Stand: 6. August 2026

Dieses Protokoll ist die fortlaufende Nachweisakte zur lokalen Umsetzung des PRD. Eine Produktionsfreigabe ist damit ausdrücklich nicht verbunden.

## Automatisierte Nachweise

| Bereich | Nachweis | Ergebnis |
|---|---|---|
| Portal-Backend | `stack/kb-admin-api/tests` | 65 Tests bestanden |
| Stack, Verträge und Sicherheit | `stack/tests` | 238 Tests bestanden |
| Hybridindex und Synchronisierung | `stack/kb-sync/tests` | 10 Tests bestanden |
| Portal-UI | `npm test` in `admin-dashboard` | Build und 2 Rendering-/Sicherheitstests bestanden |
| Routing | `caddy validate` mit lokalen Platzhalterwerten | gültig |
| Orchestrierung | `docker compose config --quiet` mit lokalen Platzhalterwerten | gültig |
| Backup, Restore und Reindex | `stack/tests/test_portal_restore_reindex_e2e.py` | im Stack-Testlauf bestanden |

## Nachgewiesene Kerninvarianten

- Rollen, Knowledgebase-Rechte, Freigaben und Originaldateizugriff werden serverseitig geprüft.
- Der globale Dokumentvergleich ist unabhängig von den sichtbaren Knowledgebases des Uploaders.
- Exakte Dubletten werden blockiert; Knowledgebase-übergreifende Treffer und Widersprüche werden an Admins geleitet.
- Uploads laufen als persistente Hintergrundjobs und zeigen einen verständlichen Verarbeitungsstatus.
- Ein abweichender Dokument-Owner benötigt ein gesondertes Recht und muss die Übernahme ausdrücklich bestätigen.
- Führungskräfte, Vertretungen, Abwesenheiten sowie Eskalationen nach zwei, vier und sechs Arbeitstagen sind abgebildet.
- Malwareprüfung, Dateitypprüfung, Makro-/Verschlüsselungsblockade, Prompt-Injection-Prüfung und Konvertierungsprüfung laufen vor der Freigabe.
- PDF- und Office-Dokumente oberhalb der Grenze von 200 Seiten beziehungsweise geschätzten Druckseiten werden abgewiesen.
- Kontrolliertes RAG-Frontmatter ersetzt nicht vertrauenswürdige Upload-Metadaten.
- Autorität und strukturierte Beziehungen wie `supersedes` und `overrides` können ausschließlich administrativ mit Begründung gepflegt werden.
- Abgelaufene, zurückgezogene, gelöschte oder nicht aktive Versionen werden nicht an das Retrieval freigegeben.
- Erinnerungen, Papierkorb, Legal Hold, physische Löschung, Audit und verschlüsseltes Backup sind automatisiert abgedeckt.

## Noch offene Go-live-Nachweise

| Nachweis | Status | Nächster Schritt |
|---|---|---|
| Mindestens 90 Prozent richtige Treffer mit den vier KAHLE-Beispieldokumenten | blockiert durch lokalen IONOS-Token | gültigen IONOS-Token im lokalen `kb-sync` hinterlegen und `eval/rag/offline_hybrid_eval.py` ausführen |
| Mindestens 95 Prozent korrekt verlinkte Originalquellen | gemeinsam mit Retrieval-Evaluation offen | Bericht der Retrieval-Evaluation auswerten |
| Höchstens 5 Prozent unbelegte Antworten ohne freigegebene Quelle | Laufzeitevaluation offen | Negativfragen mit dem lokalen Vinci-Chat ausführen |
| 80 Prozent der Testmitarbeiter schaffen den Upload ohne Erklärung | organisatorischer Praxistest offen | kurze moderierte lokale Testrunde durchführen |
| Führungskräfte entscheiden Normalfälle durchschnittlich unter drei Minuten | organisatorischer Praxistest offen | Zeitmessung in derselben Testrunde durchführen |
| RPO 24 Stunden und RTO vier Stunden | technischer Restore bestanden, Zeitnachweis offen | vollständigen lokalen Restore mit Zeitmessung protokollieren |

## Aktueller externer Prüfblocker

Der im lokalen Container `kb-sync` konfigurierte IONOS-Token wurde am 6. August 2026 vom Embedding-Endpunkt mit HTTP 401 abgelehnt. Der Evaluationscode, der Fragensatz und die vier Beispieldokumente liegen lokal bereit. Zugangsdaten werden weder in diesem Protokoll noch in Evaluationsberichten gespeichert.

Das Go-live-Gate bleibt geschlossen, bis alle offenen Nachweise erbracht und in dieser Datei dokumentiert sind.

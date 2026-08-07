# Lokale Abnahme des KAHLE-Vinci Wissensportals

Stand: 7. August 2026

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
| Portal-Backend | `stack/kb-admin-api/tests` | 89 Tests bestanden |
| Stack, Verträge und Sicherheit | `stack/tests` | 242 Tests bestanden |
| Hybridindex und Synchronisierung | `stack/kb-sync/tests` | 10 Tests bestanden |
| Portal-UI | `npm test` in `admin-dashboard` | Build und 3 Rendering-, UX- und Sicherheitstests bestanden |
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
- Der Produktionsstart aktiviert das verschlüsselte Backup-Profil zwingend und verweigert den Start ohne Schlüssel oder absolutes zweites Backup-Ziel.
- Ablauf-Sammelmails werden werktäglich ab 10:30 Uhr Europe/Berlin erzeugt; Produktion verlangt eine vollständige Microsoft-Graph-Mailkonfiguration und einen KAHLE-Absender.

## Noch offene Go-live-Nachweise

| Nachweis | Status | Nächster Schritt |
|---|---|---|
| Höchstens 5 Prozent unbelegte Antworten ohne freigegebene Quelle | Negativfrage in der Offline-Evaluation bestanden, Laufzeitprüfung im Chat offen | Negativfragen mit dem lokalen Vinci-Chat ausführen |
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

## Offene Lücke: Begründung durch Mitarbeitende

PRD 10.1 erlaubt Mitarbeitenden, eine Herabstufung mit schriftlicher Begründung zu beantragen; PRD 13.2 nennt zusätzlich „Konvertierungsfehler kommentieren" und „Sonderfall an Admin melden" als Nutzeraktionen. Die Oberfläche bietet nach dem Upload nur „Als neues Dokument vorschlagen" und „Verwerfen" an.

Wer die automatische Einstufung für falsch hält, hat damit keinen Weg, das zu äußern. Der Endpunkt für den Herabstufungsantrag existiert bereits, verlangt aber eine `document_id`, die es zum Zeitpunkt des Uploads noch nicht gibt: Dort existiert nur ein Vorgang. Eine Anmerkung am Vorgang ist bisher nicht vorgesehen; `PortalCaseActionRequest` kennt kein Textfeld.

Offen und noch nicht umgesetzt.

## Benutzeroberfläche und UX

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

Einschränkung: Der gemessene Indexneuaufbau verwendet deterministische lokale Embeddings, nicht den IONOS-Endpunkt. Der reale Neuaufbau ist dadurch deutlich langsamer als die gemessenen 0,20 Sekunden. Der Embedding-Zugang funktioniert inzwischen; die Teilmessung mit echten IONOS-Embeddings über 6000 Chunks steht noch aus. Die übrigen Schritte sind davon unberührt, und selbst mit erheblichem Aufschlag bleibt der Abstand zum Vier-Stunden-Budget groß.

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

Der IONOS-Token ist seit dem 7. August 2026 gueltig; der fruehere HTTP 401 ist behoben. Code und Compose lesen ihn aus `IONOS_API_TOKEN` oder `IONOS_API_KEY`. Zugangsdaten werden weder in diesem Protokoll noch in Evaluationsberichten gespeichert.

Der TEI-Reranker ist seit dem 7. August 2026 verfügbar: Das Image `ghcr.io/huggingface/text-embeddings-inference:cpu-1.9` ist geladen, der Dienst läuft mit `Alibaba-NLP/gte-multilingual-reranker-base` in TEI 1.9.3, und der `/rerank`-Endpunkt ist mit einer deutschen Beispielanfrage verifiziert. Die Offline-Evaluation verwendet verpflichtend denselben Reranker-Endpunkt wie die Vinci-Laufzeit und bricht bei dessen Ausfall geschlossen ab.

Damit bestehen keine technischen Blocker mehr. Offen sind nur noch die organisatorischen UX-Praxistests und die Laufzeitpruefung der Negativfragen im Vinci-Chat.

Das Go-live-Gate bleibt geschlossen, bis alle offenen Nachweise erbracht und in dieser Datei dokumentiert sind.

## Nachweismatrix der 20 PRD-Abnahmeszenarien

| Nr. | Szenario | Nachweis | Stand |
|---:|---|---|---|
| 1 | DOCX hochladen, freigeben und Originalquelle öffnen | `test_docx_http_flow_activates_and_exposes_original_only_to_read_authorized_user` | automatisiert bestanden |
| 2 | Identische Datei blockieren | `test_exact_duplicate_is_blocked_and_only_publish_or_discard_is_allowed` und `test_global_analysis_sees_cross_kb_exact_duplicate` | automatisiert bestanden |
| 3 | Identisches Dokument in weiterer Knowledgebase veröffentlichen | `test_cross_kb_exact_duplicate_publishes_existing_canonical_document_only` | automatisiert bestanden |
| 4 | Neue Version atomar ersetzen und zurückrollen | `test_real_upload_is_bound_to_selected_version_candidate_before_replacement`, `test_new_version_atomically_supersedes_previous_active_version`, `test_failed_index_activation_restores_previous_active_version` | automatisiert bestanden |
| 5 | Ähnliche Dokumente verständlich vergleichen | `test_semantic_and_lexical_signals_are_combined_and_version_is_suggested` sowie Portal-Renderingtest | technisch automatisiert; Praxistest offen |
| 6 | Knowledgebase-übergreifenden Treffer direkt an Admin geben | `test_cross_kb_or_contradiction_requires_admin_and_cannot_be_manager_approved` und `test_admin_queue_only_receives_escalated_case` | automatisiert bestanden |
| 7 | Widersprüchliche Richtlinien nicht automatisch veröffentlichen | derselbe Lifecycle-Test sowie `test_admin_sets_authority_and_structured_relation` | automatisiert bestanden |
| 8 | Prompt-Injection-Dokument in Quarantäne halten | `test_any_prompt_injection_signal_bypasses_employee_and_goes_directly_to_admin` und `test_embedded_executable_content_is_rejected_before_conversion` | automatisiert bestanden |
| 9 | Fehlerhafte Tabellen-/Excel-Konvertierung zeilen- und spaltenbezogen anzeigen und korrigieren | `test_conversion_quality_blocks_mojibake_and_flags_broken_tables`, `test_confirmed_employee_comment_creates_new_checked_draft_version`, Portal-Renderingtest | automatisiert bestanden |
| 10 | Owner bestätigt Aktualität; Führungskraft verlängert | `test_renewal_requires_owner_confirmation_then_manager_and_admin` | nach späterer Produktentscheidung zusätzlich mit Adminfreigabe automatisiert bestanden |
| 11 | Mehrfach veröffentlichtes Dokument durch Führungskraft und Admin verlängern | derselbe serverseitig verpflichtende zweistufige Verlängerungsworkflow | automatisiert bestanden |
| 12 | Abgelaufenes Dokument automatisch aus RAG entfernen | `test_expired_versions_are_removed_from_all_active_publications`, `test_expired_or_nonactive_document_can_never_be_activated` | automatisiert bestanden |
| 13 | Ohne Leserecht weder Antwortinhalt noch Originalquelle erhalten | `test_internal_scope_is_authenticated_and_derived_from_persisted_read_rights`, `test_hybrid_request_repeats_acl_in_both_prefetches_and_rejects_leak`, DOCX-HTTP-Test | automatisiert bestanden |
| 14 | Falsche Vinci-Antwort als Korrekturfall erfassen | `test_permission_feedback_is_critical_and_captures_effective_rights`, Portal-Feedbacktest | automatisiert bestanden |
| 15 | Deaktivierter Owner erzeugt Neuzuordnungsaufgabe | `test_deactivated_owner_creates_task_and_new_owner_must_confirm` | automatisiert bestanden |
| 16 | Admin bereitet Knowledgebase vor; Portal-Admin entscheidet | `test_admin_prepares_knowledgebase_change_portal_admin_decides` | automatisiert bestanden |
| 17 | Portal-Admin legt Knowledgebase direkt an | derselbe Governance-Test und HTTP-Vertrag | automatisiert bestanden |
| 18 | Dokument innerhalb von 30 Tagen wiederherstellen | `test_employee_removal_request_requires_admin_and_restore_reactivates_valid_version` | automatisiert bestanden |
| 19 | Nach 90 Tagen physisch löschen und Audit behalten | `test_trash_reminders_and_physical_deletion_at_day_90` | automatisiert bestanden |
| 20 | Vollständiger Restore und Indexneuaufbau | `test_encrypted_restore_rebuilds_authoritative_hybrid_index` | automatisiert bestanden |

Die technischen Abläufe aller 20 Szenarien besitzen damit konkrete automatisierte Nachweise. Szenario 5 benötigt zusätzlich den im Go-live-Gate geforderten Mitarbeiter-Praxistest; die messbare Retrieval-Qualität wird separat durch den KAHLE-Fragensatz nachgewiesen.

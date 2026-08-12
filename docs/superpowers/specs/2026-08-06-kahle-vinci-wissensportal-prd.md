# PRD: KAHLE-Vinci Wissensportal und sichere RAG-Wissensverwaltung

**Status:** Abgestimmtes Produktkonzept
**Stand:** 06.08.2026
**Produkt:** KAHLE-Vinci
**Zielumgebung:** Lokale Entwicklung und Abnahme, anschließend kontrollierter Produktions-Rollout
**Primäre Zielgruppe:** Mitarbeitende, Führungskräfte, Admins und Portal-Admins der KAHLE Gruppe

## 1. Zusammenfassung

KAHLE-Vinci erhält ein gemeinsames Wissensportal, über das Mitarbeitende Dokumente einfach und sicher in freigegebene Wissensbereiche einbringen können. Das Portal übernimmt den vollständigen Lebenszyklus eines Dokuments: Upload, Sicherheitsprüfung, Konvertierung in RAG-optimiertes Markdown, globale Dubletten- und Konfliktprüfung, risikobasierte Freigabe, Veröffentlichung, Quellenverlinkung, Gültigkeitsüberwachung, Versionierung, Archivierung und Löschung.

Der eigentliche Hebel liegt nicht nur in einer komfortablen Upload-Oberfläche. Entscheidend ist, dass Vinci ausschließlich freigegebene, aktuelle und für den jeweiligen Nutzer berechtigte Quellen verwendet. Dokumente dürfen nicht unkontrolliert doppelt entstehen. Alte Versionen dürfen nicht parallel aktiv bleiben. Widersprüche müssen sichtbar werden, bevor sie zu falschen Antworten führen.

Parallel wird die heutige reine Dense-Vektorsuche vollständig durch eine berechtigungsgefilterte Hybrid-Retrieval-Architektur ersetzt. Sie kombiniert semantische Dense Search, deutsche BM25-/Sparse Search, Reciprocal Rank Fusion, spezialisiertes Reranking und strukturorientiertes Parent-Child-Chunking. Dadurch erhalten auch kleinere Sprachmodelle wenige, präzise und nachvollziehbare Kontextstellen statt eines unübersichtlichen Satzes ähnlicher Textfragmente.

Das Produkt wird zunächst lokal vollständig umgesetzt und ausgiebig getestet. Erst wenn alle definierten Sicherheits-, Qualitäts-, UX- und Wiederherstellungskriterien erfüllt sind, erfolgt der kontrollierte Rollout auf den Produktionsserver.

## 2. Ausgangslage

KAHLE-Vinci verfügt heute über mehrere dateibasierte Knowledgebases, die durch `kb-sync` in getrennte Qdrant-Collections indexiert werden. Das vorhandene Vector-Admin-Dashboard erlaubt bereits administrative Dateioperationen, Versionierung, semantische Suche und die Anzeige des Indexstatus.

Der heutige Retrieval-Weg besitzt bereits einige sinnvolle Schutzmechanismen:

- Dense Retrieval mit `BAAI/bge-m3`
- Suche über mehrere Qdrant-Collections
- Mindestscore für beantwortbare Fragen
- Begrenzung der Kontext-Chunks
- Bevorzugung des bestbewerteten Dokuments
- Nachladen benachbarter Chunks
- Sonderlogik für Dokumentkennungen und Aufzählungen

Für einen wachsenden unternehmensweiten Wissensbestand fehlen jedoch zentrale Bausteine:

- eine für normale Mitarbeitende geeignete Upload- und Freigabeoberfläche
- serverseitige Lese- und Uploadrechte pro Knowledgebase
- globaler Vergleich über alle Knowledgebases
- stabile, vom Dateinamen unabhängige Dokumentidentitäten
- ein kanonisches Dokumentmodell mit kontrollierter Mehrfachveröffentlichung
- automatische Dubletten-, Versions- und Widerspruchserkennung
- verbindliche Gültigkeit und automatische Deaktivierung abgelaufener Inhalte
- durchgängige Originalquellenlinks in Vinci-Antworten
- Prompt-Injection-, Malware- und Inhaltsprüfungen
- lexikalische Suche, Fusion und dediziertes Reranking
- konsistente Rollen, Eskalationen und Auditnachweise

## 3. Problem

Die manuelle Pflege der bestehenden Knowledgebases ist zu aufwendig und zu fehleranfällig. Mit wachsendem Bestand steigen insbesondere folgende Risiken:

1. Dasselbe Dokument wird mehrfach in einer oder mehreren Knowledgebases gespeichert.
2. Eine ältere Version bleibt aktiv, obwohl bereits eine neue Version vorliegt.
3. Zwei fachlich widersprüchliche Dokumente werden gleichzeitig von Vinci verwendet.
4. Dokumente bleiben nach Ablauf ihrer fachlichen Gültigkeit im RAG aktiv.
5. Mitarbeitende erhalten Informationen aus Wissensbereichen, für die sie keine Leseberechtigung besitzen.
6. Fehlerhafte Konvertierungen verändern Tabellen, Listen, Fußnoten oder die Bedeutung eines Dokuments.
7. Prompt-Injection-Inhalte beeinflussen Retrieval, Modell oder nachgelagerte Tools.
8. Das Antwortmodell erhält zu viele ähnliche oder unpräzise Chunks und formuliert daraus eine plausible, aber falsche Antwort.
9. Verantwortlichkeiten, Freigaben und Änderungen sind später nicht nachvollziehbar.

Diese Risiken können zu falschen internen Entscheidungen und damit zu finanziellen, rechtlichen oder reputativen Schäden führen.

## 4. Produktziel

Das Wissensportal soll die Pflege des KAHLE-Vinci-Wissens so einfach machen, dass ein normaler Mitarbeiter einen Upload ohne technische Vorkenntnisse durchführen kann. Gleichzeitig muss das System so streng arbeiten, dass kein ungeprüftes, abgelaufenes, unberechtigtes oder widersprüchliches Dokument aktiv von Vinci verwendet wird.

### 4.1 Hauptziele

- einfacher Upload mit Drag-and-drop
- klare, rollenabhängige UI ohne technische Fachbegriffe
- globale Prüfung jedes Uploads über den gesamten Wissensbestand
- risikobasierte Aktivierung: automatische Veröffentlichung sauberer Bereichsdokumente, Führungskraftprüfung für allgemeine oder fachlich auffällige Fälle und zusätzliche Adminprüfung nur für kritische Fälle
- automatische und rückrollbare Versionierung
- automatische Deaktivierung abgelaufener Dokumente
- verpflichtende Quellenangaben in jeder internen Wissensantwort
- serverseitig erzwungene Rechtefilter vor jedem Retrieval
- deutlich bessere Suchqualität durch Hybrid Retrieval und Reranking
- vollständige Auditierbarkeit kritischer Entscheidungen

### 4.2 Nicht-Ziele des MVPs

- automatische Übernahme von Führungskräften aus Microsoft Graph
- eigene mobile App
- GraphRAG oder ein unternehmensweiter Knowledge Graph
- autonome Freigabeentscheidungen durch ein LLM
- Upload von Archiven oder mehreren Dateien in einem Vorgang
- Erstellung der rollenspezifischen Schulungsinhalte
- Leistungs- oder Verhaltensbewertung von Mitarbeitenden

Die Schulung erfolgt später über rollenbezogene Videos in der KAHLE-Academy. Das Portal soll lediglich auf diese Inhalte verlinken können.

## 5. Produktprinzipien

1. **Fail closed:** Fehlt eine Pflichtprüfung oder schlägt sie fehl, wird kein neuer Inhalt aktiviert.
2. **Human-in-the-Loop:** Das LLM analysiert und empfiehlt. Es entscheidet niemals selbst über Freigabe, Ersatz, Löschung oder Vorrang.
3. **Eine Quelle, mehrere Veröffentlichungen:** Ein kanonisches Dokument kann mehreren Knowledgebases zugeordnet werden, wird aber nicht physisch dupliziert.
4. **Rechte vor Retrieval:** Nicht berechtigte Inhalte erreichen weder Retriever noch Antwortmodell.
5. **Quelle vor Antwort:** Ohne gültige, berechtigte Quelle gibt Vinci keine verbindliche interne Auskunft.
6. **Aktualität vor Verfügbarkeit:** Abgelaufene Dokumente werden automatisch deaktiviert.
7. **Einfach für Mitarbeitende, detailliert für Admins:** Technische Komplexität wird rollenabhängig ausgeblendet.
8. **Jede Änderung ist eine neue Version:** Automatische und manuelle Änderungen lösen die Prüfungen erneut aus.
9. **Original bleibt nachweisbar:** Freigegebene Antworten verlinken auf die berechtigungsgeprüfte Originaldatei.
10. **Lokale Kontrolle, freigegebene externe Inferenz:** Wissensverwaltung, Rechte und Auswahl bleiben unter KAHLE-Kontrolle. Alle drei Vertraulichkeitsstufen dürfen über die freigegebenen IONOS-Endpunkte verarbeitet werden.

## 6. Benutzerrollen

Das MVP besitzt vier Systemrollen. Dokument-Owner, Vertretungen und Knowledgebase-Rechte sind Zuordnungen und keine zusätzlichen globalen Rollen.

### 6.1 Mitarbeiter

Ein Mitarbeiter darf:

- Dokumente in freigegebene Knowledgebases hochladen
- den eigenen Microsoft/OpenWebUI-Account als Owner verwenden
- bei entsprechender Berechtigung einen anderen aktiven Nutzer als Owner vorschlagen
- eigene Vorgänge und Dokumente einsehen
- Systemvorschläge prüfen und eine gewünschte Aktion auswählen
- Konvertierungsfehler in Alltagssprache kommentieren
- automatische Markdown-Korrekturen anstoßen und bestätigen
- Gültigkeitsverlängerungen anstoßen
- strengere Vertraulichkeitsstufen setzen
- eine Herabstufung mit schriftlicher Begründung beantragen
- unfertige Uploads zurückziehen, als Entwurf behalten oder löschen
- für aktive Dokumente Deaktivierungs- oder Löschanträge stellen

### 6.2 Führungskraft

Eine Führungskraft besitzt zusätzlich folgende Rechte:

- Vorgänge der zugeordneten Mitarbeitenden prüfen
- vorgeschlagene Aktionen bestätigen, ablehnen oder ändern
- Original und RAG-Markdown vergleichen
- Vertretungsfälle bearbeiten
- Fälle aktiv an einen Admin eskalieren
- Gültigkeitsverlängerungen freigeben
- Herabstufungen der Vertraulichkeit beantragen

Eine Führungskraft darf keine erkannten Knowledgebase-übergreifenden Treffer oder fachlichen Widersprüche abschließend entscheiden.

### 6.3 Admin

Jeder Admin muss einem aktiven Portal-Admin als Führungskraft zugeordnet sein. Eigene Uploads eines Admins folgen damit demselben fachlichen Freigabeweg wie andere Uploads und werden nicht als eigene Adminaufgabe an ihn selbst zurückgespielt.

Ein Admin darf:

- Benutzer aus der synchronisierten OpenWebUI-Benutzerliste für das Portal aktivieren
- Mitarbeitende Führungskräften zuordnen
- Vertretungen verwalten
- Lese- und Uploadrechte pro Knowledgebase vergeben
- alle Freigabe-, Konflikt- und Eskalationsfälle bearbeiten
- Dokumente bearbeiten, sperren, deaktivieren, wiederherstellen und Löschaufträge bearbeiten
- Knowledgebase-Zuordnungen und Geltungsbereiche verwalten
- Vertraulichkeitsstufen mit schriftlicher Begründung unmittelbar ändern
- Auditprotokolle einsehen und exportieren
- neue Knowledgebases vorbereiten, umbenennen, archivieren oder entfernen

Folgende Admin-Aktionen benötigen die Bestätigung eines Portal-Admins:

- Knowledgebase anlegen
- Knowledgebase umbenennen
- Knowledgebase archivieren
- Knowledgebase endgültig entfernen

Ein Admin darf nicht:

- Admins oder Portal-Admins ernennen, entfernen oder deren Rechte ändern
- seine eigene Rolle erweitern
- Microsoft-/OIDC-, Sicherheits- oder Backup-Konfiguration verändern
- Auditprotokolle oder Mindestaufbewahrungsfristen verändern
- harte Sicherheitsprüfungen deaktivieren
- eine Ablehnung der zuständigen Führungskraft überstimmen

### 6.4 Portal-Admin

Ein Portal-Admin besitzt alle Rechte. Er darf insbesondere:

- Admins und Portal-Admins ernennen oder entfernen
- eigene Rollen und Rechte verwalten
- Knowledgebase-Änderungen selbstständig und ohne weitere Bestätigung ausführen
- eine Ablehnung der Führungskraft in einem begründeten Ausnahmefall überstimmen
- sicherheitsrelevante Systemeinstellungen verwalten
- Admin-Sonderfälle und Overrides durchführen

Portal-Admins benötigen keine Führungskraft. Sie dürfen auch eigene oder an sie eskalierte Vorgänge ohne zweite Freigabe abschließend entscheiden. Eine reine Freigabe benötigt keine Begründung. Ablehnungen, Weiterleitungen, das Überstimmen einer früheren Ablehnung und sonstige Overrides benötigen weiterhin eine selbst geschriebene Begründung; vorbelegte Standardbegründungen erfüllen diese Pflicht nicht. Es gilt kein Vier-Augen-Prinzip für Portal-Admins. Die einzige weitere technische Sicherung lautet: Es muss jederzeit mindestens ein aktiver Portal-Admin vorhanden sein.

## 7. Identität und Anmeldung

### 7.1 Benutzerquelle

- Benutzerkonten entstehen nicht im Wissensportal.
- Die Benutzerliste stammt aus OpenWebUI und damit aus dem Microsoft-Login.
- Intern wird die stabile OpenWebUI- beziehungsweise Microsoft-Benutzer-ID verwendet.
- Die Microsoft-E-Mail-Adresse wird als aktuelle Kontaktadresse und als `owner_email` im Dokument-Metadatensatz geführt.
- Eine E-Mail-Adresse darf nicht frei im Browser überschrieben werden.
- Nur Konten aus dem KAHLE-Microsoft-Mandanten sind zulässig.

### 7.2 Portal-Anmeldung

- Das bisherige gemeinsame Admin-Code-Verfahren entfällt.
- Das Wissensportal erhält eine eigene serverseitige Microsoft-Entra-/OIDC-Anmeldung.
- Die Portal-Sitzung gilt acht Stunden.
- Kritische Adminaktionen erfordern eine frische Microsoft-Step-up-Authentifizierung.
- Rollen und Identitäten werden ausschließlich serverseitig validiert.
- Der Browser darf keine vertrauenswürdigen Rollen- oder Benutzerkennungen frei mitsenden.

### 7.3 URL und Produktbezeichnung

Empfohlener Produktname: **Vinci Wissensportal**
Empfohlener Pfad: `https://vinci.kahle.de/wissen/`

Der bisherige Pfad `/admin/vector/` wird nach erfolgreicher Migration abgeschaltet oder auf den neuen Bereich weitergeleitet.

## 8. Rechte- und Verantwortungsmodell

### 8.1 Knowledgebase-Rechte

Pro Benutzer werden getrennt verwaltet:

- Leserecht pro Knowledgebase
- Uploadrecht pro Knowledgebase
- Führungskraft
- Vertretung
- Systemrolle

Uploadrecht bedeutet nicht automatisch Leserecht und umgekehrt.

### 8.2 Owner

- Standardmäßig wird der angemeldete Benutzer als Owner gesetzt.
- Die E-Mail stammt aus seinem OpenWebUI-/Microsoft-Konto.
- Andere Owner können nur aus aktiven Vinci-Benutzern gewählt werden.
- Die Auswahl eines anderen Owners erfordert eine gesonderte Berechtigung.
- Der vorgeschlagene Owner muss die Übernahme bestätigen.
- Deaktivierte Nutzer können keine neuen Dokumente übernehmen.

Wird ein Owner deaktiviert oder verlässt das Unternehmen:

- bleiben seine Dokumente bis zum Ablauf ihrer Gültigkeit aktiv
- erhalten Führungskraft und Admin sofort eine Neuzuordnungsaufgabe
- erfolgt keine automatische Eigentumsübertragung
- darf die Führungskraft erforderliche Verlängerungen anstoßen
- wird das Dokument spätestens zum Ablauf ohne neuen Owner deaktiviert
- bleibt der frühere Owner in der Historie erhalten

### 8.3 Führungskräfte und Vertretungen

- Führungskräfte werden im MVP manuell durch Admin oder Portal-Admin zugeordnet.
- Eine Vertretung wird zusammen mit der zeitlich begrenzten Abwesenheit der Führungskraft in einem gemeinsamen Vorgang erfasst; separate, dauerhaft sichtbare Eingabebereiche sind nicht erforderlich.
- Beim Entfernen der Abwesenheit wird auch die daran gekoppelte Vertretung beendet.
- Während der Abwesenheit gehen neue Fälle direkt an die Vertretung.
- Ohne Abwesenheit erfolgt nach zwei Arbeitstagen eine Erinnerung.
- Nach vier Arbeitstagen erhält die Vertretung den Fall zusätzlich.
- Nach sechs Arbeitstagen wird an einen Admin eskaliert.
- Zeitkritische Ablauffälle werden entsprechend früher eskaliert.
- Offene Fälle werden niemals automatisch genehmigt.
- Die Benutzer- und Rechteverwaltung zeigt eine kompakte Benutzerliste und die Daten des ausgewählten Benutzers direkt daneben. Zuordnung, Owner-Berechtigung und Knowledgebase-Rechte werden erst über einen sichtbaren Speichern-Button gemeinsam übernommen; der Speicherstatus ist eindeutig erkennbar.

## 9. Dokumentmodell

### 9.1 Kanonisches Dokument

Ein Dokument existiert als kanonischer Datensatz genau einmal und besitzt:

- unveränderliche `document_id`
- eine oder mehrere Versionen
- genau ein aktuelles Original
- genau ein aktuelles RAG-Markdown
- einen Owner
- eine Gültigkeit
- eine Vertraulichkeitsstufe
- eine Autoritätsstufe
- einen fachlichen Geltungsbereich
- eine oder mehrere Knowledgebase-Veröffentlichungen
- eine vollständige Audit- und Freigabehistorie

Eine `document_id` ist unabhängig von Dateiname, Speicherpfad und Knowledgebase.

### 9.2 Version

Jede Version besitzt mindestens:

- unveränderliche `version_id`
- Bezug zur `document_id`
- Bezug zur Vorgängerversion
- Originaldatei und kryptografischen Hash
- erzeugtes RAG-Markdown und Hash
- Erstellungs- und Freigabezeitpunkt
- Freigabebeteiligte
- Änderungsgrund
- Prüfstatus
- Indexstatus

Dateinamen dienen nur der Anzeige.

### 9.3 Knowledgebase-Veröffentlichung

Ein kanonisches Dokument kann mehreren fachlichen Knowledgebases zugeordnet sein.

- Original und RAG-Markdown werden nicht dupliziert.
- Jede Veröffentlichung verweist auf dieselbe `document_id` und `version_id`.
- Änderungen und Ablauf wirken auf alle Veröffentlichungen.
- Leserechte werden weiterhin pro Knowledgebase ausgewertet.
- Die Veröffentlichung in einer zusätzlichen Knowledgebase benötigt eine Adminentscheidung.

### 9.4 Workflowstatus

Mindestens folgende Status werden benötigt:

- `draft`
- `quarantine`
- `processing`
- `pending_owner_confirmation`
- `pending_employee_decision`
- `pending_manager_approval`
- `pending_admin_approval`
- `pending_portal_admin_approval`
- `active`
- `rejected`
- `expired`
- `superseded`
- `archived`
- `trash`
- `deleted`
- `error`

Vertraulichkeitsstufen und Workflowstatus sind getrennte Konzepte.

## 10. Vertraulichkeit und Autorität

### 10.1 Vertraulichkeitsstufen

Das Portal verwendet drei Stufen:

1. `intern`
2. `bereichsbeschränkt`
3. `vertraulich`

Das System schlägt anhand des Inhalts automatisch eine Stufe und eine verständliche Begründung vor. Es prüft insbesondere auf personenbezogene Daten, Kundendaten, Bankdaten, Zugangsdaten und sensible Unternehmensinformationen.

Alle drei Stufen dürfen über die freigegebenen IONOS-Modelle verarbeitet werden. Vor jeder Modellanfrage gelten weiterhin lokale Rechteprüfung, Datenminimierung, verschlüsselte Übertragung und technische Protokollierung.

Regeln für Änderungen:

- Mitarbeiter und Führungskräfte dürfen die Stufe selbstständig erhöhen.
- Eine Herabstufung können sie mit schriftlicher Begründung beantragen.
- Admin oder Portal-Admin entscheidet über den Antrag.
- Admins und Portal-Admins dürfen unmittelbar herabstufen, benötigen aber ebenfalls eine schriftliche Begründung.
- Eine zusätzliche Knowledgebase-Zuordnung darf die Vertraulichkeit nicht automatisch reduzieren.
- Jede Änderung löst eine erneute Rechte- und Indexprüfung aus.

### 10.2 Quellen- und Autoritätshierarchie

Jedes Dokument erhält einen Quellentyp und eine Autoritätsstufe. Ausgangsmodell:

1. gesetzliche oder regulatorische Vorgabe
2. Hersteller- oder Importeursvorgabe
3. Geschäftsführungsrichtlinie
4. Bereichsrichtlinie
5. Prozess- oder Arbeitsanweisung
6. Informations- oder Schulungsunterlage

Die Hierarchie ist eine Entscheidungshilfe, keine automatische Konfliktentscheidung. Erkannte Widersprüche durchlaufen immer Stufe 3: zuerst die Führungskraft und bei Zustimmung zusätzlich einen Admin. Der Admin hinterlegt bei der Entscheidung strukturierte Beziehungen wie:

- `supersedes`
- `overrides`
- `applies_only_if`
- `related_to`

## 11. Verbindliches RAG-Metadatenschema

Jeder Upload wird serverseitig in ein kontrolliertes Schema normalisiert. Vorhandenes Frontmatter darf keine sicherheits- oder workflowrelevanten Felder erzwingen.

Mindestens folgende Felder sind erforderlich:

```yaml
document_id: <stabile UUID>
version_id: <stabile UUID>
title: <Anzeigetitel>
original_filename: <Dateiname>
original_file_id: <stabile Datei-ID>
owner_user_id: <interne Benutzer-ID>
owner_email: <Microsoft-E-Mail>
status: <Workflowstatus>
confidentiality: <intern|bereichsbeschränkt|vertraulich>
authority_type: <Quellentyp>
authority_level: <Rang>
scope: <strukturierter Geltungsbereich>
knowledgebase_ids: [<stabile Knowledgebase-IDs>]
valid_from: <Datum>
valid_until: <Datum>
rag_index: <true|false>
source_url: <authentifizierter Originalquellenlink>
previous_version_id: <optionale Version-ID>
original_sha256: <Hash>
markdown_sha256: <Hash>
created_at: <Zeitpunkt>
approved_at: <optionaler Zeitpunkt>
```

Zusätzliche technische Prüffelder werden im Metadatenspeicher geführt und müssen nicht vollständig im sichtbaren Markdown stehen.

## 12. Unterstützte Dateien und Uploadgrenzen

### 12.1 Formate

Im MVP erlaubt:

- PDF
- DOCX
- XLSX
- PPTX
- TXT
- Markdown

Nicht erlaubt:

- passwortgeschützte oder verschlüsselte Dateien
- makrohaltige Dateien
- aktive Skripte oder ausführbare Inhalte
- ZIP- und andere Archivformate
- sonstige Containerformate

Dateitypen werden anhand des tatsächlichen Inhalts und nicht nur anhand der Dateiendung geprüft.

### 12.2 Grenzen

- maximal 50 MB pro Datei
- maximal 200 Seiten bei PDF- und Office-Dokumenten
- ein Dokument pro Freigabevorgang
- asynchrone Verarbeitung
- administrativ konfigurierbare Werte innerhalb harter technischer Sicherheitsgrenzen
- größere Dateien nur als begründeter Admin-Sonderfall

### 12.3 Fortschrittsanzeige

Normale Nutzer sehen verständliche Stufen:

1. Datei wird sicher gespeichert
2. Sicherheitsprüfung läuft
3. Inhalt wird aufbereitet
4. Ähnliche Dokumente werden gesucht
5. Ergebnis kann geprüft werden

Der Browser muss für die Verarbeitung nicht geöffnet bleiben.

## 13. Upload- und Freigabeprozess

### 13.1 Standardablauf

1. Nutzer öffnet das Wissensportal mit Microsoft-Anmeldung.
2. Nutzer wählt eine Knowledgebase, für die er Uploadrecht besitzt.
3. Nutzer bestätigt oder wählt den Owner.
4. Nutzer wählt eine Gültigkeit von maximal 60 Arbeitstagen.
5. Nutzer lädt genau eine Datei per Drag-and-drop oder Dateiauswahl hoch.
6. Die Datei landet in isolierter Quarantäne.
7. Sicherheits- und Inhaltsprüfungen laufen.
8. Der Document Worker erzeugt RAG-optimiertes Markdown.
9. Das System vergleicht global über alle Knowledgebases.
10. Der Nutzer sieht Ergebnis, mögliche Treffer und eine empfohlene Aktion.
11. Der Nutzer wählt seine gewünschte Aktion.
12. Das System ordnet den Vorgang automatisch einer der drei Freigabestufen aus Abschnitt 13.3 zu.
13. Ein sauberer Upload für genau eine Bereichs-Knowledgebase wird ohne menschliche Freigabe atomar veröffentlicht und indexiert.
14. Ein allgemeiner oder fachlich auffälliger Vorgang wird der Führungskraft vorgelegt. Sie bestätigt, lehnt ab, ändert die Aktion oder eskaliert.
15. Ein kritischer Vorgang wird zuerst von der Führungskraft und anschließend zusätzlich von einem Admin oder Portal-Admin geprüft.
16. Der Nutzer wird über Aktivierung, Ablehnung oder weiteren Prüfbedarf informiert.

### 13.2 Mögliche Nutzeraktionen

Je nach Prüfergebnis:

- als neues Dokument vorschlagen
- als neue Version eines bestehenden Dokuments vorschlagen
- vorhandenes Dokument zusätzlich in der Ziel-Knowledgebase veröffentlichen
- bestehenden Upload verwerfen
- Fehler im erzeugten Markdown kommentieren
- Sonderfall an Admin melden

„Beide hochladen“ ist keine allgemeine Standardaktion. Parallele Dokumente sind nur erlaubt, wenn ihr Geltungsbereich eindeutig getrennt ist, zum Beispiel nach Standort, Marke, Abteilung, Zielgruppe, Prozess oder Zeitraum.

### 13.3 Risikobasierte Freigabestufen

Das System wählt anhand des Ziel-Wissensbereichs und der Prüfergebnisse automatisch eine von drei Stufen. Die Einstufung, die auslösenden Befunde und jede Entscheidung werden protokolliert.

#### Stufe 1: automatische Aktivierung

Die automatische Aktivierung besitzt einen zentralen, auditierten Schalter. In der lokalen Testumgebung ist sie standardmäßig aktiviert. In Produktion bleibt sie bis zur fachlichen Abnahme standardmäßig deaktiviert. Nur ein Portal-Admin darf den Schalter mit schriftlicher Begründung ändern; Admins sehen den aktuellen Zustand nur lesend.

Ein Dokument darf direkt atomar veröffentlicht und indexiert werden, wenn alle folgenden Bedingungen erfüllt sind:

- Ziel ist genau eine fachlich oder organisatorisch abgegrenzte Bereichs-Knowledgebase und nicht `kahleallgemein` („KAHLE-Allgemein“).
- Es gibt keine Dublette, keinen Versionskandidaten, keine unklare Dokumentenpriorität und keinen fachlichen Widerspruch.
- Es gibt keinen Sicherheits-, Sperrwort-, Sensitivitäts- oder Prompt-Injection-Befund.
- Konvertierung und Metadatenprüfung sind vollständig und sicher bestanden.
- Owner, Gültigkeit, Zielbereich und Zugriffsrechte sind gültig.

#### Stufe 2: Freigabe durch die Führungskraft

Eine abschließende Freigabe durch die Führungskraft des Owners ist erforderlich, wenn mindestens einer dieser Fälle vorliegt:

- Das Dokument soll in `kahleallgemein` („KAHLE-Allgemein“) veröffentlicht werden, auch wenn keine Auffälligkeit erkannt wurde.
- Es wurde eine Dublette oder hohe inhaltliche Übereinstimmung erkannt.
- Es wurde eine ältere oder neuere Version desselben Dokuments erkannt.
- Die Autorität, Dokumentenpriorität oder Ersetzungsentscheidung ist unklar, ohne dass bereits ein fachlicher Widerspruch vorliegt.

Eine exakte Dublette wird nicht erneut als separates Dokument veröffentlicht. Die Führungskraft kann sie verwerfen, einer bestehenden Quelle zuordnen oder eine nachvollziehbare Versionsaktion bestätigen.

#### Stufe 3: Freigabe durch Führungskraft und Admin

Zuerst entscheidet die Führungskraft des Owners. Bei Zustimmung folgt zusätzlich die Freigabe durch Admin oder Portal-Admin. Diese Stufe gilt insbesondere für:

- mögliche fachliche Widersprüche
- kritische Sicherheits-, Sensitivitäts-, Sperrwort- oder Prompt-Injection-Befunde, soweit die Datei technisch sicher untersucht werden konnte
- Veröffentlichung eines kanonischen Dokuments in mehreren Wissensbereichen
- nicht ausreichend sichere Konvertierungsqualität
- sonstige kritische oder vom Regelwerk nicht eindeutig entscheidbare Fälle

Führungskraft und Admin sehen Original, RAG-Markdown, Vergleichsdokumente, Fundstellen, Systembegründung und mögliche Aktionen. Lehnt die Führungskraft ab, endet der Vorgang ohne Adminfreigabe. Eine Eskalation legt ihn direkt dem Admin vor, ersetzt aber nicht die dokumentierte fachliche Bewertung.

Eine Freigabe benötigt keine zusätzliche Begründung. Ablehnung und Weiterleitung benötigen eine kurze schriftliche Begründung. Nach dem Absenden sperrt die Oberfläche den gesamten Aufgabenbereich gegen Mehrfachklicks und parallele Freigaben. Ein zentraler Ladehinweis nennt das gerade verarbeitete Dokument und bleibt bis zum erfolgreichen Abschluss oder einer verständlichen Fehlermeldung sichtbar.

Freigabeentscheidungen werden zusätzlich serverseitig persistent und global serialisiert. Treffen Entscheidungen verschiedener Nutzer gleichzeitig oder kurz nacheinander ein, wird genau ein Vorgang verarbeitet; alle weiteren erhalten eine Warteschlangenposition und werden in Eingangsreihenfolge ausgeführt. Ein Fall kann nicht mehrfach aktiv eingereiht werden. Aktivierung, Metadatenmaterialisierung und atomarer Hybridindexwechsel gehören gemeinsam zu diesem serialisierten Abschnitt. Zeitlich begrenzte Worker-Leases verhindern, dass ein abgestürzter Verarbeitungsschritt die Warteschlange dauerhaft blockiert.

Die UI bestätigt eine dauerhaft gespeicherte Entscheidung unmittelbar und zeigt den Vorgang anschließend unter „Veröffentlichung läuft“. Sie blockiert den Nutzer nicht bis zum Ende der Indexierung. Der Abschluss oder Fehler wird als Mitteilung zugestellt.

Normale Aktivierungen, Ersetzungen, Rechte-/Metadatenänderungen und Deaktivierungen aktualisieren den Hybridindex dokumentweise. Dabei werden nur die Chunks des betroffenen Dokuments neu eingebettet. Neue Punkte bleiben zunächst unveröffentlicht; alte Punkte werden fehlersicher ausgeblendet und die neue Version anschließend sichtbar geschaltet. Ein kompletter Indexneuaufbau ist auf initiale Migration, Restore sowie Änderungen an Indexschema, Embeddingmodell oder Chunking beschränkt.

#### Nicht übersteuerbare technische Blockade

Malware, ausführbare Schadbestandteile, nicht sicher entschlüsselbare Dateien oder technisch nicht untersuchbare Inhalte bleiben in Quarantäne. Sie können weder durch Führungskraft noch Admin veröffentlicht werden. Nach Bereinigung ist ein neuer Upload erforderlich.

## 14. Sicherheits- und Inhaltsprüfungen

Vor jeder fachlichen Verarbeitung laufen mindestens:

1. Größen- und Typprüfung
2. Prüfung auf Verschlüsselung und Makros
3. Malware- und Virenprüfung
4. Prüfung auf eingebettete ausführbare Inhalte
5. Prompt-Injection-Prüfung
6. Extraktions- und Konvertierungsprüfung
7. PII- und Sensitivitätsanalyse
8. Hash- und Dublettenprüfung
9. Versions- und Ähnlichkeitsprüfung
10. Widerspruchsanalyse
11. administrativ gepflegte Sperrwortprüfung

Dokumentinhalt gilt immer als `untrusted content` und niemals als Systemanweisung. Verdächtige Anweisungen, versteckte Texte oder Tool-Manipulationen führen zu Quarantäne und Adminprüfung.

Harte Dateisicherheits- und Malwareprüfungen dürfen auch durch einen Portal-Admin nicht übersprungen werden.

### 14.1 Administrierbare Sperrwörter

Admins und Portal-Admins können Begriffe oder feste Wortgruppen hinterlegen, die in Vinci nicht ungeprüft als Wissen veröffentlicht werden dürfen. Die Prüfung läuft serverseitig auf dem vollständig aufbereiteten Markdown und erneut bei jeder Korrekturversion. Sie berücksichtigt Groß- und Kleinschreibung nicht; kurze Begriffe werden als vollständige Wörter behandelt.

Ein Treffer löscht oder veröffentlicht das Dokument nicht. Er stoppt den normalen Ablauf und löst Stufe 3 aus: Zuerst prüft die Führungskraft, bei Zustimmung anschließend ein Admin oder Portal-Admin. Alle Beteiligten sehen die gefundenen Begriffe sowie Original und RAG-Markdown. Änderungen der Sperrwortliste werden auditiert. Die initialen Regeln sind `TPI` und `Reparaturleitfaden`.

## 15. Dubletten-, Versions- und Konfliktlogik

### 15.1 Prüfverfahren

Die Prüfung kombiniert:

- binären Datei-Hash
- normalisierten Text-Hash
- stabile Dokument-ID und Metadaten
- lexikalische Ähnlichkeit
- semantische Ähnlichkeit
- strukturelle Merkmale
- LLM-basierte Zusammenfassung von Unterschieden und Widersprüchen

Das LLM liefert nur Entscheidungshilfe.

### 15.2 Risikostufen

- `identisch`: Upload wird blockiert
- `sehr hohe Ähnlichkeit`: direkter Vergleich und Freigabefall
- `mittlere Ähnlichkeit`: Treffer und relevante Passagen werden angezeigt
- `geringe Ähnlichkeit`: nur im Prüfprotokoll
- `Widerspruch erkannt`: immer Stufe 3 mit Führungskraft und anschließender Adminfreigabe

Die konkreten Grenzwerte werden mit echten KAHLE-Dokumenten kalibriert und administrativ konfigurierbar gemacht. Änderungen dürfen keine Dokumente rückwirkend ungeprüft aktivieren.

### 15.3 Exakte Dubletten

Exakte Dubletten werden technisch blockiert. Die UI zeigt vorhandenes Dokument, Knowledgebase, Owner, Gültigkeit und Status.

Liegt das identische Dokument in einer anderen Knowledgebase, kann der Nutzer statt eines erneuten Uploads beantragen:

> Vorhandenes Dokument zusätzlich in der gewünschten Knowledgebase veröffentlichen.

Dieser Vorgang durchläuft Stufe 3 mit Führungskraft und anschließender Adminfreigabe. Die Originaldatei wird nicht dupliziert.

### 15.4 Ersatz einer Version

Der Austausch erfolgt atomar:

1. Neue Version wird vollständig konvertiert, geprüft und freigegeben.
2. Neue Version wird erfolgreich indexiert.
3. Erst dann wird die vorherige Version aus dem aktiven RAG entfernt.
4. Die alte Version erhält `superseded` und bleibt im Versionsarchiv.

Schlägt die neue Indexierung fehl, bleibt die bisherige gültige Version aktiv. Admins können auf eine frühere Version zurückrollen.

### 15.5 Bearbeitung und Korrekturen

- Mitarbeiter kommentieren Konvertierungsfehler in Alltagssprache.
- Nach ausdrücklicher Freigabe überarbeitet das System das Markdown.
- Admins erhalten eine direkte Bearbeitungsansicht.
- Jede Änderung erzeugt eine neue Entwurfsversion.
- Alle bisherigen Prüfergebnisse und Freigaben werden zurückgesetzt.
- Sämtliche Sicherheits-, Dubletten- und Konfliktprüfungen laufen erneut.
- Admin-Overrides benötigen eine Begründung und bleiben im Audit sichtbar.

## 16. RAG-Markdown und Document Worker

### 16.1 Qualitätsanforderungen

Die Freigabeansicht unterstützt den Vergleich von Original und Markdown. Geprüft werden insbesondere:

- Überschriftenstruktur
- Absätze und Listen
- Tabellen
- Fußnoten und Seitenbezüge
- OCR-Qualität
- nicht extrahierbare Bilder, Diagramme oder Anhänge
- Reihenfolge und Vollständigkeit

Normale Nutzer sehen eine einfache Bewertung:

- Alles in Ordnung
- Bitte prüfen
- Upload kann so nicht verarbeitet werden

Technische Details sind nur für Admins sichtbar.

### 16.2 Erkenntnisse aus den Testdateien

Die bereitgestellten Document-Worker-Ausgaben zeigen folgende Anforderungen:

- bestehendes Frontmatter ist zu normalisieren
- leere Owner-Felder dürfen nicht bestehen bleiben
- Dateinamen dürfen nicht als stabile Dokument-ID dienen
- unzulässig lange Gültigkeiten müssen korrigiert werden
- PDF-Seitenartefakte müssen strukturiert behandelt werden
- sehr lange Excel-Tabellenzeilen dürfen nicht durch normales Text-Chunking zerstört werden
- Versionen aus Titel und Inhalt müssen erkannt und als Metadaten übernommen werden

### 16.3 Tabellen und Excel

Für tabellarische Daten gilt:

- Tabellenkopf wird als Schema erkannt.
- Jede fachliche Zeile bleibt ein zusammengehöriger Datensatz.
- Sehr lange Zellen dürfen strukturiert geteilt werden.
- Jeder Teil behält Primärbezeichner und Spaltennamen.
- Ein Parent-Objekt repräsentiert den vollständigen Datensatz.
- Die Originaltabelle bleibt als Quelle verlinkt.

## 17. Gültigkeit, Erinnerungen und Verlängerung

### 17.1 Berechnung

- maximale Gültigkeit: 60 Arbeitstage
- Arbeitstage: Montag bis Freitag abzüglich gesetzlicher Feiertage in Niedersachsen
- Uploadtag zählt nicht
- Gültigkeit beginnt mit der finalen Freigabe
- Nutzer wählen Arbeitstage oder ein geprüftes Datum
- Wochenenden und Feiertage gelten auch für Erinnerungen

### 17.2 Erinnerungsstufen

- 15 Arbeitstage vor Ablauf: Owner
- 10 Arbeitstage vor Ablauf: Owner
- 5 Arbeitstage vor Ablauf: zusätzlich Führungskraft
- 1 Arbeitstag vor Ablauf: zusätzlich Admin

Die E-Mail-Adresse stammt aus dem Microsoft/OpenWebUI-Konto.

### 17.3 Sammelmail

- Versand werktäglich um 10:30 Uhr, Zeitzone `Europe/Berlin`
- pro Empfänger genau eine Ablauf-Sammelmail pro Tag
- Gruppierung nach 15, 10, 5 und 1 Arbeitstag
- Anzeige von Titel, Knowledgebase, Ablaufstufe und sicherem Vorgangslink
- keine Dokumentinhalte oder Anhänge in der E-Mail
- ohne relevante Vorgänge keine E-Mail

### 17.4 Verlängerung

Der Owner aktiviert eine Checkbox mit folgendem Sinngehalt:

> Ich habe den Inhalt geprüft und bestätige, dass er weiterhin fachlich richtig und aktuell ist.

Danach bestätigt die Führungskraft. Bei einem Dokument mit mehreren Knowledgebase-Zuordnungen folgt zusätzlich die Freigabe durch Admin oder Portal-Admin.

Offene Wissensfehler, Widersprüche oder Sicherheitsfälle blockieren die Verlängerung.

Ohne rechtzeitige Freigabe wird das Dokument automatisch aus dem aktiven RAG entfernt, erhält `expired` und bleibt revisionssicher archiviert.

## 18. Quellenverlinkung in Vinci

### 18.1 Originalquelle

Originaldatei und RAG-Markdown teilen dieselbe `document_id`. Jeder Qdrant-Punkt trägt die Quellenmetadaten der konkreten Version.

Vinci zeigt bei internen Wissensantworten:

- Dokumenttitel
- Knowledgebase
- Versionsstand und Gültigkeit
- klickbaren Link zum Original
- bei Bedarf die verwendete Passage

### 18.2 Sicherer Dateizugriff

- Quellenlinks verwenden stabile Datei- oder Dokument-IDs und keine Dateipfade.
- Der Link führt über einen authentifizierten Read-only-Endpunkt.
- Bei jedem Öffnen werden Sitzung, Benutzer und Leserecht geprüft.
- Unterstützte Formate öffnen sich möglichst als Vorschau in einem neuen Tab.
- Andernfalls erfolgt ein sicherer Download.
- Alte Versionen sind nur für berechtigte Admin- und Auditansichten verfügbar.

### 18.3 Antwortregel

Jede konkrete interne Aussage benötigt eine gültige, freigegebene und für den Nutzer sichtbare Quelle.

Ohne belastbare Quelle antwortet Vinci sinngemäß:

> Dazu habe ich keine verlässliche freigegebene Information.

Widersprüchliche Quellen werden offengelegt und nicht stillschweigend aufgelöst.

## 19. Zielarchitektur Retrieval

### 19.1 Grundmodell

Empfohlen wird ein gemeinsamer logischer Qdrant-Suchindex mit stabilen Dokument- und Knowledgebase-Metadaten. Die sichtbaren Knowledgebases bleiben fachliche und rechtliche Wissensbereiche, müssen aber nicht jeweils eine physisch getrennte Vektordatenbank sein.

Vorteile:

- ein kanonisches Dokument kann mehreren Knowledgebases zugeordnet werden
- globale Dubletten- und Konfliktsuche wird einfacher
- Berechtigungen werden über indexierte Payload-Felder erzwungen
- Dense-, Sparse- und Reranking-Repräsentationen können konsistent gepflegt werden
- IDF- und Suchsignale werden nicht unnötig über viele kleine Collections fragmentiert

### 19.2 Retrieval-Pipeline

1. Benutzer und Leserechte serverseitig auflösen.
2. Query normalisieren und bei Bedarf aus dem Gesprächskontext präzisieren.
3. Harte Filter anwenden: aktive Version, Gültigkeit, Knowledgebase-Rechte, Geltungsbereich.
4. Dense Retrieval für semantische Ähnlichkeit ausführen.
5. Deutsche BM25-/Sparse Search für exakte Begriffe, Kennungen, Zahlen und Namen ausführen.
6. Ergebnisse per Reciprocal Rank Fusion zusammenführen.
7. Nennt die Frage ein konkretes Dokument eindeutig über Dateiname, Kennung oder mindestens zwei charakteristische Titelbegriffe, werden vorrangig unterschiedliche Kapitel dieses Dokuments abgerufen. Dies gilt auch, wenn der Tool-Query nur aus dem eindeutigen Dokumenttitel besteht. Verwandte Dokumente dürfen die angefragte Quelle nicht verdrängen.
8. Kandidaten nach ihrem Parent-Abschnitt deduplizieren. Technisches YAML-Frontmatter wird nie als Wissensinhalt indexiert oder an das Antwortmodell übergeben.
9. Etwa 30 bis 50 Kandidaten mit einem spezialisierten Reranker bewerten.
10. Bei allgemeinen Fragen werden zunächst höchstens zwei Abschnitte je Dokument ausgewählt. Freie Ergebnisplätze werden anschließend nach Relevanz aufgefüllt. So bleiben Dokument- und Kapitelvielfalt erhalten, ohne kleine Wissensbestände künstlich zu beschneiden. Bei normativen Fragen erhalten höherrangige Quellen innerhalb eines engen Relevanzkorridors Vorrang. Sind mindestens drei passende Quellen der Stufen 1 bis 5 vorhanden, werden reine Informations- und Schulungsunterlagen der Stufe 6 nicht zusätzlich aufgenommen. Nahezu identische Abschnitte werden dokumentübergreifend dedupliziert; als Konflikt markierte Quellen bleiben immer sichtbar.
11. Etwa 5 bis 8 präzise Quellenblöcke auswählen. Bei einer eindeutig auf ein Dokument bezogenen Gesamtfrage werden alle nummerierten Hauptkapitel dieses Dokuments in Dokumentreihenfolge geladen. Sämtliche Parent-Abschnitte und Unterkapitel eines Hauptkapitels werden zu einem zitierbaren Quellenblock zusammengeführt, sofern das vollständige Dokument in das Kontextbudget passt; andernfalls greift die normale relevanzbasierte Auswahl.
12. Benötigte Parent- und Nachbarchunks laden.
13. Quellen, Gültigkeit, Autorität und Konflikthinweise strukturiert an das Antwortmodell übergeben.

Das Antwortmodell soll nicht die schwierige Retrieval-Auswahl übernehmen. Es formuliert auf Basis eines bereits präzise begrenzten Kontextes.

### 19.3 Parent-Child-Chunking

- Chunking folgt Überschriften, Absätzen, Listen und Tabellen.
- Kleine Abschnitte werden sinnvoll zusammengeführt.
- Große Abschnitte werden an Absatzgrenzen geteilt.
- Tabellen bleiben als fachliche Einheit erhalten.
- Kleine Child-Chunks dienen der Suche.
- Parent-Abschnitte und Nachbarchunks liefern den zusammenhängenden Antwortkontext.
- Jeder Chunk enthält Dokument-ID, Version, Überschriftenpfad, Geltungsbereich, Autorität, Knowledgebase-Zuordnungen und Quellen-ID.
- Größe und Überlappung werden anhand der KAHLE-Evaluation kalibriert.

### 19.4 Keine Agenten- oder GraphRAG-Pflicht im MVP

GraphRAG, autonome Suchschleifen und Knowledge Graphs werden erst geprüft, wenn die Evaluation zeigt, dass Hybrid Retrieval plus Reranking konkrete relevante Fragestellungen nicht zuverlässig lösen kann.

## 20. Rechteprüfung im Retrieval

Die Rechteprüfung ist eine harte Sicherheitsgrenze.

- Die Backend-API bestimmt die erlaubten Knowledgebase-IDs aus der authentifizierten Benutzer-ID.
- Qdrant erhält diese IDs als Pflichtfilter.
- Nur aktive, gültige und veröffentlichte Dokumentversionen sind durchsuchbar.
- Eine Nachfilterung ausschließlich im Browser oder Antwortmodell ist unzulässig.
- Quellenlink und Retrieval verwenden dieselbe Berechtigungslogik.
- Tests müssen nachweisen, dass keine Query, kein Reranking und kein Quellenabruf fremde Inhalte zurückliefert.
- Ein technischer Rollback darf niemals auf einen Retriever ohne Rechte- und Gültigkeitsfilter zurückfallen.

## 21. Fehler- und Incident-Verhalten

### 21.1 Ausfall einer Pflichtprüfung

- Dokument bleibt in Quarantäne oder Warteschlange.
- Aktivierung ist blockiert.
- Verarbeitung wird automatisch erneut versucht.
- Nutzer sehen eine verständliche Meldung.
- Bereits aktive, noch gültige Dokumente bleiben bei einer kurzfristigen Störung aktiv.
- Abgelaufene Dokumente werden auch bei einer Störung deaktiviert.

### 21.2 Automatische Adminmeldung

Bei einem echten Systemfehler:

- wird sofort ein Admin-Vorgang eröffnet
- wird sofort eine E-Mail versendet
- erhält der Fehler eine eindeutige Fehler-ID
- werden Schritt, Zeitpunkt und technische Diagnose ohne Dokumentinhalt gespeichert
- kann der Nutzer über „Problem an Admin melden“ zusätzliche Informationen ergänzen
- wird kein doppelter Incident erzeugt

### 21.3 Wissensfehler in Vinci

Unter jeder RAG-Antwort steht „Wissensfehler melden“ mit folgenden Gründen:

- Information ist falsch
- Information ist veraltet
- Quellen widersprechen sich
- Quelle passt nicht zur Frage
- Ich durfte diese Information vermutlich nicht sehen
- Sonstiges

Automatisch erfasst werden Frage, Antwort, Quellen, verwendete Passagen, Benutzerrechte, Modell-, Prompt- und Retrieval-Version, Zeitpunkt und Request-ID.

- möglicher Berechtigungsverstoß: sofort kritischer Admin-Fall
- fachlicher Fehler: Owner und Führungskraft
- Admin kann eine Quelle sofort aus dem RAG nehmen, ohne sie zu löschen
- Korrektur durchläuft Versionierung, Prüfung und Freigabe erneut

## 22. Benachrichtigungen und Aufgaben

Das Portal ist die führende Aufgabenquelle. E-Mail ergänzt die Portalaufgabe.

- Neue normale Freigabeaufgabe: eine direkte E-Mail
- weitere offene Standardaufgaben: tägliche Sammelmail
- kritische Sicherheits-, Rechte- und Systemfehler: sofortige Einzelmeldung
- Ablaufwarnungen: tägliche Sammelmail um 10:30 Uhr
- E-Mails enthalten keine Dokumentinhalte oder Anhänge
- jeder Link führt direkt zum authentifizierten Vorgang
- normale Benachrichtigungen sind konfigurierbar
- kritische Meldungen können nicht deaktiviert werden
- identische technische Fehler werden zu einem Incident zusammengefasst
- Nach automatischer Aktivierung erhält der Uploader sofort eine Portal- und E-Mail-Benachrichtigung, dass das Dokument für berechtigte Vinci-Nutzer abrufbar ist.
- Nach jeder Entscheidung der Führungskraft erhält der Uploader den neuen Status, die verständliche Entscheidung und die Begründung. Bei einer Weiterleitung wird klar angezeigt, dass noch keine Veröffentlichung erfolgt ist.
- Nach jeder abschließenden Adminentscheidung erhalten sowohl die zuständige Führungskraft als auch der Uploader den neuen Status, die verständliche Entscheidung und die Begründung.
- Die Statusinformation unterscheidet eindeutig zwischen „veröffentlicht und abrufbar“, „abgelehnt“, „zur Korrektur zurückgegeben“, „weitere Prüfung erforderlich“ und „verworfen“.
- E-Mails nennen Dokumenttitel, Status und sicheren Vorgangslink, enthalten aber keine vertraulichen Dokumentinhalte, Fundstellen oder Anhänge.
- Wird ein Dokument aus dem aktiven Bestand in den Papierkorb verschoben, erhalten alle aktiven Nutzer, die zuvor über mindestens einen seiner Wissensbereiche Leserecht hatten, sofort eine Portal- und E-Mail-Mitteilung. Die Empfängerliste wird vor dem Rechteentzug ermittelt. Die Mitteilung nennt Titel, Status und Begründung, aber keine Dokumentinhalte.
- Wird ein vollständiger Wissensbereich archiviert oder endgültig entfernt, erhalten alle aktiven Nutzer mit bisherigem Leserecht sowie Admins und Portal-Admins eine Portal- und E-Mail-Mitteilung. Die Mitteilung nennt den Wissensbereich, die Aktion und die Begründung.

## 23. Rückzug, Deaktivierung und Löschung

### 23.1 Rückzug

- Nicht veröffentlichte Uploads können durch den Mitarbeiter zurückgezogen werden.
- Auswahl zwischen „Später weiterbearbeiten“ und „Entwurf löschen“.
- Offene Sicherheitsfälle bleiben bestehen.
- Aktive Dokumente können nicht durch Mitarbeiter direkt entfernt werden.

### 23.2 Löschrechte

- Mitarbeiter und Führungskräfte stellen Deaktivierungs- oder Löschanträge.
- Admins dürfen Dokumente aus dem aktiven Bestand entfernen.
- Endgültige Löschung erfolgt gemäß Papierkorbmodell.
- Aufbewahrungspflichten, Legal Holds und offene Sicherheitsfälle setzen die Löschung aus.

### 23.3 Papierkorbmodell

1. Genehmigte Entfernung löscht das Dokument sofort aus allen aktiven RAG-Indizes.
   Gleichzeitig werden alle Nutzer mit bisherigem Lesezugriff über die fehlende Abrufbarkeit informiert.
2. Das Dokument bleibt 30 Tage wiederherstellbar im Papierkorb.
3. Während dieser 30 Tage zeigt das Portal ausschließlich die Wiederherstellung an; eine physische Löschung ist auch für Portal-Admins gesperrt.
4. Ab Tag 30 wird die endgültige Löschung für Admins und Portal-Admins freigeschaltet. Gleichzeitig erhalten die Admins einen Löschauftrag im Portal und per E-Mail.
5. Solange nicht gelöscht wurde, folgt alle 10 Tage eine Erinnerung.
6. Drei Tage vor Tag 90 erhält der Admin eine letzte Warnung.
7. Spätestens nach 90 Tagen erfolgt die automatische physische Löschung.

Eine Aussetzung benötigt Grund und erneutes Prüfdatum.

### 23.4 Audit nach endgültiger Löschung

Gelöscht werden Original, RAG-Markdown und Dokumentinhalt. Minimiert erhalten bleiben:

- `document_id`
- zulässiger neutralisierter Titel oder Dateiname
- kryptografischer Hash
- frühere Knowledgebase-Zuordnungen
- Upload-, Freigabe-, Deaktivierungs- und Löschzeitpunkte
- beteiligte Benutzer-IDs und Rollen
- Entscheidungs- und Löschgrund
- Hinweis auf ein Legal Hold

## 24. Audit und Aufbewahrung

### 24.1 Aufbewahrungsfristen

- technische Betriebslogs: 6 Monate
- Sicherheits- und Fehlerprotokolle: 12 Monate
- Freigaben, Ablehnungen, Rechteänderungen, Versionierungen, Eskalationen und Overrides: 24 Monate
- minimierte Löschmetadaten: 24 Monate nach endgültiger Löschung

Admins dürfen Mindestfristen nicht unterschreiten. Normale Logs enthalten keine vollständigen Dokumentinhalte.

### 24.2 Auditinhalt

Mindestens protokolliert werden:

- Anmeldung und Step-up-Authentifizierung
- Upload und Owner-Zuordnung
- alle Prüfresultate und Versionen
- Mitarbeiterempfehlung
- Freigabe, Ablehnung und Eskalation
- Rollen- und Rechteänderungen
- Klassifizierungsänderungen
- Admin- und Portal-Admin-Overrides
- Indexaktivierung und Deaktivierung
- Wiederherstellung und Löschung
- Änderungen an Schwellenwerten und Systemeinstellungen

Auditexport ist als CSV und PDF verfügbar.

## 25. Backup und Wiederherstellung

- täglich verschlüsseltes Backup von Originalen, Markdown, Metadaten, Benutzerzuordnungen und Auditdaten
- zusätzliches Backup vor Updates, Migrationen und großen Reindexierungen
- mindestens eine getrennte Backup-Kopie außerhalb des laufenden Servers
- Qdrant ist ein reproduzierbarer Index und nicht die alleinige führende Datenquelle
- Recovery Point Objective: maximal 24 Stunden Datenverlust
- Recovery Time Objective: Wiederaufnahme innerhalb von 4 Stunden
- monatlicher automatisierter Restore-Test in isolierter Umgebung
- dokumentierter Notfallprozess
- sofortige Adminmeldung bei fehlgeschlagenem Backup oder Restore-Test

## 26. Benutzeroberfläche und UX

### 26.1 Gemeinsame Anwendung

Das bestehende Admin-Dashboard wird zu einer gemeinsamen rollenbasierten Anwendung weiterentwickelt.

- Mitarbeiter: Upload, eigene Vorgänge, eigene Dokumente
- Führungskraft: Freigabe- und Vertretungsaufgaben
- Admin: fachliche Verwaltung und Qualitätsdashboard
- Portal-Admin: zusätzlich Rollen, Systemeinstellungen und kritische Overrides

Die API prüft jede Berechtigung unabhängig von der sichtbaren UI.

### 26.2 Progressive Offenlegung

- Mitarbeiter sehen Ampel, kurze Begründung und eine empfohlene Hauptaktion.
- Führungskräfte sehen Änderungen, Vergleich und Handlungsempfehlung.
- Admins sehen technische Details, Scores, Metadaten und Audit.
- Fachbegriffe wie Embedding, Chunk, Hash oder OCR-Konfidenz werden normalen Nutzern nicht angezeigt.
- Erweiterte Details öffnen sich nur bei Bedarf.

### 26.3 Geräte und Barrierearmut

- vollständig nutzbar auf Desktop und Notebook
- responsive Kernabläufe auf Smartphone und Tablet
- mobiler Upload, Aufgabenübersicht, Freigabe und Ablehnung
- komplexe Vergleiche und Markdown-Bearbeitung für größere Displays optimiert
- vereinfachte Vergleichsansicht auf kleinen Displays
- Tastaturbedienung, erkennbare Fokuszustände und ausreichende Kontraste
- deutsche Oberfläche im MVP
- keine eigene mobile App

## 27. Admin-Qualitätsdashboard

Das MVP zeigt mindestens:

- aktive, bald ablaufende und abgelaufene Dokumente
- offene Freigaben und durchschnittliche Bearbeitungszeit
- Eskalationen und überfällige Vorgänge
- Dubletten, Versionstreffer und Widersprüche
- fehlgeschlagene Konvertierungen und Sicherheitsprüfungen
- gemeldete falsche Vinci-Antworten
- Dokumenttreffer und Quellenabdeckung
- unbeantwortete interne Fragen
- Retrieval-Latenz und Fehlerrate
- Dokumente ohne aktiven Owner oder gültige Führungskraft
- Backup- und Indexstatus

Das Dashboard darf nicht zur individuellen Leistungs- oder Verhaltensbewertung verwendet werden.

## 28. Migration vorhandener Wissensbestände

Die lokale Umsetzung ersetzt den bestehenden Dense-Retriever vollständig. Bestehende Dokumente werden kontrolliert migriert.

### 28.1 Import

- Originale und vorhandene Markdown-Dateien übernehmen
- stabile Dokument- und Versions-IDs erzeugen
- Metadaten normalisieren
- global auf Dubletten, Ähnlichkeiten, Widersprüche und Prompt Injection prüfen
- Konvertierungsqualität prüfen
- fehlende Owner, Rechte, Klassifizierung und Geltungsbereiche als Aufgaben anlegen

### 28.2 Übergangsfrist

- nicht kritische Altbestände dürfen 30 Arbeitstage übergangsweise aktiv bleiben
- kritische Sicherheits-, Rechte- oder Widerspruchstreffer gehen sofort in Quarantäne
- nach 30 Arbeitstagen werden ungeprüfte Altbestände automatisch deaktiviert
- dauerhafte Übernahme benötigt Owner-Bestätigung und reguläre Freigabe

### 28.3 Rollout

1. Neue Lösung lokal vollständig umsetzen.
2. Bestehende Knowledgebases lokal neu indexieren.
3. Rechte, Gültigkeit, Quellen und Konfliktlogik integrieren.
4. Automatisierte Evaluation und manuelle Praxistests durchführen.
5. Alle Go-live-Kriterien erfüllen.
6. Produktionsbackup erstellen und Restore prüfen.
7. Kontrolliert auf den Server übertragen.
8. Produktions-Smoke-Tests durchführen.
9. Technischen Rollback vorbereithalten, ohne Rechte- oder Gültigkeitsregeln zu umgehen.

## 29. Erfolgskriterien und Go-live-Gate

Produktionsfreigabe erfolgt nur, wenn alle kritischen Kriterien erfüllt sind:

### 29.1 Sicherheit und Governance

- 0 unberechtigte Retrieval- oder Dateizugriffe in allen Sicherheitstests
- 0 aktive abgelaufene, gelöschte oder nicht freigegebene Dokumente im RAG
- 100 % blockierte exakte Dubletten
- 100 % korrekte Eskalation erkannter Knowledgebase-übergreifender Treffer und Widersprüche
- vollständige Auditierbarkeit aller kritischen Aktionen

### 29.2 Retrieval und Quellen

- mindestens 90 % richtige Dokumenttreffer bei definierten KAHLE-Testfragen
- mindestens 95 % korrekt verlinkte Originalquellen
- höchstens 5 % unbelegte Antworten bei Fragen ohne freigegebene Quelle
- keine Verschlechterung bei kritischen Richtlinienfragen
- erfolgreiche Tests für Kennungen, natürliche Sprache, Tabellen, Folgefragen, mehrere Quellen und Konflikte

### 29.3 Konvertierung und Verarbeitung

- mindestens 95 % erfolgreich konvertierte Standarddokumente
- typische Dokumente bis 10 MB innerhalb von 5 Minuten vollständig geprüft
- Tabellen- und Excel-Datensätze bleiben fachlich zusammenhängend
- erfolgreicher kompletter Neuaufbau des Suchindex aus den Quelldaten

### 29.4 UX

- mindestens 80 % der Testmitarbeiter schließen einen Upload ohne Erklärung ab
- Führungskräfte verstehen und entscheiden einen normalen Freigabefall durchschnittlich in unter 3 Minuten
- zentrale Abläufe funktionieren auf Desktop und mobil

### 29.5 Betrieb

- Backup-Wiederherstellung erfolgreich getestet
- RPO von 24 Stunden nachgewiesen
- RTO von 4 Stunden nachgewiesen
- Systemfehler erzeugen automatisch nachvollziehbare Admin-Incidents

## 30. Evaluationskonzept für Retrieval

Die bestehende Datei `eval/rag/questions.yml` wird zu einem belastbaren KAHLE-Evaluationssatz erweitert.

Erforderliche Testgruppen:

- exakte Produkt-, Dokument- und Prozesskennungen
- Synonyme und natürliche Mitarbeiterfragen
- Fragen mit einer eindeutigen Quelle
- Fragen mit mehreren ergänzenden Quellen
- Fragen mit widersprüchlichen Quellen
- Fragen zu abgelaufenen und gesperrten Dokumenten
- Fragen außerhalb der eigenen Knowledgebase-Rechte
- Tabellen- und Excel-Fragen
- Aufzählungen und vollständige Prozessfragen
- kurze Folgefragen mit Gesprächskontext
- Fragen ohne vorhandene Antwort
- manipulierte Dokumente mit Prompt-Injection-Mustern

Verglichen und protokolliert werden:

- Dense-only als Ausgangswert
- Dense plus BM25/Sparse
- Hybrid plus RRF
- Hybrid plus Reranker
- verschiedene Chunking- und Kontextstrategien
- Trefferqualität, Quellenqualität, Latenz und Ressourcenverbrauch

## 31. Technische Komponenten und voraussichtliche Änderungen

Die konkrete Implementierungsplanung folgt nach Freigabe dieses PRDs. Voraussichtlich betroffen:

- `admin-dashboard`: Ausbau zum rollenbasierten Wissensportal
- `stack/kb-admin-api`: Benutzer, Rollen, Workflows, Dokumentmodell und sichere Originalquellen
- `stack/document-worker`: neue Formate, Sicherheitsprüfungen, Normalisierung und strukturorientierte Konvertierung
- `stack/kb-sync`: kanonisches Dokumentmodell, Dense- und Sparse-Indexierung, Metadaten und atomare Aktivierung
- `stack/open-webui-tools/rag_chat_direct_qdrant.py`: vollständiger Ersatz durch berechtigungsgefiltertes Hybrid Retrieval mit Reranking
- `stack/owui-file-proxy`: authentifizierter Read-only-Zugriff auf Originalquellen
- `n8n/workflows/knowledgebase`: Erinnerungen, Sammelmails, Eskalationen und Fehlerbenachrichtigungen
- `eval/rag`: Ausbau der Testfragen und automatisierten Retrieval-Evaluation
- Produktionskonfiguration: Microsoft OIDC, Mailversand, Backups, Secrets und Monitoring

## 32. Abnahmeszenarien

Mindestens folgende Ende-zu-Ende-Szenarien müssen bestehen:

1. Mitarbeiter lädt ein sauberes neues DOCX in genau eine Bereichs-Knowledgebase hoch; das System aktiviert es automatisch und Vinci zitiert die Originalquelle.
2. Mitarbeiter lädt ein sauberes Dokument für KAHLE-Allgemein hoch; die Führungskraft genehmigt und Vinci zitiert die Originalquelle.
3. Mitarbeiter lädt eine identische Datei hoch; das System verhindert eine doppelte Veröffentlichung, zeigt das bestehende Dokument und legt die gewählte Aktion der Führungskraft vor.
4. Identisches Dokument liegt in einer anderen Knowledgebase; der Nutzer beantragt die zusätzliche Veröffentlichung, Führungskraft und anschließend Admin genehmigen.
5. Neue Version ersetzt eine alte Version nach Führungskraftfreigabe atomar und lässt sich zurückrollen.
6. Ähnliche Dokumente derselben Knowledgebase werden verständlich verglichen und der Führungskraft vorgelegt.
7. Knowledgebase-übergreifender Ähnlichkeitstreffer verlangt mindestens die Führungskraft; erst die zusätzliche Veröffentlichung oder ein Widerspruch verlangt danach den Admin.
8. Widersprüchliche Richtlinien werden erst nach Führungskraft und Admin veröffentlicht.
9. Kritischer Prompt-Injection-Befund in einer sicher untersuchten Datei durchläuft Führungskraft und Admin; Malware bleibt nicht übersteuerbar in Quarantäne.
10. Fehlerhafte Excel-Konvertierung wird zeilen- und spaltenbezogen angezeigt und korrigiert.
11. Owner bestätigt Aktualität, Führungskraft verlängert ein einfach zugeordnetes Dokument.
12. Mehrfach veröffentlichtes Dokument wird erst nach Führungskraft und Admin verlängert.
13. Abgelaufenes Dokument verschwindet automatisch aus dem RAG.
14. Nutzer ohne Leserecht erhält weder Antwortinhalt noch Originalquelle.
15. Gemeldete falsche Vinci-Antwort erzeugt einen nachvollziehbaren Korrekturfall.
16. Deaktivierter Owner erzeugt eine Neuzuordnungsaufgabe.
17. Admin bereitet neue Knowledgebase vor, Portal-Admin genehmigt.
18. Portal-Admin legt eine Knowledgebase direkt an.
19. Gelöschtes Dokument wird innerhalb von 30 Tagen wiederhergestellt.
20. Dokument wird nach 90 Tagen automatisch physisch gelöscht, Auditmetadaten bleiben erhalten.
21. Vollständiger Restore und Neuaufbau des Suchindex funktionieren aus dem Backup.

## 33. Offene Umsetzungsdetails nach PRD-Freigabe

Diese Punkte verändern das Produktziel nicht, müssen aber in der technischen Spezifikation festgelegt und durch Evaluation belegt werden:

- konkretes Reranker-Modell und Betriebsort
- konkrete deutsche BM25-/Sparse-Konfiguration
- Candidate- und Chunk-Limits je Fragetyp
- genaue Qdrant-Collection-, Shard- und Payload-Index-Struktur
- Mailtransport und Absenderadresse
- konkrete Malware- und Prompt-Injection-Scanner
- Datenbanktechnologie für Workflow-, Audit- und Rollenmodell
- Vorschauverfahren für Office-Dateien
- technische Umsetzung der Microsoft-Step-up-Authentifizierung
- feste interne Fehler- und Incident-Schweregrade
- Schwellenwerte der Ähnlichkeits- und Widerspruchserkennung

Diese Entscheidungen werden nicht nach Bauchgefühl getroffen. Sie werden anhand der vorhandenen Infrastruktur, echter KAHLE-Dokumente, Sicherheitsanforderungen und der Retrieval-Evaluation festgelegt.

## 34. Definition of Done für das MVP

Das MVP ist abgeschlossen, wenn:

- alle beschriebenen Kernabläufe implementiert sind
- Rollen und Rechte serverseitig erzwungen werden
- Migration und Hybrid Retrieval lokal vollständig funktionieren
- alle kritischen Abnahmeszenarien automatisiert oder nachvollziehbar manuell getestet wurden
- das Go-live-Gate erfüllt ist
- Backup, Restore und Rollback dokumentiert und getestet sind
- Betriebs- und Adminanleitung vorliegen
- keine offenen kritischen oder hohen Sicherheitsbefunde bestehen

Erst danach darf die Lösung auf dem Produktionsserver aktiviert werden.

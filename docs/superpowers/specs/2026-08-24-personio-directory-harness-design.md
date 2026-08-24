# Personio-Mitarbeiterverzeichnis im KAHLE-Vinci Knowledge Harness

**Stand:** 24. August 2026  
**Status:** Fachlich freigegeben

## Ziel

KAHLE-Vinci erhält ein automatisch aus Personio synchronisiertes internes
Mitarbeiterverzeichnis. Vinci beantwortet damit aktuelle Fragen zu Personen,
Positionen, Bereichen, Teams, Standorten und dienstlichen Kontaktdaten. Personio
bleibt die führende Quelle; niemand pflegt parallel eine Mitarbeiterliste in
Vinci.

Der vorhandene Knowledge Harness wird weiterverwendet. Sein bereits
implementierter Intent `employee_directory` wird um einen produktiven
Personio-Adapter und eine kontrollierte Mehrquellenplanung ergänzt.

## Fachlicher Umfang

### Sichtbare Personen

- `ACTIVE` wird in der normalen Mitarbeitersuche berücksichtigt.
- `LEAVE` wird in der normalen Mitarbeitersuche berücksichtigt.
- `ONBOARDING` wird synchronisiert, bleibt aber außerhalb ausdrücklich
  formulierter Onboarding-Fragen unsichtbar.
- `INACTIVE`, ausgeschiedene und externe Personen werden nicht indexiert
  beziehungsweise beim Vollabgleich entfernt.
- Alle angemeldeten OpenWebUI-Rollen `user` und `admin` dürfen die freigegebenen
  Verzeichnisdaten sehen. `pending` erhält keinen Zugriff.

### Freigegebene Felder

Für aktive Personen und `LEAVE`:

- stabile Personio-ID
- Vorname, Nachname und Anzeigename
- Position
- Abteilung
- Team
- Office beziehungsweise Standort
- geschäftliche E-Mail-Adresse
- geschäftliche Telefonnummer
- Beschäftigungsstatus und Beschäftigungsart als interne Filterfelder
- Zeitstempel der letzten Personio-Änderung und des letzten erfolgreichen Syncs

Für `ONBOARDING` dürfen Antworten ausschließlich folgende Felder enthalten:

- Vorname und Nachname
- zukünftige Position
- Abteilung beziehungsweise Bereich
- Team
- geplanter Standort

E-Mail-Adresse, Telefonnummer, Eintrittsdatum, Vertragsdaten und andere
Personio-Felder werden für Onboarding-Ergebnisse bereits vor dem EvidenceBundle
entfernt. Sie werden nicht lediglich durch eine Prompt-Anweisung verborgen.

Nicht verarbeitet werden private Kontaktdaten, Vergütung, Bank- oder
Steuerdaten, Geburtsdatum, Abwesenheiten, Krankheitsdaten, Vertragsdetails,
Leistungsdaten oder Beurteilungen.

## Architektur

Ein neuer interner Docker-Dienst `personio-directory` kapselt die gesamte
Personio-Integration:

```text
Personio API
    │
    ▼
personio-directory
    ├── Authentifizierung und Tokenverwaltung
    ├── Voll- und Delta-Sync
    ├── Feldmapping und Datenschutzfilter
    ├── kanonischer lokaler Zustand
    ├── Status- und Löschlogik
    ├── separater Qdrant-Index
    └── interne Suchschnittstelle
            │
            ▼
KAHLE Knowledge Harness
    ├── Intent und Informationsbedarfe
    ├── Personio-/RAG-Retrievalplan
    ├── parallele Ausführung bei Mischfragen
    └── gemeinsames EvidenceBundle
            │
            ▼
Vinci-Antwort mit getrennten Quellen
```

Der Dienst veröffentlicht keinen externen Port. OpenWebUI erreicht ihn nur im
internen Docker-Netz. Personio-Zugangsdaten liegen ausschließlich in diesem
Dienst. Weder Modell noch Browser, OpenWebUI-Tooldefinition oder
Qdrant-Nutzdaten enthalten die Zugangsdaten.

## Personio-Synchronisation

### API-Auswahl

Vor der endgültigen Adapterfestlegung werden mit den realen KAHLE-Credentials
Employee API v1 und Persons/Employments API v2 read-only geprüft. V2 ist die
bevorzugte Zielversion, sofern Position, Abteilung, Team, Office, Status und
geschäftliche Kontaktdaten mit vertretbar wenigen Aufrufen und eindeutigen
Klartextwerten verfügbar sind. Andernfalls wird der erste produktive Adapter
über v1 gebaut. Der fachliche Adaptervertrag bleibt versionsunabhängig.

### Betriebsmodus

- initialer Vollabgleich
- Delta-Sync alle 15 Minuten
- täglicher vollständiger Soll-Ist-Abgleich
- idempotente Upserts anhand der Personio-ID
- überlappendes Delta-Fenster zur Absicherung von Zeitgrenzen
- Entfernung nicht mehr gelieferter oder nicht mehr zulässiger Personen
- optional später Webhooks als Beschleuniger, niemals als einziger
  Synchronisationsmechanismus

Der letzte erfolgreich abgeschlossene Sync-Zeitpunkt wird atomar gespeichert.
Ein fehlgeschlagener Lauf darf weder den letzten gültigen Index ersetzen noch
den Fortschrittszeiger vorziehen.

### Konfiguration

Lokal werden die vorhandenen Windows-Umgebungsvariablen verwendet:

```text
PERSONIO_CLIENT_ID
PERSONIO_API
```

`PERSONIO_API` wird intern als Client-Secret behandelt. Die Werte dürfen weder
ausgegeben noch in Git, Test-Fixtures, Logs oder Rolloutpakete geschrieben
werden. Produktiv werden dieselben Namen in `stack/.env.production` gesetzt.

## Kanonisches Datenmodell und Index

Die Personio-ID ist der Primärschlüssel. Name oder E-Mail-Adresse sind keine
Identitätsschlüssel. Ein kanonischer Datensatz enthält nur die freigegebenen
Felder und normalisierte Suchwerte. Personen werden in einer eigenen
Qdrant-Collection indexiert, getrennt vom Dokumentindex `vinci_knowledge`.

Exakte Metadatenfelder unterstützen Namen, E-Mail, Telefonnummer, Status,
Position, Abteilung, Team und Standort. Ein kompakter Suchtext ermöglicht
natürliche Fragen. Exakte Filter und semantische Suche werden kombiniert;
Telefonnummern und E-Mail-Adressen dürfen nicht ausschließlich über Embeddings
gesucht werden.

Der Index speichert keine historischen Versionen einer Person. Ein erfolgreicher
Upsert ersetzt den aktuellen Datensatz. Entfernte Personen werden physisch aus
der aktiven Collection gelöscht.

## Suchverhalten

### Unter-Intents

Der Harness unterscheidet mindestens:

- `person_lookup`: Informationen über eine bestimmte Person
- `directory_search`: Personen nach Rolle, Bereich, Team oder Standort
- `coworker_lookup`: organisatorisch nächstgelegene Kolleginnen und Kollegen
- `onboarding_search`: ausdrücklich angefragte Onboarding-Personen

Formulierungen wie „Was weißt du über Max Mustermann?“, „Wo arbeitet Max
Mustermann?“ oder „Was macht Max Mustermann?“ gelten als Personensuche. Eine
solche offene Frage bleibt auf die freigegebenen Personio-Verzeichnisfelder und
gegebenenfalls ausdrücklich belegtes internes RAG-Wissen beschränkt. Sie löst
keine freie Personenrecherche aus.

### Onboarding-Grenze

`ONBOARDING` wird nur bei einem eindeutigen Onboarding-Bezug berücksichtigt.
„Neu“ allein genügt nicht. Zulässige Beispiele sind:

- „Wer ist aktuell im Onboarding?“
- „Welche neuen Serviceberater sind im Onboarding?“
- „Welche Onboarding-Mitarbeitenden kommen nach Hannover?“

Normale Rollen-, Team- und Standortfragen liefern keine Onboarding-Personen.

### Organisatorische Zusammenarbeit

„Mit wem arbeitet Person X zusammen?“ wird deterministisch interpretiert:

1. andere aktive Personen im gleichen Team, sofern ein Team gepflegt ist;
2. andernfalls gleiche Position am gleichen Standort;
3. andernfalls gleiche Abteilung am gleichen Standort;
4. der Standort allein reicht nicht aus.

Die Antwort benennt die verwendete Zuordnungsgrundlage und behauptet keine
tatsächliche persönliche, fachliche oder projektbezogene Zusammenarbeit.
Onboarding-Personen werden nur bei ausdrücklich genanntem Onboarding-Bezug
einbezogen.

## Harness-Routing und Quellenhoheit

Das Routing richtet sich nach Informationsbedarfen, nicht allein danach, ob in
der Frage ein Personenname vorkommt.

### Nur Personio-Verzeichnis

Reine Fragen nach aktuellen Stammdaten, Organisation oder Kontakten verwenden
ausschließlich `personio_directory`. `rag_chat` wird in diesem Fall nicht
aufgerufen, und ein leerer Treffer fällt nicht auf alte Dokumentinformationen
zurück.

### Nur RAG

Reine Fragen zu Projekten, Systemen, Prozessen, Arbeitsweisen oder
Arbeitsanweisungen verwenden `rag_chat`.

### Personio und RAG

Fragen wie „Was hat Stefan Schrader mit VSX zu tun?“, „Wie hängen Jan Oltmanns
und KAHLE-Vinci zusammen?“ oder „Wer ist Ansprechpartner und welche
Arbeitsanweisung gilt?“ erzeugen zwei Informationsbedarfe. Der Harness führt
`personio_directory` und `rag_chat` serverseitig parallel aus und führt beide
Ergebnisse in einem EvidenceBundle zusammen. Die korrekte Ausführung hängt
nicht davon ab, ob das Antwortmodell selbst parallele Toolaufrufe plant.

Quellenhoheit:

- Personio ist führend für aktuelle Rolle, Team, Abteilung, Standort und
  Kontaktdaten.
- RAG ist führend für dokumentierte Projekte, Systeme, Prozesse, Tätigkeiten
  und Verantwortungszusammenhänge.
- Bei Widersprüchen zu aktuellen Stammdaten gilt Personio.
- Jede Quelle belegt nur ihren eigenen Teil. Ein Personio-Treffer ersetzt keine
  fehlende Projektdokumentation und umgekehrt.
- Interne Mitarbeiterfragen lösen keine automatische Websuche aus.

Personio-Quellen erhalten eigene IDs wie `[P1]`, Dokumentquellen weiterhin
`[R1]`. Der Harness-Endvalidator akzeptiert nur IDs aus dem zusammengeführten
EvidenceBundle.

## Antwortverhalten

Antworten nennen die fachliche Quelle und den letzten erfolgreichen
Sync-Zeitpunkt, ohne einen direkten Personio-Link auszugeben:

```text
Quelle: Personio-Mitarbeiterverzeichnis, zuletzt synchronisiert am
24.08.2026 um 10:15 Uhr.
```

Bei keinem Treffer lautet die stabile Antwort sinngemäß:

```text
Dazu finde ich im aktuellen Personio-Mitarbeiterverzeichnis keine passende
freigegebene Information.
```

Es gibt keinen Rückfall auf Modellwissen. Bei Mischfragen darf der belegte
RAG-Teil dennoch beantwortet werden; die fehlende Personio-Information wird
offen ausgewiesen.

## Fehler- und Sicherheitsverhalten

- Der letzte erfolgreiche Index bleibt bei einem Personio-Ausfall verfügbar.
- Ab einem Sync-Alter von mehr als 24 Stunden kennzeichnet Vinci den Stand als
  möglicherweise veraltet.
- Ohne jemals erfolgreichen Sync werden keine Mitarbeiterangaben beantwortet.
- HTTP 429 und temporäre API-Fehler werden mit begrenztem exponentiellem
  Backoff, Jitter und `Retry-After` behandelt.
- Fehlerhafte Einzelpersonen werden übersprungen; Logs enthalten nur
  Personio-ID und sanitisierten Fehlercode.
- Namen, E-Mail-Adressen, Telefonnummern, Token, Secrets und vollständige
  API-Antworten erscheinen nicht in Logs.
- Der interne Suchendpunkt prüft den gebundenen OpenWebUI-Nutzerkontext und
  akzeptiert nur `user` oder `admin`.
- Onboarding-Feldreduktion und Statusfilter werden serverseitig durchgesetzt.

## Lokale Abnahme unter `localhost:3004`

Die lokale Prüfung verwendet echte KAHLE-Credentials ausschließlich aus den
Windows-Umgebungsvariablen. Zuerst erfolgt ein read-only API-Probe ohne
Indexierung, danach der kontrollierte lokale Vollsync.

Pflichtfälle für alle verfügbaren Vinci-Modelle:

1. Person nach Name, Rolle, Standort, Telefon und E-Mail finden.
2. Personen nach Position, Abteilung, Team und Standort auflisten.
3. `LEAVE` in normaler Suche berücksichtigen.
4. `ONBOARDING` in normaler Suche verbergen.
5. `ONBOARDING` bei ausdrücklicher Onboarding-Frage mit reduzierten Feldern
   liefern.
6. `INACTIVE` und externe Personen nicht liefern.
7. Zusammenarbeitskaskade Team, Position plus Standort, Abteilung plus Standort
   belegen.
8. Reine Personenfrage ruft nur `personio_directory` auf.
9. Reine Prozessfrage ruft nur `rag_chat` auf.
10. Mischfrage ruft beide Adapter auf und führt Quellen korrekt zusammen.
11. Leerer Personio-Treffer fällt nicht auf Dokumente oder Modellwissen zurück.
12. `pending` erhält keinen Zugriff.
13. Veralteter Sync wird sichtbar gekennzeichnet.
14. Secrets und personenbezogene Felder erscheinen nicht in Logs oder
    Akzeptanzartefakten.

Die bestehende Harness-Akzeptanzmatrix wird erweitert. Ein produktives
Rolloutpaket entsteht erst nach grünen automatisierten Tests und erfolgreicher
interaktiver Prüfung unter `http://localhost:3004`.

## Nicht enthalten

- Änderungen oder Schreibzugriffe in Personio
- private oder sensible HR-Daten
- Historisierung von Mitarbeiterprofilen in Vinci
- Websuche nach Beschäftigten
- Ableitung tatsächlicher Projektzusammenarbeit allein aus Team oder Standort
- öffentlich erreichbarer Personio-Suchendpunkt
- Webhooks in der ersten produktiven Ausbaustufe

## Referenzen

- `docs/research/2026-08-19-personio-vinci-personalsuche.md`
- `docs/research/2026-08-19-kahle-wissens-harness-audit.md`
- `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py`
- `stack/open-webui-tools/hybrid_retrieval.py`
- `scripts/openwebui/kahle-harness-acceptance-matrix.json`

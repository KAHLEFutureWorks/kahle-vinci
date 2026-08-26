# Personio als Datenquelle für die KAHLE-Vinci-Personalsuche

Stand: 19. August 2026  
Quellenbasis: ausschließlich offizielle Personio-Dokumentation und offizielles Personio Help Center

> **Fachliche Aktualisierung vom 26. August 2026:** Für die Umsetzung ist
> `Name (preferred)` die einzige erforderliche Namensquelle. Vor- und Nachname
> werden ausschließlich intern daraus abgeleitet. Die Beschäftigungsart wird
> nicht gelesen, gefiltert oder angezeigt; externe Personen werden wie interne
> Personen behandelt. Historische Feld- und Filterüberlegungen weiter unten
> dokumentieren den damaligen Recherchestand, gelten aber nicht mehr als
> Umsetzungsvorgabe. `Last modified` bleibt für den Delta-Sync verpflichtend.

## Kurzfazit

Ja, Personio bietet geeignete öffentliche APIs, um ein automatisch gepflegtes Mitarbeiterverzeichnis in KAHLE-Vinci bereitzustellen. Für den ersten produktiven Aufbau ist eine **serverseitige, rein lesende Custom Integration** sinnvoll, die ausschließlich folgende freigegebene Felder abruft:

- stabile Personio-ID
- Vorname und Nachname
- geschäftliche E-Mail-Adresse
- Position/Rolle
- Abteilung beziehungsweise Team
- Büro/Standort
- geschäftliche Telefonnummer, sofern sie im KAHLE-Personio-Konto als auslesbares Attribut vorhanden und freigegeben ist

Die Daten sollten pro Person als strukturierter Datensatz in Vinci gespeichert werden. Änderungen werden regelmäßig synchronisiert; inaktive oder nicht mehr vorhandene Personen werden aus dem Vinci-Suchindex entfernt. Personio bleibt dabei das führende System.

Die technische Machbarkeit ist damit belegt. Vor der Umsetzung müssen im KAHLE-Personio-Konto insbesondere **Lizenz, konkrete Attributnamen, API-Freigaben und die gelieferten Testantworten** geprüft werden.

## 1. Verfügbare API-Varianten

### Variante A: Employee API v1

Der Endpunkt [`GET /v1/company/employees`](https://developer.personio.de/v1.0/reference/get_company-employees) liefert Mitarbeiterdaten einschließlich freigegebener System- und benutzerdefinierter Attribute. Er unterstützt außerdem:

- Feldprojektion über `attributes[]`
- Filterung nach E-Mail-Adresse
- inkrementelle Abfragen über `updated_since`
- Pagination über `limit` und `offset`

Für einen ersten KAHLE-Vinci-Verzeichnissync ist v1 wahrscheinlich der einfachere Weg, weil typische Mitarbeiterattribute in einer Antwort zusammengeführt werden und ihre Werte direkt geliefert werden.

### Variante B: Persons and Employments API v2

Personio stellt außerdem die neueren v2-Ressourcen bereit:

- [`GET /v2/persons`](https://developer.personio.de/reference/get_v2-persons) für Identitäts- und Personeninformationen
- [`GET /v2/persons/{person_id}/employments`](https://developer.personio.de/reference/get_v2-persons-person-id-employments) für Beschäftigungsverhältnisse

Person und Employee stehen laut Personio in einer 1:1-Beziehung. Beschäftigungsinformationen wie Position, Büro, Organisationseinheiten und Status liegen in v2 überwiegend am Employment-Datensatz. Das v2-Schema führt unter anderem Supervisor, Office, Org Units, Legal Entity, Job/Position und Beschäftigungsstatus; die dokumentierten Statuswerte sind `ACTIVE`, `INACTIVE`, `ONBOARDING` und `LEAVE` ([Employment-Schema](https://developer.personio.de/reference/patch_v2-persons-person-id-employments-employment-id)).

Personio hat die Person-and-Employment-v2-APIs als allgemein verfügbar angekündigt ([GA-Ankündigung](https://developer.personio.de/changelog/person-employment-v2-apis-ga-announcement)). Für eine langfristige Neuentwicklung sollte v2 deshalb in einem kurzen technischen Proof of Concept geprüft werden. Je nach Antwortstruktur können jedoch zusätzliche Aufrufe für Employments, Offices oder Org Units erforderlich sein.

### Empfehlung zur Auswahl

1. Im KAHLE-Konto einen API-Test mit v1 und v2 durchführen.
2. Wenn v2 alle benötigten Felder mit vertretbar wenigen Aufrufen liefert, v2 als Zielarchitektur verwenden.
3. Falls Telefonnummer oder organisatorische Klartexte in v2 aufwendige Zusatzauflösungen benötigen, den ersten produktiven Sync über v1 umsetzen.

## 2. Authentifizierung, Zugang und Berechtigungen

### Custom Integration

Die Integration wird in Personio unter **Marketplace > Connected integrations > Create custom integration** angelegt. Sie erhält eine Client-ID und ein Client-Secret. Laut aktuellem Personio Help Center ist die Erstellung eigener Custom Integrations im **Core-Pro-Plan** verfügbar; im Core-Plan stehen nur Marketplace-Integrationen zur Verfügung ([API-Zugangsdaten verwalten](https://support.personio.de/hc/en-us/articles/4404623630993-Generate-and-manage-API-credentials), [eigene Integration bauen](https://support.personio.de/hc/en-us/articles/7438224536093-Build-your-own-integration-with-our-APIs)).

Die Person, die die Integration einrichtet beziehungsweise verwaltet, benötigt die entsprechenden Konfigurationsrechte für Marketplace/API. Der eigentliche API-Zugriff wird nicht durch die normalen Mitarbeiterrollen eingeschränkt, sondern durch die Berechtigungen der Integration. Deshalb ist die Attributfreigabe sicherheitskritisch.

Für Vinci sind ausschließlich erforderlich:

- **Read** für Employees/Persons
- die konkret benötigten lesbaren Mitarbeiterattribute
- optional Webhook Read/Write, falls Vinci Webhooks selbst registrieren und verwalten soll

Schreibrechte auf Mitarbeiterdaten sind nicht notwendig. Personio weist zudem darauf hin, dass Write nicht automatisch Read einschließt ([API-Zugangsdaten verwalten](https://support.personio.de/hc/en-us/articles/4404623630993-Generate-and-manage-API-credentials)).

### OAuth 2.0 für v2

V2 verwendet den OAuth-2.0-Client-Credentials-Flow:

```text
POST https://api.personio.de/v2/auth/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials
client_id=...
client_secret=...
scope=personio:persons:read
```

Der Token-Endpunkt und das optionale, leerzeichengetrennte Scope-Feld sind offiziell dokumentiert ([Obtain Access Token](https://developer.personio.de/reference/post_v2-auth-token)). `GET /v2/persons` verlangt den Scope `personio:persons:read`. Personio beschreibt Zugriffstokens als 24 Stunden gültig ([Token-Changelog](https://developer.personio.de/changelog/authentication-api-improved-bearer-token)).

### Secrets nur auf dem Server

Client-ID, Secret und Access Token dürfen nur auf dem KAHLE-Vinci-Server beziehungsweise in dessen Secret-/Umgebungsvariablen liegen. Personio rät ausdrücklich von Browser-Implementierungen ab und verhindert direkte Browserzugriffe per CORS, weil die Credentials sonst offengelegt werden könnten ([Getting Started](https://developer.personio.de/docs/getting-started-with-the-personio-api)).

## 3. Eignung der gewünschten Felder

| Vinci-Information | Personio-Quelle | Bewertung |
|---|---|---|
| Vorname, Nachname | Person/Employee | direkt verfügbar |
| Geschäftliche E-Mail | Person/Employee | direkt verfügbar; als lesbares Attribut freigeben |
| Rolle/Position | Employment beziehungsweise Employee-Attribut `position` | direkt verfügbar |
| Abteilung/Team | Employment Org Units beziehungsweise Employee-Attribute | verfügbar; in v2 ggf. ID-Auflösung erforderlich |
| Standort | Employment `office` beziehungsweise Employee-Attribut `office`/Workplace | verfügbar; fachlich festlegen, welches Feld KAHLE meint |
| Telefon | voreingestelltes oder benutzerdefiniertes Mitarbeiterattribut | verfügbar, wenn im KAHLE-Konto gepflegt und für die API freigegeben |

Personio unterscheidet System-/Preset-Attribute und benutzerdefinierte Attribute. Nur die für die Integration freigegebenen Attribute werden über die Employee API geliefert; benutzerdefinierte Attribute enthalten jeweils den aktuellen, nicht den geplanten oder historischen Wert ([Getting Started](https://developer.personio.de/docs/getting-started-with-the-personio-api)). Die tatsächlich für die Credentials erlaubten Felder können über [`GET /v1/company/employees/attributes`](https://developer.personio.de/v1.0/reference/get_company-employees-attributes) ermittelt werden.

Personio führt die mobile Telefonnummer für neuere Konten als voreingestelltes Attribut; bei älteren Konten kann sie weiterhin ein benutzerdefiniertes Feld sein ([Attributübersicht](https://support.personio.de/hc/en-us/articles/115002699585-Overview-of-all-attributes-in-Personio)). Deshalb darf die Implementierung keinen festen `dynamic_...`-Bezeichner annehmen, bevor die KAHLE-Attributliste ausgelesen wurde.

Für die Vinci-Personalsuche sollte ausschließlich die **geschäftliche** Telefonnummer und E-Mail übernommen werden. Private Telefonnummern und private E-Mail-Adressen gehören nicht in den allgemeinen Suchindex.

## 4. Pagination und Filter

### V1 Employee API

Personio erzwingt bei v1 Pagination. Der dokumentierte Maximalwert beträgt 100 Mitarbeiter pro Seite; ohne Parameter werden 50 Datensätze geliefert. Folgeseiten werden über `offset` und `limit` abgefragt ([Pagination Adoption Guide](https://developer.personio.de/v1.0/docs/pagination-adoption-guide-for-v1-get-employees-endpoint)).

Relevante Parameter sind:

- `limit`
- `offset`
- `email`
- `attributes[]`
- `updated_since`

`updated_since` akzeptiert ISO-8601 oder ein Datum. Der Filter berücksichtigt nur Attribute, die für die API-Credentials freigegeben sind. In Kombination mit `attributes[]` werden nur Personen geliefert, bei denen eines der ausgewählten Attribute seit dem Zeitpunkt geändert wurde. Die aktuelle Referenz weist darauf hin, dass bei `updated_since` die Parameter `email`, `limit` und `offset` ignoriert werden ([List Employees](https://developer.personio.de/v1.0/reference/get_company-employees)). Dieses Verhalten muss im KAHLE-Konto praktisch validiert werden.

### V2 Persons API

V2 verwendet Cursor-Pagination mit 1 bis 50 Personen pro Seite, Standardwert 10. Unterstützt werden unter anderem Filter für:

- IDs und E-Mail-Adressen
- Vor- und Nachname
- `created_at` und `updated_at`, jeweils auch mit `.gt`/`.lt`
- `status=ACTIVE|INACTIVE`

Mehrere Filter werden mit logischem UND kombiniert ([List persons](https://developer.personio.de/reference/get_v2-persons)).

## 5. Aktive und ausgeschiedene Personen

Für die Vinci-Suche sollen grundsätzlich nur aktive Personen indexiert werden. In v2 bedeutet `status=ACTIVE`: Das jüngste Beschäftigungsverhältnis ist active, leave oder onboarding. `INACTIVE` bedeutet, dass das jüngste Beschäftigungsverhältnis inactive ist ([List persons](https://developer.personio.de/reference/get_v2-persons)).

Wichtig: Langzeitabwesende Personen (`LEAVE`) gelten in diesem Filter weiterhin als aktiv. Ob sie in Vinci auffindbar bleiben sollen, ist eine fachliche KAHLE-Entscheidung.

Personio weist darauf hin, dass beendete Beschäftigungsverhältnisse nicht zwangsläufig als gelöschte Person aus dem System verschwinden. Änderungen und Beendigungen können über Employment-Events signalisiert werden ([Event-driven data](https://developer.personio.de/docs/event-driven-data-from-personio)). Daher muss der Sync:

- inaktive Personen aus dem Vinci-Index entfernen,
- echte Löschungen verarbeiten,
- zusätzlich regelmäßig einen vollständigen Soll-Ist-Abgleich durchführen.

## 6. Inkrementelle Synchronisation und Webhooks

### Polling/Delta-Sync

Ein inkrementeller Sync ist über beide API-Versionen möglich:

- v1: `updated_since`
- v2 Persons: `updated_at.gt`
- v2 Employments: ebenfalls `updated_at.gt`

Dabei muss der letzte **erfolgreich abgeschlossene** Sync-Zeitpunkt gespeichert werden. Für sichere Überschneidungen sollte Vinci einige Minuten vor diesem Zeitpunkt erneut beginnen und Upserts idempotent anhand der stabilen Personio-ID durchführen.

### Webhooks

Personio v2 bietet Webhooks für Personen und Beschäftigungsverhältnisse. Relevante Events sind unter anderem:

- `person.created`
- `person.updated`
- `person.deleted`
- `employment.created`
- `employment.updated`
- `employment.deleted`
- `employment.started`
- `employment.terminated`

`person.updated` wird unter anderem bei Änderungen an Vorname, Nachname, Preferred Name, E-Mail und allen Custom Attributes ausgelöst. `employment.updated` umfasst unter anderem Department, Office, Position, Supervisor, Status und Team ([Webhook Event Catalog](https://developer.personio.de/reference/webhooks)).

Die Events liefern im Wesentlichen IDs und Ereignismetadaten. Vinci muss anschließend die aktuelle Person beziehungsweise das Employment über die API abrufen. Das ist datensparsamer als vollständige Mitarbeiterdaten im Webhook.

Personio beschreibt Webhooks ausdrücklich als Mittel gegen wiederholtes Polling ([Event-driven data](https://developer.personio.de/docs/event-driven-data-from-personio)). Gleichzeitig ist die Zustellwiederholung begrenzt: Laut Getting-Started-Dokumentation erfolgen drei Wiederholungen innerhalb von etwa 30 bis 60 Sekunden; Redirects werden nicht unterstützt ([Getting Started](https://developer.personio.de/docs/getting-started-with-the-personio-api)). Deshalb dürfen Webhooks nicht der einzige Synchronisationsmechanismus sein.

## 7. Rate Limits und Robustheit

Für `GET /v1/company/employees` dokumentiert Personio:

- 300 Requests pro Minute
- Burst bis 15 Requests pro Sekunde
- HTTP 429 bei Überschreitung
- mindestens eine Sekunde Verzögerung vor einem Retry

Quelle: [Rate Limits on GET Employees](https://developer.personio.de/changelog/rate-limits-on-get-employees-endpoint-may-6-2024).

Für die übrigen hier relevanten Endpunkte ist in den geprüften offiziellen Quellen keine einheitliche numerische Grenze veröffentlicht. Die Integration muss deshalb grundsätzlich `429` und serverseitige Fehler mit exponentiellem Backoff, Jitter und – sofern vorhanden – `Retry-After` behandeln.

## 8. Empfohlene Architektur für KAHLE-Vinci

```text
Personio API
    │
    ▼
Personio Directory Sync auf dem Vinci-Server
    ├── Token-/Secret-Verwaltung
    ├── Voll- und Delta-Sync
    ├── Feldmapping und Datenschutzfilter
    ├── Status-/Löschlogik
    └── Sync-State und Fehlerprotokoll
    │
    ▼
Kanonischer Mitarbeiterdatensatz je Personio-ID
    ├── exakte Metadatenfelder
    └── kompakter Suchtext
    │
    ▼
Vinci-Suchindex / RAG
```

### Empfohlener Betriebsmodus

1. **Initialer Vollabgleich** aller aktiven Personen.
2. **Delta-Sync alle 15 Minuten** über `updated_since` beziehungsweise `updated_at.gt`.
3. **Täglicher Vollabgleich**, der auch fehlende, inaktive oder gelöschte Personen erkennt.
4. Optional **Webhooks als Beschleuniger**, sobald ein von außen erreichbarer, abgesicherter Endpoint vorhanden ist.
5. Personio-ID als unveränderlicher Primärschlüssel; E-Mail-Adresse nicht als Primärschlüssel verwenden.
6. Idempotente Upserts und echte Löschung/Deaktivierung im Vinci-Index.

### Datenform pro Mitarbeiter

Beispiel für einen kanonischen Datensatz:

```json
{
  "source": "personio",
  "personio_id": "123456",
  "active": true,
  "first_name": "Max",
  "last_name": "Mustermann",
  "display_name": "Max Mustermann",
  "position": "Serviceberater",
  "department": "Service",
  "team": "KAHLE Hannover",
  "office": "Hannover",
  "business_email": "max.mustermann@kahle.de",
  "business_phone": "+49 ...",
  "source_updated_at": "2026-08-19T08:15:00Z"
}
```

Für eine zuverlässige Suche sollten Name, E-Mail und Telefonnummer nicht nur in Embeddings landen, sondern zusätzlich als normalisierte exakte Metadatenfelder vorliegen. Aus denselben Daten kann ein kompakter Suchtext erzeugt werden, zum Beispiel:

```text
Max Mustermann ist Serviceberater im Bereich Service am Standort Hannover.
Erreichbar unter max.mustermann@kahle.de und +49 ...
```

So funktionieren sowohl Fragen wie „Wer ist Ansprechpartner im Service in Hannover?“ als auch exakte Suchen nach einer E-Mail-Adresse oder Telefonnummer.

## 9. Datenschutz und Zugriffsschutz

Personio stellt technisch eine Attribut-Whitelist bereit; KAHLE bleibt jedoch dafür verantwortlich, welche Personaldaten in Vinci verarbeitet und welchen Nutzern sie angezeigt werden. Für die Einführung sind mindestens folgende Punkte festzulegen:

- eindeutiger Zweck: internes Mitarbeiter- und Ansprechpartnerverzeichnis
- Rechtsgrundlage und Information der Beschäftigten
- Datenminimierung auf dienstlich notwendige Kontakt- und Organisationsdaten
- Ausschluss privater Kontaktdaten, Vergütung, Geburtsdatum, Abwesenheiten, Bank-, Steuer- und sonstiger HR-Daten
- Zugriff nur für freigegebene interne Vinci-Nutzer
- Protokollierung von Sync-Fehlern ohne unnötige personenbezogene Inhalte
- Löschung beziehungsweise Entfernung aus dem Suchindex bei Austritt
- definierte Aufbewahrung von Sync-State, Logs und Backups
- gemeinsame Prüfung mit Datenschutz beziehungsweise Betriebsrat, soweit bei KAHLE erforderlich

Normale Personio-Mitarbeiterrollen begrenzen den API-Zugriff einer Custom Integration nicht. Deshalb müssen die API-Credentials selbst auf die minimal benötigten Attribute beschränkt werden ([API-Zugangsdaten verwalten](https://support.personio.de/hc/en-us/articles/4404623630993-Generate-and-manage-API-credentials)).

## 10. Offene Validierungspunkte im KAHLE-Personio-Konto

Vor einer Implementierung müssen wir gemeinsam mit einem Personio-Administrator prüfen:

1. Ist der KAHLE-Vertrag tatsächlich **Core Pro**, und erscheint „Create custom integration“?
2. Welche Attribute sind im KAHLE-Konto für dienstliche Telefonnummer, Standort, Position, Abteilung und Team hinterlegt?
3. Ist „Telefon“ ein voreingestelltes oder ein `dynamic_...`-Attribut?
4. Wird die gewünschte geschäftliche Telefonnummer bei allen relevanten Mitarbeitenden gepflegt?
5. Soll `LEAVE` weiterhin in Vinci sichtbar sein?
6. Sollen Personen in `ONBOARDING` bereits auffindbar sein oder erst ab Beschäftigungsbeginn?
7. Welche Personengruppen sind auszuschließen, etwa externe Beschäftigte, Auszubildende oder bestimmte Gesellschaften?
8. Liefert v2 die benötigten Klartexte direkt oder nur referenzierte IDs für Office/Org Units?
9. Sind Webhook-Berechtigungen und ein öffentlich erreichbarer HTTPS-Callback für Vinci zulässig?
10. Welche datenschutzrechtliche Freigabe und gegebenenfalls Betriebsratsbeteiligung ist erforderlich?

## 11. Empfohlener nächster Schritt

Ein read-only Proof of Concept ohne Indexierung:

1. Custom Integration mit ausschließlich Employee/Persons Read anlegen.
2. Nur die sieben benötigten Attribute freigeben.
3. Credentials sicher als Server-Umgebungsvariablen hinterlegen.
4. Attributliste und jeweils eine Testseite aus v1 und v2 abrufen.
5. Prüfen, wie KAHLE-Telefon, Standort, Position, Team und Status tatsächlich geliefert werden.
6. Entscheidung zwischen v1 und v2 dokumentieren.
7. Erst danach den Vinci-Sync und den Suchindex implementieren.

Dieser Test verändert keine Daten in Personio und lässt sich vollständig mit Leserechten durchführen.

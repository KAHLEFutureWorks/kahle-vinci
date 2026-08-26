# Retrievalplanung, Dokumentmetadaten und claim-genaue Evidenz

**Stand:** 25. August 2026
**Status:** Fachlich freigegeben

## Ziel

Der gemeinsame KAHLE-Vinci-Harness plant den Wissensabruf vor jedem Adapteraufruf,
grenzt Dokumente anhand fachlicher Portalmetadaten ein und lässt nur Aussagen zu,
deren benötigte Fakten oder Beziehungen in einer konkreten Textstelle belegt sind.
Die Regeln gelten für alle heutigen und zukünftigen Vinci-Modelle.

## Grundsatz für hochgeladene Dokumente

Klassifikations- und Evidenzmetadaten werden nicht in hochgeladene PDF-, Word-
oder Markdown-Dateien geschrieben. Originaldatei, extrahierter Inhalt, Version,
Freigabe und Prüfsumme bleiben unverändert. Die kanonischen Metadaten liegen in
der Wissensportal-Datenbank und werden beim Indexieren als Qdrant-Payload
übernommen.

Bestehende aktive Dokumentversionen werden über einen wiederholbaren Backfill
klassifiziert. Automatisch eindeutige Werte dürfen direkt übernommen werden;
unsichere Vorschläge werden als prüfbedürftig gespeichert und niemals als harte
Retrievalfilter verwendet. Der Backfill erzeugt keine neuen fachlichen Fakten.

## Gemeinsame Verträge

`RetrievalPlan` entsteht vor Personio- oder RAG-Aufrufen und enthält mindestens:

- erforderliche Adapter,
- eine oder mehrere strukturierte Informationsbedarfe,
- erlaubte Dokumentdomänen und Dokumentarten,
- benötigte Evidenzfähigkeiten,
- benötigte explizite Beziehungen,
- gebundenen Berechtigungsumfang.

Ein Informationsbedarf ist modellunabhängig. Bei unsicherer Klassifikation wird
nicht hart auf eine Domäne eingeschränkt; ACL, Version, Veröffentlichung und
Gültigkeit bleiben immer harte Filter.

## Dokumentklassifikation

Die erste Schemafassung verwendet kontrollierte Werte für:

- `domain`: fachlicher Gegenstandsbereich,
- `document_type`: Art und Verbindlichkeit des Dokuments,
- `topics`: behandelte Gegenstände,
- `evidence_capabilities`: welche Antwortarten das Dokument ausdrücklich tragen kann,
- `source_provider`: Ursprung der Quelle,
- `classification_status`: `confirmed`, `inferred` oder `review_required`,
- `classification_version`: Version der Klassifikationslogik.

Nur `confirmed` und hinreichend eindeutige `inferred`-Metadaten dürfen die Suche
einschränken. `review_required` bleibt beobachtbar, wirkt aber nicht als harter
Ausschluss.

## Beziehungsbelege

Eine Verantwortungs- oder Zuständigkeitsaussage benötigt einen strukturierten
Beziehungsbedarf aus Subjektart, Prädikat und Objekt. Eine Quelle erfüllt ihn nur,
wenn eine einzelne belegte Textstelle die Beziehung ausdrücklich trägt. Zwei
getrennte Aussagen über eine Person und ein System dürfen nicht zu einer neuen
Zuständigkeit zusammengesetzt werden.

Beim Backfill dürfen Beziehungsmetadaten nur mit exaktem `evidence_span`,
Quellen-ID und Dokumentversion gespeichert werden. Fehlt die Aussage im Inhalt,
muss das fachliche Dokument ergänzt oder eine andere autoritative Quelle
angebunden werden.

## Claim-genaues EvidenceBundle

`supported_claims` enthält strukturierte Claims mit stabiler Claim-ID,
Quellen-ID, Text, Typ und exaktem Evidenzausschnitt. Ein kompletter
Elternabschnitt gilt nicht pauschal als eine unterstützte Aussage. Der
Endvalidator akzeptiert nur Quellen- und Claim-IDs aus demselben EvidenceBundle.

Personio bleibt führend für aktuelle Verzeichnisstammdaten. RAG bleibt führend
für dokumentierte Prozesse, Systeme, Projekte und Verantwortungsbeziehungen.
Beide Adapter verwenden denselben Claim-Vertrag.

## Migration und Betrieb

Die Portal-Datenbank erhält additive Tabellen beziehungsweise Spalten; bestehende
Dokument- und Versions-IDs bleiben erhalten. Der Backfill ist idempotent,
protokolliert nur technische Zähler und löst anschließend eine kontrollierte
Neuindexierung der betroffenen aktiven Versionen aus. Rollback entfernt oder
ignoriert die neue Klassifikationsversion, ohne Originaldokumente zu verändern.

## Abnahme

- Arbeitsanweisungen verwenden keine Software-Release-Evidenz.
- Systembeschreibungen und Personendaten erzeugen keine Zuständigkeit.
- Eine ausdrücklich dokumentierte Beziehung bleibt auffindbar.
- Existenztreffer werden nicht als Bedienungsanleitung klassifiziert.
- Bestehende Dokumente lassen sich ohne Dateiänderung nachklassifizieren.
- Personio-, RAG- und Mischfragen behalten ihre getrennte Quellenhoheit.
- Alle Vinci-Modelle erhalten denselben RetrievalPlan und dasselbe EvidenceBundle.

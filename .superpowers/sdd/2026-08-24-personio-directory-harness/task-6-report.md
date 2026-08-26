# Task 6 report — Mehrquellenplanung im Knowledge Harness

## Implementierung

- `RetrievalPlan` beschreibt jetzt mehrere erforderliche Quellen über
  `required_tools`. Die schreibgeschützte Kompatibilitätsansicht
  `required_tool` liefert bei einer Einzelquelle weiterhin deren Namen und bei
  Mischfragen `multi_source`.
- `plan_retrieval` klassifiziert Informationsbedarfe ohne Modellzweige:
  aktuelle Personen-, Organisations- und Kontaktdaten verwenden nur
  `personio_directory`; Prozesse, Systeme und Arbeitsanweisungen nur
  `rag_chat`; explizite Beziehungsfragen zu Personen und Projekten verwenden
  beide Quellen.
- `merge_evidence` führt Personio- und RAG-Evidenz zusammen. Personio bleibt
  führend für aktuelle Rolle, Team, Abteilung, Standort und dienstliche
  Kontaktdaten, während dokumentierte Projekt- und Systembezüge aus RAG
  erhalten bleiben.
- Der Endvalidator akzeptiert nun neben bestehenden numerischen Quellen auch
  getrennte `P`- und `R`-Quellen-IDs und weist unbekannte IDs aus dem
  zusammengeführten EvidenceBundle zurück.
- Die bisherige reine RAG-Planung und ihre Ereignisform bleiben für alle
  nicht-directory-bezogenen Anfragen erhalten. Die tatsächliche parallele
  Toolausführung ist ausdrücklich noch nicht Bestandteil dieses Tasks.

## Verifikation

```text
C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest stack/tests/test_kahle_knowledge_harness.py stack/tests/test_kahle_harness_reference_matrix.py -q
34 passed

C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest stack/tests -q
391 passed

git diff --check
exit 0
```

Es wurden keine echten Personio-Credentials, keine Windows-Umgebungsvariablen
und keine Personio-API verwendet.

## Reviewkorrektur

- Allgemeine Wörter wie Team, Rolle, Bereich oder Telefonnummer lösen innerhalb
  einer Prozess-, System- oder Dokumentfrage keine Personio-Suche mehr aus.
  Personio wird nur bei einer konkreten Personen-, Kontakt- oder
  Mitarbeiterlistenfrage eingeplant.
- Onboarding wird ausschließlich bei einer ausdrücklichen Personen- oder
  Listenfrage durchsucht. Fragen zum Onboarding-Prozess bleiben beim RAG.
- Unstrukturierte RAG-Aussagen zu aktuellen Stammdaten einer in Personio
  gefundenen Person werden unterdrückt. Belegte Projekt-, System-, Prozess-
  und Verantwortungsbezüge bleiben dagegen als RAG-Evidenz erhalten.

Aktualisierte Verifikation: 41 fokussierte Harness-/Referenztests und 398
Stack-Tests sind grün; `git diff --check` ist sauber.

## Zweite Reviewkorrektur

Gemischte unstrukturierte RAG-Sätze werden nur entlang einer engen,
deterministischen Klauselstruktur getrennt. Aktuelle Rollen-, Team- oder andere
Stammdatenklauseln werden entfernt; eine eigenständige Projekt-, System- oder
Prozessklausel bleibt mit ihrer ursprünglichen RAG-Quelle erhalten. Ist die
Trennung nicht eindeutig, wird der gesamte unstrukturierte RAG-Claim verworfen.
Dadurch entstehen weder unvollständige Satzfragmente noch neue Quellen-IDs.

Aktualisierte Verifikation: 42 fokussierte Harness-/Referenztests und 399
Stack-Tests sind grün; `git diff --check` ist sauber.

## Dritte Reviewkorrektur

Eine RAG-Klausel mit Projekt-, System- oder Prozesswort bleibt nur erhalten,
wenn sie eine vollständige, eindeutige Beziehungsform enthält, etwa
`begleitet`, `verantwortet`, `arbeitet an/am`, `ist beteiligt an`,
`unterstützt` oder `leitet` mit einem passenden Objekt. Unsichere Formulierungen
mit „möglicherweise“, „eventuell“ oder „vielleicht“ sowie unvollständige
Fragmente werden verworfen. Die vorherige gemischte VSX-Regression bleibt
abgedeckt und vollständig bereinigt.

Aktualisierte Verifikation: 43 fokussierte Harness-/Referenztests und 400
Stack-Tests sind grün; `git diff --check` ist sauber.

## Vierte Reviewkorrektur

Die vollständige, nicht eingeschränkte Form „ist am <Projekt/System/Prozess>
beteiligt“ wird jetzt ausdrücklich als dokumentierte RAG-Beziehung erkannt.
Sie wird deshalb nicht durch die allgemeine Kopula-Erkennung als aktuelle
Stammdatenangabe verworfen. Unsichere Varianten und alle bisherigen Konflikt-
und Klauseltrennungsfälle bleiben durch die Regressionstests geschützt.

Aktualisierte Verifikation: 44 fokussierte Harness-/Referenztests und 401
Stack-Tests sind grün; `git diff --check` ist sauber.

# Decisions

## Status and Evidence Rules

Dieses Dokument enthält nur dauerhafte, für Änderungen relevante Festlegungen.

- `Confirmed` bedeutet, dass eine Entscheidung oder Policy durch aktuelle
  verbindliche Dokumentation, Tests, Contracts oder einen eindeutigen
  Entscheidungsbeleg ausdrücklich bestätigt ist.
- `Observed` bedeutet, dass der aktuelle technische Zustand in Code oder
  Konfiguration erkennbar ist, ohne damit eine bestätigte historische
  Architekturentscheidung zu behaupten.
- `Rationale: Unknown rationale` bedeutet, dass das Repository keinen
  belastbaren Entscheidungsgrund dokumentiert. Ein Grund wird nicht aus dem
  technischen Zustand abgeleitet.

## ADR-001: Tiered local verification

Status: Confirmed

Decision:
Die lokale Verification ist in Targeted, Fast, Full und Specialized gegliedert.
`scripts/run-local-tests.ps1` ist der kanonische Runner. Full ist dessen
Standard und das erforderliche Abschluss-Gate für substantielle,
bereichsübergreifende, Security-, Datenmodell-, Integrations- und
Infrastrukturänderungen.

Evidence:

- `docs/VERIFICATION.md`, Abschnitte „Welcher Tier ist wann erforderlich?“ und
  „Kanonische Befehle“
- `scripts/run-local-tests.ps1`
- `stack/tests/test_verification_harness.py`

Rationale:
Dokumentiert. Targeted liefert schnelles Feedback während der Implementierung,
Fast deckt lokal begrenzte Änderungen offline ab, Full ergänzt Portal-Backend,
Produktionsbuild und Renderingtests, Specialized prüft nur betroffene
Laufzeit- oder Providergrenzen.

Implications:

- Targeted und Specialized ersetzen den erforderlichen Fast oder Full Verify
  nicht.
- Ein Checkfehler und ein Setupfehler bleiben unterschiedliche Ergebnisse, aber
  beide verhindern Exit-Code 0.

## ADR-002: One canonical production environment template

Status: Confirmed

Decision:
`stack/env.production.template` ist die einzige kanonische eingecheckte Vorlage
für die Produktionskonfiguration. Die reale `stack/.env.production` bleibt
nicht versioniert. Ein konkurrierender Weg über
`stack/.env.production.example` ist nicht zulässig.

Evidence:

- `stack/env.production.template`
- `stack/tests/test_production_auth_contracts.py`
- `docs/operations/netcup-production-deployment.md`

Rationale:
Unknown rationale.

Implications:

- Neue Produktionsvariablen werden in `env.production.template`, Compose und
  den betroffenen Contracts gemeinsam gepflegt.
- Dokumentation darf keinen zweiten Produktions-Env-Einstieg einführen.

## ADR-003: Portal source of truth and derived search index

Status: Confirmed

Decision:
Die Portal-SQLite-Datenbank und die zugehörigen Portaldateien unter
`kb-portal-data` sind die führende Portalquelle. Qdrant ist ein daraus
abgeleiteter Suchindex. Klassische Quellen unter `knowledgebases` bleiben ein
getrennter Bestand und eine kontrollierte Migrationsquelle.

Evidence:

- `docs/operations/data-paths.md`, Abschnitt „knowledgebases und
  Portal-Persistenz“
- `docs/operations/kb-admin-dashboard.md`, Abschnitt „Persistenz des
  Wissensportals“
- `admin-dashboard/README.md`, Abschnitt „Sicherheit“
- `stack/tests/compose_static_check.py`

Rationale:
Unknown rationale.

Implications:

- Qdrant darf nicht zur alleinigen Datenquelle für Dokumente, Metadaten oder
  Wiederherstellung werden.
- Änderungen an Portalbestand und klassischem Bestand müssen beide Pfade
  bewusst unterscheiden.

## ADR-004: Separate portal and classic Vector security models

Status: Confirmed

Decision:
Das Wissensportal verwendet die übernommene Open-WebUI-Sitzung, erlaubte
Domains, aktive Portalidentitäten, Portalrollen, getrennte Lese- und
Uploadrechte sowie ausdrückliche Bestätigungen für kritische Aktionen. Die
klassische Vector-Administration verlangt davon getrennt eine Open-WebUI-
Adminrolle und einen zusätzlichen Freigabecode.

Evidence:

- `docs/operations/kb-admin-dashboard.md`
- `docs/operations/netcup-production-deployment.md`, Abschnitt „Portal and
  Classic Vector Security“
- `stack/kb-admin-api/app/main.py`
- `stack/kb-admin-api/app/portal_governance.py`
- `stack/tests/test_production_auth_contracts.py`
- `stack/kb-admin-api/tests/test_portal_api.py`

Rationale:
Unknown rationale.

Implications:

- Portalrollen oder Portalbestätigungen ersetzen den klassischen Freigabecode
  nicht.
- Der klassische Freigabecode erteilt keine Portalrolle oder Portal-ACL.
- Änderungen müssen beide Sicherheitsmodelle getrennt testen.

## ADR-005: Isolated Python service test processes

Status: Confirmed

Decision:
Tests der eigenständigen Python-Dienste werden in getrennten Prozessen mit
deterministischem Modulpfad ausgeführt. Suiten mit jeweils eigenem Paket namens
`app` werden nicht in einem gemeinsamen pytest-Prozess kombiniert.

Evidence:

- `docs/VERIFICATION.md`, Abschnitt „Targeted Checks“
- `scripts/run-local-tests.ps1`
- `stack/tests/test_verification_harness.py`

Rationale:
Dokumentiert. Mehrere Python-Dienste besitzen ein eigenes Paket `app`. Deshalb
startet der Runner jede Suite in einem getrennten Prozess und setzt den
jeweiligen Modulpfad deterministisch.

Implications:

- Neue Service-Suiten werden als eigene Runner-Checks ergänzt.
- Ein scheinbar kürzerer gemeinsamer pytest-Aufruf ist nicht kanonisch.

## ADR-006: Compose as the current runtime integration boundary

Status: Observed

Decision:
Der aktuelle technische Aufbau integriert Open WebUI, Portal, Retrieval,
Dokumentdienste, Personio, Academy, n8n, SearxNG und Qdrant über Docker Compose,
ein gemeinsames internes Netzwerk, Dienstendpunkte, Volumes und kontrollierte
Host-Mounts.

Evidence:

- `stack/docker-compose.yml`
- `stack/docker-compose.prod.yml`
- `stack/docker-compose.local-edge.yml`
- `stack/docker-compose.kahle-ui.yml`
- `docs/operations/data-paths.md`

Rationale:
Unknown rationale.

Implications:

- Servicegrenzen, Mount-Modi, Profile und Härtung sind Teil des aktuellen
  Laufzeitvertrags.
- Dieser beobachtete Zustand belegt keine historische Entscheidung gegen andere
  Deploymentmodelle.

## ADR-007: Pinned Open WebUI overrides and generated tool bundles

Status: Confirmed

Decision:
KAHLE-spezifische Open-WebUI-Anpassungen werden gegen die gepinnte Version
`v0.11.0` als ausgewählte Read-only-Overrides eingebunden. Open-WebUI-Tools
bleiben in getrennten Quellen wartbar und werden mit
`stack/open-webui-tools/build_tools.py` in eigenständige Bundles unter `dist/`
gebaut. Der Sync-Check ist Teil von Fast und Full.

Evidence:

- `stack/.env.example`
- `stack/docker-compose.yml`
- `stack/open-webui-tools/build_tools.py`
- `stack/tests/test_kahle_open_webui_frontend.py`
- `stack/tests/test_hybrid_retrieval_security.py`
- `docs/VERIFICATION.md`

Rationale:
Dokumentiert. Die Tool-Quellen bleiben getrennt und testbar, während die in
Open WebUI verwendeten Bundles eigenständige Dateien sein müssen.

Implications:

- Ein Open-WebUI-Upgrade benötigt eine bewusste Override-, Contract-, Security-
  und Frontend-Prüfung.
- Quellen und `dist/` müssen gemeinsam aktualisiert werden; `dist/` wird nicht
  isoliert bearbeitet.

## ADR-008: Personio authority and evidence-bound employee routing

Status: Confirmed

Decision:
Personio ist die führende Quelle für aktuelle Mitarbeiter-, Rollen-, Standort-,
Kontakt-, Onboarding- und Supervisor-Daten. Reine aktuelle Verzeichnisfragen
verwenden ausschließlich `personio_directory`; fachliche Prozess- und
Zuständigkeitsfragen verwenden `rag_chat`. Benötigt eine Frage beide Arten von
Evidenz, werden die Quellen kombiniert, ohne dass RAG aktuelle
Personio-Stammdaten überschreiben darf. Führungskräfte werden ausschließlich
über stabile und eindeutig auflösbare Personio-Supervisor-IDs beantwortet.
Abteilungs-, Bereichs- und funktionale Kontaktfragen sind bewusst gemischt:
RAG belegt gemeinsame Kontaktwege, Personio liefert aktuelle individuelle
Geschäftskontakte. Eine ausdrücklich neu benannte Person in einer
Supervisor-Frage wird unabhängig von einer vorherigen Supervisor-Frage
aufgelöst; nur referenzielle Supervisor-Folgefragen übernehmen den passenden
vorherigen Personenkontext.

Evidence:

- `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py`
- `stack/open-webui-overrides/open_webui/utils/middleware.py`
- `stack/personio-directory/app/search.py`
- `stack/tests/test_kahle_knowledge_harness.py`
- `stack/tests/test_middleware_internal_rag_routing.py`
- `stack/personio-directory/tests/test_search.py`
- `docs/operations/personio-directory.md`

Rationale:
Aktuelle Personaldaten ändern sich unabhängig vom Wissensbestand. Eine feste
Quellenautorität verhindert veraltete oder halluzinierte Personenangaben und
erlaubt zugleich, aktuelle Personen mit belegtem Prozesswissen zu verbinden.

Implications:

- Neue natürliche Formulierungen werden nur als kontrollierte Varianten und
  mit Regressionstests ergänzt; eine offene semantische Personensuche ist nicht
  zulässig.
- Sichtbare RAG-Fortschrittsanzeigen erscheinen nur, wenn `rag_chat` tatsächlich
  Teil des Retrieval-Plans ist.
- Ohne eindeutige Supervisor-Evidenz wird keine Führungskraft genannt.
  Eindeutig heißt: alle Personio-Claims tragen dieselbe `personio_id`;
  gleiche Namen genügen nicht. Die Regel gilt für die Vorabsuche und für
  modellgeführte Personio-Aufrufe (Nutzerentscheidung 2026-10-07).
- Eine Person, die ein Dokument als zuständig, bearbeitend oder als
  Ansprechpartner nennt, wird nur genannt, wenn Personio in derselben Anfrage
  genau eine aktuelle Person (eine `personio_id`, nicht veraltet) mit diesem
  Namen bestätigt. Die Vorabsuche fragt dafür bis zu drei genannte Namen per
  `person_lookup` ab. Unbestätigte Aussagen fallen aus der Evidenz; nennt die
  Antwort den Namen dennoch, ist das der blockierende Verstoß
  `unconfirmed_person_name`. „Ansprechpartner für <Thema>“ ohne Personen- oder
  Einheitsbezug ist eine Dokumentenfrage (Nutzerentscheidung 2026-10-08).
- Externe Ansprechpartner sind davon ausgenommen, weil Personio nur KAHLE-Personal
  kennt. Extern ist ein Satz mit einer fremden Firma (Rechtsform ohne KAHLE,
  „Hersteller“, „extern“, „Dienstleister“, „Lieferant“, „Anbieter“) oder mit
  einer E-Mail-Adresse bzw. URL außerhalb der KAHLE-Domains. Ein externer Name
  ohne solchen Hinweis bleibt blockiert, bis das Dokument die Firma nennt.
- Dokumentierte Kontaktwege und aktuelle Personio-Kontakte werden in gemischten
  Antworten getrennt ausgewiesen. Explizit verlangte E-Mail-Adressen oder
  Telefonnummern benötigen weiterhin einen exakten freigegebenen Wert.
- Ein Kontaktwert, der wörtlich in einer belegten, redaktionellen RAG-Aussage
  der aktuellen Anfrage steht, gilt als an deren Quelle gebunden und darf mit
  dieser Quelle genannt werden (Nutzerentscheidung 2026-09-30). Aussagen, die
  eine Person benennen, sind davon ausgenommen. Personio-Kontaktfelder werden
  nur auf eine ausdrückliche Kontaktfrage genannt.
- Kein Fachthema erhält eine pauschale Enthaltung. Mahnungen und
  Kundenbeschwerden folgen derselben Prozess- und Zuständigkeitslogik wie
  andere Themen, etwa Garantieanträge (Nutzerentscheidung 2026-10-07, ersetzt
  die Abnahmeregel vom 2026-08-26).

## ADR-009: Knowledge answers are validated before delivery

Status: Confirmed

Decision:
Antworten mit Evidenz aus `rag_chat` oder `personio_directory` werden vor der
Auslieferung gegen den Antwortvertrag geprüft. Verstöße haben einen
Schweregrad: `blocking` (unter anderem unbekannte Quellen-ID, fehlendes Zitat,
ungebundener Kontakt oder Link, fehlende Pflichtabschnitte, fehlender
Geltungsbereich, von Personio nicht bestätigte Person aus einem Dokument)
oder `advisory`. Bei einem blockierenden Verstoß folgt genau
ein Korrekturaufruf ohne Tools mit derselben Evidenz und einer Zeitgrenze je
Basismodell; scheitert auch er, wird eine neutrale Enthaltung ausgeliefert.
`KAHLE_ANSWER_ENFORCEMENT` steuert das Verhalten: `observe` misst nur
(Compose- und Produktions-Default), `enforce` puffert und korrigiert.

Evidence:

- `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py`
- `stack/open-webui-overrides/open_webui/utils/middleware.py`
- `stack/docker-compose.yml`, `stack/docker-compose.local-edge.yml`,
  `stack/env.production.template`
- `stack/tests/test_kahle_harness_phase2.py`
- `docs/superpowers/plans/2026-09-30-harness-phase2-answer-enforcement.md`

Rationale:
Prompt-Regeln allein halten die Modelle nicht zuverlässig an Quellen und
Kontaktwerte. Eine deterministische Prüfung mit einem Korrekturversuch
verhindert, dass ein blockierender Verstoß den Nutzer erreicht, ohne Antworten
grundlos zu verwerfen.

Implications:

- Neue blockierende Prüfungen werden in `BLOCKING_VIOLATION_CODES` des Harness
  und in `eval/harness/harness_eval.py` gemeinsam gepflegt.
- Ein Wechsel der Produktion auf `enforce` ist eine ausdrückliche
  Freigabeentscheidung und nicht Teil einer Codeänderung.
- Die Zeitgrenzen des Korrekturaufrufs sind über
  `KAHLE_ANSWER_RETRY_TIMEOUTS` je Basismodell-Präfix einstellbar.

## ADR-010: A restrictive document scope is an evidence obligation

Status: Confirmed

Decision:
Nennt eine belegte, redaktionelle Aussage einen einschränkenden
Geltungsbereich (eine echte Teilmenge der KAHLE-Standorte), muss die Antwort
diesen Geltungsbereich nennen. Gibt es einen typisierten Funktionskontakt,
dessen Gültigkeitsfeld genau diese Standorte ausnimmt, muss die Antwort ihn als
Weg für alle anderen Fälle nennen. Die Pflicht wird bei jeder Prüfung aus der
Evidenz berechnet (`required_scope`, Verstoß `required_scope_missing`);
Enthaltungen sind ausgenommen. Die Suche liefert dafür den
Geltungsbereich-Abschnitt jedes gewählten Dokuments und den passenden
Funktionskontakt. Fest eingebaute Prozess-, Standort- oder Kontakttexte für
einzelne Dokumente sind nicht zulässig (Nutzerentscheidung 2026-10-05: Pflicht
für alle Dokumente mit einschränkendem Geltungsbereich).

Evidence:

- `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py`
- `stack/open-webui-tools/rag_chat_hybrid_tool.py`
- `stack/open-webui-tools/hybrid_retrieval.py`
- `stack/tests/test_kahle_harness_phase3c.py`
- `docs/superpowers/plans/2026-10-05-harness-phase3c-scope-evidence-and-opt-out-rollback.md`

Rationale:
Der frühere Werbewiderspruch-Sonderpfad nannte Standorte und Kontakt aus
festem Code. Die allgemeine Regel leitet beides aus den Dokumenten ab und gilt
damit auch für künftige standortgebundene Prozesse.

Implications:

- Die KAHLE-Standortliste existiert in Harness, Tool, Hybridsuche und Guard;
  Tests koppeln die Kopien. Ein neuer Standort wird in allen Kopien zugleich
  ergänzt.
- Ein Dokument mit einschränkendem Geltungsbereich braucht für den Weg „alle
  anderen Standorte“ einen typisierten Funktionskontakt mit passendem
  Gültigkeitsfeld.

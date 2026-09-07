# Führungskräfte-Konsens und strukturierte Anfrageauflösung

**Stand:** 4. September 2026

**Status:** Fachliches Design freigegeben, schriftliche Spezifikation zur Prüfung

## Ziel

KAHLE-Vinci soll die direkte Führungskraft einer eindeutig genannten Person aus
der expliziten Personio-Supervisor-Beziehung beantworten. Bei Fragen nach der
Führungskraft eines Bereichs darf Vinci die dominante Supervisor-Zuordnung
verwenden, wenn sie mindestens 90 Prozent aller gefundenen aktiven Beschäftigten
des Bereichs abdeckt.

Gleichzeitig werden die Systemprompts an den aktuellen Knowledge Harness
angepasst. Eine strukturierte Anfrageauflösung soll kurze Folgefragen in eine
eigenständige Suchanfrage überführen, ohne die ursprüngliche Nutzerfrage zu
verändern oder Fachwissen zu erfinden.

## Verbindliche Grundsätze

- Personio bleibt die einzige Quelle für aktuelle Personen, organisatorische
  Zuordnungen und Führungskräfte.
- Eine Supervisor-Aussage benötigt immer eine explizite, eindeutig auflösbare
  Personio-Supervisor-ID.
- Titel, Reihenfolge, Teamnamen, RAG-Texte und Modellwissen dürfen keine
  Führungskraft begründen.
- Der Harness löst Anfrage und Kontext auf, plant Quellen und stellt Evidenz
  bereit. Das Modell formuliert ausschließlich aus dieser Evidenz.
- Der Harness ersetzt keine fachliche Modellantwort durch eine eigene Antwort.
- Die Originalanfrage bleibt unverändert und nachvollziehbar erhalten.
- Tests und technische Ausgaben enthalten keine realen Mitarbeiterdaten.

## Führungskraft einer konkreten Person

Eine Anfrage wie „Wer ist die Führungskraft von Erika Beispiel?“ wird als
`supervisor_lookup` behandelt.

Der Personio-Dienst beantwortet sie nur, wenn:

1. der Name genau einer aktuellen Person zugeordnet werden kann;
2. diese Person eine explizite `supervisor_personio_id` besitzt;
3. diese ID genau einer aktuellen Person im freigegebenen Verzeichnisbestand
   zugeordnet werden kann.

Mehrdeutige Namen, fehlende Supervisor-Werte und nicht auflösbare IDs ergeben
keinen Supervisor-Claim. Vinci benennt dann die konkrete Wissenslücke und nutzt
weder RAG, Websuche noch Modellwissen als Ersatz.

## Führungskraft eines Bereichs

### Kandidatenmenge

Eine Bereichsfrage kann Abteilung, Team und optional einen Standort enthalten.
Der Personio-Dienst verwendet dieselbe exakte, normalisierte Bereichs- und
Standortauflösung wie die bestehende Verzeichnissuche. Berücksichtigt werden
ausschließlich Beschäftigte mit dem Status `ACTIVE`, die alle ausdrücklich
genannten Filter erfüllen.

Die Regel gilt bereits ab einer gefundenen Person. Bei genau einer Person muss
die Evidenz kenntlich machen, dass die Aussage auf einer einzigen gefundenen
Zuordnung beruht.

### 90-Prozent-Regel

Für jeden Kandidaten wird die explizite `supervisor_personio_id` betrachtet.
Der Nenner ist die Anzahl aller gefundenen aktiven Beschäftigten. Fehlende und
nicht auflösbare Supervisor-Zuordnungen bleiben im Nenner und senken damit die
Quote.

Der häufigste eindeutig auflösbare Supervisor wird genau dann als dominante
Führungskraft ausgegeben, wenn:

```text
Anzahl Beschäftigte mit dieser Supervisor-ID / Anzahl aller Kandidaten >= 0,90
```

Die Berechnung verwendet die exakten ganzzahligen Anzahlen und keine vorab
gerundeten Prozentwerte. Da eine Quote über 50 Prozent verlangt wird, kann es
keinen gültigen Gleichstand zwischen zwei Supervisoren geben.

Unterhalb der Schwelle liefert der Dienst keinen Supervisor-Claim. Die
Wissenslücke erklärt, dass für den gefundenen Bereich keine ausreichend
einheitliche Personio-Zuordnung vorliegt.

### Evidenz und Ausgabe

Der Personio-Vertrag darf bereitstellen:

- Name und freigegebene geschäftliche Daten der ermittelten Führungskraft;
- Anzahl der berücksichtigten Beschäftigten;
- Anzahl der Beschäftigten mit der dominanten Supervisor-Zuordnung;
- daraus berechnete Quote;
- den Hinweis auf eine Ein-Personen-Gruppe.

Interne Personio-IDs und die vollständige Kandidatenliste werden weder dem
Modell noch technischen Logs offengelegt. Vinci darf die Quote nennen, muss sie
aber nicht nennen, wenn die einfache Antwort dadurch klarer bleibt.

## Strukturierte Anfrageauflösung

### Verantwortung

Ein fokussiertes Harness-Modul erzeugt vor der Quellenplanung einen
`ResolvedRequest`. Es verbessert nicht den Stil des Nutzerprompts und erzeugt
keine Antwort. Es löst ausschließlich nachweisbare Bezüge aus dem aktuellen
Turn und dem unmittelbar relevanten Gesprächskontext auf.

Der Vertrag enthält mindestens:

```text
original_query
resolved_query
intent
information_needs
entities.persons
entities.organizational_units
entities.locations
entities.systems
context_references
ambiguities
required_clarification
```

`original_query` bleibt wortgleich. `resolved_query` wird nur für Routing und
Retrieval verwendet. Das Antwortmodell erhält die Originalfrage, die
aufgelösten Kontextangaben und das resultierende EvidenceBundle getrennt.

### Zulässige Kontextübernahme

Kurze Folgefragen wie „Und wie geht es dann in Hannover?“ dürfen Thema,
Dokument- oder Produktkennung und System aus der unmittelbar vorherigen
fachlich passenden Unterhaltung übernehmen. Neue ausdrückliche Angaben aus der
aktuellen Frage, beispielsweise ein anderer Standort oder ein neuer Name,
haben immer Vorrang.

Der Resolver darf:

- Pronomen und Verweise wie „dort“, „davon“, „dann“ und „das“ auflösen;
- einen bekannten Prozess oder ein bekanntes System in die Retrieval-Anfrage
  übernehmen;
- eine verkürzte Folgefrage als eigenständige Suchanfrage formulieren;
- eine notwendige Rückfrage markieren, wenn mehrere plausible Bezüge bleiben.

Der Resolver darf nicht:

- Personen, Zuständigkeiten, Kontakte oder Prozessschritte ergänzen;
- einen alten Namen übernehmen, wenn die aktuelle Frage einen neuen Namen
  enthält;
- einen fachfremden älteren Turn als Kontext verwenden;
- fehlende Personio- oder RAG-Evidenz durch Modellwissen ersetzen.

Die erste Umsetzung bleibt deterministisch und baut auf den vorhandenen
Kontext- und Anfragefunktionen auf. Ein zusätzliches Modell oder ein freier
Prompt-Rewriter ist nicht Bestandteil dieser Änderung.

## Quellenplanung und Evidenzfluss

```text
Originalfrage und unmittelbar relevanter Chatkontext
  -> ResolvedRequest
  -> Harness-Quellenplan
  -> Personio, RAG oder beide Quellen
  -> EvidenceBundle
  -> AnswerContract
  -> modellseitige Formulierung
```

Der `ResolvedRequest` ist keine Evidenz. Fachliche Aussagen dürfen nur aus dem
EvidenceBundle stammen. Bei Supervisorfragen bleibt Personio alleinige Quelle.

## Systemprompts der drei Vinci-Modelle

KAHLE-Vinci verwendet den Standardprompt. Thinking und Max Thinking verwenden
gemeinsam den Thinking-Prompt. Beide Dateien erhalten denselben Wissensvertrag.

Folgende Regeln werden entfernt:

- statische fachliche E-Mail-Adressen und Kontakte;
- pauschale Datenschutz-Weiterleitungen;
- fest formulierte fachliche Antwortblöcke ohne aktuelle Evidenz;
- Anweisungen, die eine bereits vom Harness getroffene Quellenentscheidung
  konkurrierend erneut im Modell treffen lassen.

Folgende Regeln bleiben oder werden präzisiert:

- Sicherheits-, Datenschutz-, Berechtigungs- und Prompt-Schutzregeln;
- Personio als einzige Quelle für aktuelle Personen und Führungskräfte;
- RAG als Quelle für dokumentierte Prozesse, Zuständigkeiten und
  Funktionskontakte;
- ausschließliche Antwort aus dem aktuellen EvidenceBundle;
- transparente Benennung fehlender oder widersprüchlicher Evidenz;
- Quellenangaben, wenn das EvidenceBundle Quellen liefert;
- keine Kontaktwerte, Personen oder Arbeitsschritte außerhalb der Evidenz;
- keine fachliche Ersetzung einer Modellantwort durch den technischen Guard.

Thinking und Max Thinking dürfen ausführlicher analysieren und strukturieren,
aber keine zusätzlichen internen Fakten ableiten.

## Fehler- und Grenzfälle

- Kein Bereichstreffer: keine Supervisor-Aussage.
- Ein Bereichstreffer ohne auflösbaren Supervisor: keine Supervisor-Aussage.
- Ein Bereichstreffer mit auflösbarem Supervisor: belegte Aussage mit Hinweis
  auf die einzelne zugrunde liegende Zuordnung.
- Neun von zehn Kandidaten mit demselben Supervisor: gültige Aussage.
- Acht von neun Kandidaten mit demselben Supervisor: keine Aussage, da die
  Quote unter 90 Prozent liegt.
- Neun gültige Zuordnungen und eine fehlende Zuordnung: gültige Aussage mit
  90 Prozent.
- Zwei ähnlich häufige Supervisoren: keine Aussage.
- Folgefrage mit eindeutigem Standortwechsel: vorheriges Thema behalten,
  aktuellen Standort verwenden.
- Folgefrage mit neuem Personennamen: neuen Namen verwenden, alten Namen nicht
  übernehmen.
- Mehrdeutiger Kontext: genau eine kurze Rückfrage statt einer geratenen Suche.

## Betroffene Komponenten

- `stack/personio-directory/app/search.py`
- `stack/personio-directory/app/models.py`, falls der bestehende Evidenzvertrag
  die aggregierten Zählwerte noch nicht ausdrücken kann
- `stack/personio-directory/tests/test_search.py`
- `stack/personio-directory/tests/test_api.py`
- `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py`
- ein fokussiertes Anfrageauflösungsmodul unter
  `stack/open-webui-overrides/open_webui/utils/`, sofern die vorhandene
  Middleware dadurch nicht weiter anwächst
- `stack/open-webui-overrides/open_webui/utils/middleware.py`
- `stack/tests/test_kahle_knowledge_harness.py`
- `stack/tests/test_middleware_internal_rag_routing.py`
- `stack/open-webui-prompts/kahle-vinci-systemprompt.md`
- `stack/open-webui-prompts/kahle-vinci-thinking-systemprompt.md`
- bestehende Prompt- und Akzeptanzvertragstests

Die genaue Dateigrenze für die Anfrageauflösung wird im Implementierungsplan
anhand der bestehenden Import- und Teststruktur festgelegt. Es werden keine
neuen externen Abhängigkeiten eingeführt.

## Verifikation

Die Implementierung erfolgt testgetrieben:

1. fehlende Supervisor-Konsensfälle als fehlschlagende Personio-Tests;
2. minimale 90-Prozent-Auswertung;
3. fehlschlagende Prompt-Vertragstests für statische Kontakte und konkurrierende
   Routingregeln;
4. Bereinigung beider Promptdateien;
5. fehlschlagende Tests für semantische Folgefragen und Kontextwechsel;
6. minimale strukturierte Anfrageauflösung;
7. gezielte Personio-, Harness-, Middleware- und Prompt-Tests;
8. vollständiger lokaler Verify gemäß `docs/VERIFICATION.md`;
9. erneute manuelle UI-Abnahme mit allen drei Vinci-Modellen.

## Abnahmekriterien

- Die direkte Führungskraft einer eindeutig genannten Person wird aus der
  aktuellen Personio-Supervisor-ID korrekt ausgegeben.
- Eine Bereichsführungskraft wird bei exakt 90 Prozent oder mehr ausgegeben und
  unterhalb von 90 Prozent nicht ausgegeben.
- Fehlende Supervisor-Daten zählen gegen die Quote.
- Eine Ein-Personen-Gruppe wird transparent gekennzeichnet.
- Keine Supervisor-Antwort verwendet RAG, Websuche, Titel oder Modellwissen.
- Die Mahnungsfrage erzeugt ohne belegte Zuständigkeit keinen erfundenen
  Datenschutzkontakt.
- Standortabhängige Prozesse und Kontakte stammen vollständig aus der
  gefundenen RAG-Evidenz.
- „Und wie geht es dann, wenn ich in Hannover bin?“ übernimmt den unmittelbar
  vorherigen Prozessbezug und liefert eine eigenständige Retrieval-Anfrage.
- Ein neuer Personen-, Standort- oder Themenbezug überschreibt alten Kontext.
- Standard, Thinking und Max Thinking folgen demselben Quellen- und
  Evidenzvertrag.
- Tool-Bundles sind synchron, alle erforderlichen lokalen Prüfungen bestehen.

## Nicht Bestandteil

- Änderungen an Personio-Stammdaten oder Personio-Schreibzugriffe;
- Ableitung eines Abteilungsleiters aus Stellenbezeichnungen;
- freies modellbasiertes Umschreiben aller Nutzerprompts;
- nachträgliches Ersetzen einer fachlichen Modellantwort durch einen Guard;
- Produktionsrollout, Serverumschaltung, Push oder Änderung realer Secrets.

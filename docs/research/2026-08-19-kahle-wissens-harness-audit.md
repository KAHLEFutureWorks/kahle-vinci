# Audit des KAHLE-Vinci Anfrage- und Antwortflusses

Stand: 19. August 2026

## Ergebnis

Der aktuelle Pfad besitzt bereits viele Bausteine eines Wissens-Harnesses, aber
keine eindeutige Instanz für die endgültige Antwort. Middleware, `rag_chat`,
Antwortmodell und Outlet-Guard treffen jeweils eigene fachliche Entscheidungen.
Der sichtbare Antwortwechsel entsteht konkret dadurch, dass der Guard nach dem
Antwortstream `message.content` ersetzt und die Middleware diesen neuen Inhalt
anschließend als `chat:outlet` und `chat:completion` an die Oberfläche sendet.

Der erste sichere Migrationsschritt ist deshalb ein gemeinsamer, rein
beobachtender Vertragskern in
`open_webui/utils/kahle_knowledge_harness.py`. Er erzeugt strukturierte
Zwischenzustände und vergleicht seine Evidenzentscheidung mit dem Altpfad. Er
führt keine Werkzeuge aus und verändert weder Prompt noch Antwort oder UI.

## Heutiger Datenfluss

1. Die Middleware liest Modell, Nachrichten, Nutzer und verfügbare Werkzeuge.
2. `_expanded_internal_rag_query` ergänzt ausgewählte Rückfragen und Aliase.
3. `_looks_like_internal_rag_request` und
   `_is_internal_clarification_followup` entscheiden, ob `rag_chat` erzwungen
   wird.
4. Bei einer internen Anfrage führt `chat_completion_tools_handler` vor dem
   Modell ausschließlich `rag_chat` aus. Der Abruf verwendet den übergebenen
   Nutzer und damit den berechtigungsgefilterten Retrieval-Pfad.
5. Die Middleware reduziert das Werkzeugergebnis über
   `_internal_rag_source_outcome` auf `found`, `missing`, `clarification` oder
   `guided`. Bei `missing` und `clarification` hinterlegt sie bereits einen
   direkten finalen Text.
6. Der Modelllauf erhält den Werkzeugkontext. Für interne Fragen wird der erste
   sichtbare Modelltext teilweise unterdrückt. Native Tool- und Quellenereignisse
   werden während der Werkzeugausführung erzeugt.
7. Nach Ende des Streams ruft `outlet_filter_handler` die installierten
   Outlet-Filter auf.
8. `kahle_toolcall_guard.Filter.outlet` liest Quellen und Modellantwort erneut.
   Für RAG-Fälle ersetzt er den Inhalt über `_set_message_content`:

   - `clarification`: Antwort wird durch das Feld `ANSWER` des Tools ersetzt.
   - `guided`: Antwort wird durch eine deterministische Sonderantwort ersetzt.
   - `missing`: Antwort wird durch „Dazu habe ich kein internes Wissen.“ ersetzt.
   - `found`: `_rag_answer_text` filtert den vorhandenen Text, erzeugt
     Öffnungszeiten deterministisch oder ruft mit `_synthesize_rag_answer` ein
     zweites Sprachmodell auf. Scheitert dies, wird ebenfalls „kein Wissen“
     ausgegeben.
   - Ohne RAG-Quelle kann `_needs_rag_refresh` den Abruf im Guard erneut starten.

9. Die Middleware persistiert den Outlet-Inhalt und sendet `chat:outlet` sowie
   eine neue `chat:completion`. Dadurch wird der zuvor sichtbare Text ersetzt.

## Bestandsaufnahme des Guards

### Technische Sicherheits- und Vertragsprüfungen

Diese Aufgaben gehören grundsätzlich in einen deterministischen Endvalidator:

- Entfernen sichtbarer Pseudo-Toolcalls und Reasoning-Leaks.
- Prüfung und Kanonisierung erzeugter Downloadlinks und Dateimetadaten.
- Blockieren unzulässiger oder falsch gewählter Dateiwerkzeuge.
- Prüfung von Werkzeugfehlern und sicherheitsbedingten Sperrhinweisen.
- Nutzergebundene Aufgabenlisten und administrative Ablaufhinweise.
- Schema- und Payload-Normalisierung für Werkzeugergebnisse.

Auch diese Regeln sollten langfristig strukturierte Validierungsfehler liefern,
statt beliebige fertige Texte zu erzeugen. Sie sind jedoch nicht die Ursache des
aktuellen RAG-Antworttausches.

### Freie oder fachliche Inhaltsbearbeitung

Diese Funktionen konkurrieren heute mit der eigentlichen Antwortkomponente und
müssen aus dem nachgelagerten Guard entfernt werden:

- `_synthesize_rag_answer`: zweiter LLM-Aufruf nach der fertigen Antwort.
- `_rag_answer_text`: Auswahl, Kürzung, Neusynthese und pauschale Enthaltung.
- `_retain_context_supported_answer` und `_retain_grounded_answer`: zeilenweise
  Kürzung eines bereits formulierten Textes.
- `_deterministic_opening_hours_answer`: fachliche Antworterstellung im Guard.
- `_rag_context_supports_request`: sinnvolle Evidenzregel, aber an der falschen
  Stelle. Sie gehört vor die Antwort in den EvidenceBundle-Schritt.
- `_call_rag_chat_tool` im Outlet-Pfad: nachträglicher Retrieval-Neustart.
- Die `clarification`, `guided`, `missing` und `found`-Zweige im Outlet, soweit
  sie `message.content` ersetzen.
- `_synthesize_web_answer`, `_web_answer_text` und nachträgliche Webrecherche:
  dasselbe Architekturproblem außerhalb des internen Wissenspfads.

### Gemischte Funktionen

Einige Funktionen enthalten sowohl nützliche technische Auswertung als auch
fachliche Entscheidung:

- `_extract_rag_source_outcome` liest zuverlässig ein Werkzeugergebnis, verliert
  aber durch die vier groben Zustände wesentliche Evidenzinformationen.
- `_extract_rag_clarification`, `_extract_rag_guided_response` und
  `_extract_rag_feedback_from_message` extrahieren deterministisch Daten. Die
  anschließende direkte Ersetzung der Antwort ist das Problem.
- Quellenmarkenprüfung und Quellen-ID-Abgleich sind sinnvolle Endprüfungen. Das
  Entfernen ganzer Sätze ist dagegen Inhaltsbearbeitung.

## Erster gemeinsamer Harness im Schattenbetrieb

Der neue Vertragskern enthält:

- `UserIntent`
- `ResolvedContext`
- `RetrievalPlan`
- `EvidenceBundle`
- `AnswerContract`
- `HarnessDecision`

Die Middleware ruft ihn nach dem bestehenden, berechtigungsgefilterten
`rag_chat`-Abruf für beide Vinci-Modelle auf. Das Ergebnis liegt intern unter
`metadata.kahle_knowledge_harness_shadow`. Zusätzlich wird festgehalten, ob die
alte und die neue Evidenzentscheidung fachlich übereinstimmen.

Der neue Kern unterscheidet bereits:

- `supported`
- `partially_supported`
- `unsupported`

Eine reine WPS-Systembeschreibung ist bei einer Bedienfrage damit
`partially_supported`. Eine echte Anleitung mit mehreren konkreten Handlungen
ist `supported`. Der Schattenpfad liefert ausdrücklich keinen Antworttext.

Aktiv ist der Schattenbetrieb standardmäßig. Er kann über
`KAHLE_KNOWLEDGE_HARNESS_SHADOW=false` abgeschaltet werden. Dieses Flag ändert
nur die Beobachtung, nicht den bestehenden Antwortpfad.

## Referenztests

Der neue schnelle Testpfad deckt strukturierte Verträge, WPS ohne und mit
Anleitung, Aliase, Gesprächsbezug, Kundensperren-Mehrdeutigkeit,
Berechtigungsumfang, Modellparität sowie geplante native Ereignisse ab.

Die bereits vorhandenen Tests ergänzen Personen- und Kontaktsuche, direkte und
fortgesetzte Öffnungszeiten, breite Prozessübersichten, unterschiedliche
Retrieval-Berechtigungen, Quellenanzeige, Feedbacklink und das Unterdrücken
unbelegter interner Antworten.

Reproduzierbarer Befehl:

```powershell
docker run --rm -v C:/kahle-vinci:/workspace -w /workspace `
  kahle-open-webui:v0.11.0-kahle.2 python -m pytest -q -p no:cacheprovider `
  stack/tests/test_kahle_harness_acceptance_report.py `
  stack/tests/test_kahle_knowledge_harness.py `
  stack/tests/test_kahle_harness_reference_matrix.py `
  stack/tests/test_rag_evidence_bundle_contract.py `
  stack/tests/test_kahle_toolcall_guard.py `
  stack/tests/test_middleware_internal_rag_routing.py `
  stack/tests/test_hybrid_retrieval_security.py `
  stack/tests/test_vinci_starter_prompt_contracts.py `
  stack/tests/test_kahle_open_webui_frontend.py
```

Aktueller Stand: 185 Tests bestanden in 5,80 Sekunden.

## Zweiter Implementierungsschritt: EvidenceBundle aus `rag_chat`

`rag_chat` liefert jetzt zusätzlich zum kompatiblen `FOUND`-Textformat ein
maschinenlesbares `EVIDENCE_BUNDLE_JSON` mit der Schema-Version
`kahle.evidence-bundle.v1`. Das Bundle enthält:

- `status`
- `supported_claims`
- `missing_information`
- `conflicts`
- `sources`

Die Evidenzentscheidung entsteht damit direkt am berechtigungsgefilterten
Retrieval-Ergebnis. Der Schatten-Harness übernimmt ein gültiges Bundle
unverändert. Nur bei älteren Werkzeugergebnissen ohne Bundle verwendet er die
lokale kompatible Ableitung.

Eine reine Systembeschreibung für eine prozedurale Anfrage ergibt
`partially_supported`. Eine tatsächliche Anleitung mit mehreren konkreten
Handlungen ergibt `supported`. Fehlende Treffer und notwendige Rückfragen sind
`unsupported`. Konfliktmarkierungen werden als konkrete Quellen-IDs
weitergegeben.

Quell- und Dist-Datei sind über `build_tools.py --check` synchron geprüft.

## Modellunabhängigkeit

Der Harness besitzt keine fachliche Verzweigung anhand eines Modellnamens.
KAHLE-Vinci, KAHLE-Vinci-Thinking, KAHLE-Vinci-Max-Thinking und zukünftige
Vinci-Modelle erhalten dieselbe Richtlinie `harness_policy: shared`.

Das Registrierungsprogramm erkennt künftig auch neue Modelle anhand des
KAHLE-Vinci-Namensraums. Es bindet `rag_chat`, `kahle_tasks` und
`kahle_workflow` gemeinsam an. Unbekannte zukünftige Modelle behalten dabei
ihren eigenen Systemprompt. Das Registrierungsprogramm überschreibt nur die
bereits bekannten Vinci-Prompts.

## Dritter Implementierungsschritt: Antwortvertrag vor dem Stream

Der aktive Harness erzeugt jetzt `kahle.answer-contract.v1` und ergänzt ihn vor
dem Antwortmodell als Systemkontext. Der Vertrag ist für alle Vinci-Modelle
identisch und enthält Intent, aufgelösten Kontext, EvidenceBundle und
Antwortregeln.

Der Antwortpfad unterscheidet dabei:

- `supported`: Antwort ausschließlich aus den belegten Aussagen.
- `partially_supported`: belegte Teile beantworten und fehlende Informationen
  ausdrücklich benennen.
- `unsupported`: kein allgemeines Modellwissen verwenden. Eine notwendige
  Rückfrage oder eine stabile Enthaltung wird vor dem Stream festgelegt.

Im aktiven Modus setzt die Middleware
`metadata.kahle_knowledge_harness_active`. Der Outlet-Guard erkennt damit, dass
die RAG-Antwort bereits der Antwortkomponente gehört, und verändert ihren
Inhalt nicht mehr. Pseudo-Toolcalls, Dateiverträge und andere technische
Guard-Prüfungen bleiben aktiv.

Der Rollout ist bewusst getrennt:

- Lokales Overlay: `KAHLE_KNOWLEDGE_HARNESS_MODE=active`
- Ohne explizite Variable: `shadow`
- Optionaler Not-Aus: `off`

Das neue Harness-Modul ist als eigener Read-only-Mount in OpenWebUI eingebunden.
Der lokale Container wurde mit dem aktiven Modus neu erstellt, die RAG-Tools
wurden aus den geprüften Dist-Dateien aktualisiert und OpenWebUI meldete
`healthy`.

## Lokale UI-Abnahme des aktiven Pfads

Die sichtbare Abnahme erfolgte angemeldet über den vollständigen Portalweg
`http://localhost:3004/wissen/`. Der erste Lauf machte einen veralteten,
persistiert registrierten Guard sichtbar: Das Antwortmodell hatte eine korrekte
Teilantwort erzeugt, die alte Guard-Version ersetzte sie danach durch „Dazu habe
ich kein internes Wissen.“ Nach der gezielten lokalen Aktualisierung nur der
Guard-Funktion bleibt die ursprüngliche Antwort stabil.

Die native Quellenaufbereitung übernimmt im vorgerouteten RAG-Pfad nun die
kanonischen Dokumentdaten aus `SOURCES_JSON`. Sichtbar geprüft wurden:

- Dokumentname statt der generischen Quelle `rag_chat/rag_chat`
- anklickbare kanonische Dokumentquelle
- anklickbarer Link „Wissensfehler melden“
- keine nachträgliche Antwortüberschreibung nach weiteren sechs Sekunden
- ehrliche Teilantwort ohne erfundene WPS-Schrittfolge

Die fachlich relevante Suite umfasst aktuell 185 bestandene Tests. Ein Lauf
über das gesamte Verzeichnis `stack/tests` scheiterte bereits bei der Sammlung
zweier dokumentbezogener Tests an der im OpenWebUI-Testimage nicht vorhandenen
Abhängigkeit `python-docx`; dies ist getrennt vom Harness-Ergebnis.

Die Modellparität ist im gemeinsamen Werkzeug- und Quellenpfad erreicht. Die
sichtbaren Antworten von KAHLE-Vinci und KAHLE-Vinci-Thinking zeigen jedoch
noch eine gemeinsame Vertragslücke: Bei `partially_supported` ergänzen die
Modelle teilweise unbelegte Empfehlungen, Beispiele oder Support-Verweise,
obwohl sie keine Bedienungsschritte erfinden. Eine weitere Verschärfung des
Prompts allein hat dies nicht zuverlässig verhindert.

## Vierter Implementierungsschritt: deterministischer Endvalidator

Das gemeinsame Harness-Modul stellt nun die kleine Interface
`validate_answer(answer, decision)` bereit. Der Validator verändert die Antwort
nicht. Er liefert ausschließlich `kahle.answer-validation.v1` mit dem Status
`accepted` oder `retry_required` und strukturierten Verstößen.

Deterministisch geprüft werden aktuell:

- gebundener Benutzer- und Berechtigungskontext
- verwendete Quellen-IDs gegen das EvidenceBundle
- erforderliche Quellenmarken
- offengelegte Informationslücken bei `partially_supported`
- unbelegte Beispiele
- unbelegte Ansprechpartner-, Support- und Hilfsverweise

Die Middleware hält die erste Modellantwort zurück, prüft sie und erteilt bei
Verstößen genau einen strukturierten Auftrag `kahle.answer-retry.v1` an dasselbe
Antwortmodell. Auch der Wiederholungsversuch bleibt bis zur Prüfung unsichtbar.
Wenn er erneut scheitert, verwendet die Antwortkomponente eine stabile
Teilantwort aus `missing_information`. Der Guard formuliert weiterhin keinen
Inhalt um.

Der Prüfverlauf wird als `kahle.answer-validation-run.v1` am Chatbeitrag
gespeichert. Im lokalen WPS-Test wurden zuerst ein nicht offengelegter fehlender
Anleitungsteil und ein unbelegter Hilfsverweis erkannt. Der Wiederholungsversuch
entfernte den Hilfsverweis, benannte die Lücke aber noch nicht ausreichend.
Daher erschien korrekt nur die stabile Teilantwort. Dokumentquelle,
Wissensfehler-Link und ein einzelner Quellenabschnitt blieben sichtbar.

Ein separater lokaler Lauf traf vorübergehend auf
`reranker_unavailable:http_529`. Dieser Retrieval-Fehler wurde korrekt als
`unsupported` behandelt und nicht mit einem Validatorfehler vermischt. Der
technische Fehlerpfad enthält jetzt ebenfalls den kanonischen
Wissensfehler-Link.

## Fünfter Implementierungsschritt: Referenzmatrix und messbare Folgeturns

Die Referenzfälle liegen jetzt zusätzlich in einer gemeinsamen Matrix. Sie
prüft WPS-Evidenz, Personenanfragen, Aliase, Rückfragen, Berechtigungen und
Modellparität unabhängig von einem konkreten Vinci-Modellnamen. Neben
KAHLE-Vinci und KAHLE-Vinci-Thinking sind ausdrücklich
KAHLE-Vinci-Max-Thinking sowie ein exemplarisches zukünftiges Vinci-Modell
enthalten.

Personen- und Mitarbeiterfragen erhalten den strukturierten Intent
`employee_directory`. Der aktuelle RetrievalPlan verwendet dafür weiterhin
`rag_chat`. Die geplante Personio-Anbindung wird später als serverseitiger,
read-only Retrieval-Adapter an dieser Routergrenze ergänzt. Personio soll dann
für freigegebene geschäftliche Kontakt- und Organisationsdaten die führende
Quelle sein. Es wurden bewusst noch keine Personio-Zugangsdaten, API-Aufrufe
oder nur scheinbar austauschbare Ein-Adapter-Abstraktionen eingebaut.

Dokumentierte Aliase werden nun vor Routing und Retrieval als ganze Tokens
kanonisch aufgelöst. Die Originalfrage bleibt im `ResolvedContext` erhalten.
Der lokale Zweiturn-Test
`Wie sind unsere Öffnungszeiten?` -> `TD in NIE` lieferte dadurch stabil den
Teiledienst in Nienburg, eine kanonische Nienburg-Dokumentquelle und den
Wissensfehler-Link. Derselbe Turn wurde mit `tool_called: rag_chat`, akzeptierter
Endvalidierung und 4.954 ms Laufzeit gespeichert. Damit ist auch belegt, dass
Validation und Metriken bei aktiviertem Echtzeit-Speichern nicht nur im ersten,
sondern in jedem folgenden Turn serverseitig persistiert werden.

Das neue Metrikobjekt `kahle.harness-metrics.v1` erfasst pro Antwort unter
anderem Modell, Intent, Werkzeugpfad, Evidenzstatus, Quellen, Retry, Fallback
und Laufzeit. Eine lokale Stichprobe aus sechs bereits gespeicherten Läufen
ergab 100 % korrekten Werkzeugpfad, 100 % akzeptierte Endvalidierungen,
P50 1.379 ms und P95 6.529 ms. Die Feedback-Link-Quote lag über die gemischte
Stichprobe bei 83,33 %, weil darin noch ein Lauf vor der Linkkorrektur enthalten
ist; die beiden Wiederholungstests danach enthielten den Link. Die Stichprobe
enthält bislang nur KAHLE-Vinci-Thinking und ist daher noch kein fachlicher
Modellparitätsnachweis.

## Sechster Implementierungsschritt: Kundensperre, Prozesse und Modellmessung

Der aktive Kundensperren-Test mit dem Mitarbeiter-Schulungskonto trennt die
beiden fachlich unterschiedlichen Anliegen korrekt. Auf
`Wie sperre ich einen Kunden in Vaudis?` folgt die gezielte Auswahl zwischen
Werbung/Befragungen und allgemeiner Kundensperre. Der Folgeturn `Werbung` wird
zu einer vollständigen Retrieval-Anfrage aufgelöst und erneut über `rag_chat`
geführt. Da im aktuellen Berechtigungsumfang keine einschlägige freigegebene
Evidenz gefunden wurde, erschien eine nachvollziehbare Enthaltung ohne
erfundene Vaudis-Schritte. Rückfrage und Folgeturn enthielten jeweils den
Wissensfehler-Link und eine akzeptierte Endvalidierung.

Auch die breite Frage nach dokumentierten internen Prozessen lieferte im
Mitarbeiterumfang keine freigegebene Evidenz. Vinci erzeugte daraus keine
Prozessliste aus allgemeinem Modellwissen. Der Werkzeugpfad, der gebundene
Berechtigungsumfang und die Enthaltung wurden in den Harness-Metriken
gespeichert. Die deterministischen Retrieval-Sicherheitstests prüfen weiterhin
denselben Prompt mit erlaubter und nicht erlaubter Evidenz. Ein echter
Zwei-Konten-UI-Vergleich blieb offen, weil der automatisierte Wechsel zum
separaten Führungskraft-Kennwort von der lokalen Sicherheitsprüfung nicht
freigegeben wurde.

Für Paritätsberichte speichert `kahle.harness-metrics.v1` nun zusätzlich zur
technischen OpenWebUI-ID den lesbaren `model_name`. Ein aktiver Vergleich von
KAHLE-Vinci und KAHLE-Vinci-Thinking für `Wer ist Thomas Keller?` ergab denselben
belegten fachlichen Kern, dieselbe geschäftliche E-Mail, dieselbe Dokumentquelle,
denselben Feedback-Link und jeweils eine akzeptierte Endvalidierung. Die zuletzt
gemessene KAHLE-Vinci-Laufzeit betrug 2.049 ms; der vorhandene Thinking-Lauf
6.529 ms. Aus diesen Einzelläufen darf noch keine allgemeine Latenzaussage
abgeleitet werden.

KAHLE-Vinci-Max-Thinking ist in der lokalen OpenWebUI-Modellliste noch nicht
registriert. Sein gemeinsamer Harness-Vertrag ist automatisiert abgedeckt, ein
ehrlicher UI-Paritätsnachweis ist lokal aber erst nach der Modellregistrierung
möglich. Die relevante Suite umfasst nun 185 bestandene Tests.

## Siebter Implementierungsschritt: wiederholbare Akzeptanzmatrix

Die zehn ursprünglich vereinbarten Referenzgruppen liegen nun als versionierte,
modellunabhängige Matrix in
`scripts/openwebui/kahle-harness-acceptance-matrix.json`. Personenfragen tragen
darin bereits den späteren Adapterhinweis `personio`; das heute erforderliche
Werkzeug bleibt für alle Fälle `rag_chat`.

`scripts/openwebui/kahle-harness-acceptance.py` erzeugt aus normalisierten
Harness-Läufen einen deterministischen Bericht. Er ruft selbst keine Modelle
auf, liest keine OpenWebUI-Datenbank und erfindet keine fehlenden Ergebnisse.
Damit können Browser-, API- und Containerläufe später dieselbe Auswertung
verwenden. Pro Modell und Berechtigungsprofil unterscheidet der Bericht:

- `passed`: alle Pflichtfälle vorhanden und alle technischen Verträge erfüllt
- `failed`: vorhandenes Modell mit Vertragsfehlern oder fehlenden Pflichtfällen
- `unavailable`: erwartetes Modell lokal nicht verfügbar
- `not_authorized`: Profil wurde für den Lauf nicht freigegeben

Ein vorhandener Lauf gilt nur dann als technisch akzeptiert, wenn `rag_chat`
verwendet wurde, ein Berechtigungsumfang gebunden ist, die Endvalidierung
akzeptiert wurde, der Wissensfehler-Link vorhanden ist und eine als `supported`
bewertete Antwort mindestens eine Quelle besitzt.

Die bereits real ausgeführten lokalen Läufe wurden in
`docs/research/2026-08-20-kahle-harness-local-acceptance-runs.json`
normalisiert. Der aktuelle Bericht ist bewusst noch nicht grün:

- KAHLE-Vinci/Mitarbeiter: `failed`, zwei Pflichtfälle fehlen
- KAHLE-Vinci-Thinking/Mitarbeiter: `failed`, zwei Pflichtfälle fehlen
- KAHLE-Vinci-Max-Thinking/Mitarbeiter: `unavailable`
- alle Führungskraftkombinationen: `not_authorized`

Die sechzehn zugeordneten Läufe erfüllen jeweils ihre technischen
Harness-Verträge. Über diese Stichprobe liegen P50 bei 4.954 ms und P95 bei
16.917 ms. Der Bericht
wird reproduzierbar ausgegeben mit:

```powershell
python scripts/openwebui/kahle-harness-acceptance.py `
  docs/research/2026-08-20-kahle-harness-local-acceptance-runs.json
```

Ein Exitcode ungleich null ist in diesem Zwischenstand beabsichtigt: Er bildet
die fehlende Freigabereife korrekt ab.

Der damalige WPS-Negativfall ist als ein konkretes Beispiel inzwischen mit
beiden lokalen Modellen belegt. Thinking
lieferte direkt eine akzeptierte ehrliche Teilantwort. KAHLE-Vinci benötigte den
einmaligen strukturierten Retry und anschließend den stabilen Fallback der
Antwortkomponente. Dafür unterscheidet die Metrik jetzt den letzten
Modellvalidierungsstatus vom tatsächlich ausgelieferten Zustand
`delivery_status: safe_fallback`. Ein solcher Fallback ist im Bericht zulässig,
bleibt aber über `retry_count`, `fallback_used` und den Validierungsverlauf
vollständig sichtbar.

## Achter Implementierungsschritt: Scope und negierte Anforderungen

Der aktive Vinci-Lauf für `TD in NIE` löste die Aliase korrekt auf, gab im
ersten Versuch aber zusätzlich die belegten Öffnungszeiten von Verkauf und
Service aus. Der Endvalidator erkennt deshalb nun eine allgemeine
`unrequested_scope_expansion`: Wenn genau ein bekannter Bereich angefragt ist,
darf die Antwort keine eigenen Abschnitte für andere Bereiche ergänzen. Der
Wiederholungslauf enthielt anschließend ausschließlich den Teiledienst in
Nienburg mit kanonischer Quelle und akzeptiertem Auslieferungsstatus.

Die Prozessfrage mit dem Zusatz `keine unbelegten Ablaufschritte` wurde zunächst
fälschlich als prozedurale Anleitung interpretiert. Die Intent-Auflösung entfernt
jetzt ausdrücklich verneinte Anleitungs- und Schrittwünsche, bevor sie den
prozeduralen Bedarf bestimmt. Dadurch bleibt eine Übersichtsfrage eine
Übersichtsfrage. Der anschließende reale Vinci-Wiederholungslauf fand drei
Quellen, beendete den Antwortstream jedoch auch nach mehr als zwei Minuten
nicht. Er wurde kontrolliert abgebrochen und nicht als Akzeptanzlauf gewertet;
in den OpenWebUI-Logs war kein Retrieval- oder Harnessfehler sichtbar. Dieser
Fall bleibt als separater Provider-/Timeoutbefund offen.

Die Kundensperren-Rückfrage und der Folgeturn `Werbung` sind mit Vinci
bestanden. Die konkreten VaudisX-Felder, der Bemerkungseintrag und der
Datenschutzkontakt sind in den beiden angezeigten Arbeitsanweisungen
ausdrücklich belegt. Eine allgemeine Kundensperre wurde nicht daraus abgeleitet.

## Neunter Implementierungsschritt: begrenzte Antwortstreams

Aktive Harness-Antworten besitzen jetzt eine eigene serverseitige Frist. Sie
beträgt standardmäßig 60 Sekunden und kann über
`KAHLE_ANSWER_STREAM_TIMEOUT_SECONDS` zwischen 5 und 300 Sekunden eingestellt
werden. Die Begrenzung gilt sowohl für die erste Antwort als auch für den genau
einen erlaubten strukturierten Wiederholungsversuch. Andere Modelle und
Antwortpfade außerhalb des aktiven KAHLE-Harness behalten ihr bisheriges
Streamingverhalten.

Bei einer Überschreitung beendet die Middleware den offenen Stream, führt keine
nachträgliche Guard-Umschreibung aus und liefert stattdessen die bereits vom
AnswerContract vorbereitete sichere Teilantwort. Der gespeicherte
Validierungsverlauf enthält `answer_stream_timeout`; die Metrik kennzeichnet die
Auslieferung als `safe_timeout_fallback`. Kanonische Dokumentquellen und der
Wissensfehler-Link werden anschließend weiterhin durch denselben finalen
Auslieferungspfad ergänzt.

Ein deterministischer Test mit einem absichtlich nie endenden asynchronen Stream
belegt, dass die Frist den Lauf beendet. Die vollständige relevante Suite umfasst
185 bestandene Tests. Nach dem lokalen Neustart war OpenWebUI gesund. Ein
API-Kontrolllauf mit aktiviertem Vinci-Werkzeugsatz beantwortete die zuvor
hängende Prozessfrage in 7,50 Sekunden. Dieser API-Lauf belegt die wieder
erreichbare Provider-Antwort, ersetzt aber keinen nativen UI-Akzeptanzlauf:
Der integrierte Testbrowser blockierte `localhost`, und der reduzierte API-Aufruf
enthielt nicht die Chat- und Beitragsmetadaten des OpenWebUI-Frontends. Deshalb
wurde er nicht in die Akzeptanzdatei aufgenommen.

Der anschließende Frontend-äquivalente Lauf verwendete den vollständigen
OpenWebUI-Vertrag mit Nutzerbeitrags-ID, Assistentenbeitrags-ID, Sitzungs-ID und
Vinci-Werkzeugsatz. Der serverseitig gespeicherte Beitrag belegt `rag_chat`, den
gebundenen Berechtigungsumfang, drei kanonische Dokumentquellen und den
Wissensfehler-Link. Die Evidenz war `partially_supported`; beide Modellversuche
benannten die Informationslücke nicht ausreichend. Deshalb lieferte die
Antwortkomponente korrekt ihre sichere Teilantwort aus. Die Metrik weist
`delivery_status: safe_fallback`, einen Retry und 16.917 ms Gesamtlaufzeit aus.
Dieser Lauf ist nun als Vinci-Referenzfall `process_overview` erfasst.

## Zehnter Implementierungsschritt: systemneutrale Anleitungs- und ACL-Verträge

Der Anleitungsvertrag ist jetzt ausdrücklich systemneutral. Der Audit zeigte,
dass die grundsätzliche EvidenceBundle-Architektur zwar allgemein war, die
produktive Erkennung prozeduraler Fragen aber noch `wps` und `vaudis` als
Begriffe enthielt. Diese Produktnamen wurden aus der Entscheidung entfernt.
Stattdessen erkennt der gemeinsame Harness allgemeine Anleitungswünsche,
Wie-Handlungsfragen und typische Tätigkeitsformen. Verneinte Wünsche wie
`keine Ablaufschritte` werden weiterhin vor der Intententscheidung entfernt.

Ein neuer Regressionstest verwendet das frei erfundene interne System
`FooDesk`. Eine Quelle, die nur dessen Existenz und Zweck bestätigt, führt bei
`Wie richte ich einen Vorgang ein?` zu `partially_supported` und zur offen
benannten fehlenden Anleitung. Der Test läuft zusätzlich mit einer exemplarischen
zukünftigen Vinci-Modell-ID. Die Akzeptanzfälle heißen deshalb nun
`procedure_without_guide` und `procedure_with_guide`; WPS bleibt lediglich ein
fachliches Beispiel unter mehreren. Quell- und Dist-Version des RAG-Werkzeugs
sind synchron geändert.

Der reale Berechtigungsvergleich verwendete anschließend für beide lokalen
Modelle denselben DSE-/Werbewiderspruchsprompt. Nur das Leserecht des
Mitarbeitendenkontos für `Richtlinien und Arbeitsanweisungen` war temporär
deaktiviert. Beide Mitarbeitendenläufe lieferten `unsupported`, null Quellen und
keine geschützten Ablaufschritte. Beide Führungskraftläufe lieferten `supported`
mit exakt den zwei freigegebenen Arbeitsanweisungen. Alle vier Läufe verwendeten
`rag_chat`, enthielten den gebundenen Berechtigungsumfang, eine akzeptierte
Endvalidierung und den Wissensfehler-Link. Danach wurde das Leserecht auf den
gesicherten Ausgangszustand zurückgestellt; beide Konten besitzen wieder zwei
von zwei lokalen Lesefreigaben.

Die vier Läufe sind als `permissions` erfasst. Anschließend wurde der vorhandene
vollständige DSE-/Vaudis-Prozess als systemneutraler Positivfall
`procedure_with_guide` mit beiden Mitarbeitendenmodellen ausgeführt. Beide
Antworten waren `supported`, verwendeten dieselben zwei Arbeitsanweisungen und
bestanden die Endvalidierung ohne Retry oder Fallback. Damit ist auch belegt,
dass keine künstliche WPS-Anleitung oder ein eigener WPS-Wissensbereich nötig
ist.

Der Bericht enthält nun 22 technisch gültige Läufe mit P50 6.529 ms und P95
16.917 ms. KAHLE-Vinci und KAHLE-Vinci-Thinking bestehen im Mitarbeitendenprofil
jetzt jeweils alle zehn Referenzfälle. Da das
Führungskraftprofil nun für lokale Tests freigegeben ist, zeigt der Bericht die
dort noch nicht ausgeführten Referenzfälle offen als fehlend statt als
`not_authorized`. KAHLE-Vinci-Max-Thinking bleibt für beide Profile lokal
`unavailable`. Die vollständige relevante Suite umfasst 185 bestandene Tests.

## Nächster begrenzter Schritt

Die autorisierten Führungskraft-Referenzfälle wurden anschließend vollständig
über Frontend-äquivalente Chats ausgeführt. Personenfrage, Anleitungsfälle,
Prozessübersicht, Öffnungszeiten-Rückfrage, Alias-Folgeturn und
Kundensperrenklärung bestanden mit KAHLE-Vinci und
KAHLE-Vinci-Thinking. Identische reale Läufe wurden nur dann mehreren
Referenzgruppen zugeordnet, wenn derselbe Prompt tatsächlich mehrere Verträge
belegt, beispielsweise Personensuche, Modellparität und native Quellenanzeige.

Der Akzeptanzbericht enthält nun 40 technisch gültige Zuordnungen. Beide
verfügbaren Modelle bestehen in beiden Profilen jeweils alle zehn
Referenzgruppen. P50 liegt bei 6.485 ms, P95 bei 16.917 ms. Es gibt keine
fehlgeschlagenen oder nicht autorisierten Modell-Profil-Kombinationen mehr.

Als Nächstes ist KAHLE-Vinci-Max-Thinking lokal zu registrieren und durch
dieselbe Matrix zu führen. Bis dahin bleibt dieses Modell für Mitarbeitende und
Führungskräfte ehrlich als `unavailable` ausgewiesen. Erst ein vollständig
grüner Bericht darf die Vorbereitung eines Rolloutpakets auslösen.

## Elfter Implementierungsschritt: Personio-Verzeichnis und Mehrquellenabnahme

Die bisherige Akzeptanzmatrix war noch auf den reinen Dokumentpfad begrenzt.
Selbst Personenfragen erwarteten darin `rag_chat` und verwiesen nur auf einen
späteren Personio-Adapter. Dieser Zwischenstand ist mit der produktiven
Mehrquellenplanung nicht mehr gültig. Der historische Bericht mit 40
Zuordnungen bleibt als Nachweis für den damaligen RAG-Stand erhalten, ist aber
kein Release-Nachweis für das Personio-Verzeichnis.

Die Matrix unter
`scripts/openwebui/kahle-harness-acceptance-matrix.json` beschreibt jetzt für
jeden Fall die exakte Werkzeugmenge, den erwarteten Intent, zulässige
Evidenzstatus, zulässige Quellenarten, verbotene Felder und boolesche
Prüfverträge. Reine aktuelle Stammdatenfragen erwarten ausschließlich
`personio_directory`. Reine Prozessfragen erwarten ausschließlich `rag_chat`.
Mischfragen erwarten beide Adapter. Eigene Fälle decken Verzeichnisfilter,
Onboarding-Sichtbarkeit und Feldreduktion, die drei Stufen der
Zusammenarbeitskaskade, den fehlenden Personio-Treffer ohne Rückfall, den
`pending`-Zugriff und einen veralteten Sync ab.

Die Matrix verwendet nur synthetische Testbezeichnungen. Reale Namen,
Kontaktdaten und Fragen werden ausschließlich interaktiv eingegeben. Der
erweiterte Reporter verwirft Antworttext, Fragen, Personio-IDs, Kontaktwerte und
Rohbelege auch dann, wenn ein Runner sie versehentlich mitsendet. Pro Fall
bleiben nur Fall-ID, Modell-ID, erwartete und tatsächliche Werkzeuge, Intent,
Evidenzstatus, Quellenarten, Validierungsstatus, Laufzeit und die ausdrücklich
vereinbarten booleschen Assertions erhalten. Ein reiner Verzeichnisfall mit
zusätzlichem RAG-Aufruf und eine Mischfrage mit nur einem Adapter schlagen
deterministisch fehl.

Der fokussierte Offline-Vertrag umfasst elf bestandene Reporttests. Darin ist
auch ein Negativtest enthalten, der synthetische Namen, E-Mail-Adresse,
Telefonnummer, Personio-ID und Rohbeleg in die Eingabe einstreut und nachweist,
dass keiner dieser Werte im Bericht erscheint.

Ein nachgelagerter Review hat außerdem die Matrix als einzige Vertrauensquelle
für Modelle, Profile und Pflichtfälle festgeschrieben. Externe Laufdateien
können diese drei Mengen weder ersetzen noch erweitern. Leere Laufdaten,
fehlende Modellläufe, nicht autorisierte Profile und unvollständige Fälle
führen zu einem Exitcode ungleich null. Manipulierte Namen, E-Mail-Adressen und
Kennungen in Modell-, Profil- oder Fallfeldern werden nicht in Abdeckung,
Ergebnisse oder Fehlergründe übernommen. Der Datenschutztest verwendet nun
zusätzlich eine konkrete synthetische Telefonnummer.

Ein späterer read-only Probe meldete ausschließlich den bereinigten Fehlercode
`personio_response_invalid` und machte eine Abweichung im aktuellen v2-Envelope
sichtbar. Der Client unterstützt deshalb zusätzlich `_data`,
`_meta.links.next.href` sowie `_data` für getrennte Employment-Antworten. Die
bisherigen `data`- und `links.next`-Formen bleiben kompatibel. Fremde
Cursor-Hosts, fehlerhafte Linkformen und übergroße Antworten werden weiterhin
abgewiesen; unvollständige v2-Felddaten führen zur sicheren v1-Bewertung statt
zur Ausgabe der Stichprobendaten. Die Abdeckung erfolgt ausschließlich mit
synthetischen Datensätzen; während des Fixes fand kein weiterer Live-Zugriff
statt.

Der genaue Ablauf für den read-only API-Probe, den kontrollierten lokalen Sync,
aggregierte Zustands- und Qdrant-Prüfungen sowie die 14 interaktiven Pflichtfälle
steht in `docs/operations/personio-directory.md`. Reale Credentials wurden in
diesem Implementierungsschritt weder gelesen noch verwendet. Ein erneut
erfolgreicher read-only API-Probe, Vollsync und die Abnahme unter
`http://localhost:3004` bleiben deshalb offen. Ein Produktionsrollout ist bis
zu diesem Nachweis gesperrt.

## Elfter Implementierungsschritt: Max-Parität und belastbare Abnahmeverträge

`KAHLE-Vinci-Max-Thinking` wird nun idempotent durch dasselbe lokale
Registrierungsskript bereitgestellt. Fehlen das ausgeblendete Basismodell oder
das Vinci-Modell, werden ausschließlich diese Zeilen ergänzt; vorhandene
Konfigurationen bleiben unverändert. Anschließend erhalten Vinci, Thinking,
Max-Thinking und künftige Vinci-Modell-IDs weiterhin denselben Harness-,
Werkzeug- und Berechtigungspfad. Die Registrierungs- und Berichtsfunktionen sind
durch eigene Regressionstests abgesichert.

Frontend-äquivalente Max-Läufe wurden mit dem Mitarbeitenden- und dem
Führungskraft-Schulungskonto ausgeführt. Belegt sind die allgemeine
Anleitungsenthaltung am fiktiven System FooDesk, Personeninformationen,
Prozessübersicht, die Gesprächsauflösung `TD in NIE`, Öffnungszeiten in
Nienburg sowie die Unterscheidung der Werbe-/Befragungssperre von einer
allgemeinen Kundensperre. Der vorhandene DSE-/Vaudis-Folgeturn liefert dabei
den systemneutralen Positivfall für eine ausreichend dokumentierte Anleitung;
es existiert weiterhin keine WPS-Sonderlogik.

Für den Max-Berechtigungsvergleich wurde das Leserecht des
Mitarbeitendenkontos für `Richtlinien und Arbeitsanweisungen` nur während eines
einzelnen Laufs deaktiviert. Der Lauf lieferte `unsupported`, null Quellen und
keine geschützten Schritte. Der gleichwertige Führungskraftlauf lieferte die
zwei freigegebenen Arbeitsanweisungen. Der gesicherte Ausgangszustand
`can_read=1, can_upload=1` wurde im `finally`-Pfad wiederhergestellt und danach
erneut aus der Datenbank gelesen.

Ein Max-Prozesslauf deckte außerdem eine alte konkurrierende Zuständigkeit auf:
Der Modellprompt verlangte selbst die Ausgabe des Feedback-Links, obwohl der
gemeinsame Harness den kanonischen Link bereits deterministisch ausliefert.
Diese Prompt-Anweisung ist für Vinci und Thinking entfernt und wirkt über die
gemeinsame Modellregistrierung auch für Max. Die Endprüfung erkennt zusätzlich
ausformulierte Feedback-Link-Platzhalter, schreibt sie nicht um und sendet
stattdessen einen strukturierten Wiederholungsauftrag. Ein realer Wiederholungslauf
belegt zwei Validierungsversuche, einen Retry, akzeptierte Auslieferung,
kanonische Dokumentquellen und keinen Link-Platzhalter.

Der Akzeptanzreport verlangt nun pro Referenzfall explizite fachliche
Assertion-Ergebnisse und prüft Evidenzstatus, Intent sowie Modellparität für
Evidenzstatus, fachlichen Kern und Quellen-IDs. Fehlende manuelle Aussagen
werden dadurch nicht mehr still als bestanden gewertet. Offen bleibt bewusst
nur die visuelle Portalabnahme unter `http://localhost:3004/wissen/`: native
`rag_chat`-Animation, sichtbare Dokumentquellen, genau ein funktionierender
Wissensfehler-Link und kein nachträglicher Antwortwechsel. Vor dieser Abnahme
wird kein Produktionspaket freigegeben.

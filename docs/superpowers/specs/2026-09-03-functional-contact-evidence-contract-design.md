# Freigegebene Funktionskontakte als strukturierte RAG-Evidenz

Stand: 3. September 2026

Status: Fachlicher Vertrag im Gespräch freigegeben; schriftliche Fassung zur
abschließenden Durchsicht. Noch nicht implementiert.

## 1. Zweck und Einordnung

Diese Spezifikation ergänzt
[Modellgeführtes Quellenrouting](2026-09-01-model-led-knowledge-routing-design.md).
Sie ersetzt ausschließlich die bisher versuchte heuristische Entscheidung,
ob ein Kontaktwert aus RAG einer Person oder einer Funktion gehört.
Der ursprüngliche Release-A-Auftrag umfasst weiterhin Tasks 1–9. Task 10,
Push, Merge und Produktionsaktivierung bleiben ohne gesonderte Freigabe außen vor.

Die Nutzerentscheidungen sind:

- Funktionskontakte werden in einem festen Tabellenformat im bestehenden
  Wissensdokument gepflegt und durchlaufen die vorhandene Dokumentfreigabe.
- Eine zweite Kontaktverwaltung und eine neue Pflegeoberfläche sind nicht nötig.
- Persönliche Kontakte kommen ausschließlich aus Personio.
- Das Modell wählt Werkzeuge und formuliert die Antwort weiterhin selbst.
- Noch nicht übertragene Kontakte aus Fließtext werden vorübergehend nicht als
  Funktionskontakte ausgegeben. Normales Prozesswissen bleibt nutzbar.

## 2. Ursache und gewählter Ansatz

Der aktuelle RAG-Produzent erzeugt Claims aus Textpassagen und leitet
`claim_type` aus dokumentweiten `evidence_capabilities` ab. Der Harness sammelt
Kontaktliterale aus `text` und `evidence_span`. Das Vorkommen einer Adresse
belegt jedoch weder ihren Funktionscharakter noch ihren Verwendungszweck.
Namens-, Wortstamm- und Satzgrenzenheuristiken haben wiederholt individuelle
Kontakte zugelassen und legitime Funktionskontakte verworfen.

Gewählt wird deshalb ein ausdrücklich gepflegter und freigegebener
Kontaktvertrag. KI-Extraktion mit menschlicher Bestätigung bleibt eine mögliche
spätere Pflegehilfe, gehört aber nicht zu dieser Änderung. Vollautomatische
semantische Zuordnung im Chat ist keine Freigabequelle.

## 3. Redaktionelles Format

Ein Abschnitt mit der exakten Überschrift `Funktionskontakte` enthält eine
Markdown-Tabelle mit diesen fünf Spalten:

| Funktion | Kontaktart | Kontaktwert | Verwendungszweck | Geltungsbereich |
| --- | --- | --- | --- | --- |
| Marketing | E-Mail | marketing@example.invalid | Anfragen an das Marketing | gruppenweit |
| IT-Support | Kontaktseite | https://support.example.invalid/tickets | Technische Störungen melden | gruppenweit |

Alle fünf Zellen sind Pflichtfelder. Kontaktarten sind exakt `E-Mail`,
`Telefon` und `Kontaktseite`. Eine Zeile enthält genau einen Kontaktwert.
Eine Funktion darf mehrere Zeilen für unterschiedliche Kontaktarten,
Verwendungszwecke oder Geltungsbereiche besitzen.

Die Überschriftenebene ist unerheblich; der Abschnittstitel und die Spaltennamen
sind kontrollierte Formatwerte, keine vom Modell ergänzten Synonyme. Äußere
Leerzeichen werden entfernt. Innerhalb der Zellen wird kein Wert geraten,
ergänzt, aus einem Linktitel gewonnen oder aus einer Fortsetzungszeile repariert.
Codeblöcke, Beispielanfragen und Suchhilfeabschnitte sind keine Kontaktquellen.

Der Kontaktwert steht als einfacher Text in der Zelle, nicht als Markdown-Link
oder HTML. E-Mail und Telefon werden mit zentralen syntaktischen Prüfungen
validiert. Kontaktseiten müssen absolute HTTPS-URLs ohne Zugangsdaten sein;
sie werden durch diese Funktion weder aufgerufen noch auf Erreichbarkeit geprüft.
Die syntaktische Gültigkeit einer URL ist kein Nachweis ihrer Vertrauenswürdigkeit.

Die fachlich Verantwortlichen bestätigen bei der bestehenden Dokumentfreigabe,
dass die Einträge gemeinsame Funktionskontakte sind und Zweck sowie
Geltungsbereich stimmen. Die Software kann diese fachliche Wahrheit nicht
aus dem Format oder der Schreibweise der Adresse beweisen.

## 4. Freigabe, Rechte und führender Bestand

Die Tabelle ist Bestandteil der Originalquelle und ihrer veröffentlichten
Version. Sie erhält keinen eigenen Freigabestatus und keine eigene ACL.
Eine Tabellenüberschrift allein umgeht niemals Dokumentfreigabe oder Rechte.

Für Portalquellen gelten die vorhandenen aktiven Versionen, Veröffentlichungen,
Gültigkeitszeiträume und Wissensbereichsrechte. Für klassische Quellen gelten
weiterhin deren eigene kanonischen Freigabe- und Gültigkeitsprüfungen.
Die beiden Bestände werden nicht zusammengeführt. Nicht kanonische Quellen
werden durch das neue Format nicht nachträglich vertrauenswürdig.

Qdrant und BM25 bleiben abgeleitete Indizes. Änderungen werden am Dokument
vorgenommen, nicht an einem separat gepflegten Kontaktbestand.

## 5. Verarbeitung und Interface

Der vorhandene Indexierungsweg erkennt das Format deterministisch im
kanonischen Markdown. Eine gültige Tabellenzeile wird als zusammengehöriger
Datensatz mit Dokument-, Versions- und Zeilenbezug verarbeitet. Überlange oder
unvollständige Zeilen dürfen nicht durch das normale Chunk-Splitting zu
scheinbar gültigen Teilkontakten werden; sie liefern keinen Kontakt-Claim.

Die Implementierung verwendet eine zentrale Formatdefinition und einen
testbaren Parser am vorhandenen Markdown-/Indexierungsübergang. Kein eigener
HTTP-Dienst, kein LLM-Aufruf und kein neues führendes Datenmodell sind nötig.
Die genaue Dateiaufteilung wird im anschließenden Umsetzungsplan festgelegt.

Der RAG-Evidenzvertrag wird um den typisierten Claim `functional_contact`
erweitert. Sein fachlicher Inhalt umfasst:

- Funktion, Kontaktart, exakter Kontaktwert, Verwendungszweck und Geltungsbereich;
- die vorhandenen `claim_id`, `source_id`, `document_id` und `version_id`;
- einen eindeutigen Bezug zur vollständigen Ursprungszeile.

Die technischen JSON-Schlüssel werden einmalig kanonisch festgelegt und auf
Produzenten- und Konsumentenseite identisch geprüft. Alias-Schlüssel,
Kollisionen, unbekannte Felder und unpassende Datentypen werden nicht nachträglich
normalisiert. Der neue Claim darf nicht bloß durch ein vom Modell gesetztes
`claim_type` oder die dokumentweite Fähigkeit `contact_details` entstehen.
Er muss aus dem kontrollierten Tabellenparser im bestehenden RAG-Werkzeugpfad
stammen. Direkte EvidenceBundle-Eingänge dürfen die gleichen Prüfungen nicht umgehen.

Retrieval prüft Rechte, aktive Version und Gültigkeit vor der Verwendung.
Die Kontaktzeile bleibt bei Suche und Weitergabe mit ihrem Zweck und
Geltungsbereich verbunden. Suchhilfen dürfen zur Dokumentfindung beitragen,
aber nie selbst als Kontaktbeleg dienen. Ein Titelgleichstand begründet keinen
Zugriff auf ein anderes Dokument.

## 6. Harness und Antwortvertrag

Für den modellgeführten Pfad gilt:

1. Individuelle erlaubte Kontaktwerte entstehen nur aus validierten
   Personio-Kontaktfeldern.
2. Funktionale erlaubte Kontaktwerte entstehen nur aus validierten
   `functional_contact`-Claims.
3. Das Scannen generischer RAG-Claims nach E-Mail- oder Telefonliteralen
   erzeugt keine Kontaktfreigabe mehr. Das gilt auch für `evidence_span` und
   eingebettete Adressen in URLs.
4. Der AnswerContract transportiert vollständige Kontaktzuordnungen, nicht
   nur eine lose Liste erlaubter Adressen. Das Modell darf Funktion, Zweck
   und Geltungsbereich verschiedener Zeilen nicht vermischen.
5. Quellen-, Claim-ID-, Kontaktliteral-, Status- und Datenschutzprüfungen
   bleiben bestehen. Die Bereinigung darf Unterstützung nie aufwerten.

Prozesswissen bleibt RAG-Evidenz, auch wenn ein Dokument einen nicht freigegebenen
Kontakt im Fließtext enthält. Die Antwort darf den Prozess beschreiben, den
unfreigegebenen Kontaktwert aber nicht als Kontakt ausgeben. Dafür ist die
geplante Prüfung vor sichtbarer Ausgabe aus Task 7 erforderlich; ein Prompt
allein ist kein ausreichendes Gate. Quellenlinks und Feedbacklinks behalten
ihre separate technische Zulassung und begründen keine Kontaktfreigabe.

Die Zeilenbindung verhindert insbesondere das Vermischen strukturierter
Felder. Die semantische Richtigkeit beliebiger frei formulierter Antworten
lässt sich damit nicht vollständig deterministisch beweisen. Sie bleibt Teil
von Modellauftrag und Abnahmetests; der Entwurf behauptet keine allgemeine
Sprachverständnis- oder Personenklassifikationsgarantie.

Die Heuristiken, die ausschließlich RAG-Kontakte als persönlich oder funktional
klassifizieren sollen, werden im modellgeführten Pfad durch diesen Vertrag
ersetzt. Unabhängige Prüfungen für Personenfelder und Supervisor-Evidenz werden
nicht pauschal entfernt. Eine Tabelle legitimiert niemals eine aktuelle
Personen- oder Führungskräfteaussage aus RAG.

## 7. Fehler und Konflikte

- Fehlende oder ungültige Tabellenstruktur: kein Kontakt aus diesem Block.
- Ungültige Einzelzeile: kein Kontakt aus dieser Zeile; unabhängig gültige
  Zeilen und normales Prozesswissen bleiben verwendbar.
- Exakte Duplikate dürfen ohne Informationsverlust zusammengeführt werden.
- Unterschiedliche Werte für dieselbe Funktion, Kontaktart, denselben Zweck
  und Geltungsbereich werden als Konflikt behandelt, nicht durch Auswahl des
  ersten Treffers aufgelöst. Redaktionell beabsichtigte Alternativen müssen
  durch unterschiedliche Zwecke oder Geltungsbereiche erkennbar sein.
- Fehlende Rechte, abgelaufene oder ersetzte Version: keine Kontaktfreigabe
  aus der betroffenen Quelle, auch nicht aus einem alten Indexeintrag.
- Kein freigegebener Kontakt: begrenzte Auskunft über die fehlende Evidenz,
  kein Ersatz durch Personio-Einzelkontakt, Websuche oder Modellwissen.

Diagnosen verwenden Fehlercodes, Quellenreferenzen im berechtigten Kontext
und Summenzahlen. Technische Logs und Testberichte enthalten keine realen
Kontaktwerte, Namen, Dokumentpassagen oder Secrets.

## 8. Migration und Abnahme

Die Implementierung liefert eine kopierbare leere Vorlage mit Anleitung.
Reale Kontaktquellen werden nicht automatisch umgeschrieben oder veröffentlicht.
Ihre einmalige redaktionelle Übertragung bleibt Aufgabe der Verantwortlichen.
Bis zur Übertragung nennt Vinci daraus keine Funktionskontakte.

Nach Anpassung des Indexformats ist eine kontrollierte Neuindexierung nötig.
Alte Payloads ohne typisierte Kontakte werden nicht heuristisch aufgewertet.
Der Produktionsdefault bleibt für Release A `legacy`; die neue Regel gilt
im lokal zu prüfenden `model_led`-Pfad. Ein Rückfall auf `legacy` bedeutet auch
Rückfall auf dessen bisherige Kontaktlogik, nicht Fortbestand dieser neuen Garantie.

Pflichttests verwenden ausschließlich synthetische Personen und reservierte Werte:

- gültige Tabelle für E-Mail, Telefon und Kontaktseite samt vollständiger Zuordnung;
- fehlerhafte Header, fehlende Zellen, ungültige Werte, Code-/Suchhilfeblöcke,
  überlange Zeilen, Dubletten und widersprüchliche Einträge;
- Rechte, Version und Gültigkeit einschließlich veralteter Indexeinträge;
- keine Kontaktfreigabe aus Fließtext, Evidence-Span oder grober Dokumentfähigkeit;
- keine Alias-, Collision-, ID- oder direkten EvidenceBundle-Bypässe;
- Erhalt gültiger Prozessbelege und gültiger Funktionskontakte unabhängig
  von vermeintlichen Personennamen oder Wörtern wie Fuhrpark und Leitfaden;
- keine Vermischung von Funktion, Zweck, Geltungsbereich und Kontaktwert;
- Personio-not-found erzeugt weder RAG-Personenersatz noch Web-Fallback;
- ungültige Kontaktantwort vor Sichtbarkeit abgefangen, inklusive Task-7-Retry;
- Quell-/Bundle-Sync, isolierte Dienstsuiten, Full Verify, Modellmatrix und UI-Abnahme.

Die wiederholt fehlgeschlagenen Kontaktklassifikations-Tests werden anhand des
neuen Vertrags überarbeitet, nicht stillschweigend übersprungen. Tests für
unabhängige Sicherheitsinvarianten bleiben erhalten.

## 9. Fortsetzung des laufenden Plans

Der pausierte Stand liegt auf `0cb5ff0` mit uncommitteten Änderungen an Harness
und Tests. Der strukturierte Vertragsfix besitzt nur fokussierte GREEN-Evidenz;
die vollständige Task-5-Suite und Full Verify dieses Zwischenstands fehlen.
Dieser Stand wird bewahrt und im Umsetzungsplan ausdrücklich eingeordnet.

Der neue Plan ergänzt den Kontaktvertrag zwischen Indexierung, RAG-Produzent,
Harness und Task-7-Validierung und passt die betroffenen Abnahmekriterien an.
Es wird keine weitere Wortlisten-Fixrunde unter unverändertem Vertrag gestartet.
Tasks 1–4 werden nicht wiederholt. Task 5 bleibt bis zur Abnahme des angepassten
Vertrags offen; Task 6–9 werden in einer ausdrücklich beschriebenen
Abhängigkeitsreihenfolge fortgesetzt.

## 10. Repository-Evidence

- `stack/kb-sync/app/canonical_inventory.py`: getrennte klassische und
  Portal-Inventare; Portalversionen und Veröffentlichungen.
- `stack/kb-sync/app/hybrid_index.py`: Markdown-Abschnitte, Tabellenzeilen und
  bestehendes Chunk-Splitting.
- `stack/kb-sync/app/hybrid_sync.py`: abgeleitete Payloads und Indexierung.
- `stack/open-webui-tools/rag_chat_hybrid_tool.py`: RAG-Claim-Produktion.
- `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py`:
  Claim-Prüfung, Kontaktwerte und AnswerContract.
- `stack/open-webui-overrides/open_webui/utils/kahle_internal_knowledge.py`:
  request-lokale tatsächliche Werkzeugergebnisse.
- `docs/VERIFICATION.md`: verbindliche lokale Verification.

Diese Evidence belegt den lokalen Aufbau, keinen produktiven Rollout.

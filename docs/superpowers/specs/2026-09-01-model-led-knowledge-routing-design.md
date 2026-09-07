# Modellgeführtes Quellenrouting für KAHLE-Vinci

**Stand:** 1. September 2026

**Status:** Architekturgrundsatz fachlich freigegeben, Umsetzung geplant

## Ziel

KAHLE-Vinci soll natürliche interne Fragen nicht mehr über eine stetig wachsende
Sammlung von Formulierungsregeln im Knowledge Harness auf Personio, RAG oder
beide Quellen verteilen. Das ausgewählte Vinci-Modell entscheidet anhand klar
beschriebener, nativ sichtbarer Werkzeuge, welche Evidenz es benötigt. Der
Harness bleibt als serverseitiger Sicherheits- und Evidenzrahmen erhalten, darf
aber keine fachliche Antwort mehr vorformulieren oder eine fertige Antwort
inhaltlich ersetzen.

Der freigegebene Quellenmaßstab lautet:

- aktuelle Personen ausschließlich aus `personio_directory`;
- Funktionspostfächer und dokumentierte Kontaktwege ausschließlich aus
  `rag_chat`;
- Kombination nur bei einem tatsächlichen Bedarf an beiden Evidenzarten.

## Beobachtete Ursache der aktuellen Fehler

Der heutige Pfad verteilt dieselbe fachliche Entscheidung auf mehrere Stellen:

1. `kahle_knowledge_harness.py` klassifiziert Formulierungen über zahlreiche
   reguläre Ausdrücke und plant die Quellen vorab.
2. `middleware.py` führt diesen Plan aus, blendet andere native Tools teilweise
   aus und kann einen fertigen Harness-Text als direkte Antwort festlegen.
3. `rag_chat_hybrid_tool.py` reduziert Treffer über eine satzbasierte
   Überschneidungsheuristik auf Claims.
4. Das Antwortmodell formuliert zusätzlich aus dem übergebenen Kontext.
5. Die Endvalidierung läuft erst nach dem Stream und dokumentiert Verstöße,
   korrigiert sie aber nicht vor der sichtbaren Ausgabe.

Dadurch kann eine einzelne ungenaue Vorentscheidung nicht mehr vom Modell
korrigiert werden. Gleichzeitig können Suchhilfen wie „Für Fragen wie …“ oder
ein Dokument-Kurzindex fälschlich als Antwortbeleg erscheinen. Die zuletzt
ergänzten Kontaktregeln verschärfen dieses Problem: Sie verbessern exakt
getestete Sätze, erhöhen aber die Abhängigkeit von Wortlisten und
Sonderbehandlungen.

## Zielarchitektur

```text
Nutzerfrage und zulässiger Gesprächskontext
  -> verfügbare native Tools mit klar getrennter Quellenhoheit
  -> Modell wählt Personio, RAG, beide oder kein internes Wissens-Tool
  -> bestehende OpenWebUI-Toolschleife führt nur die gewählten Tools aus
  -> request-lokaler Evidence-Recorder normalisiert die tatsächlichen Ergebnisse
  -> Harness erzeugt EvidenceBundle und AnswerContract
  -> Modell formuliert die Antwort aus dem Evidenzvertrag
  -> Antwort wird vor Sichtbarkeit deterministisch validiert
       -> gültig: einmalig ausgeben
       -> ungültig: genau ein modellseitiger Korrekturversuch
       -> erneut ungültig: stabile, fachlich neutrale Enthaltung
```

Das Modell entscheidet über die semantische Werkzeugwahl. Der Harness bindet
Berechtigungen, führt Werkzeuge aus, normalisiert Evidenz, erzwingt
Quellenhoheit, validiert Quellen- und Kontaktwerte und begrenzt Wiederholungen.

## Quellen- und Werkzeugvertrag

| Informationsbedarf | Zulässige Quelle | Unzulässig |
| --- | --- | --- |
| aktuelle Person, Profil, geschäftliche Einzelkontakte | Personio | RAG oder Web als Ersatz |
| aktuelle Rollen-, Team-, Abteilungs- oder Standortliste | Personio | RAG-Personenlisten |
| aktuelle Onboarding-Personen | Personio | RAG |
| Führungskraft | Personio mit eindeutig auflösbarer Supervisor-ID | Titel, Reihenfolge, Team, RAG oder Modellwissen |
| Funktionspostfach, Ticketsystem, Einreichungs- oder Kontaktweg | RAG | Personio-Einzelkontakt als Ersatz |
| dokumentierter Prozess, Arbeitsanweisung oder Zuständigkeit | RAG | aktuelle Person aus altem Dokument ableiten |
| ausdrücklich aktuelle Person plus dokumentierter Prozess oder Kontaktweg | Personio und RAG | Zusammenführen nicht belegter Beziehungen |
| externe aktuelle Information | freigegebene Websuche | Websuche für fehlende interne Personen- oder Supervisor-Daten |

Bei mehrdeutigen Kurzfragen wie „Wie erreiche ich Marketing?“ darf das Modell
RAG allein oder beide internen Quellen wählen, sofern die sichtbare Antwort nur
die tatsächlich belegten Teile enthält. Die automatisierte Abnahme prüft hier
Mindest- und Höchstmenge zulässiger Tools statt eine einzige erzwungene
Toolkombination. Eindeutige Kontrollfälle bleiben strikt:

- „Wer arbeitet im Marketing?“ -> nur Personio.
- „Wie lautet das Funktionspostfach des Marketings?“ -> nur RAG.
- „Wie lautet das Funktionspostfach und wer arbeitet aktuell im Marketing?“ ->
  Personio und RAG.

## Modell-sichtbares Personio-Tool

Personio wird nicht als zweites, in der OpenWebUI-Datenbank gespeichertes
Python-Tool implementiert. Das würde den vorhandenen internen HTTP-Client, die
Antwortvalidierung und den Secret-Zugriff duplizieren.

Stattdessen erzeugt ein kleines tiefes Modul im OpenWebUI-Override für jede
zulässige Anfrage einen normalen Tool-Eintrag im bereits verwendeten Format:

```python
{
    "spec": {"name": "personio_directory", ...},
    "callable": bound_personio_search,
    "type": "kahle_internal",
    "direct": False,
}
```

Das Tool ist nur für allgemeine KAHLE-Vinci-Modelle und OpenWebUI-Rollen
`user` oder `admin` sichtbar. Die Toolparameter enthalten ausschließlich die
unveränderte natürliche `query`. Das Modell darf keinen Personio-Intent, keine
Personio-ID, keine Berechtigungsrolle und keinen Supervisor-Kandidaten setzen.

Der private Personio-Endpunkt erhält dafür den internen Intent `auto`. Der
Personio-Dienst klassifiziert nur seine eigenen begrenzten Suchformen
(`person_lookup`, `directory_search`, `coworker_lookup`, `onboarding_search`,
`supervisor_lookup`). Diese adapterlokale Interpretation bleibt notwendig; sie
entscheidet nicht mehr, ob Personio oder RAG benutzt wird.

Die API antwortet zusätzlich mit `resolved_intent`. Der OpenWebUI-Client prüft
damit weiterhin feldgenau, dass Onboarding-Ergebnisse nur die dafür erlaubten
Felder enthalten. Rohantworten, Personio-IDs, Namen und Kontaktwerte bleiben aus
technischen Logs entfernt.

## Supervisor-Folgekontext

Die bereits sicherheitsrelevante Supervisor-Regel bleibt erhalten, wird aber
aus dem allgemeinen Routing herausgelöst:

- Ein ausdrücklich genannter vollständiger Name wird immer aus der aktuellen
  Frage aufgelöst.
- Nur eine referenzielle Supervisor-Folgefrage ohne neuen Namen darf den
  unmittelbar passenden vorherigen Nutzerkontext als privaten
  `candidate_query` erhalten.
- Diese Kontextübernahme findet ausschließlich beim Personio-Tool statt.
- Andere Personen-, Rollen-, Kontakt- oder Prozessfragen übernehmen dadurch
  keinen vorherigen Kontext.
- Ohne eindeutige Supervisor-ID bleibt die Antwort geschlossen.

## Request-lokaler Evidenzrahmen

Ein neues Modul
`stack/open-webui-overrides/open_webui/utils/kahle_internal_knowledge.py`
bildet die tiefe Schnittstelle zwischen nativer Toolschleife und Harness. Es
übernimmt vier Aufgaben:

1. das modell-sichtbare Personio-Tool sicher binden;
2. die vorhandene `rag_chat`-Callable ohne Änderung ihrer Berechtigungen
   request-lokal um einen Ergebnis-Recorder wickeln;
3. ausschließlich tatsächlich aufgerufene interne Tools und ihre validierten
   Ergebnisse in den bestehenden EvidenceBundle-Vertrag überführen;
4. vor dem nächsten Modellschritt einen AnswerContract aus der aktuellen
   Evidenz erzeugen.

Das Modul trifft keine fachliche Antwortentscheidung und besitzt keine
Abteilungs-, Rollen- oder Formulierungswortlisten. Die Werkzeugnamen,
Berechtigungsrollen, maximalen Wiederholungen und erlaubten Quellenarten sind
kontrollierte technische Werte.

## Rolle des Knowledge Harness

Folgende Teile bleiben erhalten:

- `EvidenceBundle` und die Parser für validierte Personio- und RAG-Ergebnisse;
- Quellen-ID- und Claim-ID-Prüfung;
- Berechtigungsumfang und Datenschutzregeln;
- Quellenhoheit: Personio vor RAG bei aktuellen Personenfeldern;
- exakte erlaubte Kontaktwerte aus der aktuellen Evidenz;
- Konflikt-, Teilbeleg- und Fail-closed-Status;
- `AnswerContract`, `AnswerValidation` und der begrenzte Korrekturauftrag;
- datensparsame technische Metriken.

Folgende Verantwortlichkeiten entfallen nach erfolgreicher Migration:

- semantische Vorabklassifikation der Nutzerfrage in Personio, RAG oder beide;
- Abteilungs- und Kontaktwortlisten für die globale Werkzeugwahl;
- `_organization_contact_answer()` und andere fachliche Direktantworten;
- vorab erzwungene Toolaufrufe aufgrund eines Harness-RegEx-Treffers;
- das Ausblenden von RAG oder Websuche allein aufgrund eines vorab geratenen
  Personio-only-Plans;
- der native RAG-Fallback, der eine fertige direkte Antwort verwirft und
  nachträglich RAG erzwingt.

`kahle_direct_final_content` bleibt als allgemeine technische
Middleware-Funktion bestehen, weil Datei-, Formular- und Mailflüsse sie
weiterhin verwenden. Entfernt werden nur die Knowledge-Harness-Schreibstellen.

## RAG: Suchhilfe ist kein Antwortbeleg

Die Kontaktquelle „Wichtige Funktionspostfächer und Kontakte“ zeigt ein
allgemeines Indexproblem: Beispielanfragen und Kurzindizes sollen die Suche
verbessern, dürfen aber nicht als Evidenz ausgegeben werden.

Der Markdown-Chunker kennzeichnet deshalb Abschnitte unter kontrollierten
Überschriften wie „Für Fragen wie“, „Beispielanfragen“, „Suchbegriffe“,
„Synonyme“ oder „Kurzindex“ als `retrieval_hint`.

- Hint-Chunks bleiben für die erste hybride Dokumentfindung indexiert.
- Ein Hint-Treffer erweitert die Kandidaten um antwortbare Chunks desselben
  bereits ACL-geprüften Dokuments.
- Vor Reranking, EvidenceBundle und Modellkontext werden Hint-Chunks entfernt.
- Ein Dokument ohne passenden antwortbaren Chunk liefert keinen Claim.
- `_claim_evidence_spans()` darf bei null inhaltlicher Überschneidung nicht
  mehr auf den ersten Satz eines Abschnitts zurückfallen.

Die dokumentweite Fähigkeit `contact_details` bleibt als grober Kandidatenfilter
erhalten. Sie ist allein kein Beleg für einen konkreten Kontaktwert oder eine
bestimmte Funktion.

Diese Änderung erfordert eine kontrollierte Neuindexierung, verändert aber
weder Originaldokumente noch Portalversionen oder Freigaben.

## Antwortvalidierung vor der sichtbaren Ausgabe

Bei einem Turn mit tatsächlich aufgerufenem internen Wissens-Tool wird nur der
finale Antworttext gepuffert. Toolstatus und Quellenereignisse dürfen weiter
sichtbar laufen. Vor der ersten Textausgabe prüft `validate_answer()`:

- stammen zitierte Quellen-IDs aus dem aktuellen EvidenceBundle;
- stehen ausgegebene Kontaktwerte wortgleich in der aktuellen Evidenz;
- werden fehlende oder widersprüchliche Belege korrekt offengelegt;
- bleibt eine Supervisor-Aussage an Personio-Evidenz gebunden;
- wurden Berechtigungs- und Datenschutzregeln eingehalten.

Bei einem Verstoß erhält dasselbe Antwortmodell genau einmal
`AnswerValidation.retry_prompt()` zusammen mit demselben EvidenceBundle. Im
Korrekturlauf sind keine neuen Wissens- oder Webtools verfügbar. Scheitert auch
dieser Lauf oder überschreitet er das Zeitlimit, wird eine stabile fachlich
neutrale Enthaltung ausgegeben. Der Validator formuliert niemals selbst eine
Person, einen Kontaktweg oder einen Prozess.

Allgemeine Antworten ohne internen Toolaufruf behalten den normalen
Streamingpfad. Die Qualität der modellseitigen Toolwahl wird über die
Akzeptanzmatrix und Laufzeitmetriken abgesichert.

## Migrations- und Rückfallstrategie

Die Umstellung erfolgt in zwei Releases:

### Release A: paralleler, rückfallfähiger Pfad

- Neuer Modus `KAHLE_KNOWLEDGE_ROUTING_MODE=legacy|model_led`.
- Produktionsdefault bleibt zunächst `legacy`.
- Lokales Overlay und definierte Abnahmeläufe verwenden `model_led`.
- Im modellgeführten Modus wird der alte semantische Plan nur noch
  side-effect-free als Vergleichsmetrik berechnet; er führt keine Tools aus und
  verändert keine Antwort.
- Rückfall erfolgt durch Zurücksetzen auf `legacy` und Neuerstellen von
  `open-webui`.

### Release B: Altpfad entfernen

Erst nach bestandener automatisierter Matrix, manueller UI-Abnahme für alle
Vinci-Modelle und stabilen lokalen Metriken werden die deterministischen
Routing- und Direktantwortfunktionen samt ihren wortlautgebundenen Tests
entfernt. Der Rückfall erfolgt dann über die vorherige geprüfte Revision bzw.
das vorherige Container-Image, nicht über dauerhaft doppelte Fachlogik.

Ein Produktionsrollout, eine Serverumschaltung oder ein Push ist nicht Teil
dieser Spezifikation und benötigt eine gesonderte Freigabe.

## Nicht betroffen

- Portal-ACLs, Dokumentfreigabe, Versionierung und Qdrant als abgeleiteter Index;
- Personio-Sync, Feldfreigaben und read-only Zugriff;
- Academy-Provisionierung;
- Datei-, Formular-, Aufgaben-, Kalender- und Mailrouting;
- externe Websuche für tatsächlich externe aktuelle Informationen;
- der technische Toolcall-Guard für Pseudo-Toolcalls, Downloadverträge und
  sonstige nicht fachliche Sicherheitsprüfungen.

## Abnahmekriterien

- Freie Formulierungen und kompakte Nomenphrasen wie
  „Serviceassistenzen Neustadt“ erreichen Personio ohne neue Harness-Wortliste.
- Aktuelle Personen- und Supervisorfragen verwenden weder RAG noch Websuche.
- Funktionspostfach-, Ticket- und Einreichungsfragen verwenden RAG und zeigen
  nur den passenden antwortbaren Dokumentabschnitt.
- Eine explizite Personen-plus-Prozessfrage verwendet beide Quellen; beide
  Antwortteile bleiben getrennt belegt.
- Ein Hint- oder Kurzindex-Abschnitt erscheint nie als Antwortclaim.
- Fehlende Personio- oder RAG-Evidenz führt nicht zu Modellwissen oder Websuche.
- Supervisor-Folgepronomen funktionieren; ein neuer Name übernimmt niemals den
  vorherigen Kandidaten.
- Ungültige erste Antworten werden vor Sichtbarkeit höchstens einmal vom Modell
  korrigiert und anschließend stabil fail-closed beendet.
- KAHLE-Vinci, Thinking, Max-Thinking und zukünftige Vinci-Modelle erhalten
  denselben Quellen- und Sicherheitsvertrag.
- Tests und technische Berichte verwenden ausschließlich synthetische Personen
  und reservierte Kontaktwerte.

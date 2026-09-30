# Funktionskontakte pflegen und übernehmen

Stand: 3. September 2026. Diese Anleitung beschreibt den lokal implementierten
Kontaktvertrag. Sie bestätigt weder eine Produktionsaktivierung noch eine
abgeschlossene Modell- oder UI-Abnahme.

## Quellen und Zuständigkeiten

| Information | Führende Quelle |
| --- | --- |
| Gemeinsames Postfach, Funktionstelefon, Kontaktseite | Freigegebene Tabelle im bestehenden Wissensdokument |
| Aktuelle Personen, geschäftliche Einzelkontakte, Team, Standort | Personio |
| Führungskraft | Eindeutig auflösbare Personio-Supervisor-Beziehung |
| Ablauf und dokumentierte fachliche Zuständigkeit | Freigegebenes Prozessdokument |

Der Dokument-Owner prüft die Angaben fachlich und pflegt die Originalquelle.
Die bestehende zuständige Freigabe prüft und veröffentlicht die Dokumentversion.
Der Betrieb prüft Indexierung und Rückweg. Es gibt keine zweite Kontaktverwaltung
und keine zusätzliche Pflegeoberfläche. `can_read` und `can_upload` bleiben
getrennt. Die Tabelle erhält weder eigene Rechte noch eine Sonderfreigabe.

## Bestehende Kontakte schrittweise übertragen

1. Die fachlich führende Originalquelle und ihren Owner bestimmen. Portalquellen
   und klassische Quellen getrennt behandeln; keine neuen Kopien als Konkurrenz
   zum führenden Dokument anlegen.
2. Prüfen, ob der Kontakt tatsächlich gemeinsam genutzt wird. Die Schreibweise
   einer Adresse beweist das nicht. Individuelle Kontakte nicht in die Tabelle
   übernehmen und keine aktuellen Personen oder Führungskräfte aus RAG ableiten.
3. Die [leere Vorlage](../templates/funktionskontakte.md) übernehmen und alle fünf
   Felder ausfüllen. Je Zeile genau ein Kontakt; Funktion, Zweck und Bereich
   fachlich bestätigen. Kontaktseiten werden syntaktisch geprüft, nicht aufgerufen
   oder auf Vertrauenswürdigkeit geprüft.
4. Andere freigegebene Quellen auf widersprüchliche Angaben prüfen. Unterschiedliche
   Werte für dieselbe Kombination aus Funktion, Kontaktart, Zweck und Bereich
   müssen redaktionell geklärt werden. Bei beabsichtigten Alternativen den
   unterschiedlichen Zweck oder Bereich ausdrücklich beschreiben.
5. Neue Dokumentversion über den vorhandenen Upload-, Prüf- und Freigabeprozess
   veröffentlichen. Keine Originalquelle automatisch überschreiben und keine
   Version durch direkte Änderungen an Datenbank oder Suchindex freischalten.
6. Im kanonischen Markdown prüfen, ob die fünf Spalten und die Überschrift
   `Funktionskontakte` erhalten sind. Tabellen in Codeblöcken oder unter
   Suchbegriffen, Synonymen und Beispielanfragen zählen nicht als Kontaktbeleg.
7. Nach regulärer Indexierung mit einem berechtigten Testkonto prüfen: passender
   Kontakt, richtiger Zweck und Bereich, aktive Version und aufrufbare Quelle.
   Mit einem eingeschränkten Konto darf weder der Kontakt noch eine vertrauliche
   Quellenexistenz sichtbar werden. Nur technische Ergebnisse protokollieren.

Die Software übernimmt keine fachliche Bestätigung. Unvollständige, ungültige
oder überlange Zeilen (standardmäßig mehr als 900 Zeichen) erhalten keinen
typisierten Kontaktbeleg. Andere gültige Zeilen und belegtes Prozesswissen
bleiben nutzbar. Werte werden nicht aus fehlenden Zellen ergänzt.

## Übergang und Konflikte

Im modellgeführten Pfad sind typisierte Zeilen der Tabelle „Funktionskontakte“
die bevorzugte Kontaktfreigabe. Seit dem 30.09.2026 gilt zusätzlich: Ein
Kontaktwert, der **wörtlich in einer belegten, redaktionellen RAG-Aussage der
aktuellen Anfrage** steht, ist an die Quelle dieser Aussage gebunden und darf mit
Zitat und Geltungsbereich aus derselben Aussage genannt werden. Typisierte Zeilen
behalten Vorrang. Suchhilfen, OCR-Hilfstexte, alte Indexeinträge außerhalb der
gelieferten Evidenz und Werte, die nicht wörtlich belegt sind, erzeugen weiterhin
keine Kontaktfreigabe. Fehlende
Angaben werden offen benannt, nicht durch Einzelkontakte, Websuche oder
Modellwissen ersetzt. Ein unklarer Geltungsbereich wird erfragt oder die
belegten Bereiche werden ausdrücklich getrennt dargestellt.

Widersprüchliche Werte eines Schlüssels werden im Retrieval zurückgehalten.
Eine unvollständige Konfliktprüfung erteilt ebenfalls keine Kontaktfreigabe.
Nicht zugängliche Quellen dürfen keinen sichtbaren Konflikthinweis auslösen.
Korrekturen erfolgen an den Originalquellen mit neuer Freigabe und Indexierung.

Die Antwortprüfung wird über `KAHLE_ANSWER_ENFORCEMENT` gesteuert. Mit
`observe` (Default im Basis-Stack) läuft sie nur beobachtend. Mit `enforce`
(lokales Edge-Overlay) wird eine Antwort mit internem Wissen vor der Anzeige
geprüft: Ein ungebundener Kontaktwert ist ein blockierender Verstoß, löst genau
einen Korrekturlauf ohne Tools aus und führt, wenn auch dieser scheitert, zu
einer neutralen Enthaltung.

Kontaktarten sind ausschließlich `E-Mail`, `Telefon` und `Kontaktseite`. Zeilen
mit anderen Bezeichnungen, zum Beispiel „Ticket-System“, erhalten keinen
typisierten Kontaktbeleg; Links auf ein Ticketsystem als `Kontaktseite` pflegen.

## Indexierung und Rückweg

Qdrant und BM25 sind abgeleitete Indizes. Der Kontaktvertrag
`kahle.functional-contact.v1` wird aus der kanonischen Datei unter
`stack/open-webui-tools/` an KB-Sync und Harness verteilt. Nach einer Änderung
der Indexierung ist eine kontrollierte Neuindexierung nötig; Altpayloads werden
nicht automatisch zu typisierten Kontakten aufgewertet.

Vor einer später freigegebenen lokalen Aktivierung:

- Full Verify erfolgreich abschließen und Mount-Herkunft (`KAHLE_ROOT`) prüfen.
- Bestehende Wiederherstellungsmöglichkeit, Collection-/Aliaszustand und passenden
  BM25-Stand sichern. Führende Dokumente und Versionen unverändert erhalten.
- Betroffene lokale Images kontrolliert neu bauen. Den vorhandenen internen
  `/reindex-all`-Pfad nutzen, keine direkte Kontaktpflege in Qdrant durchführen.
- Aktive Version, Rechte und synthetische positive sowie negative Fälle prüfen.
  Ein Indexierungs-Erfolgsstatus allein ist keine fachliche Abnahme.

Diese Anleitung führt keinen dieser Betriebsschritte selbst aus. Ohne geprüften
Rückweg oder freigegebene Testdaten nicht aktivieren oder neu indexieren.

Ein Rückfall auf `legacy` stellt die alte Routing- und Kontaktlogik wieder her,
nicht die neuen Kontaktregeln. Eine Dokumentkorrektur erfolgt unabhängig davon
über die bestehende Versionsverwaltung. Datenbank, Collection/Alias und BM25
müssen bei einer Wiederherstellung konsistent sein. Keine willkürlichen
Einzeldateien oder alten Indexstände über aktuelle Freigaben kopieren.

## Abnahme und datensparsame Berichte

Die ausführbare Matrix steht in
`scripts/openwebui/kahle-harness-acceptance-matrix.json` (v2). Die
[UI-Anleitung](../KAHLE-VINCI-UI-ABNAHME-HARNESS.md) beschreibt Eingabeformat,
Werkzeug-/Quellennachweise und die Trennung von Offline-Kontrolltests und
tatsächlichen Modellläufen. Ein grüner Offline-Test ist kein Modellnachweis.

Gespeichert werden nur bekannte Fallkennungen, Modell-/Profilkennungen,
technische Werkzeug- und Quellenarten, Statuscodes, Zeitmessungen und boolesche
Prüfergebnisse. Keine Rohfragen, Antworten, Dokumentpassagen, Kontaktwerte,
Personio-IDs oder Secrets. Auffälligkeiten vor Ort gegen die autorisierte Quelle
prüfen; die automatische Markierungsquote ist keine bewiesene Modellfehlerquote.

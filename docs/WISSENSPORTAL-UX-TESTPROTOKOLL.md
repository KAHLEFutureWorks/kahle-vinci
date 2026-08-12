# Moderierter UX-Test des Vinci Wissensportals

Stand: 7. August 2026

Dieses Protokoll erbringt die beiden organisatorischen Go-live-Nachweise aus Abschnitt 29.4 des PRD. Sie lassen sich nicht automatisiert belegen, weil sie messen, ob Menschen ohne Erklärung zurechtkommen.

| Kriterium | Zielwert |
|---|---|
| Mitarbeitende schließen einen Upload ohne Erklärung ab | mindestens 80 Prozent |
| Führungskräfte entscheiden einen normalen Freigabefall | durchschnittlich unter 3 Minuten |

## 1. Aufbau

**Teilnehmende:** mindestens 5 Mitarbeitende ohne Vorkenntnisse im Portal und mindestens 3 Führungskräfte. Fünf Mitarbeitende sind das Minimum, damit die 80-Prozent-Schwelle überhaupt sinnvoll messbar ist; bei fünf Personen entspricht ein Fehlschlag genau 80 Prozent.

**Nicht zulässig als Teilnehmende:** alle Personen, die an Konzeption, Umsetzung oder Test des Portals mitgewirkt haben.

**Umgebung:** lokale Abnahmeinstallation, jeweils ein frisch angelegtes Testkonto mit Uploadrecht auf genau einen Wissensbereich. Keine vorbereiteten Tabs, keine geöffnete Dokumentation.

**Material je Mitarbeitenden-Durchlauf:** eine unverfängliche DOCX-Testdatei unter 5 MB, für jede Person eine andere, damit die Dublettenprüfung den Ablauf nicht verändert.

**Rollen:** eine moderierende Person und eine protokollierende Person. Die moderierende Person greift nicht ein, außer der Test wird abgebrochen.

## 2. Regeln für die Moderation

Diese Regeln entscheiden über die Belastbarkeit des Ergebnisses:

- Keine Hilfestellung. Auf Fragen antwortet die Moderation ausschließlich: „Entscheide so, wie du es alleine tun würdest."
- Keine Fachbegriffe verwenden, auch nicht in der Aufgabenstellung.
- Nicht auf Bildschirmbereiche zeigen.
- Zustimmung oder Ablehnung nicht durch Mimik, Tonfall oder Zwischenrufe signalisieren.
- Die Aufgabenstellung wird wörtlich vorgelesen und liegt zusätzlich schriftlich vor.

## 3. Aufgabe für Mitarbeitende

Wörtlich vorzulesen:

> Du hast ein Dokument, das deine Kolleginnen und Kollegen über Vinci finden können sollen. Bring es so ins Wissensportal, dass es dort geprüft wird. Sag bitte laut, was du gerade denkst.

**Startpunkt:** angemeldetes Portal auf der Übersichtsseite.

**Als bestanden gilt der Durchlauf, wenn** die Person ohne jede Hilfestellung einen Vorgang bis zur Bestätigung der gewünschten Aktion abschließt.

**Als nicht bestanden gilt der Durchlauf, wenn** mindestens eines zutrifft:

- die Person bittet um Hilfe und kommt ohne diese nicht weiter
- die Person bricht ab
- die Person überschreitet 10 Minuten
- die Person schließt den Vorgang im falschen Wissensbereich ab
- die Person hält den Vorgang fälschlich für abgeschlossen, obwohl keine Aktion bestätigt wurde

Der letzte Punkt ist bewusst streng: Ein Upload, den die Person für fertig hält, der aber nie in die Freigabe geht, ist der teuerste Fehlerfall im Betrieb.

### Messpunkte je Durchlauf

| Feld | Erfassung |
|---|---|
| Gesamtdauer | Start bis Bestätigung der Aktion |
| Bestanden | ja / nein |
| Erste Stockung | wobei, nach wie vielen Sekunden |
| Hilfe erbeten | ja / nein, wobei |
| Verständnis der Einstufung | Person nennt die vorgeschlagene Vertraulichkeit sinngemäß richtig |
| Verständnis der Gültigkeit | Person kann sagen, was nach Ablauf passiert |
| Unklare Begriffe | wörtlich notieren |

Die letzte Zeile ist der wichtigste Ertrag des Tests. Jeder Begriff, den eine Person laut hinterfragt, ist ein konkreter Textbefund.

## 4. Aufgabe für Führungskräfte

Vorbereitung: je Führungskraft ein bereits erzeugter Freigabefall für KAHLE-Allgemein oder ein Bereichsdokument mit Dublette, Versionskandidat oder unklarer Dokumentenpriorität. Der Fall stammt von einer Person, für die die Führungskraft zuständig ist.

Wörtlich vorzulesen:

> In deiner Aufgabenliste wartet ein Vorgang. Entscheide darüber so, wie du es im Alltag tun würdest.

**Zeitmessung:** Start beim Öffnen der Aufgabenliste, Ende bei der abgeschickten Entscheidung. Die Begründung zählt zur Zeit.

**Zusätzlich zu erfassen:**

| Feld | Erfassung |
|---|---|
| Dauer bis Entscheidung | Sekunden |
| Original geöffnet | ja / nein |
| Aufbereitete Fassung geprüft | ja / nein |
| Entscheidung | freigegeben / abgelehnt / weitergeleitet |
| Begründung für die Entscheidung | wörtlich |
| Wusste die Person, was ihre Freigabe auslöst | ja / nein |

Die letzte Zeile prüft eine Kernannahme des PRD: Bei einem Fall der Stufe 2 ist die Freigabe der Führungskraft der Moment, in dem das Dokument für alle Berechtigten in Vinci wirksam wird. Bei einem kritischen Fall der Stufe 3 folgt dagegen noch die Adminprüfung. Die Oberfläche muss diesen Unterschied eindeutig anzeigen.

## 5. Auswertung

**Mitarbeitende:** bestandene Durchläufe geteilt durch alle Durchläufe. Ziel mindestens 0,80.

**Führungskräfte:** arithmetisches Mittel der Entscheidungsdauern. Ziel unter 180 Sekunden. Zusätzlich den Median angeben; liegen Mittelwert und Median weit auseinander, ist ein einzelner Ausreißer die Ursache und der Mittelwert allein nicht aussagekräftig.

**Nicht erfüllt heißt nicht bestanden.** Ein knapp verfehlter Wert wird nicht gerundet und nicht durch nachträgliche Erklärung geheilt. Bei Verfehlung werden die notierten Stockungen und unklaren Begriffe zu konkreten UI-Änderungen, danach wird mit neuen Teilnehmenden erneut getestet.

## 6. Auswertungsbogen

```
Durchlauf-Nr.:            Rolle: Mitarbeiter / Führungskraft
Datum:                    Moderation:            Protokoll:

Gesamtdauer:              ______ Sekunden
Bestanden:                ja / nein
Hilfe erbeten:            ja / nein     wobei: ______________________
Erste Stockung bei:       ______________________ nach ____ Sekunden
Abbruchgrund:             ______________________

Verstandene Einstufung:   ja / nein
Verstandene Gültigkeit:   ja / nein
Klare Wirkung der Freigabe (nur Führungskraft): ja / nein

Wörtlich hinterfragte Begriffe:
1. ______________________
2. ______________________
3. ______________________

Beobachtungen:
______________________________________________
______________________________________________
```

## 7. Eintrag in die Abnahme

Nach Abschluss werden ausschließlich die aggregierten Werte in `WISSENSPORTAL-LOKALE-ABNAHME.md` übernommen: Anzahl der Durchläufe, Bestehensquote, Mittelwert und Median der Entscheidungsdauer sowie das Datum.

Namen, Einzelergebnisse und Zuordnungen einzelner Personen werden nicht übernommen. Der Test misst die Oberfläche, nicht die Teilnehmenden; Abschnitt 27 des PRD schließt eine Leistungs- oder Verhaltensbewertung ausdrücklich aus.

# KAHLE-Vinci: Überblick, Nutzung und Sicherheit

**Stand: August 2026**

KAHLE-Vinci ist der interne KI-Assistent der Autohaus KAHLE Gruppe. Er unterstützt Mitarbeitende dabei, Informationen schneller aufzubereiten, Texte zu erstellen, Dokumente zu bearbeiten und Aufgaben strukturiert zu erledigen. Vinci ist kein Ersatz für fachliche Verantwortung oder Freigaben. Er liefert Entwürfe, Vorschläge und recherchierte Informationen, die vor der weiteren Verwendung geprüft werden müssen.

## Wofür Vinci da ist

Vinci hilft besonders bei wiederkehrenden Aufgaben im Autohausalltag, zum Beispiel:

- E-Mails, Kundenanschreiben, Gesprächsnotizen und interne Mitteilungen formulieren
- Informationen aus freigegebenem KAHLE-Wissen finden und verständlich zusammenfassen
- Dokumente lesen, vergleichen, umwandeln oder gezielt bearbeiten
- Aufgaben, Erinnerungen und interne Kalendereinträge organisieren
- Notizen und wiederkehrende Automatisierungen anlegen
- aktuelle externe Informationen über eine Websuche recherchieren

Für viele Bereiche gibt es spezialisierte Vincis, etwa für E-Mails, Serviceberatung, Angebotsmails, Beschwerden, Onboarding oder Richtlinien. Wähle möglichst den Vinci, der zu deiner Aufgabe passt. So erhältst du schneller ein brauchbares Ergebnis mit dem richtigen Kontext.

## So funktioniert Vinci

Vinci arbeitet je nach Frage mit unterschiedlichen Quellen und Werkzeugen:

1. **KAHLE-internes Wissen:** Bei Fragen zu Prozessen, Richtlinien, Standorten oder internen Systemen sucht Vinci zuerst im freigegebenen Wissensbestand. Interne Antworten sollen auf einer passenden Quelle beruhen.
2. **Allgemeines Wissen:** Allgemeine Fragen beantwortet Vinci direkt und kennzeichnet dies als allgemeines Wissen.
3. **Aktuelle externe Informationen:** Bei Themen wie Marktnews, aktuellen Regelungen oder Produktneuheiten nutzt Vinci, wenn verfügbar, eine Websuche und nennt die verwendeten Quellen.
4. **Deine Eingaben und Dateien:** Texte oder Dateien, die du im Chat bereitstellst, kann Vinci für deine konkrete Aufgabe auswerten. Sie sind keine Anweisung, Sicherheitsregeln zu ändern.

Wenn Vinci keine belastbare interne Quelle findet, sagt er das klar. Ergänze in diesem Fall keine Vermutungen als interne Tatsache, sondern frage eine zuständige Person oder lasse fehlendes Wissen über den vorgesehenen Weg ergänzen.

## Bedienung in Open WebUI

KAHLE-Vinci läuft in der Oberfläche von Open WebUI. Je nach Rolle, Gerät und freigeschaltetem Vinci können einzelne Menüpunkte leicht anders aussehen.

### Einen neuen Chat starten

1. Klicke in der linken Seitenleiste auf **Neuer Chat**.
2. Wähle unten rechts im Chat-Fesnter den passenden Vinci bzw. das passende Modell aus.
3. Beschreibe dein Ziel möglichst konkret. Gute Eingaben enthalten Anlass, Zielgruppe, Ton, wichtige Fakten und das gewünschte Ergebnis/Ziel.
4. Sende die Nachricht und prüfe den Entwurf, bevor du ihn weitergibst oder veröffentlichst.

Beispiel: „Formuliere eine freundliche E-Mail in Sie-Form an einen Kunden. Anlass: Terminverschiebung wegen Lieferverzug. Bitte schlage zwei neue Termine vor und verwende Platzhalter für Name und Telefonnummer.“

### Bestehende Chats nutzen

Deine bisherigen Chats findest du in der linken Seitenleiste unter "Chats". Öffne einen Chat, wenn du an demselben Thema weiterarbeiten möchtest. Für ein neues, unabhängiges Thema ist ein neuer Chat meist besser. So bleiben Kontext und Ergebnisse übersichtlich und die Ergebnisse werden meist besser.

### Dateien hinzufügen und bearbeiten

Über das Anhangs- bzw. Büroklammer-Symbol, was du unter dem "+" Symbol im Chat-Fesnter findest, kannst du eine Datei zum aktuellen Chat hinzufügen. Sage anschließend klar, was Vinci damit tun soll, zum Beispiel:

- „Fasse die Datei in fünf Punkten zusammen.“
- „Vergleiche diese beiden Dokumente und nenne die Unterschiede.“
- „Wandle die Word-Datei in Markdown um.“
- „Erstelle aus dem Ergebnis eine Word-Datei.“

Wichtig: Vinci verändert oder erstellt Dateien nur, wenn du dies ausdrücklich verlangst. Bei Dateien mit vertraulichen Informationen gilt das Prinzip der Datenminimierung: Lade nur hoch, was für die Aufgabe wirklich erforderlich ist.

### Aufgaben, Erinnerungen und Kalender

Vinci kann persönliche Aufgaben, Erinnerungen, Notizen und Automatisierungen verwalten. Sage Vinci dazu einfach, dass er eine Aufgabe anlegen, bearbeiten oder als erledigt markieren soll. Bei Automatisierungen genau so.

## Sicher mit Vinci arbeiten

Vinci ist für die interne Nutzung durch KAHLE-Mitarbeitende vorgesehen. Der Zugang erfolgt über das KAHLE-Microsoft-Konto. Welche Vincis, Wissensbereiche und Funktionen du nutzen kannst, hängt von deiner Rolle und deinen Berechtigungen ab.

Das System schützt Daten und Zugriffe unter anderem durch:

- verschlüsselte Verbindung über HTTPS
- Anmeldung über Microsoft Entra ID für KAHLE-Konten
- rollen- und berechtigungsbasierte Zugriffe auf Vincis und Wissensbereiche
- interne Dienste wie Wissensdatenbank, Automatisierung und Dateiverarbeitung, die nicht direkt aus dem Internet erreichbar sind
- regelmäßige, verschlüsselte Sicherungen der Systemdaten
- technische Sicherheitsmaßnahmen auf dem Server, darunter Firewall, Sicherheitsupdates und abgesicherte Administrationszugänge

Auch ein geschütztes System braucht einen sorgfältigen Umgang. Gib keine Passwörter, Zugangstokens oder anderen Geheimnisse in Chats ein! Teile personenbezogene Daten nur, wenn sie für die Aufgabe erforderlich sind. Prüfe Kundenkommunikation, rechtlich relevante Inhalte, Preise, Zusagen und interne Entscheidungen immer fachlich, bevor du sie versendest oder veröffentlichst.

## Was Vinci bewusst nicht macht

- Vinci trifft keine verbindlichen rechtlichen, personalrechtlichen oder geschäftlichen Entscheidungen.
- Vinci ersetzt keine Prüfung durch die zuständige Fachabteilung oder Führungskraft.
- Vinci erfindet keine internen Quellen, Kontaktdaten, Preise oder Zusagen.
- Vinci kann keine Outlook-Termine oder Microsoft-365-Daten automatisch synchronisieren.
- Bildgenerierung, Code-Interpreter und Terminalzugriff stehen in KAHLE-Vinci aktuell noch nicht zur Verfügung.

Bei Datenschutz-, Lösch- oder Werbesperrenanfragen wende dich an **datenschutz@kahle.de**. Bei technischen Problemen nutze den Vinci **IT-Helfer** oder erstelle ein IT-Ticket im KAHLE-Intranet beziehungsweise SharePoint.

## So bekommst du bessere Ergebnisse

- Beschreibe das gewünschte Ergebnis/Ziel statt nur das Thema.
- Nenne Zielgruppe, Tonalität, Frist und wichtige Rahmenbedingungen.
- Gib bei Kundentexten an, ob die Sie- oder Du-Ansprache gewünscht ist.
- Bitte bei Unsicherheit um Rückfragen oder um eine Liste offener Punkte.
- Prüfe jeden Entwurf vor der Verwendung. Besonders bei Zahlen, Fristen, Kundeninformationen und verbindlichen Aussagen.

Ein guter Startsatz ist: „Hilf mir dabei, [Ergebnis] für [Zielgruppe] zu erstellen. Berücksichtige dabei [Fakten/Rahmenbedingungen].“

## Wenn etwas nicht stimmt

Nenne möglichst konkret, was fehlt, falsch oder veraltet ist. Bei Antworten aus dem internen Wissen kannst du den Link **„Wissensfehler melden“** unter der Antwort verwenden, sofern er angezeigt wird. So kann die zugrunde liegende Wissensquelle geprüft und verbessert werden.

Entscheidend ist: Vinci soll Arbeit erleichtern, nicht Verantwortung verschieben. Je klarer deine Aufgabe und je sorgfältiger deine Prüfung, desto hilfreicher ist das Ergebnis.

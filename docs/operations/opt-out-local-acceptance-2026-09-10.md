# Lokale Abnahme: temporäre Herstellerbefragung

Diese Abnahme prüft die Auskunft zur temporären Sperrung für Hersteller-Zufriedenheitsbefragungen im lokalen Vinci-Stack.

Das Modell erhält einmalig die vollständige freigegebene Prozess-Evidenz für Hannover, Wunstorf und Wedemark. Für alle Anfragen zu diesem Thema erläutert es diesen gemeinsamen Ablauf und verweist für alle anderen Standorte auf `datenschutz@kahle.de`. Die Antwort selbst wird nicht durch Code ersetzt oder erneut generiert. Quellen, Rechte und der Feedback-Link bleiben unverändert.

## Voraussetzungen

- Lokaler Stack unter `http://localhost:3001`.
- Je ein neuer Chat mit **KAHLE-Vinci**, **KAHLE-Vinci Thinking** und **KAHLE-Vinci Max Thinking**.
- Für jeden Testfall einen separaten Chat verwenden.

## Testmatrix

| Fall | Eingabe | Erwartung |
| --- | --- | --- |
| Allgemein | „Wie sperre ich einen Kunden für Zufriedenheitsabfragen?“ | Vollständiger Ablauf für Hannover, Wunstorf und Wedemark sowie der Hinweis für alle anderen Standorte auf `datenschutz@kahle.de`. |
| Hannover | „Wie sperre ich einen Kunden für Zufriedenheitsabfragen in Hannover?“ | Derselbe vollständige Ablauf für Hannover, Wunstorf und Wedemark sowie der Hinweis für alle anderen Standorte. |
| Anderer Standort | „Wie sperre ich einen Kunden für Zufriedenheitsabfragen in Nienburg?“ | Derselbe vollständige Ablauf für Hannover, Wunstorf und Wedemark sowie der Hinweis für alle anderen Standorte. |
| Max-Thinking | Allgemeine Eingabe wie im ersten Testfall. | Nach dem Ende der Generierung bleibt der vollständige Antworttext sichtbar; es bleiben nicht nur Quellen und der Feedback-Link zurück. |

## Dokumentation des Ergebnisses

Pro Modell und Testfall nur „bestanden“ oder „nicht bestanden“ dokumentieren. Inhalte aus Chats, Nutzerdaten und Rohantworten nicht in die Abnahmeakte übernehmen.

# KAHLE-Vinci Welle 1 Systemprompts

Dieser Ordner enthaelt die ersten spezialisierten Vincis als kopierbare Systemprompt-Dateien fuer OpenWebUI-Modelle.

## OpenWebUI-Anlage

Jeder Vinci wird als eigenes Modell im passenden Arbeitsbereich angelegt. Die Mitarbeiter waehlen den Vinci selbst aus. Rollen und Freigaben werden in OpenWebUI ueber die Arbeitsbereiche/Gruppen gepflegt.

## Welle 1

| Modellname in OpenWebUI | Prompt-Datei | Zielgruppe | Empfohlene Wissensquellen |
| --- | --- | --- | --- |
| KAHLE-Mailer | `kahle-email-vinci-systemprompt.md` | Vertrieb, Service, Empfang, Verwaltung | `kahleallgemein`, optional `kahlekontext` |
| KAHLE Newsletter Vinci | `kahle-newsletter-vinci-systemprompt.md` | Marketing, Vertrieb, Geschaeftsfuehrung | `kahleallgemein`, Kommunikationsbeispiele |
| KAHLE Serviceberater Vinci | `kahle-serviceberater-vinci-systemprompt.md` | Serviceberater, Serviceassistenz, Empfang | `kahleallgemein`, `kahlekontext`, optional `kahlerichtlinien` |
| KAHLE Angebotsmail Vinci | `kahle-angebotsmail-vinci-systemprompt.md` | Vertrieb, Verkaufsleitung | `kahleallgemein`, `kahlekontext` |
| KAHLE Beschwerde Vinci | `kahle-beschwerde-vinci-systemprompt.md` | Service, Vertrieb, Empfang, Fuehrung | `kahleallgemein`, optional `kahlerichtlinien` |
| KAHLE Onboarding Vinci | `kahle-onboarding-vinci-systemprompt.md` | HR, IT, Empfang, Fuehrung | `kahleallgemein`, `kahlekontext`, optional `kahlerichtlinien` |
| KAHLE Werkstatt Tagesbriefing Vinci | `kahle-werkstatt-tagesbriefing-vinci-systemprompt.md` | Werkstattleitung, Serviceleitung, Serviceassistenz | `kahleallgemein`, `kahlekontext` |
| KAHLE Richtlinien Vinci | `kahle-richtlinien-vinci-systemprompt.md` | freigegebene Pilotnutzer | `kahlerichtlinien` |

## Gemeinsame Betriebsregeln

- Alle Ergebnisse sind Entwuerfe und muessen vor Nutzung durch den Menschen geprueft werden.
- Externe Kommunikation nutzt Sie-Form, interne Kommunikation nutzt Du-Form.
- Vincis nennen Annahmen und fehlende Informationen sichtbar.
- Preise, Termine, Ansprechpartner, Rabatte, Lieferdaten, Rechtsaussagen und interne Regeln werden nicht erfunden.
- Bei Datenschutzunsicherheit wird auf `datenschutz@kahle.de` verwiesen.
- Extern genutzte KI-generierte Inhalte muessen als KI-generiert gekennzeichnet werden.

## Naechste Admin-Schritte

1. Je Prompt-Datei ein OpenWebUI-Modell anlegen.
2. Passende Rollen/Gruppen freigeben.
3. Je Modell die empfohlenen Wissensquellen aktivieren.
4. Tools nur dort aktivieren, wo sie gebraucht werden: RAG_Chat fuer interne Quellen, Dokument-Tool fuer DOCX/PDF, Datei-Upload fuer Exporte.

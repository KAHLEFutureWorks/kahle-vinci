# Harness-Qualität: Roadmap der testgetriebenen Korrekturen

Grundlage: [Harness-Analyse vom 29.09.](../../research/2026-09-29-vinci-harness-analyse.md)

Diese Roadmap ordnet die geprüften Befunde und die vier Qualitätsbremsen den
Umsetzungsphasen zu. Jede Phase bekommt beim Start einen eigenen, detaillierten
TDD-Plan unter `docs/superpowers/plans/`. Nur Phase 1 ist bereits detailliert
ausgearbeitet, weil die späteren Pläne auf ihrer Baseline aufbauen.

## Festgelegte Entscheidungen (29.09.)

| Thema | Entscheidung |
| --- | --- |
| Zielbild Routing | Modellgeführt, mit serverseitigen Leitplanken (Evidenz, Quellenhoheit, Kontakte, Validierung) |
| Pflichtmodelle | Mistral-Small-24B, gpt-oss-120b, Qwen3.5-397B |
| Antwortvalidierung | Antworten mit internem Wissen werden gepuffert und bei einem blockierenden Verstoß genau einmal korrigiert, sonst folgt eine neutrale Enthaltung |
| Reihenfolge | Zuerst Phase 1 (Eval), dann Phase 0 (Quick Wins), dann 2, 3, 4 |
| Sonderfälle mit Geltungsbereich | Als typisierte Portal-Dokumentmetadaten, nicht im Code |
| Legacy-Direktantworten | Werden vollständig entfernt (`_knowledge_harness_direct_answer`, `HarnessDecision.direct_answer`) |

## Zuordnung der Befunde

| Nr. | Befund (Analyse) | Phase | Nachweis „behoben“ |
| --- | --- | --- | --- |
| 1 | Validator greift nicht ein (K-, W2) | 0 (Schweregrade), 2 (Puffer + Retry) | Runtime-Eval: 0 blockierende Verstöße in ausgelieferten Antworten; `retry_count` wird befüllt |
| 2 | `model_led` führt die Legacy-Vorplanung aus (W1, K6) | 3 | Routing-Eval `model_led` ≥ Legacy-Baseline für alle drei Modelle; genau eine Vertragsnachricht |
| 3 | Umlaut-Normalisierung (K1) | 0 | Offline-Eval: `procedural`-Treffer für alle Umlaut-/ASCII-Paare |
| 4 | Zuständigkeitsfragen landen bei Personio (K2) | 0 (Direktantworten entfernen, Namensmuster), 3 (Regex-Planung entfernen) | Offline- und Runtime-Eval-Kategorie `responsibility` |
| 5 | Validator-Fehlalarme (K4) | 0 | Unit-Tests für die verneinte Freigabe, „möglich“ und „Support“ als `advisory` |
| 6 | Einzelfall-Hardcoding (U1, U3, U4) | 0 (Modell-ID), 3 (Geltungsbereichs-Metadaten) | Kein Werbewiderspruch-Sonderpfad mehr im Code; Eval-Kategorie `scope_location` unverändert oder besser |
| 7 | Toter Code (U2) | 0 | Entfernt, Tests grün |
| 8 | Prompt-Widersprüche (W4–W8, M4) | 0 (Textkorrekturen), 4 (Anweisungen nur aus dem Harness, modularer Prompt) | Prompt-Sync-Check; Runtime-Eval nicht schlechter |
| 9 | Fünf Zitierformate (M1) | 0 | Ein Format in Tool, Harness, Validator und Guard; Eval-Metrik „Zitate gültig“ |
| 10 | Eval-Lücken | **1** | Offline- und Runtime-Eval laufen reproduzierbar |
| – | Mehrfachaufrufe gehen in der Evidenzsitzung verloren (K5) | 0 | Unit-Test mit zwei `rag_chat`-Aufrufen |

| Qualitätsbremse | Phasen |
| --- | --- |
| Validator greift nicht | 0, 2 |
| Zwei Routing-Paradigmen | 3 |
| Fehlerhafte, überangepasste Regelbasis | 0, 3 |
| Widersprüchliche, teure Modellführung | 0, 4 |

## Phasen und Abnahmekriterien

| Phase | Inhalt | Abnahme | Verify |
| --- | --- | --- | --- |
| 1 | Routing-Korpus, Offline-Eval gegen den Harness-Planer, Runtime-Eval gegen `localhost:3004` je Modell, Metriken ohne Personendaten | Offline-Baseline eingecheckt; Runtime-Baseline, sobald IONOS wieder antwortet | Fast |
| 0 | Umlaute, Validator-Schweregrade, Evidenzsitzung, toter Code, Direktantworten entfernen, Modell-ID konfigurierbar, Prompt-Korrekturen, ein Zitierformat | Alle Befund-Tests grün; Offline-Eval besser als die Baseline; Runtime-Eval nicht schlechter | Full (Middleware und Guard sind High-Risk) |
| 2 | Puffern, blockierende Prüfung, ein Retry ohne Tools, Enthaltung, Metriken | Keine blockierenden Verstöße ausgeliefert; Retry-Rate und p95-Latenz je Modell dokumentiert | Full + Runtime-Eval |
| 3 | Keine Vorab-Ausführung in `model_led`, eine Vertragsnachricht, schärfere Tool-Beschreibungen, Geltungsbereichs-Metadaten, danach Release B | `model_led` ≥ Baseline je Modell; keine Personio-/Supervisor-Regression | Full + Runtime-Eval + UI-Abnahme |
| 4 | Evidenz nur einmal, Vertrag als Pflichtenliste, Modellprofile, modularer Prompt, strukturierte Ausgabe prüfen | Weniger Tokens pro interner Antwort bei gleicher oder besserer Eval-Metrik | Full + Runtime-Eval |

## Arbeitsregeln für alle Phasen

- Jede Verhaltensänderung beginnt mit einem fehlschlagenden Test (Red),
  danach die minimale Umsetzung (Green), dann Aufräumen.
- Ist eine Änderung im Chat sichtbar, bekommt sie zusätzlich einen Fall im
  Routing-Korpus `eval/harness/routing_cases.yml`.
- Nach jeder Phase wird der Offline-Eval neu erzeugt und mit der Baseline
  verglichen. Sobald IONOS antwortet, gilt dasselbe für den Runtime-Eval.
- Eval-Ergebnisse enthalten weder Antworttexte noch Personendaten, nur IDs,
  Toolmengen, Verstoßcodes, Enthaltungs-Flags und Latenzen.
- Produktionsaktivierung, Rollout und externe Live-Probes gehören nicht zu
  diesen Plänen.

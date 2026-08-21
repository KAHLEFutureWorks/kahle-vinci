# Codex-Harness-Prinzipien für KAHLE-Vinci

Stand: 19. August 2026

## Kurzfazit

KAHLE-Vinci sollte die Harness-Prinzipien von Codex übernehmen, aber nicht den Codex-App-Server oder dessen Coding-Werkzeuge einbauen. Der relevante Kern ist eine gemeinsame, deterministische Orchestrierungsschicht zwischen Nutzer, Modell, Werkzeugen, Berechtigungen und Benutzeroberfläche.

Der heutige nachgelagerte Guard ist dafür die falsche Stelle: Er bewertet und ersetzt bereits erzeugte Antworten. Dadurch entstehen sichtbare Antwortwechsel, verlorene Tool-Animationen und Fälle, in denen ein korrektes RAG-Ergebnis trotzdem als „kein Wissen“ endet. Künftig sollte der Harness vor und während der Antwort steuern; nach der Antwort darf nur noch technisch validiert werden.

## Was OpenAI unter einem Harness versteht

OpenAI beschreibt den Codex-Harness als Orchestrierungsschicht, die Modell, Werkzeuge und Laufzeitumgebung verbindet. Sie verwaltet insbesondere:

- den Agentenlauf aus Modell- und Werkzeugschritten,
- Threads, Turns und persistente Zustände,
- Konfiguration, Authentifizierung und Berechtigungen,
- einheitliche Werkzeugausführung und Laufzeitrichtlinien,
- typisierte Ereignisse für Benutzeroberflächen,
- Rückfragen und Freigaben während eines laufenden Turns,
- Traces, Evaluationen und Rückkopplungsschleifen.

Wichtig ist die Trennung: Das Modell entscheidet und formuliert innerhalb eines klaren Rahmens. Der Harness liefert Kontext, begrenzt Möglichkeiten, führt Werkzeuge aus, prüft Zustände und macht den Ablauf beobachtbar. Er ist keine zweite Antwortinstanz, die einen fertigen Text nachträglich frei umschreibt.

## Befund im aktuellen Vinci-Stand

Im Projekt existieren bereits wichtige Harness-Bausteine:

- Erkennung interner Wissensanfragen und von Rückfragen im Middleware-Layer,
- Query-Erweiterung und RAG-Fallbacks,
- Berechtigungsprüfung vor dem Wissensabruf,
- ein Workflow-Orchestrator,
- native Tool- und Quellenereignisse in OpenWebUI,
- ein Guard mit Regeln für Belege und interne Aussagen.

Die Verantwortlichkeiten sind jedoch ungünstig verteilt. Der Guard enthält inzwischen Retrieval-Auswertung, Antwortsynthese, Speziallogik und nachträgliche Textkorrekturen. Damit konkurrieren Modell, RAG-Werkzeug und Guard um die endgültige Antwort. Die beobachteten Fehler sind deshalb keine einzelnen Promptfehler, sondern ein Architekturproblem.

## Empfohlene Zielarchitektur

```text
Nutzeranfrage
  -> Thread- und Gesprächskontext
  -> Intent-, Alias- und Rückfrageauflösung
  -> Mehrdeutigkeitsprüfung
       -> bei echter Mehrdeutigkeit gezielte Rückfrage
  -> Werkzeug- und Richtlinien-Router
  -> Retrieval-Plan
  -> RAG-Abruf im erlaubten Wissensumfang
  -> Evidenzprüfung
  -> Antworterstellung ausschließlich aus der Evidenz
  -> deterministische Endprüfung
  -> native Tool-, Quellen- und Statusereignisse in OpenWebUI
```

### 1. Gemeinsamer Harness

KAHLE-Vinci und KAHLE-Vinci-Thinking sollten denselben Harness, dieselbe Berechtigungslogik, denselben Retrieval-Plan und dasselbe Evidenzpaket verwenden. Unterschiede zwischen den Modellen dürfen erst bei Reasoning-Tiefe und Antwortstil entstehen.

### 2. Strukturierte Zwischenzustände

Statt lose Textfragmente zwischen Middleware, Tool und Guard zu reichen, sollte der Harness typisierte Zustände verwenden:

- `UserIntent`: fachliche Absicht, interne/externe Einordnung, benötigte Angaben,
- `ResolvedContext`: aufgelöste Abkürzungen, Standorte, Bereiche und Gesprächsbezüge,
- `RetrievalPlan`: Suchfragen, Filter, Berechtigungsumfang und Abbruchregeln,
- `EvidenceBundle`: Treffer, relevante Textstellen, Quellen, Konflikte und fehlende Angaben,
- `AnswerContract`: erlaubte Aussagen, gewünschtes Format und Zitierpflicht,
- `HarnessEvent`: sichtbare Status- und Toolereignisse.

### 3. Evidenzprüfung vor der Antwort

Die Evidenzprüfung sollte nicht nur `FOUND: true/false` liefern, sondern beispielsweise:

```json
{
  "status": "supported | partially_supported | unsupported",
  "supported_claims": [],
  "missing_information": [],
  "conflicts": [],
  "sources": []
}
```

Ein Treffer zu „WPS ist ein Terminplanungssystem“ reicht dann nicht als Beleg für eine Schritt-für-Schritt-Anleitung zur Terminbuchung. Gleichzeitig kann Vinci eine teilweise belegte Antwort geben, statt die gesamte Antwort auf „kein Wissen“ zu reduzieren.

### 4. Keine inhaltliche Nachbearbeitung durch den Guard

Nach der Antwort sollte nur noch deterministisch geprüft werden:

- Sind Pflichtquellen vorhanden?
- Existieren alle verwendeten Quellen-IDs wirklich?
- Entspricht die Ausgabe dem vereinbarten Schema?
- Wurden Berechtigungs- und Datenschutzregeln eingehalten?

Bei einem Fehler erhält die Antwortkomponente einen strukturierten Wiederholungsauftrag. Der Validator ersetzt den Inhalt nicht selbst. Sicherheitsfunktionen des bisherigen Guards bleiben erhalten; die freie RAG-Antwortsynthese entfällt.

### 5. Native, sichtbare Ereignisse

Der Ablauf sollte als Ereignisstrom an OpenWebUI gehen, zum Beispiel:

- `intent/started` und `intent/completed`,
- `clarification/required`,
- `retrieval/started` und `retrieval/completed`,
- `evidence/completed`,
- `answer/started` und `answer/completed`.

Damit bleibt „Untersucht: rag_chat“ sichtbar, Quellen werden zuverlässig angezeigt und der Nutzer sieht nur eine endgültige Antwort statt eines Textes, der nachträglich umspringt.

## Was wir von Codex übernehmen sollten

1. **Ein gemeinsamer Kern für alle Oberflächen und Modelle.** Keine separate RAG-Logik je Modell.
2. **Threads, Turns und Items als klare Zustände.** Toolaufrufe, Rückfragen und Antworten bleiben nachvollziehbar.
3. **Progressive Kontextfreigabe.** Nur passende Werkzeuge, Dokumentausschnitte und Regeln in den jeweiligen Schritt geben.
4. **Laufzeitrichtlinien statt überladener Systemprompts.** Berechtigungen, Werkzeugpflicht und Abbruchregeln im Harness durchsetzen.
5. **Unveränderliche Gesprächshistorie.** Nachträgliche Korrekturen als neue interne Zustände behandeln, nicht als stilles Umschreiben.
6. **Direkt lesbare Traces.** Intent, normalisierte Anfrage, Retrieval, Evidenzentscheidung und finale Antwort zusammen protokollieren.
7. **Evaluationen als Produktbestandteil.** Reale Fehlerfälle werden zu wiederholbaren Tests.
8. **Begrenzte Wiederholungen und klare Abbruchregeln.** Kein endloses Nachsuchen und keine unkontrollierte Kontextvergrößerung.

## Was wir nicht übernehmen sollten

- Shell-, Datei- oder Coding-Werkzeuge von Codex,
- Mehragenten-Orchestrierung für normale Wissensfragen,
- einen riesigen Systemprompt als Ersatz für Architektur,
- autonome externe Aktionen ohne ausdrückliche Freigabe,
- pauschale Umschreibung jeder Nutzerfrage,
- den Codex-App-Server als technische Abhängigkeit.

Für Vinci ist die richtige Übernahme ein domänenspezifischer Wissens-Harness, keine Kopie eines Coding-Agenten.

## Empfohlener Migrationsplan

### Phase 0: Referenzfälle und Messung

Eine feste Testsammlung aus 30 bis 50 realen Anfragen anlegen, unter anderem:

- WPS-Anleitung ohne vorhandene Anleitung: keine erfundenen Schritte,
- WPS-Anleitung mit später vorhandener Anleitung: vollständige belegte Antwort,
- Personen- und Kontaktsuche,
- Abkürzungen wie TD, VK, NIE, HAN und SHG,
- Öffnungszeiten mit direkter Frage und Rückfrage,
- breite Prozessübersichten,
- Kundensperre, Werbewiderspruch und notwendige Klärungsfrage,
- gleiche Anfrage mit unterschiedlichen Benutzerrechten,
- Modellparität zwischen Vinci und Vinci-Thinking.

### Phase 1: Gemeinsamen Harness extrahieren

Routing, Aliasauflösung, Gesprächskontext und Werkzeugwahl aus Middleware und Guard in ein eigenes Modul verschieben. Zunächst im Schattenbetrieb ausführen und Entscheidungen mit dem bestehenden Ablauf vergleichen.

### Phase 2: Evidenzvertrag einführen

RAG liefert ein strukturiertes `EvidenceBundle`. Die Antwortkomponente erhält nur belegte Ausschnitte und einen `AnswerContract`. Die nachträgliche inhaltliche Guard-Umschreibung wird für Testkonten deaktiviert.

### Phase 3: Native Ereignisse vereinheitlichen

Toolstatus, Quellen und Rückfragen werden durch den Harness als native OpenWebUI-Ereignisse ausgegeben. Beide Modelle laufen durch denselben Pfad.

### Phase 4: Kontrollierter Rollout

Zuerst Testkonten, dann eine kleine Nutzergruppe, danach alle Nutzer. Für jede Stufe bleiben Rückfalloption und Vergleichswerte erhalten.

## Qualitäts- und Abnahmekriterien

- Anteil interner Fragen mit korrektem Werkzeugaufruf,
- Treffergenauigkeit der ausgewählten Quellen,
- Anteil vollständig belegter Aussagen,
- korrekte Enthaltung bei fehlender Evidenz,
- korrekte Rückfrage bei echter Mehrdeutigkeit,
- keine sichtbare nachträgliche Ersetzung einer Antwort,
- zuverlässige Quellen- und Feedbackanzeige,
- gleiche fachliche Qualität bei beiden Vinci-Modellen,
- Antwortzeit im Median und im 95. Perzentil.

Die finale Antwort muss separat vom Retrieval bewertet werden: Ein korrektes Toolergebnis garantiert noch keine korrekte Nutzerantwort. Genau dieser Unterschied erklärt einen Teil der aktuellen Vinci-Probleme.

## Offizielle OpenAI-Quellen

- [Harness engineering: leveraging Codex in an agent-first world](https://openai.com/index/harness-engineering/)
- [Unlocking the Codex harness: how we built the App Server](https://openai.com/index/unlocking-the-codex-harness/)
- [How GPT-5.6 fuses frontier intelligence with frontier efficiency](https://openai.com/index/gpt-5-6-frontier-intelligence-efficiency/)
- [Using GPT-5.4 – Prompting and workflow guidance](https://developers.openai.com/api/docs/guides/latest-model)
- [Agent evals](https://developers.openai.com/api/docs/guides/agent-evals)
- [Trace grading](https://developers.openai.com/api/docs/guides/trace-grading)

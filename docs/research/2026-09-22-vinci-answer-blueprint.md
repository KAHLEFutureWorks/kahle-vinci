# Bessere RAG-Antworten durch einen belegten Antwortbauplan

Stand: 22. September 2026

## Ergebnis

Der nächste sinnvolle Qualitätsschritt ist kein weiterer allgemeiner Systemprompt
und kein nachgelagerter Antwort-Guard. KAHLE-Vinci sollte vor dem einzigen
Antwortlauf einen strukturierten, vollständig aus der Evidenz erzeugten
`AnswerBlueprint` bereitstellen.

Der heutige Dokumentüberblick liefert bereits die sechs Überschriften. Die
fachlichen Details liegen jedoch weiterhin als umfangreiche, teilweise durch
OCR ergänzte Textblöcke im Werkzeugkontext. Das Modell muss deshalb gleichzeitig
die Dokumentstruktur erkennen, relevante Belege den Abschnitten zuordnen,
OCR-Rauschen ignorieren und die Antwort formulieren. Unterschiedliche Modelle
lösen diese vier Aufgaben unterschiedlich zuverlässig.

Der Antwortbauplan trennt diese Aufgaben:

1. Retrieval und Markdown-Struktur bestimmen die vollständigen Abschnitte.
2. Der Harness ordnet jedem Abschnitt ausschließlich vorhandene Belegausschnitte
   und Quellenkennungen zu.
3. Das Modell formuliert in einem einzigen Lauf aus diesem Bauplan die
   Nutzerantwort.
4. Die Qualitätsprüfung misst das Ergebnis offline oder beobachtend. Sie ersetzt
   die Antwort nicht und startet keinen zweiten Modelllauf.

## Was andere Harnesses dafür zeigen

### DSPy: Aufgabenvertrag statt immer längerer Prompt

DSPy beschreibt LLM-Aufgaben als strukturierte Signaturen mit benannten Ein- und
Ausgaben. Module können ihre Ausführungsstrategie ändern, ohne den fachlichen
Aufgabenvertrag neu zu schreiben. Optimierer testen Instruktionen und Beispiele
gegen eine definierte Metrik und speichern anschließend das beste Artefakt für
die spätere Nutzung. Das Training beziehungsweise Kompilieren findet damit
außerhalb der normalen Nutzeranfrage statt.

Für Vinci ist nicht die Einführung von DSPy selbst entscheidend. Übertragbar
sind drei Prinzipien:

- ein expliziter Vertrag zwischen Retrieval und Antwortmodell,
- ein messbares Qualitätsziel statt manueller Promptverlängerung,
- Offline-Optimierung, deren Ergebnis versioniert und im Betrieb nur gelesen wird.

DSPy weist außerdem darauf hin, dass Instruktionsoptimierung häufig besser
generalisiert als ein kleiner, schiefer Satz von Beispielen. Beispiele bleiben
nützlich, müssen aber gegen getrennte Referenzfälle geprüft werden.

Quellen:

- [DSPy: Program, don't prompt](https://dspy.ai/current/)
- [DSPy: Metrics and evaluation](https://dspy.ai/current/diving-deeper/metrics-and-evaluation/)
- [DSPy: Choosing an optimizer](https://dspy.ai/current/diving-deeper/choosing-an-optimizer/)

### Anthropic: Die Schnittstelle zum Modell ist oft der größere Hebel

Anthropic empfiehlt einfache, zusammensetzbare Workflows und betont die
Qualität der Werkzeuge und ihrer Schnittstellen. Im beschriebenen SWE-bench-
Beispiel wurde mehr Zeit in die Verbesserung der Werkzeuge als in den
Gesamtprompt investiert. Das passt zum Vinci-Befund: Das Modell braucht nicht
noch mehr allgemeine Anweisungen, sondern eine leichter verständliche und
schwerer misszuverstehende Evidenzschnittstelle.

Der ebenfalls beschriebene Evaluator-Optimizer-Workflow verwendet einen zweiten
Modelllauf und gegebenenfalls mehrere Wiederholungen. Das kann bei komplexen
Schreibaufgaben helfen, passt aber nicht zu Vincis gewünschtem Echtzeitpfad.
Dieses Muster sollte daher nur offline für Prompt- und Vertragsentwicklung
genutzt werden.

Quelle:

- [Anthropic: Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)

### OpenAI: Struktur mechanisch absichern, Qualität mit Evals entwickeln

Structured Outputs können ein Modell auf ein definiertes JSON-Schema festlegen
und damit fehlende Schlüssel oder ungültige Aufzählungswerte vermeiden. OpenAI
empfiehlt zugleich, das Schema anhand von Evaluationen für den konkreten
Anwendungsfall zu entwickeln. Für Vinci wäre eine vollständig strukturierte
Endausgabe technisch möglich, würde aber Streaming, Markdown-Darstellung und
Providerparität unnötig stark verändern.

Der passendere Einsatz liegt vor dem Antwortmodell: Der Harness erzeugt selbst
einen typisierten `AnswerBlueprint`. Das Modell erhält also strukturierte
Eingaben, darf die sichtbare Antwort aber weiterhin natürlich formulieren.

OpenAI empfiehlt eval-getriebene Entwicklung mit aufgabenspezifischen Fällen,
automatisierbarer Bewertung und regelmäßigem Abgleich mit menschlichem
Feedback. Der Prompt Optimizer benötigt dafür Datensätze mit Bewertungen oder
Grader-Ergebnissen. Dieses Prinzip lässt sich mit der vorhandenen Vinci-
Akzeptanzmatrix modellunabhängig umsetzen, ohne den Produktivpfad an einen
bestimmten Optimierer zu binden.

Quellen:

- [OpenAI: Structured model outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [OpenAI: Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices)
- [OpenAI: Prompt optimizer](https://developers.openai.com/api/docs/guides/prompt-optimizer)
- [OpenAI: Harness engineering](https://openai.com/index/harness-engineering/)

## Empfohlener Vinci-Vertrag

Der bestehende `EvidenceBundle` bleibt die belegte Faktenquelle. Für breite
Dokument- und Prozessfragen wird daraus zusätzlich ein Antwortbauplan erzeugt:

```json
{
  "schema_version": "kahle.answer-blueprint.v1",
  "intent": "document_overview",
  "sections": [
    {
      "section_id": "1",
      "heading": "Plantafel Teiledienst",
      "order": 1,
      "claims": [
        {
          "claim_id": "R1C1",
          "source_id": "R1",
          "evidence_span": "Zur Plantafel Teiledienst kommt ihr über den Reiter Plantafel ..."
        }
      ],
      "coverage": "supported"
    }
  ]
}
```

Für jeden Abschnitt gelten folgende Regeln:

- Die Reihenfolge stammt aus den nummerierten Markdown-Hauptüberschriften.
- Jeder fachliche Stichpunkt bleibt als eigener Belegausschnitt erhalten.
- Die Belege werden bereits im Harness dem richtigen Abschnitt zugeordnet.
- Automatisch erkannter Bildinhalt wird als `auxiliary_ocr` markiert und nicht
  gleichrangig mit dem redaktionellen Text behandelt.
- Fehlen zu einem Abschnitt belastbare Details, steht dort
  `coverage: missing`; das Modell erfindet keinen Ersatz.
- Quellenkennungen kommen ausschließlich aus demselben `EvidenceBundle`.

Der `AnswerContract` fordert anschließend nur noch, jeden Bauplanabschnitt in
derselben Reihenfolge verständlich zu erklären. Das Modell muss die
Dokumentstruktur nicht mehr rekonstruieren.

## Warum das besser zum aktuellen Fehler passt

Beim Dokument „Digitales Autohaus Teiledienst“ sind alle sechs Kapitel und die
zugehörigen Arbeitsschritte in `rag.md` vorhanden. Die Datei enthält zusätzlich
zwölf OCR-Blöcke aus Screenshots. Der aktuelle Harness kann die sechs
Kapitelüberschriften erkennen, reicht deren fachliche Inhalte aber nicht als
kompakte Abschnittseinheiten im Antwortvertrag weiter. Dadurch können Modelle
nur die ersten oder semantisch auffälligsten Passagen auswählen.

Ein AnswerBlueprint löst genau diese Lücke. Er ist keine fertige Antwort und
keine nachträgliche Korrektur. Er macht die vorhandene Evidenz für das Modell
lesbarer und erzwingt keine unbelegten Aussagen.

## Offline-Bewertung

Vor einer Aktivierung sollte ein kleiner, aber getrennter Referenzkorpus die
folgenden Maße prüfen:

- `section_coverage`: Sind alle erwarteten Abschnitte vorhanden?
- `claim_coverage`: Werden die wesentlichen Belege jedes Abschnitts erklärt?
- `grounding`: Lassen sich alle fachlichen Aussagen auf Claim-IDs zurückführen?
- `ordering`: Bleibt die dokumentierte Reihenfolge erhalten?
- `noise_avoidance`: Werden OCR-Fragmente nicht als eigenständige Fakten ausgegeben?
- `model_parity`: Erreichen Vinci, Thinking und Max denselben fachlichen Kern?

Deterministische Prüfer eignen sich für Reihenfolge, Abschnittsanzahl und
Quellenkennungen. Ein LLM-Grader kann ergänzend Verständlichkeit und fachliche
Abdeckung bewerten, aber ausschließlich offline. Stichproben mit menschlicher
Bewertung kalibrieren den Grader.

## Abgrenzung

Nicht empfohlen sind:

- weitere dokument- oder modellbezogene Sonderanweisungen im Systemprompt,
- eine hart codierte Antwort für dieses einzelne Teiledienst-Dokument,
- ein zweiter Produktivaufruf zur Bewertung und Neugenerierung,
- eine nachträgliche inhaltliche Ersetzung durch den Guard,
- die sofortige Einführung von DSPy, LangGraph oder einer weiteren Runtime-
  Abhängigkeit.

## Nächster Umsetzungsschritt

Als begrenzten Pilot sollte Vinci den `AnswerBlueprint` zunächst nur für
vollständig erkannte, nummerierte Dokumentübersichten erzeugen. Der Pilot nutzt
das vorhandene TD/DA-Dokument sowie mindestens zwei anders strukturierte
Prozessdokumente als Gegenprobe. Erst wenn die Offline-Matrix eine messbare
Verbesserung über alle drei Modelle zeigt, wird der Vertrag allgemein aktiviert.

## Stand des lokalen Piloten

Die erste Umsetzung übernimmt nur redaktionelle Claims in den kompakten
`AnswerBlueprint`. OCR-Claims bleiben im `EvidenceBundle` mit
`evidence_role: auxiliary_ocr` erkennbar, werden aber nicht zusätzlich im
Blueprint wiederholt. Das verhindert, dass umfangreicher erkannter Bildtext
die eigentlichen Arbeitsschritte im Bauplan verdrängt. Eine verbesserte
Modellantwort ist dadurch noch nicht belegt; dafür sind Browser- und
Modellvergleiche mit der Offline-Matrix erforderlich.

# Harness Phase 3b: Evidenzgesteuerte Vorabsuche und Rückbau des Werbewiderspruch-Sonderpfads

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**

- **Teil A:** Interne Prozessfragen bekommen immer Tool-Evidenz, auch wenn die alte Schlagwortsperre nicht anschlägt. Allgemeine Anleitungsfragen bleiben frei beantwortbar.
- **Teil B:** Der Werbewiderspruch-Sonderpfad entfällt. Die Prozessbeschreibung ist seit Task 6 aus Phase 3 über ihren Abschnitt „Suchbegriffe“ auffindbar.

**Ausgangslage (Messungen 01.10.):**

| Befund | Beleg |
| --- | --- |
| Mit Vorplanung führt der Harness `rag_chat` nur aus, wenn zusätzlich `_looks_like_internal_rag_request` anschlägt oder Abkürzung bzw. Organisationskontakt erkannt sind (`_plan_kahle_retrieval_gate`). | 16 Prozess-, Zuständigkeits- und Funktionskontaktfälle bleiben modellgeführt. Mistral antwortet dort sporadisch ohne Tool aus Allgemeinwissen. Status `not_run`, also ohne Antwortprüfung. |
| Der Planer erkennt keine Internheit. | „Wie koche ich Nudeln?“, „Wie beantrage ich einen Reisepass?“ und weitere ergeben `procedure/internal_processes`. Die Sammelart `internal_knowledge/internal_general` trifft auch „Hauptstadt von Frankreich“. |
| `rag_chat` trennt zuverlässig. | 7/7 allgemeine Anleitungsfragen: `FOUND=false`, Status `unsupported`, keine Quellen. Interne Fragen mit Dokument: `FOUND=true`. |
| Lücken im lokalen Korpus | „Rechnung stornieren“, „HU-Anmeldung“, „Garantieanfrage“: `FOUND=false`. |
| Der Werbewiderspruch-Sonderpfad ist für natürliche Formulierungen wirkungslos. | Probe `optout_generic_probe.py`: Mit und ohne Sonderpfad im Tool identisch. 7 von 8 Formulierungen finden die Prozessbeschreibung. Nur „am Standort Hannover“ landet beim Hannover-Standortdokument (allgemeine Standortlogik). |

**Architecture:**

- **Teil A:**
  - Neues Feld `RetrievalPlan.evidence_probe`.
  - `_plan_kahle_retrieval_gate` gibt den Plan auch dann zurück, wenn die Schlagwortsperre nicht anschlägt, aber eine spezifische Bedarfsart vorliegt (`procedure`, `functional_contact`, `functional_responsibility`, `workflow`, `opening_hours`, `system_usage_locations`). In diesem Fall ist `evidence_probe=True`.
  - Die Vorabsuche läuft dann still, ohne Status-Chip.
  - Findet sie Evidenz (`found` oder `clarification`): **gebunden**. Ab hier gilt der normale Harness-Pfad mit Vertrag, Prüfung und Korrektur.
  - Findet sie nichts: **verworfen**.
    - Kein Vertrag, keine Quellen-Chips.
    - `rag_chat` bleibt dem Modell verfügbar.
    - Ein kurzer Systemhinweis sagt dem Modell, dass die interne Suche nichts ergeben hat.
  - Die Sammelart `internal_knowledge/internal_general` bleibt ausgenommen.
- **Teil B:**
  - Die Harness-Umschreibung `_canonical_marketing_opt_out_query` entfällt. Damit werden alle an das Marker-Tripel gebundenen Sonderzweige tot, also Standortvertrag, Middleware-Zweige und Tool-Filter.
  - Diese Zweige werden in zwei Schritten entfernt.
  - Vor dem zweiten Schritt (Tool-Filter) gibt es eine Zwischenmessung.

**Tech Stack:** Python 3.11, pytest, Open WebUI v0.11.0-Overrides, `eval/harness`.

## Vorbereitung und Befehle

Branch `feat/harness-eval-foundation`. Edits an CRLF-Dateien nur mit dem Edit-Werkzeug oder mit Python-Skripten, die CRLF erhalten. Commits hängen am Exit-Code von pytest, nicht an grep.

```bash
P=./.venv-verify/Scripts/python.exe
$P -m pytest stack/tests/test_kahle_harness_phase3b.py -q -p no:cacheprovider
$P -m pytest stack/tests -q -p no:cacheprovider          # Ausgang: 1298 passed
$P -m pytest eval/harness/tests -q -p no:cacheprovider
```

## Dateistruktur

| Datei | Änderung |
| --- | --- |
| `eval/harness/routing_cases.yml` | 4 allgemeine Anleitungsfragen (`no_knowledge_tool`) |
| `eval/harness/harness_eval.py` | `evidence_probe` lesen und je Modell zählen |
| `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py` | Teil A: `RetrievalPlan.evidence_probe`. Teil B: Umschreibung und Marker-Zweige entfernen |
| `stack/open-webui-overrides/open_webui/utils/middleware.py` | Teil A: Gate, `_evidence_probe_outcome`, Freigabepfad, Metrik. Teil B: `temporary_survey_*`-Zweige entfernen |
| `stack/open-webui-functions/kahle_toolcall_guard.py` | Teil B: Marker-Zweige entfernen |
| `stack/open-webui-tools/rag_chat_hybrid_tool.py`, `hybrid_retrieval.py` (+ `dist/` per `build_tools.py`) | Teil B, Schritt 2: Sonderfilter entfernen |
| Create `stack/tests/test_kahle_harness_phase3b.py` | neue Tests |
| bestehende Tests mit Werbewiderspruch-Bezug | Teil B: anpassen oder entfernen, je Fall begründet |

---

## Teil A: Evidenzgesteuerte Vorabsuche

### Task 1: Korpus um allgemeine Anleitungsfragen ergänzen

**Files:** `eval/harness/routing_cases.yml`

- [ ] Vier Fälle der Kategorie `no_knowledge_tool` mit `expected_tools: []` und `findings: [P3b]` direkt nach `none_general_leasing` einfügen:
  - `none_howto_cooking`: „Wie koche ich Nudeln?“
  - `none_howto_pivot`: „Wie erstelle ich eine Pivot-Tabelle?“
  - `none_howto_passport`: „Wie beantrage ich einen Reisepass?“
  - `none_howto_flight`: „Wie storniere ich einen Flug bei Lufthansa?“
- [ ] `eval/harness/tests` → PASS (Korpusschema). Offline-Planer laufen lassen. Erwartung: Der Planer liefert für alle vier `rag_chat`; genau dieses Verhalten fängt Teil A ab.
- [ ] Commit `test(eval): add general how-to questions to the routing corpus`

### Task 2: `RetrievalPlan.evidence_probe` und Gate

**Files:** Harness, Middleware; Test `stack/tests/test_kahle_harness_phase3b.py`

- [ ] **Failing tests:**
  - `RetrievalPlan(...).evidence_probe` ist per Default `False` und steht in `to_dict()`.
  - Gate (AST-Loader wie in Phase 3, zusammen mit `_evidence_probe_kinds_match`), parametrisiert:

    | Fall | Erwartung |
    | --- | --- |
    | Schlagwortsperre falsch, Bedarf `procedure` | Plan mit `evidence_probe=True` |
    | Schlagwortsperre wahr, Bedarf `procedure` | Plan mit `evidence_probe=False` |
    | Schlagwortsperre falsch, nur `internal_knowledge` | `None` |
    | Schlagwortsperre falsch, Bedarf `procedure`, `rag_chat` nicht in `tools_dict` | `None` |
    | `harness_mode='off'` | unverändert wie heute |
    | Bedarf `personio_directory` | unverändert, kein Probe-Flag |
- [ ] **Implement:**
  - Feld `evidence_probe: bool = False` am Dataclass `RetrievalPlan` samt Serialisierung.
  - In der Middleware: `_EVIDENCE_PROBE_KINDS` und `_evidence_probe_kinds_match(plan)`.
  - Im Gate nach dem bestehenden RAG-Zweig: `if 'rag_chat' in required_tools and 'rag_chat' in tools_dict and _evidence_probe_kinds_match(plan): return replace(plan, evidence_probe=True)`.
- [ ] `stack/tests` vollständig → PASS
- [ ] Commit `feat(harness): mark specific internal needs for an evidence-gated pre-search`

### Task 3: Gebunden oder verworfen

**Files:** Middleware; Tests in `test_kahle_harness_phase3b.py`

- [ ] **Failing tests:**
  - `_evidence_probe_outcome(plan, rag_outcome)`:

    | Eingabe | Ergebnis |
    | --- | --- |
    | Probe und `found` | `bound` |
    | Probe und `clarification` | `bound` |
    | Probe und `missing` | `released` |
    | Probe und `''` | `released` |
    | `forbidden` | `bound` (Zugriffsverweigerung bleibt geschlossen) |
    | kein Probe-Plan | `''` |
  - `_evidence_probe_release_prompt()` liefert den Hinweistext, siehe die Entscheidung unten.
  - Statische Tests am Quelltext:
    - Für einen Probe-Plan wird `emit_prerouted_rag_status` erst bei `bound` gesetzt.
    - Bei `released` werden `kahle_retrieval_tools` geleert, die Vorab-Quellen aus `sources` entfernt und keine Harness-Entscheidung gebaut.
    - `pre_routed_internal_rag` wird auf `''` gesetzt, damit `rag_chat` in den nativen Tools bleibt.
  - Metrik: `_knowledge_harness_routing_metric_fields` übernimmt `metadata['kahle_evidence_probe']`.
- [ ] **Implement:**
  - Beide Hilfsfunktionen.
  - Im Pre-Route-Block: Bei `evidence_probe` werden der Vorab-Status nicht gesendet und die Quellen erst nach der Bewertung übernommen.
  - Bei `released`: Hinweis über `add_or_update_system_message(..., append=True)` anhängen. Qwen akzeptiert keine späten Systemnachrichten; dieser Weg führt sie wie bei der Harness-Anweisung zusammen.
  - Bei `bound`: den abgeschlossenen Status-Output senden und normal weiterlaufen.
- [ ] `stack/tests` vollständig → PASS
- [ ] Commit `feat(middleware): bind or release the evidence-gated pre-search by its result`

**Abweichung bei der Umsetzung (02.10., `375d312`):**

- Der Hinweis bei verworfener Vorabsuche wird nicht per `add_or_update_system_message(..., append=True)` an die Systemnachricht angehängt.
- Stattdessen geht er über `metadata['_kahle_final_answer_prompt']`, der den Text an die Systemnachricht und direkt an die letzte Nutzernachricht hängt.
- Grund: Am Ende des langen System-Prompts hat Mistral den Hinweis ignoriert und eine Rechnungsstornierung mit allgemeinen Schritten beantwortet. Neben der Nutzernachricht nennt Mistral zuerst die fehlende interne Evidenz.

### Task 4: Eval-Auswertung

**Files:** `eval/harness/harness_eval.py`; Tests `eval/harness/tests`

- [ ] **Failing test:** `score_answer` übernimmt `evidence_probe` aus `kahle_harness_metrics`. `summarize_answers` zählt je Modell `probe_bound` und `probe_released`.
- [ ] Routing bleibt an tatsächlich gebundenen oder vom Modell gerufenen Tools gemessen. Eine verworfene Vorabsuche zählt nicht als Tool-Aufruf.
- [ ] Commit `test(eval): report bound and released evidence probes`

## Teil B: Rückbau des Werbewiderspruch-Sonderpfads

### Task 5: Umschreibung entfernen, Marker-Zweige in Harness, Middleware und Guard

**Files:** Harness, Middleware, Guard; bestehende Tests

- [ ] **Failing tests** (`test_kahle_harness_phase3b.py`):
  - `resolve_request("Wie sperre ich einen Kunden für Werbung am Standort Walsrode?", []).retrieval_query` ist die unveränderte Frage.
  - Quelltext ohne `_canonical_marketing_opt_out_query`, `temporary_survey_opt_out` und `temporary_survey_without_location`.
  - Die Rückfrage zur Kundensperre bleibt erhalten, `_customer_lock_followup_query` liefert aber eine natürliche Frage:
    - „Wie hinterlege ich einen Werbewiderspruch in Vaudis{ am Standort X}?“
    - Bei allgemeiner Sperre unverändert.
- [ ] **Implement:**
  - Umschreibung an beiden Stellen in `resolve_request` entfernen.
  - `_marketing_opt_out_query`, `_opt_out_contract_scope` und `_SUPPORTED_OPT_OUT_LOCATIONS` entfernen. Den `location_mode`-Vertrag für diesen Prozess entfernen, damit verschwindet auch der ~7.000-Zeichen-Zwang.
  - In der Middleware entfallen `temporary_survey_opt_out` im Gate und im Pre-Route samt Direktausführung sowie der Standortzweig in `full_output`.
  - Im Guard entfallen die Marker-Zweige.
- [ ] Bestehende Tests mit Werbewiderspruch-Bezug je Fall entscheiden:
  - Tests des entfernten Verhaltens werden gelöscht.
  - Personenschutz-, Kontakt- und Zitierprüfungen bleiben bestehen und werden auf natürliche Fragen umgestellt.
  - Jede Löschung steht mit Begründung in der Commit-Nachricht.
- [ ] `stack/tests` vollständig → PASS
- [ ] Commit `refactor(harness): retire the marketing opt-out query rewrite and its contract`

### Task 6: Zwischenmessung

- [ ] Ausrollen (`deploy_branch.sh`, Container neu erstellen).
- [ ] Laufzeit-Eval für die Kategorien `scope_location` und `followup`, alle drei Modelle.
- [ ] Antwort-Probe: Für die vier natürlichen Werbewiderspruch-Fragen und die Befragungsfrage nennt die Antwort die Standorte Hannover, Wunstorf und Wedemark. Für andere Standorte nennt sie `datenschutz@kahle.de`. Ausgelieferte blockierende Verstöße: 0. Länge je Antwort.
- [ ] **Gate:** Routing nicht schlechter als `2026-10-01-runtime-phase3-hybrid.json` (±1 je Kategorie) und die Inhalts-Probe bestanden. Sonst Stopp und Rückmeldung an den Nutzer.

### Ergebnis Task 6 (01.10.) und Revision (02.10.)

**Gate nicht bestanden, Rückbau zurückgenommen** (`88f7456`, Revert `a2dfbfb`):

- Routing: bestanden (`scope_location` 6/6 je Modell, `followup` je 4/6, keine ausgelieferten blockierenden Verstöße).
- Inhalt: nur 4 von 18 Werbewiderspruch-Antworten nannten drei Standorte und `datenschutz@kahle.de`. gpt-oss enthielt sich in 4 von 6 Fällen.

**Ursache (gemessen 02.10., `optout_evidence_probe.py`, `optout_missing_probe.py`):**

| Anfrage | Belegte Aussagen | Status | Begründung des Tools |
| --- | --- | --- | --- |
| „Wie hinterlege ich einen Werbewiderspruch in Vaudis?“ (natürlich) | 132 | `partially_supported` | „enthalten aber keine ausreichende Anleitung“ |
| umgeschriebene Passivfrage „Wie wird … durchgeführt?“ | 132 | `supported` | – |

- Die Belegmenge ist gleich. Entscheidend ist die Anleitungserkennung: `_context_has_procedure` (Tool) und `_procedure_is_supported` (Harness) zählen nur die Verben öffnen, navigieren, klicken, wählen, eingeben, erfassen, speichern, bestätigen, erstellen und brauchen drei verschiedene Treffer.
- Das Dokument beschreibt seine Schritte als nummerierte Liste mit aufrufen, öffnen, entfernen, dokumentieren, eintragen, prüfen, wiederherstellen. Davon trifft nur „öffnen“.
- Natürliche „Wie …?“-Fragen gelten als Anleitungsfrage und werden deshalb herabgestuft. Die Passivfrage der Umschreibung umging diese Prüfung.
- Die Umschreibung hat also einen Fehler der Anleitungserkennung verdeckt. Er betrifft jedes Dokument mit anderen Verben.

**Revidierte Reihenfolge für Teil B:**

#### Task 5a: Anleitungserkennung strukturell machen

**Files:** `rag_chat_hybrid_tool.py` (+ `dist/`), Harness; Tests `test_kahle_harness_phase3b.py`

- [ ] **Failing tests** für beide Erkennungen (Tool über den Bundle-Loader, Harness direkt):
  - Eine nummerierte Liste mit mindestens drei Schritten, von denen mindestens einer mit einem Handlungsverb beginnt, ist eine Anleitung (synthetischer Auszug im Stil der Werbewiderspruch-Schritte).
  - Fließtext, der nur „öffnen“ erwähnt, ist keine Anleitung.
  - Eine nummerierte Faktenliste ohne Handlungsverb (Standorte, Öffnungszeiten) ist keine Anleitung.
  - Die bisherigen Verbfälle bleiben grün.
- [ ] **Implement:**
  - Gemeinsame Regel in beiden Modulen, entweder mindestens drei verschiedene Handlungsverben oder mindestens drei nummerierte Schritte mit mindestens einem Handlungsverb.
  - Die Verbliste wird um aufrufen, eintragen, entfernen, dokumentieren, prüfen, auswählen, anlegen, ausfüllen, hinterlegen, aktivieren/deaktivieren erweitert.
  - Danach `build_tools.py` und `--check`.
- [ ] `stack/tests` vollständig → PASS. Commit `fix(rag): recognise numbered step lists as procedures`.
- [ ] Ausrollen. `optout_missing_probe.py` → natürliche Werbewiderspruch-Fragen `supported`.

#### Task 5b: Rückbau erneut anwenden

- [ ] `git revert a2dfbfb` (stellt `88f7456` wieder her), `stack/tests` → PASS.
- [ ] Zwischenmessung wie Task 6.
- [ ] Fällt die Inhaltsprüfung nur wegen fehlender Standortnennung durch, folgt eine dokumentgetriebene Prompt-Regel: „Nennt eine Quelle einen Geltungsbereich, gib ihn an und nenne den dokumentierten Weg für alle anderen Fälle.“ Danach erneut messen.
- [ ] Anderes Scheitern: Stopp und Rückmeldung.

### Task 7: Tool-Sonderfilter entfernen

**Files:** `rag_chat_hybrid_tool.py`, `hybrid_retrieval.py`, `dist/`; Tests `test_hybrid_retrieval_security.py`, `test_rag_evidence_bundle_contract.py`

- [ ] **Failing tests:** Quelltext ohne `temporary_survey_` und `_marketing_opt_out_query`. Bestehende Sicherheitstests der Hybridsuche (ACL, Zugriffsfilter) bleiben unverändert grün.
- [ ] **Implement:** Die Sonderfilter entfernen, danach `build_tools.py`, dann `build_tools.py --check`.
- [ ] `stack/tests` vollständig → PASS
- [ ] Commit `refactor(tools): drop the marketing opt-out retrieval filters`

### Task 8: Verify, Ausrollen, Messung

- [ ] Full Verify → Exit 0
- [ ] Ausrollen.
- [ ] Voller Laufzeit-Eval → `eval/harness/results/2026-10-0X-runtime-phase3b.json`
- [ ] Antwort-Probe aus Task 6 wiederholen.
- [ ] Zusammenfassung committen.

## Abnahme Phase 3b

- Routing je Modell mindestens so gut wie in `2026-10-01-runtime-phase3-hybrid.json` (±2 Rauschen).
- Fälle mit Status `not_run` bei internen Prozessfragen, für die der Korpus ein Dokument hat: 0.
- Die vier neuen allgemeinen Anleitungsfragen werden beantwortet, keine Enthaltung, kein Quellen-Chip.
- Keine ausgelieferten blockierenden Verstöße.
- Werbewiderspruch-Inhalts-Probe bestanden. Die Walsrode-Antwort ist deutlich kürzer als 7.000 Zeichen.

## Bekannte Grenzen

- Korpuslücken (Rechnung stornieren, HU-Anmeldung, Garantieanfrage) werden zu verworfenen Vorabsuchen. Sie zeigen sich im Eval als `probe_released` bei erwartetem `rag_chat` und sind Inhaltsarbeit, kein Harness-Fehler.
- Die Formulierung „am Standort Hannover“ zieht das Standortdokument vor die Prozessbeschreibung. Die allgemeine Standortlogik ist nicht Teil dieses Plans. Der Fall `scope_natural_hannover` macht es messbar.

## Ergebnis (05.10.) und Abschluss

Nutzerentscheidung 05.10.:
- Phase 3b schließt mit Teil A und den beim Rückbau gefundenen Korrekturen ab.
- Der Sonderpfad bleibt aktiv.
- Der Rückbau folgt als Phase 3c, mit dem Geltungsbereich als Evidenzrolle, Vertragspflicht und Korrekturaufruf.

**Beim Rückbau gefundene und behobene Fehler:**

- `828782d`: Die Anleitungserkennung kannte nur neun Verben. Nummerierte Schrittlisten galten deshalb als „keine ausreichende Anleitung“.
- `cae6329`: Die Pflicht-Flags der Vorabsuche (`_kahle_force_rag_tool_call`, `_kahle_pre_route_rag_call`, `_kahle_information_needs`) lagen in einer Metadaten-Kopie, die `chat_completion_tools_handler` nicht liest. Statt des geplanten Aufrufs entschied das Task-Modell; gpt-oss rief kein Tool auf.
- `70e4b71`: Die Harness-Metriken erklären den Evidenzstatus (`contract_origin`, `prerouted_rag`, `rag_call_count`, `evidence_missing`).
- `62ec5a2`: Prompt-Regel zum Geltungsbereich. Ohne Sonderpfad brachte sie keine messbare Wirkung (5 von 18 vollständig).

**Full Verify:** 13/13 Bereiche bestanden, Exit 0.

**Voller Laufzeit-Eval** (106 Fälle, Sonderpfad aktiv, `2026-10-05-runtime-phase3b.json`):

| Modell | korrekt | gemeinsame 102 (Hybrid 01.10.) | Fehler | ausgelieferte blockierende Verstöße | verworfene / gebundene Vorabsuchen |
| --- | --- | --- | --- | --- | --- |
| Mistral | 98/106 | 94 (91) | 0 | 0 | 8 / 7 |
| gpt-oss | 97/106 | 93 (95) | 0 | 0 | 8 / 7 |
| Qwen | 98/106 | 94 (94) | 0 | 0 | 8 / 7 |

**Abnahme:**

| Kriterium | Ergebnis |
| --- | --- |
| Routing ±2 | erfüllt |
| Allgemeine Anleitungsfragen | 4/4 je Modell korrekt, ohne Enthaltung |
| Ausgelieferte blockierende Verstöße | 0 |
| `not_run` bei internen Fragen mit Dokument | nicht ganz erfüllt, siehe unten |
| Werbewiderspruch-Inhalt (mit Sonderpfad) | 16 von 18 vollständig. Beide Lücken bei „Der Kunde will keine Werbung mehr bekommen …“ (Mistral, gpt-oss: Kontakt ja, drei Standorte nein) |
| Walsrode-Antwort deutlich kürzer | nicht erfüllt (3.055–7.710 Zeichen). Hängt am Rückbau, geht in Phase 3c |

**Zu `not_run` bei internen Fragen mit Dokument:**

- Verbleibend sind `followup_scope_location_reply` (alle Modelle), `responsibility_lease_returns` (Mistral) und `internal_complaint_notes` (gpt-oss).
- Sie haben nur die Sammelart `internal_knowledge` bzw. sind Standort-Folgeantworten und sind deshalb bewusst von der Vorabsuche ausgenommen.

**Zur Bewertung von gpt-oss (−2):** Die Abweichung kommt aus den Korpuslücken. HU-Anmeldung ×2, Rechnungsstorno und Garantieanfrage werden jetzt als verworfene Vorabsuche mit Hinweis frei beantwortet, statt dass das Modell ergebnislos `rag_chat` aufruft.

# Harness Phase 3c: Geltungsbereich als Evidenzpflicht, danach Rückbau des Werbewiderspruch-Sonderpfads

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Antworten aus Dokumenten mit eingeschränktem Geltungsbereich nennen diesen Bereich und den dokumentierten Weg für alle anderen Fälle. Die Pflicht ergibt sich aus der Evidenz, nicht aus fest eingebauten Standortnamen. Danach entfällt der Werbewiderspruch-Sonderpfad samt Anfrage-Umschreibung, Standortvertrag und Tool-Sonderfiltern.

**Ausgangslage (Phase 3b, 05.10.):**

| Befund | Beleg |
| --- | --- |
| Mit Sonderpfad sind 16 von 18 Werbewiderspruch-Antworten vollständig, ohne Sonderpfad 5–6 von 18. | Zwischenmessungen 01.–05.10. |
| Ohne Sonderpfad ist die Evidenz gleich gut (`supported`, Geltungsbereich und Kontakt in den Aussagen), die Modelle nennen den Geltungsbereich aber selten. | Diagnosemetriken `70e4b71`, Probe `optout_evidence_probe.py` |
| Die vollständigen Antworten kommen aus fest eingebauten Texten. | `KAHLE_KNOWLEDGE_LOCATION_CONTEXT` im Harness und `_rag_final_response_instruction` im Tool nennen Hannover, Wunstorf, Wedemark und `datenschutz@kahle.de` wörtlich. |
| Eine reine Prompt-Regel wirkt nicht. | `62ec5a2`: 5 von 18 |
| Das Prozessdokument nennt seinen Geltungsbereich nur als Tabellenzeile („Geltungsbereich \| Servicebereiche der Standorte Hannover (HAN), Wunstorf (WUN) und Wedemark (WED)“). | Der Weg für andere Standorte kommt aus dem typisierten Funktionskontakt `datenschutz@kahle.de` mit Gültigkeitsfeld „Alle KAHLE-Standorte außer Hannover, Wunstorf …“. |
| 17 Portaldokumente enthalten eine Geltungsbereich-Angabe. | `kb-portal-data/files/**/rag.md` (nur gezählt, nicht als Architektur-Evidenz) |

**Architecture:**

- **Geltungsbereich-Pflicht (Harness):**
  - `_scope_requirements(evidence)` erkennt in belegten, redaktionellen Aussagen einen einschränkenden Geltungsbereich.
  - Erkannt werden die Formen „Geltungsbereich …“ sowie „gilt nur / ausschließlich für …“.
  - Pflicht wird er nur, wenn er eine echte Teilmenge der KAHLE-Standorte (`_REQUEST_LOCATIONS`) nennt.
  - Der Ausnahmeweg ist ein typisierter Funktionskontakt, dessen `scope` mit „außer“ bzw. „alle anderen“ genau diese Standorte ausnimmt.
  - Ergebnis: `{"source_id", "locations", "exception_contacts"}`. Es gibt keine fest eingebauten Prozess- oder Standorttexte.
- **Vertrag und Prompt:**
  - Das neue Feld `AnswerContract.required_scope` füllen beide Vertragswege (`build_decision`, `build_result_driven_decision`).
  - `answer_prompt()` ergänzt einen allgemeinen Satz, der die Werte aus der Evidenz nennt.
- **Validator:**
  - Der neue blockierende Code `required_scope_missing` greift, wenn ein Pflicht-Standort oder ein Ausnahmekontakt fehlt.
  - Im modellgeführten Modus wird die Pflicht wie die übrigen Prüfungen aus der Evidenz neu berechnet.
  - Enthaltungen sind ausgenommen.
  - `retry_prompt` nennt die fehlenden Werte. Der vorhandene einmalige Korrekturaufruf erledigt den Rest.
- **Rückbau:** Erst wenn die Pflicht wirkt, werden `07f2209` (Harness, Middleware, Guard) und danach die Tool-Sonderfilter zurückgenommen, jeweils mit Inhalts-Gate.

**Tech Stack:** Python 3.11, pytest, Open WebUI v0.11.0-Overrides, `eval/harness`.

## Vorbereitung und Befehle

Branch `feat/harness-eval-foundation`, Ausgang `e7adaff`.

- Edits an CRLF-Dateien nur mit dem Edit-Werkzeug oder mit Python-Skripten (Write-Werkzeug, keine Heredocs mit Backslashes), die CRLF erhalten.
- Commits hängen am Exit-Code von pytest.
- Nie `git revert --no-commit` offen lassen und dabei andere Dateien committen.

```bash
P=./.venv-verify/Scripts/python.exe
$P -m pytest stack/tests/test_kahle_harness_phase3c.py -q -p no:cacheprovider
$P -m pytest stack/tests -q -p no:cacheprovider          # Ausgang: 1335 passed
$P -m pytest eval/harness/tests -q -p no:cacheprovider   # Ausgang: 41 passed
```

**Messungen:**
- Laufzeit-Eval je Modell getrennt, da Hintergrundaufgaben nach 30 Minuten enden.
- Inhalts-Probe: `optout_answer_check.py` (Scratchpad) nach Läufen mit `--keep-chats`.
- Vor jeder Messung `/health` prüfen, weil Docker Desktop über Nacht ausfällt.

## Dateistruktur

| Datei | Änderung |
| --- | --- |
| `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py` | `_scope_requirements`, `AnswerContract.required_scope`, Prompt-Satz, Validator-Code, Retry-Anweisung |
| `stack/open-webui-overrides/open_webui/utils/middleware.py` | Task 5: Kundensperren-Rückfrage nutzt die Harness-Funktion |
| `stack/open-webui-tools/rag_chat_hybrid_tool.py`, `hybrid_retrieval.py`, `dist/` | Task 6: Sonderfilter und fest eingebaute Standort-Anweisung entfernen |
| Create `stack/tests/test_kahle_harness_phase3c.py` | neue Tests |
| bestehende Tests mit Werbewiderspruch-Bezug | Task 4 und 6: je Fall entscheiden und begründen |

---

### Task 1: Geltungsbereich erkennen

**Files:** Harness; Test `test_kahle_harness_phase3c.py`

- [ ] **Failing tests** mit synthetischen Bundles im Format des `rag_chat`-Bundles (Fixture wie `_rag_result` in `test_kahle_harness_contact_literals.py`):
  - Eine Tabellenzeile „Geltungsbereich | Servicebereiche der Standorte Hannover (HAN), Wunstorf (WUN) und Wedemark (WED)“ plus ein Funktionskontakt `datenschutz@kahle.de` mit `scope` „Alle KAHLE-Standorte außer Hannover, Wunstorf und Wedemark“ ergeben eine Pflicht mit `locations=("Hannover", "Wunstorf", "Wedemark")` und `exception_contacts=("datenschutz@kahle.de",)`.
  - „Diese Anleitung gilt nur für Walsrode.“ ergibt eine Pflicht ohne Ausnahmekontakt.
  - „Geltungsbereich: alle KAHLE-Standorte“ ergibt keine Pflicht, weil der Bereich nicht einschränkend ist.
  - Eine Aussage, die Standorte nur aufzählt („In Hannover und Wunstorf gibt es …“), ergibt keine Pflicht.
  - Ein Funktionskontakt ohne passende Ausnahme ergibt keinen Ausnahmekontakt.
  - Aussagen mit `evidence_role != "editorial"` oder ohne Quelle werden nicht berücksichtigt.
  - `unsupported`-Evidenz ergibt keine Pflicht.
- [ ] **Implement** `_scope_requirements(evidence: EvidenceBundle) -> tuple[dict[str, Any], ...]`.
- [ ] `stack/tests` → PASS. Commit `feat(harness): recognise restrictive document scopes in the evidence`.

### Task 2: Vertrag und Prompt

**Files:** Harness; Test `test_kahle_harness_phase3c.py`

- [ ] **Failing tests:**
  - Beide Vertragswege füllen `answer_contract.required_scope` aus der Evidenz.
  - Ohne Geltungsbereich bleibt das Feld leer.
  - `answer_prompt()` enthält den allgemeinen Satz: „Die Quellen begrenzen ihren Geltungsbereich auf {Standorte}. Nenne diesen Geltungsbereich und für alle anderen Fälle den dokumentierten Weg ({Kontakte}).“
  - Der Satz entsteht nur aus Evidenzwerten. Bei leerem Feld fehlt er.
- [ ] **Implement:** das Feld `required_scope: tuple[dict[str, Any], ...] = ()` sowie Prompt-Satz und Serialisierung.
- [ ] `stack/tests` → PASS. Commit `feat(harness): carry the documented scope into the answer contract`.

### Task 3: Validator und Korrekturaufruf

**Files:** Harness; Tests `test_kahle_harness_phase3c.py`, `eval/harness/tests` (Codeliste)

- [ ] **Failing tests:**

  | Antwort | Erwartung |
  | --- | --- |
  | ohne Wedemark | `required_scope_missing` (blocking) mit `missing_locations=["Wedemark"]` |
  | ohne `datenschutz@kahle.de` | `missing_contacts` |
  | Enthaltungstext | keine Verletzung |
  | im modellgeführten Modus aus Evidenz neu berechnet | ein manipuliertes `required_scope` im serialisierten Vertrag wird ignoriert |

  `retry_prompt` nennt die fehlenden Werte: „Nenne den Geltungsbereich aus der Evidenz: … Nenne für alle anderen Fälle: …“.
- [ ] **Implement:** den Code in `BLOCKING_VIOLATION_CODES`, die Prüfung in `validate_answer` und die Anweisung in `retry_prompt`. Das Eval kennt die Codes über `BLOCKING_VIOLATION_CODES`; prüfen, ob `harness_eval` eine eigene Liste führt, und angleichen.
- [ ] `stack/tests` und `eval/harness/tests` → PASS. Commit `feat(harness): require the documented scope before delivery`.
- [ ] **Zwischenmessung mit Sonderpfad:**
  - Ausrollen, `scope_location` für alle Modelle, Inhalts-Probe.
  - Erwartung: weiterhin ≥ 16 von 18, keine neuen Enthaltungen, Routing unverändert.
  - Andere Prozessfragen dürfen nicht leiden. `procedure` und `internal_knowledge` je Modell mitmessen und mit Phase 3b vergleichen (±1).

### Task 4: Rückbau Harness, Middleware, Guard

- [ ] `git revert 07f2209` (stellt `4fb27d0` wieder her), Konflikte nur in Testdateien erwartet (beide Seiten behalten).
- [ ] Die Kontaktbindung im Vorabsuche-Weg aus `4fb27d0` bleibt (personenfreie RAG-Kontakte, Personio nur auf Kontaktfrage).
- [ ] `stack/tests` → PASS. Commit.
- [ ] **Gate:**
  - Ausrollen, `scope_location` + `followup` für alle Modelle.
  - Inhalts-Probe ≥ 15 von 18. Die bekannte Hannover-Lücke (Standortdokument statt Prozessbeschreibung) ist ausgenommen und wird getrennt ausgewiesen.
  - Routing nicht schlechter als Phase 3b (±1 je Kategorie), keine ausgelieferten blockierenden Verstöße.
  - Walsrode-Antwort unter 4.000 Zeichen bei mindestens zwei Modellen.
  - Sonst Stopp und Rückmeldung.

### Task 5: Kundensperren-Rückfrage zusammenführen

**Files:** Middleware, Guard; Tests

- [ ] **Failing tests:**
  - Die Middleware-Variante liefert für dieselben Eingaben dasselbe wie `_customer_lock_followup_query` des Harness. Parametrisiert werden „Werbung“, „Werbung für Walsrode“, „Nienburg“, „allgemein“.
  - Die Guard-Variante (eigenständig ausgerollte Function) wird über dieselbe Tabelle geprüft.
- [ ] **Implement:**
  - Die Middleware ruft die Harness-Funktion. Ihr bisheriger eigener Zweig entfällt.
  - Der Guard bleibt eine Kopie, weil er eigenständig ausgerollt wird; ein gemeinsamer Tabellentest hält ihn gleich.
- [ ] `stack/tests` → PASS. Commit `refactor(middleware): use the harness customer-lock follow-up`.

### Task 6: Tool-Sonderfilter entfernen

**Files:** `rag_chat_hybrid_tool.py`, `hybrid_retrieval.py`, `dist/`; Tests `test_hybrid_retrieval_security.py`, `test_rag_evidence_bundle_contract.py`

- [ ] **Failing tests:**
  - Der Quelltext enthält kein `temporary_survey_`, kein `_marketing_opt_out_query`, kein `_prioritize_marketing_opt_out_evidence` und keine Standortnamen in `_rag_final_response_instruction`.
  - `full_procedure` hängt nur noch an `document_overview`.
  - Die Sicherheitstests der Hybridsuche (ACL, Zugriffsfilter) bleiben unverändert grün.
- [ ] **Implement**, danach `build_tools.py` und `--check`.
- [ ] `stack/tests` → PASS. Commit `refactor(tools): drop the marketing opt-out retrieval filters`.
- [ ] **Gate** wie Task 4.

### Task 7: Verify, Ausrollen, Messung

- [ ] Full Verify → Exit 0
- [ ] Ausrollen.
- [ ] Voller Laufzeit-Eval je Modell → `eval/harness/results/2026-10-XX-runtime-phase3c.json`.
- [ ] Inhalts-Probe.
- [ ] Zusammenfassung und Abschluss im Plan, Commit.

## Abnahme Phase 3c

- Keine fest eingebauten Werbewiderspruch-Texte, Marker oder Standortlisten außerhalb von `_REQUEST_LOCATIONS` in Harness, Middleware, Guard und Tool.
- Werbewiderspruch-Inhalts-Probe ≥ 15 von 18. Die Hannover-Lücke wird getrennt ausgewiesen.
- Routing je Modell mindestens wie in `2026-10-05-runtime-phase3b.json` (±2), keine ausgelieferten blockierenden Verstöße.
- Walsrode-Antworten deutlich kürzer als bisher (Median unter 4.000 Zeichen).

## Bekannte Grenzen

- **„am Standort Hannover“** findet das Standortdokument statt der Prozessbeschreibung (allgemeine Standortlogik der Suche, eigener Folgeschritt).
- **Pflicht gilt für alle 17 Dokumente.** Die Geltungsbereich-Pflicht greift nicht nur beim Werbewiderspruch, sondern bei jedem Dokument mit einschränkendem Geltungsbereich. Das ist gewollt, kann aber für dort belegte Antworten zusätzliche Korrekturaufrufe auslösen. Task 3 misst `procedure` und `internal_knowledge` deshalb mit.
- **Korpuslücken** (HU-Anmeldung, Rechnungsstorno, Garantieanfrage) bleiben Inhaltsarbeit.

# Functional Contact Evidence Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freigegebene Funktionskontakte aus strukturierten Dokumenttabellen statt Textklassifikation übernehmen und den begonnenen Release A lokal vollständig abnehmen.

**Architecture:** Ein reiner Python-Vertrag definiert Tabellenformat, Kontaktwerte und typisierte Evidenz. Der vorhandene Bundle-Builder verteilt denselben Quellstand an Indexer, RAG-Tool und Harness. Der bestehende Retrieval-/Freigabepfad bleibt führend; nur explizit validierte Kontakte erhalten eine Ausgabefreigabe.

**Tech Stack:** Python, bestehende Markdown-Verarbeitung, Qdrant/BM25, OpenWebUI-Overrides und Tool-Bundles, Docker Compose, pytest, Windows PowerShell.

**Spec:** `docs/superpowers/specs/2026-09-03-functional-contact-evidence-contract-design.md`, ergänzt `docs/superpowers/specs/2026-09-01-model-led-knowledge-routing-design.md`.

**Aktuelle Freigabe vom 3. September 2026:** Zuerst ohne neue Ausgabesperre,
Korrekturlauf oder Ersatzantwort testen. Task 5 wurde auf Beobachtung umgestellt.
Zusatzprüfung erst als gesonderter Test bei gehäuften, reproduzierbaren Fehlern.
Keine automatische Aktivierung und kein unbelegter Fehlerquoten-Grenzwert.

## Global Constraints

- Persönliche Kontakte kommen ausschließlich aus Personio.
- Das Modell wählt Werkzeuge und formuliert die Antwort weiterhin selbst.
- Eine zweite Kontaktverwaltung und eine neue Pflegeoberfläche sind nicht nötig.
- Qdrant und BM25 bleiben abgeleitete Indizes.
- Alias-Schlüssel, Kollisionen, unbekannte Felder und unpassende Datentypen werden nicht nachträglich normalisiert.
- Noch nicht übertragene Kontakte aus Fließtext werden vorübergehend nicht als Funktionskontakte ausgegeben. Normales Prozesswissen bleibt nutzbar.
- Eine Tabelle legitimiert niemals eine aktuelle Personen- oder Führungskräfteaussage aus RAG.
- Quellenlinks und Feedbacklinks behalten ihre separate technische Zulassung und begründen keine Kontaktfreigabe.
- Tests und Berichte verwenden synthetische Personen und reservierte Werte. Keine realen Quellen automatisch umschreiben oder veröffentlichen.
- Kein Push, Merge, Produktionsrollout oder ursprünglicher Task 10. Lokale Aktivierung erst nach dem Offline-Gate.
- Python-Dienste mit eigenem `app` getrennt testen. Quelle und erzeugte Kopien gemeinsam ändern und prüfen.
- Freitextsemantik ist kein deterministisch beweisbarer Teil des Vertrags. Keine neue allgemeine Personenklassifikation und keine Routing-Wortlisten.

## Recovery und Reihenfolge

Ausgangspunkt ist Dokumentationscommit `d5b7920`. Der spätere Planungscommit
ändert nur Dokumentation. Prüfe vor Ausführung den tatsächlichen HEAD.
Uncommittete Änderungen gehören zum gesicherten Round-4-Zwischenstand:

- `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py`
- `stack/tests/test_kahle_knowledge_harness.py`

Nicht zurücksetzen. Die 58 fokussiert grünen Vertragstests sind kein vollständiges
Gate; 28 semantische Regressionen waren zuletzt bewusst rot. Der Bericht liegt
unter `.superpowers/sdd/2026-09-01-model-led-knowledge-routing/task-5-report.md`.
Lesen, nicht überschreiben. Dieser neue Plan erhält seinen eigenen SDD-Arbeitsraum
und eigenen Ledger. Die alten Tasks 1–4 sind fertig und werden nicht wiederholt.

| Neuer Task | Bezug zum ursprünglichen Plan | Abhängigkeit |
| --- | --- | --- |
| 1 | neuer zentraler Kontaktvertrag | keine Runtime-Aktivierung |
| 2 | ursprünglicher Task 6 plus Kontaktindexierung | 1 |
| 3 | RAG-Produzent und Retrieval | 2 |
| 4 | Abschluss des angepassten ursprünglichen Tasks 5 | 1–3 |
| 5 | ursprünglicher Task 7 plus Kontaktseitenprüfung | 4 |
| 6 | ursprünglicher Task 8 plus Kontaktmigration | 5 |
| 7 | ursprünglicher Task 9 und gesamtes Abschluss-Gate | 1–6 |

Die geänderte Reihenfolge ist durch den freigegebenen Quellenvertrag nötig:
Der Harness kann typisierte Kontakte erst nach ihrem Produzenten vollständig
prüfen. Bis Task 5 abgeschlossen ist, bleibt `model_led` lokal deaktiviert.
Vor jeder Task-Grenze nur dessen exakte Pfade stagen, Diff prüfen und reviewen.

## Datei- und Distributionskarte

| Datei | Aufgabe |
| --- | --- |
| `stack/open-webui-tools/functional_contact_contract.py` (neu) | einzige handgepflegte Formatdefinition, Parser, Wert-/Datensatzprüfung |
| `stack/open-webui-tools/build_tools.py` | Vertrag in Bundles einbetten und zwei bytegleiche Laufzeitkopien erzeugen; `--check` prüft alles |
| `stack/kb-sync/app/functional_contact_contract.py` (erzeugt) | Kopie für bestehendes KB-Sync-Docker-Build-Context |
| `stack/open-webui-overrides/open_webui/utils/functional_contact_contract.py` (erzeugt) | Kopie für Harness; zusätzlicher Read-only-Mount |
| `stack/kb-sync/app/hybrid_index.py`, `hybrid_sync.py` | vollständige Kontaktzeilen, Hint-Klassifikation und Payloads |
| `stack/open-webui-tools/hybrid_retrieval.py` | ACL-geprüfte Kontakte, versionierte Zeilenherkunft und Konfliktauflösung |
| `stack/open-webui-tools/rag_chat_hybrid_tool.py` | typisierte Claims statt Freitext-Kontaktfreigabe |
| `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py` | tatsächliche Evidenz, vollständige Kontaktzuordnungen, Finalvalidierung |
| `stack/open-webui-overrides/open_webui/utils/middleware.py` | Ausgabe erst nach Validierung, maximal ein Korrekturlauf |

Kein Import eines anderen Dienstes namens `app`. Der Vertrag benötigt nur die
Standardbibliothek. Die erzeugten Dateien sind keine unabhängig gepflegten
Implementierungen. Der vorhandene Docker-Build-Kontext von KB-Sync bleibt gleich.

## Verbindliches Interface

```python
CONTACT_SCHEMA = "kahle.functional-contact.v1"
CONTACT_HEADER = ("Funktion", "Kontaktart", "Kontaktwert", "Verwendungszweck", "Geltungsbereich")
CONTACT_CHANNELS = {"E-Mail": "email", "Telefon": "phone", "Kontaktseite": "url"}

# Reine Funktionen, keine Netzwerk-/Datei-/Modellzugriffe:
def parse_functional_contacts(markdown: str, *, max_row_chars: int = 900) -> tuple[dict, ...]: ...
def validate_functional_contact(value: object) -> dict | None: ...
def functional_contact_key(contact: dict) -> tuple[str, str, str, str]: ...
def extract_contact_literals(text: str) -> tuple[tuple[str, str], ...]: ...
```

Ein Parserdatensatz besitzt exakt diese Schlüssel, ohne zusätzliche Felder:

```python
{
    "schema_version": "kahle.functional-contact.v1",
    "function": "Marketing", "channel": "email",
    "value": "marketing@example.invalid", "purpose": "Marketinganfragen",
    "scope": "gruppenweit", "row_number": 4,
    "evidence_span": "| Marketing | E-Mail | marketing@example.invalid | Marketinganfragen | gruppenweit |",
}
```

`row_number` ist eine positive, einsbasierte Zeilennummer im normalisierten
kanonischen Markdown ohne Frontmatter. Der Parser läuft auf diesem vollständigen
Text vor beliebiger Chunk-Aufteilung. Alle Fachfelder sind nichtleere Strings;
`row_number` ist ein Integer, kein Boolean. Die fünf Zellen werden nur außen
getrimmt. Keine normalisierten Aliasfelder und keine stillschweigende Typkonversion.
`functional_contact_key` liefert `(function, channel, purpose, scope)` exakt.

Das Qdrant-Payload erhält `functional_contact` mit diesem Datensatz und
`functional_contact_key` als SHA-256 des kanonisch JSON-serialisierten Schlüssels.
Dokument-/Versionsbezug bleibt auf dem vorhandenen Payload. `chunk_kind` ist
`functional_contact`; ein Punkt entspricht einer vollständigen Zeile.
Die Fachfelder kommen nicht aus der Nutzerfrage oder einem Modellparameter.

Ein funktionaler Claim hat exakt die bisherigen sieben RAG-Schlüssel plus
`functional_contact`. `claim_type` ist `functional_contact`; `text` und
`evidence_span` sind die exakte vollständige Zeile. Der passende Quelleneintrag
trägt dieselbe geprüfte Kontaktstruktur. Der Harness prüft Gleichheit von
Zeile, Struktur und Dokument-/Versionsbezug, nicht allein das Typetikett.

Quellenvertrauen stammt aus dem internen Werkzeugaufruf und seinem kontrollierten
Produzenten, nicht aus einer Selbstbehauptung im JSON. Modelltexte und zitierte
Marker werden niemals als Toolresultat aufgenommen. Ein kompromittierter
Indexer ist dadurch nicht kryptografisch abgesichert; keine solche Garantie behaupten.

---

### Task 1: Zentralen Kontaktvertrag und prüfbare Distribution anlegen

**Files:** Create `stack/open-webui-tools/functional_contact_contract.py`,
`stack/tests/test_functional_contact_contract.py`; modify `stack/open-webui-tools/build_tools.py`,
`stack/docker-compose.yml`, `stack/tests/test_open_webui_override_contracts.py`;
generate beide Laufzeitkopien aus der Dateikarte und die beiden bisherigen
Bundles `dist/rag_chat_hybrid_tool.py`, `dist/kahle_workflow_orchestrator.py`.

**Consumes:** kanonisches Markdown. **Produces:** die vier Funktionen und das
exakte Datensatzformat aus dem verbindlichen Interface, in allen drei Laufzeiten.

- [ ] Neue Tests laden die kanonische Datei mit dem vorhandenen importlib-Muster als `contract`. Schreibe zuerst diesen Test:

```python
def test_exact_functional_contact_row(contract):
    row = "| Marketing | E-Mail | marketing@example.invalid | Marketinganfragen | gruppenweit |"
    text = "\n".join(("## Funktionskontakte", "| Funktion | Kontaktart | Kontaktwert | Verwendungszweck | Geltungsbereich |", "| --- | --- | --- | --- | --- |", row))
    records = contract.parse_functional_contacts(text)
    assert len(records) == 1
    assert records[0]["row_number"] == 4
    assert records[0]["evidence_span"] == row
    assert records[0]["value"] == "marketing@example.invalid"
    assert contract.validate_functional_contact(records[0]) == records[0]
    assert contract.validate_functional_contact(dict(records[0], Value="other@example.invalid")) is None
```

- [ ] RED: `& .\.venv-verify\Scripts\python.exe -m pytest stack/tests/test_functional_contact_contract.py -q -p no:cacheprovider`.
- [ ] Parser als zeilenweisen Zustandsautomaten implementieren: Frontmatter vor Aufruf entfernen, CRLF normalisieren; Markdown-Fences mit Backticks oder Tilden überspringen; Heading-Stack führen. Nur Tabellen unter exakt `Funktionskontakte` außerhalb von `Für Fragen wie`, `Beispielanfragen`, `Suchbegriffe`, `Synonyme`, `Kurzindex` aufnehmen. Keine Erkennung von Überschriften innerhalb Fences.
- [ ] Genau fünf Header und Separatorzellen verlangen. Fehlender/falscher Header verwirft den Block. Jede Datenzeile getrennt prüfen; leere Zellen, zusätzliche Zellen, HTML/Markdown-Link als Wert, Zeilenumbruch im Wert oder Zeile über `max_row_chars` verwerfen. Keine Fortsetzungsreparatur.
- [ ] Wertprüfung zentral implementieren: E-Mail mit vollständigem Syntaxmatch; Telefon aus bestehendem synthetisch getesteten Telefonvertrag inklusive Datumsausschluss; URL mittels `urllib.parse.urlsplit`, Scheme exakt HTTPS, nichtleerer Host, keine Zugangsdaten/Steuerzeichen. Nicht fetchten. Literalextraktion erkennt E-Mail, Telefon, HTTPS-/HTTP-URLs und Mailto-Ziele für die spätere Verbotsprüfung; dieselben Werte werden nicht durch Extraktion freigegeben.
- [ ] Distribution im vorhandenen Builder implementieren, ohne Build-Kontextänderung:

```python
CONTRACT_SOURCE = TOOLS_DIR / "functional_contact_contract.py"
CONTRACT_TARGETS = (
    TOOLS_DIR.parent / "kb-sync/app/functional_contact_contract.py",
    TOOLS_DIR.parent / "open-webui-overrides/open_webui/utils/functional_contact_contract.py",
)
```

Die Quelldatei erhält einen Hinweis auf erzeugte Kopien. Kopien bytegleich
erzeugen. Vertrag vor Retrieval in beide Bundles einbetten; ausschließlich den
zu diesem eingebetteten Modul gehörenden Import aus Bundles entfernen. Quellmodule
behalten reguläre Imports. `--check` muss bei jeder abweichenden Kopie fehlschlagen.
Tests richten ihren isolierten Importpfad ein; kein Runtime-Import eines fremden `app`.

- [ ] Read-only-Mount neben bestehendem Harness-Mount hinzufügen: `${KAHLE_ROOT:?KAHLE_ROOT is required}/stack/open-webui-overrides/open_webui/utils/functional_contact_contract.py:/app/backend/open_webui/utils/functional_contact_contract.py:ro`. Härtung unangetastet lassen.
- [ ] GREEN inklusive parametrischer Fälle für alle Kontaktarten, falsche Header, Fences, Suchhilfe-Vorfahren, ungültige/überlange Einzelzeilen und Kopiendrift. Builder ausführen, `--check`, Compose-Static-Check und Override-Contracts ausführen.
- [ ] Nur Task-1-Dateien committen: `feat(knowledge): define canonical functional contact contract`. Geerbte Harness-/Teständerungen bleiben unstaged.

### Task 2: Vollständige Kontaktzeilen indexieren und ursprünglichen Task 6 integrieren

**Files:** Modify `stack/kb-sync/app/hybrid_index.py`, `hybrid_sync.py`,
`stack/kb-sync/tests/test_hybrid_index.py`, `test_hybrid_sync.py`.

**Consumes:** `parse_functional_contacts` aus Task 1. **Produces:**
`ChildChunk.functional_contact: dict | None = None`, `kind='functional_contact'`
oder `kind='retrieval_hint'`; Payload gemäß Interface in Full- und Einzelsync.

- [ ] Failing Test zur Zeilenatomizität ergänzen:

```python
def test_contact_child_never_contains_other_contact():
    markdown = "\n".join(("## Funktionskontakte", "| Funktion | Kontaktart | Kontaktwert | Verwendungszweck | Geltungsbereich |", "| --- | --- | --- | --- | --- |", "| IT | E-Mail | it@example.invalid | Störungen | gruppenweit |", "| Marketing | E-Mail | marketing@example.invalid | Kampagnen | gruppenweit |"))
    children = ParentChildChunker().chunk("synthetic-doc", markdown)
    contacts = [child for child in children if child.kind == "functional_contact"]
    assert len(contacts) == 2
    assert contacts[0].functional_contact["function"] == "IT"
    assert "marketing@example.invalid" not in contacts[0].parent_content
    assert contacts[0].content == contacts[0].parent_content
```

- [ ] RED: isoliert `& .\.venv-verify\Scripts\python.exe -m pytest stack/kb-sync/tests -q -p no:cacheprovider`.
- [ ] Parser vor `_split_table` anwenden. Gültige Zeilen aus normaler Tabellenaufteilung ausnehmen, unverändert als atomare Kontaktchunks übernehmen. Ungültige Zeilen erhalten niemals typisierten Payload; Dokumenttext darf als generische Evidenz bestehen bleiben, ohne Kontaktfreigabe.
- [ ] Kontrollierte Hint-Überschriften aus Task 1 als `retrieval_hint` markieren, einschließlich Unterabschnitten. Keine beliebigen Sätze mit „Frage“ klassifizieren. Die vorhandenen ursprünglichen Task-6-RED-Tests bleiben maßgeblich.
- [ ] In `reindex` und `sync_document` denselben Payload-Aufbau für Kontaktfelder verwenden. Dokumentvalidierung, Staging, Publikationswechsel und Rollback erhalten. Einen Keyword-Index für `functional_contact_key` ergänzen. `HYBRID_SCHEMA_VERSION=3` bleibt unverändert, da die Erweiterung additiv ist; Kontaktpayload besitzt seine eigene v1-Kennung. Altdaten ohne Vertrag gelten niemals als Kontakte.
- [ ] GREEN: Full- und Einzelsync, atomare Zeilen, ungültige/überlange Zeilen, Freigabe-/Versionsfehler und Hinweis-Chunks isoliert testen.
- [ ] Commit: `feat(rag): index approved contact rows and retrieval hints`.

### Task 3: ACL-geprüfte Kontaktzeilen als typisierte RAG-Claims liefern

**Files:** Modify `stack/open-webui-tools/hybrid_retrieval.py`,
`rag_chat_hybrid_tool.py`, `stack/tests/test_hybrid_retrieval_security.py`,
`test_rag_evidence_bundle_contract.py`; regenerate beide `dist`-Bundles.

**Consumes:** Payload aus Task 2. **Produces:**
`RetrievedChunk.chunk_kind: str = 'text'`, `functional_contact: dict | None = None`
und funktionale Claims/Quelleneinträge gemäß Interface.

- [ ] Test mit vorhandenen `load_tool`, `configured_tool`, `chunk`, `evidence_from_result` schreiben. Eine generische Passage mit Adresse darf keinen funktionalen Claim erzeugen:

```python
def test_plain_prose_never_becomes_functional_claim(monkeypatch):
    module = load_tool()
    tool = configured_tool(module, monkeypatch, [chunk("Marketing nutzt marketing@example.invalid.")])
    result = asyncio.run(tool.rag_chat("Wie erreiche ich Marketing?", __user__={"id": "user-1"}))
    claims = evidence_from_result(result)["supported_claims"]
    assert all(claim["claim_type"] != "functional_contact" for claim in claims)
```

- [ ] RED für Kontakte plus bestehende Hint-/Nullüberlappungsregressionen: `& .\.venv-verify\Scripts\python.exe -m pytest stack/tests/test_hybrid_retrieval_security.py stack/tests/test_rag_evidence_bundle_contract.py -q -p no:cacheprovider`.
- [ ] Vor Verarbeitung jedes Such-/Erweiterungsergebnisses ACL, aktive Version, Veröffentlichung, `valid_from` und `valid_until` defensiv prüfen. Fehlende/ungültige Datumswerte ablehnen. Nicht erst nach dem Reranking prüfen. Vorhandenen `mandatory_acl_filter` bei jedem Qdrant-Aufruf verwenden.
- [ ] Hints dürfen nur bereits ACL-geprüfte Dokument-/Versions-IDs auf antwortbare Chunks erweitern. Vor Reranker, Kontext und Claims entfernen. Kontaktchunks dürfen niemals durch Parent-/Kapitelaggregation mit anderen Zeilen aufgefüllt werden. Kontaktkontext ist exakt die ausgewählte Zeile.
- [ ] Für jeden relevanten Kontakt-Key dessen andere autorisierte aktive Treffer über den bestehenden Qdrant-HTTP-Adapter und `/points/scroll` prüfen. Filter ist Mandatory-ACL plus exakter `functional_contact_key`, nie Titel oder Modellparameter. Pagination verarbeiten, maximal 10 Seiten mit je 100 Punkten. Timeout oder verbleibender Offset nach dem Limit bedeutet `functional_contact_conflict_check_incomplete`: keine Werte dieses Keys freigeben. Nicht autorisierte Treffer dürfen keinen sichtbaren Konflikt auslösen.
- [ ] Identische Fachdatensätze dürfen mehrere Quellen tragen. Verschiedene Werte desselben Keys ergeben `functional_contact_conflict`: alle betroffenen Werte zurückhalten, Teilbelegstatus/Missing Information erhalten. Unabhängige Kontakte bleiben verwendbar. Kein „erster Treffer gewinnt“.
- [ ] Quelleneintrag und Claim aus derselben validierten Kontaktstruktur bauen. `claim_id` folgt dem vorhandenen `R{number}C{index}`-Format; `source_id` bleibt `#{number}`. Keine Fachfelder aus Prompt oder dokumentweiter Capability ableiten. Generische Claims verwenden weiterhin vorhandene Textlogik.
- [ ] `_claim_evidence_spans` gibt bei bester Überlappung null `[]` zurück. Positiv belegte Sätze und bestehende Konfliktverarbeitung erhalten. Funktionale Claims brauchen keine Satzzerlegung, nur die ausgewählte vollständige Zeile.
- [ ] GREEN zusätzlich für stale/expired Payload, manipulierte Suchantwort, Pagination, versteckte Konflikte, gültige Kontaktseite, falsches Typetikett und typisierte Zeile mit unpassendem Evidence-Span. Builder und `--check` ausführen.
- [ ] Commit: `feat(rag): emit source-bound functional contact evidence`.

### Task 4: Angepassten result-driven Harness fertigstellen

**Files:** Modify `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py`,
`stack/tests/test_kahle_knowledge_harness.py`, `test_kahle_internal_knowledge.py`;
modify `kahle_internal_knowledge.py` nur für tatsächlich nötige Ergebnisprüfung.

**Consumes:** tatsächliche interne Toolresultate und Task-3-Claims.
**Produces:** `AnswerContract.allowed_contact_bindings: tuple[dict, ...] = ()`.
Jede Bindung enthält `source_kind`, `source_id`, `claim_id`, `channel`, `value`;
RAG zusätzlich `function`, `purpose`, `scope`, `document_id`, `version_id`,
`row_number`. Personio bekommt keine erfundene Funktion.
`allowed_contact_values` wird aus diesen validierten Bindungen abgeleitet.

- [ ] Geerbten Diff und Round-4-Bericht prüfen. ID-/Alias-/Collision-Fixes bewahren. Neue semantische Tests einzeln dem neuen Vertrag zuordnen: Kontaktfreigabe aus Fließtext verbieten, Prozessbeleg nicht wegen vermeintlichem Namen verwerfen. Keine unabhängigen Personen-/Supervisor-Tests löschen oder abschwächen.
- [ ] Failing Test durch öffentliche Entscheidungsschnittstelle schreiben:

```python
def test_model_led_plain_text_contact_is_not_authorized():
    harness = load_harness()
    raw = "KAHLE_RAG_RESULT\nEVIDENCE_BUNDLE_JSON: " + json.dumps({
        "schema_version": "kahle.evidence-bundle.v1", "status": "supported",
        "sources": [{"number": 1, "document_id": "d1", "version_id": "v1"}],
        "supported_claims": [{"claim_id": "R1C1", "source_id": "#1", "text": "Erika Beispiel ist Ansprechpartnerin. E-Mail: erika@example.invalid."}],
        "missing_information": [], "conflicts": [],
    })
    decision = harness.build_result_driven_decision(
        called_tools=("rag_chat",), query="Wie läuft die Anfrage ab?", messages=[],
        model_id="kahle-vinci", permission_scope={"user_id": "user-1"},
        rag_result=raw,
    )
    assert decision is not None
    assert decision.answer_contract.allowed_contact_values == ()
    assert decision.answer_contract.allowed_contact_bindings == ()
```

Ergänze einen separaten positiven Prozessbeleg ohne aktuelle Personenbehauptung:
„Öffne das Portal und erfasse die Anfrage; Rückfragen an team@example.invalid.“
Der Prozessbeleg bleibt erhalten, beide Kontaktfreigaben bleiben leer.

- [ ] RED und abschließendes GREEN mit der exakten früheren Task-5-Suite:

```powershell
& .\.venv-verify\Scripts\python.exe -m pytest stack/tests/test_kahle_knowledge_harness.py stack/tests/test_kahle_internal_knowledge.py stack/tests/test_middleware_internal_rag_routing.py stack/tests/test_open_webui_override_contracts.py -q -p no:cacheprovider
```
- [ ] Quell-/Claim-IDs und exakte Schlüssel vor Inhaltsverarbeitung prüfen. Funktionale Struktur gegen Quelleneintrag, Zeile, Dokument, Version und Task-1-Validator vergleichen. Direkte EvidenceBundle-Eingänge gleich prüfen. `unsupported` bleibt ohne ausgabefähige Kontakte; partial niemals aufwerten.
- [ ] Im `model_led`-Pfad Bindungen nur aus bestätigten funktionalen Claims bzw. validierten Personio-Kontaktfeldern ableiten. Kein Freitext-/Evidence-Span-Scan als Freigabequelle. Legacy behält seinen abgegrenzten bisherigen Pfad.
- [ ] Nur die Kontaktzweige der Namens-/Satzheuristiken ersetzen. Personenfelder und Supervisor-Beziehungen bleiben Personio-gebunden; kein Aufbau einer neuen Fachwortliste. Bei einem verbleibenden unabhängigen Architekturproblem ausdrücklich eskalieren.
- [ ] Answer-Prompt erhält vollständige Bindungen, verlangt zeilengetreue Zuordnung und keine Quellenergänzung. Kein Harness-generierter fachlicher Antworttext. Bestehende Dateien-/Formulare-/Mail-Direktantworten unangetastet lassen.
- [ ] GREEN: beide RAG-only/Personio-not-found-Pfade, typisierte Kontakte, generisches Prozesswissen, strukturierte Tampering-Fälle, Schlüssel-Kollisionen, fehlende IDs, Monotonie, gemischte Evidenz. Exakte Task-5-Suite ausführen und reporten.
- [ ] Commit: `fix(knowledge): authorize contacts from typed source bindings`. Angepassten ursprünglichen Task 5 erst nach Review als abgeschlossen ausweisen.

### Task 5: Antworten zunächst nur beobachten, nicht blockieren

**Änderungsfreigabe vom 3. September 2026:** Der Nutzer hat zuerst Modellführung
und Tests ohne zusätzliche Ausgabesperre gewählt. Dieser Abschnitt ersetzt
den früheren Task 5 mit Pufferung, Korrekturlauf und Ersatzantwort vollständig.

**Files:** Modify `stack/open-webui-overrides/open_webui/utils/middleware.py`,
`kahle_knowledge_harness.py`, `stack/tests/test_middleware_internal_rag_routing.py`,
`test_kahle_knowledge_harness.py`; Reporter und Reporttests aus Task 6 für
beobachtete Qualität statt erzwungener Freigabe ergänzen.

**Consumes:** tatsächliche EvidenceBundles und vollständige Kontaktbindungen.
**Produces:** Beobachtungsmetadaten mit `mode: shadow`, getrenntem
`delivery_status: observed` und unverändertem Prüfergebnis
`final_validation_status`. Keine Garantie fehlerfreier Modellantworten.

- [ ] Bestehende Kontakt-/Linkprüfungen als reine Beobachtung erhalten. Der Rückgabewert darf keine Ausgabe sperren, ersetzen oder einen Modellaufruf auslösen. Den uncommitteten neuen Ersatzantwortzweig entfernen; bestehende betriebliche Timeoutbehandlung nicht mit einem Kontaktguard verwechseln.
- [ ] RED-Verhaltenstests: Eine Antwort mit unbelegtem Kontakt bleibt unverändert; die Beobachtung meldet den Verstoß. Auch Fehler der Beobachtung verändern die Antwort nicht und werden als `observation_error` ohne Rohdaten markiert. Alle Textteile der sichtbaren Antwort berücksichtigen.
- [ ] `model_led` verwendet keine Legacy-Frageheuristik zur anfänglichen Ausgabesperre. Allgemeine Antworten behalten Streaming. Legacy und unabhängige Schutzprüfungen für Zugriffe, Dateien und externe Aktionen bleiben unverändert.
- [ ] Beobachtung verwendet tatsächliche Quellen und separat geprüfte aktuelle technische Links. Keine generischen Textkontakte als Freigabe; Quellen- und Linktext bleiben getrennt. Diagnosen enthalten keine Kontaktwerte.
- [ ] Reporter unterscheidet Auslieferung und Qualität: `observed` allein ist kein bestandenes Ergebnis. Fehlende Beobachtung, erkannte Verstöße und Beobachtungsfehler bleiben sichtbar. Keine automatisch aktivierte Zusatzprüfung.
- [ ] GREEN: vierteilige bisherige Zielsuite sowie `stack/tests/test_kahle_harness_acceptance_report.py`, danach Full Verify. Keine Live-Modellabnahme aus Offline-Fixtures ableiten.
- [ ] Commit nach Review: `feat(knowledge): observe contact answers without blocking delivery`.

### Task 6: Outcome-Matrix, Vorlage und Migrationsanleitung

**Files:** Modify `scripts/openwebui/kahle-harness-acceptance.py`,
`kahle-harness-acceptance-matrix.json`, `stack/tests/test_kahle_harness_acceptance_report.py`,
`docs/KAHLE-VINCI-UI-ABNAHME-HARNESS.md`; create
`docs/templates/funktionskontakte.md`, `docs/operations/functional-contact-evidence.md`.

**Consumes:** ausgeführte Toolereignisse und validierte Quellen-/Kontaktarten.
**Produces:** ursprünglicher Task-8-Vertrag plus neue Kontakt-Abnahmefälle.

- [ ] RED-Tests auf vorhandenen Report-Fixtures erweitern:

```python
assert set(case["required_tools"]).issubset(run["actual_tools"])
assert set(run["actual_tools"]).issubset(case["allowed_tools"])
assert set(case["expected_source_kinds"]).issubset(run["validated_source_kinds"])
```

Die Assertions stehen in konkreten Report-Tests für fehlendes Pflichttool,
zusätzliches Webtool, fehlende Quelle und allgemeine Unterhaltung ohne Tools;
die Fixture-Feldnamen werden mit dem existierenden Reporter abgeglichen und
genau dort migriert, nicht durch einen zweiten Reporter ersetzt.

- [ ] RED/GREEN: `& .\.venv-verify\Scripts\python.exe -m pytest stack/tests/test_kahle_harness_acceptance_report.py -q -p no:cacheprovider`.
- [ ] Strikte aktuelle Personenfälle Personio-only; Funktionskontaktfälle RAG-only; explizit gemischte Fälle beide. Mehrdeutige Bereichskontakte RAG erforderlich, Personio zusätzlich zulässig. `actual_tools` nur aus Ausführung, niemals Legacy-Plan.
- [ ] Neue synthetische Fälle: bestätigte Kontaktzeile für jede Art, unmigrierter Fließtext, fehlender/mehrdeutiger Geltungsbereich, kollidierende Zeilen, unzugängliche/alte Version, falsche Funktion bei richtigem Wert, Hint-Treffer und fehlerhafte Antwort ohne Ersatz. Auffälligkeiten messen, nicht durch einen Korrekturlauf verdecken. Alte Supervisor-Folgefragen und kompakte Nomenphrasen erhalten.
- [ ] Vorlage enthält außerhalb des kopierbaren Tabellenabschnitts die Pflegeanleitung; unter `## Funktionskontakte` nur exakte Header und Separator, keine fingierten Produktivkontakte. Anleitung erklärt Verantwortlichkeit, Veröffentlichung, neue Version, Konflikte, vorübergehendes Nichtnennen und Rollback-Grenze.
- [ ] Saved Reports nur Fallkennung, technische Status-/Tool-/Quellenarten und boolesche Resultate; keine Rohfragen, Antworten, Belege oder Kontaktwerte. Commit: `test(knowledge): add typed contact acceptance and migration guide`.

### Task 7: Lokales Release-A-Abschluss-Gate

**Files:** Modify `stack/docker-compose.local-edge.yml`, `stack/env.production.template`,
`stack/tests/test_personio_directory_contracts.py`, `docs/operations/personio-directory.md`,
`ARCHITECTURE.md`, `DECISIONS.md`, `docs/VERIFICATION.md`.

**Consumes:** alle vorherigen grünen Task-Reviews. **Produces:** vollständige
lokale Release-A-Abnahme, niemals einen Produktionsnachweis.

- [ ] Failing Contracttest zur allein lokalen Aktivierung ergänzen:

```python
assert "KAHLE_KNOWLEDGE_ROUTING_MODE: model_led" in local_overlay_text
assert "KAHLE_KNOWLEDGE_ROUTING_MODE:-legacy" in base_compose_text
```

Die Strings an die vorhandene YAML-Schreibweise binden; zusätzlich YAML-Werte
prüfen, damit Kommentare den Test nicht erfüllen. Basis/Produktion bleiben legacy.

- [ ] Alle isolierten gezielten Suiten aus ursprünglichem Task 9 ausführen. Danach zwingend:

```powershell
.\scripts\run-local-tests.ps1 -Tier Full -Python .\.venv-verify\Scripts\python.exe -Npm npm.cmd
```

Produktfehler stoppen das Gate. Reproduzierbares Sandbox-`spawn EPERM` mit
demselben Build außerhalb der Sandbox prüfen. Keine Fehler als Erfolg umdeuten.

- [ ] Vor lokalem Start Mount-Herkunft prüfen: `KAHLE_ROOT` muss die zu testenden Dateien tatsächlich bereitstellen. Keine Dateien ungefragt in `C:/kahle-vinci` kopieren. Eine Worktree-/Host-Abweichung ist ein Setup-Problem, kein Rolloutnachweis. Geschützte Env nur über `scripts/start-stack.ps1`; keine aufgelöste Compose-Ausgabe.
- [ ] Lokale Dienste KB-Sync (neue erzeugte Datei im Image), Personio und OpenWebUI kontrolliert neu bauen/erstellen. Vor Reindex bestehende lokale Wiederherstellungsmöglichkeit prüfen und Collection-/Aliaszustand datensparsam sichern. Keine Originalquellen ändern. Kanonischen `/reindex-all`-Aufruf aus ursprünglichem Task 9 verwenden, nur HTTP-Status und Erfolgsboolean berichten.
- [ ] Matrix für KAHLE-Vinci, Thinking und Max-Thinking ausführen. Positive Kontaktfälle benötigen eine ausdrücklich kontrollierte synthetische, freigegebene Testquelle. Fehlt die dafür notwendige lokale Freigabe-/Testdatenmöglichkeit, Abnahme als blockiert melden; keine echten Dokumente oder Freigaben automatisch ersetzen. Kein automatisches Umschreiben realer Kontakte.
- [ ] UI unter `http://localhost:3004` mit Browser-Skill prüfen: sichtbare Tools, Quellen-/Feedbacklinks, Streaming ohne neue Antwortsperre oder Ersatz, Supervisor-Folgekontext, unmigrierte Kontaktquelle. Fehlerhafte Zwischenwerte ausdrücklich erfassen und bewerten, nicht nachträglich verstecken. Für unabhängige Namen frische Chats verwenden.
- [ ] Dokumentation aus verifiziertem Verhalten aktualisieren: ADR-008, Kontaktquellenmatrix, neue erzeugte Kopien, lokale Aktivierung, Reindex und Rückfall auf alte Legacy-Regeln. Kein „produktiv installiert“ behaupten.
- [ ] Commit nur verifizierte Dokumentation/Aktivierung: `chore(knowledge): verify model-led functional contacts locally`.
- [ ] Abschließenden Review über die gesamte Release-A-Änderung seit `508deb7` durchführen, nicht nur seit diesem Plan. Erst bei erfüllten Tests/Abnahmen Release A abschließen. Task 10 bleibt freigabepflichtig. Kurze nutzbare Testprompts und einen nichttechnischen Teams-Text mitliefern.

## Plan-Selbstprüfung

| Spezifikation | Abdeckung |
| --- | --- |
| Format, Wertprüfung, keine KI-Klassifikation | Task 1 |
| Freigabe, aktive Version, Rechte, alter Index | Tasks 2–3, 7 |
| Zeilenatomizität, zentrale Definition, erzeugte Distribution | Tasks 1–3 |
| Herkunft, exakte Keys, direkte Bundle-Eingänge | Tasks 3–4 |
| Personio-/RAG-Quellenhoheit, Prozesswissen bleibt nutzbar | Tasks 4–5 |
| Konflikte ohne versteckte Quellenlecks | Task 3 |
| Beobachtung ohne Antwortersatz, Quellen-/Feedbacklinks | Task 5 |
| Redaktionelle Vorlage, Übergangsregel, datensparsame Matrix | Task 6 |
| Neuindexierung, Full, drei Modelle, UI, kein Produktionsrollout | Task 7 |

Die Funktionsnamen und Datensatzfelder sind in einem gemeinsamen Interface
definiert. Referenzierte frühere Tasks dienen nur dem belegten Rückbezug; die
ausführungsrelevanten Änderungen und Gates sind hier ausdrücklich beschrieben.
Bei einem neuen load-bearing Sicherheitsproblem nicht weitere heuristische
Fixrunden anhängen, sondern Ursache und Vertragskonflikt offenlegen.

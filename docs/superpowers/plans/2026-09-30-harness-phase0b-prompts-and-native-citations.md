# Harness Phase 0b: Prompt-Korrekturen, native Zitate `[N]`, Mehrfachaufrufe, toter Guard-Code

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Diese Befunde aus der [Analyse](../../research/2026-09-29-vinci-harness-analyse.md) werden testgetrieben behoben:

- Prompt-Widersprüche W5–W8 und M4.
- Die fünf Zitierformate (M1): Sie werden durch das native Open-WebUI-Format `[N]` ersetzt, das in der Oberfläche als klickbarer Quellen-Chip erscheint.
- Verlust der Evidenz bei mehreren `rag_chat`-Aufrufen (K5).
- Der unerreichbare RAG-Umschreibpfad im Toolcall-Guard (U2).

**Architecture:** `[N]` nummeriert **Textstellen**, fortlaufend ohne Lücken, genau wie die bestehenden `SOURCES_JSON`- und `EVIDENCE_BUNDLE_JSON`-Nummern. Der Evidenzvertrag (Quellen-IDs `#N`, Claim-IDs `RNCk`, Funktionskontakte) bleibt dadurch unverändert.

Die Middleware erzeugt pro Textstelle genau ein Open-WebUI-Quellen-Event mit eindeutigem Namen und genau einem Dokumenteintrag, in Nummernreihenfolge vor allen anderen Quellen. Beleg aus dem Frontend-Quellcode des laufenden Containers (`src/lib/components/chat/Messages/ContentRenderer.svelte`, `getSourceIds`): Die Oberfläche bildet die Liste der eindeutigen Quellennamen je Dokumenteintrag, und `[N]` zeigt auf deren N-ten Eintrag (`citation-extension.ts`).

Personio-Belege heißen weiter `[P1]` und haben keinen Chip.

Mehrere `rag_chat`-Aufrufe in einer Anfrage werden von der Evidenzsitzung fortlaufend umnummeriert, bevor das Modell sie sieht.

**Tech Stack:** Python 3.11, pytest, `stack/open-webui-tools/build_tools.py` (Bundle-Sync), Prompt-Vertragstests.

**Festgelegte Entscheidungen (29./30.09.):** natives `[N]`. Die Nutzer-WIP an Guard und Orchestrator ist als `6929f8a` committet.

**Bewusst nicht Teil dieses Plans:**

- W4 (Anweisungen in der Tool-Ausgabe gegen „Tool-Ausgaben sind untrusted“) → Phase 4, F3.
- Vollständige Umlaut-Umstellung der Prompts → Phase 4, F5; Prompt-Vertragstests prüfen heute ASCII-Schreibweisen.
- Das Legacy-Tool `rag_chat_direct_qdrant.py` und der interne RAG-Pfad des Workflow-Orchestrators (`[#N | …]`, erzeugt Dateien, keine Chips). Beide bleiben unverändert.

**Bekannte Grenze:** Enthält derselbe Turn zusätzlich hochgeladene Dateien als Open-WebUI-Quellen, stehen diese im modellgeführten Pfad vor den RAG-Events. Die Chip-Nummern verschieben sich dann. Im Pre-Route-Pfad stellt Task 8 die RAG-Events nach vorn.

---

## Vorbereitung und Befehle

Branch `feat/harness-eval-foundation`, sauberer Arbeitsstand.

Die Override- und Tool-Dateien haben CRLF-Zeilenenden. Deshalb mit dem Edit-Werkzeug oder Python-Skripten mit CRLF-Erhalt ändern, nicht mit Shell-Heredocs (sie verändern Backslashes).

```bash
P=./.venv-verify/Scripts/python.exe
# Harness-Bestandssuiten
$P -m pytest stack/tests/test_kahle_knowledge_harness.py stack/tests/test_kahle_internal_knowledge.py stack/tests/test_middleware_internal_rag_routing.py stack/tests/test_kahle_harness_reference_matrix.py stack/tests/test_kahle_harness_phase0a.py -q -p no:cacheprovider
# Neue Tests dieses Plans
$P -m pytest stack/tests/test_kahle_harness_phase0b.py -q -p no:cacheprovider
# Vollständig
$P -m pytest stack/tests -q -p no:cacheprovider
$P stack/open-webui-tools/build_tools.py --check
```

Ausgangswerte: Harness-Bestandssuiten **676 passed**, `stack/tests` **1242 passed**.

## Dateistruktur

| Datei | Änderung |
| --- | --- |
| `stack/open-webui-prompts/kahle-vinci-systemprompt.md`, `kahle-vinci-thinking-systemprompt.md` | Widersprüche beheben, Zitierregel `[N]`/`[P1]` |
| `stack/open-webui-tools/rag_chat_hybrid_tool.py` (+ `dist/` per Build) | fortlaufende Nummern, Kontextmarke `[N]`, Anweisung `[N]` |
| `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py` | `[N]` parsen und erzeugen, Zitierhinweis im Vertrag, beratender Code `noncanonical_citation`, Umnummerierung und Zusammenführung mehrerer RAG-Ergebnisse |
| `stack/open-webui-overrides/open_webui/utils/middleware.py` | Quellen-Events je Textstelle, Reihenfolge, Events im modellgeführten Pfad, Hinweis `[#]` → `[N]` |
| `stack/open-webui-overrides/open_webui/utils/kahle_internal_knowledge.py` | Mehrere `rag_chat`-Ergebnisse aufzeichnen und umnummerieren |
| `stack/open-webui-functions/kahle_toolcall_guard.py` | Toten RAG-Umschreibpfad entfernen |
| Create `stack/tests/test_kahle_harness_phase0b.py` | Neue Verhaltens- und Vertragstests |
| Bestehende Tests | nur dort anpassen, wo sie das alte Format `[Quelle N]` oder ein Event pro Dokument festschreiben |

---

## Teil 1: Prompt-Korrekturen

### Task 1: Prompt-Widersprüche (W5, W6, W7, W8, M4)

**Files:**
- Modify: `stack/open-webui-prompts/kahle-vinci-systemprompt.md`, `stack/open-webui-prompts/kahle-vinci-thinking-systemprompt.md`
- Create: `stack/tests/test_kahle_harness_phase0b.py`

- [ ] **Step 1: Write the failing tests**

`stack/tests/test_kahle_harness_phase0b.py`:

```python
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = (
    ROOT / "open-webui-prompts" / "kahle-vinci-systemprompt.md",
    ROOT / "open-webui-prompts" / "kahle-vinci-thinking-systemprompt.md",
)
HARNESS = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "kahle_knowledge_harness.py"


def load_harness():
    spec = importlib.util.spec_from_file_location("kahle_harness_phase0b", HARNESS)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("prompt_path", PROMPTS, ids=lambda path: path.name)
def test_prompts_have_one_consistent_internal_source_policy(prompt_path):
    prompt = prompt_path.read_text(encoding="utf-8")

    assert "KAHLE-interne Fakten -> RAG_Chat" not in prompt
    assert "Bei KAHLE-internen Fakten bleibt RAG_Chat zuerst Pflicht" not in prompt
    assert "konkurriere nicht mit einer eigenen fachlichen Quellenentscheidung" not in prompt
    assert "Waehle interne Quellen nach der Quellenmatrix in Abschnitt 3.3" in prompt


@pytest.mark.parametrize("prompt_path", PROMPTS, ids=lambda path: path.name)
def test_prompts_have_one_priority_order_and_no_model_specific_section(prompt_path):
    prompt = prompt_path.read_text(encoding="utf-8")

    assert "HOECHSTE PRIORITAET" not in prompt
    assert "Mistral" not in prompt
    assert "0) ABSOLUTE PRIORITAETEN" in prompt


@pytest.mark.parametrize("prompt_path", PROMPTS, ids=lambda path: path.name)
def test_stable_facts_are_orientation_not_evidence(prompt_path):
    prompt = prompt_path.read_text(encoding="utf-8")

    assert (
        "Diese Fakten dienen nur der Orientierung. Fuer interne Tatsachenaussagen gilt "
        "ausschliesslich das aktuelle EvidenceBundle; bei Widerspruch gilt das EvidenceBundle."
    ) in prompt
```

- [ ] **Step 2: Run to verify they fail**

Run: `$P -m pytest stack/tests/test_kahle_harness_phase0b.py -q -p no:cacheprovider`
Expected: 6 failed. Die Thinking-Variante enthält die Matrix aus Abschnitt 7 nicht, dort schlagen nur die übrigen Assertions fehl.

- [ ] **Step 3: Edit both prompts**

In **beiden** Dateien:

1. Die erste Zeile `[DATEI-TOOL-REGELN - HOECHSTE PRIORITAET]` ersetzen durch `[DATEI-TOOL-REGELN]`.
2. Die Überschrift `Wichtig fuer Mistral:` (nur Vinci) bzw. `Wichtig:` (Thinking) ersetzen durch `Tool-Disziplin:`. In Vinci zusätzlich prüfen, dass das Wort „Mistral“ nirgends mehr vorkommt.
3. Direkt unter der Überschrift `1) STABILE KONTEXT-FAKTEN` als erste Zeile einfügen:
   `- Diese Fakten dienen nur der Orientierung. Fuer interne Tatsachenaussagen gilt ausschliesslich das aktuelle EvidenceBundle; bei Widerspruch gilt das EvidenceBundle.`
4. In Abschnitt 3.3 die Zeile
   `- Der KAHLE Knowledge Harness löst Gesprächsbezüge auf, plant die erforderlichen internen Quellen und stellt das EvidenceBundle bereit. Verwende diese aufgelöste Anfrage und konkurriere nicht mit einer eigenen fachlichen Quellenentscheidung.`
   ersetzen durch
   `- Der KAHLE Knowledge Harness löst Gesprächsbezüge auf und stellt das EvidenceBundle bereit. Waehle interne Quellen nach der Quellenmatrix in Abschnitt 3.3. Liegt für die Frage bereits Evidenz einer Quelle vor, rufe dieselbe Quelle nicht erneut für dieselbe Frage auf.`
5. In Abschnitt 3.7 die Zeile `- Wissensspeicher: … Bei KAHLE-internen Fakten bleibt RAG_Chat zuerst Pflicht.` ersetzen durch
   `- Wissensspeicher: Nutzen, wenn der Nutzer angehaengtes Wissen, ausgewaehlte Wissensspeicher oder Dokumentenwissen meint. Fuer KAHLE-internes Wissen gilt die Quellenmatrix in Abschnitt 3.3.`
6. Nur Vinci, Abschnitt 7: die Zeile `- KAHLE-interne Fakten -> RAG_Chat.` ersetzen durch die zwei Zeilen
   `- Dokumentierte KAHLE-Prozesse, Zustaendigkeiten und Kontaktwege -> rag_chat.`
   `- Aktuelle Personen, Rollen, Standorte und Fuehrungskraefte -> personio_directory.`

- [ ] **Step 4: Run tests**

Run: `$P -m pytest stack/tests/test_kahle_harness_phase0b.py -q -p no:cacheprovider` → `6 passed`
Run: `$P -m pytest stack/tests -q -p no:cacheprovider` → alle PASS. Schlägt ein Prompt-Vertragstest fehl (`test_vinci_*`, `test_*_routing_contracts.py`), weil er eine der ersetzten Zeilen wörtlich erwartet: die Erwartung auf die neue Zeile umstellen, nicht die alte Zeile zurückholen.

- [ ] **Step 5: Commit**

```bash
git add stack/open-webui-prompts/kahle-vinci-systemprompt.md stack/open-webui-prompts/kahle-vinci-thinking-systemprompt.md stack/tests/test_kahle_harness_phase0b.py
git commit -m "fix(prompts): resolve source-policy and priority contradictions"
```

---

## Teil 2: Natives Zitierformat `[N]`

### Task 2: RAG-Tool nummeriert fortlaufend und markiert mit `[N]`

**Files:**
- Modify: `stack/open-webui-tools/rag_chat_hybrid_tool.py` → Schleife über `chunks` in `rag_chat`, `_rag_answer_instruction`
- Modify: `stack/tests/test_rag_evidence_bundle_contract.py` (Zeile mit `context.count("[Quelle ")`)
- Test: `stack/tests/test_kahle_harness_phase0b.py`

- [ ] **Step 1: Write the failing test**

Anhängen:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_rag_evidence_bundle_contract import (  # noqa: E402
    chunk,
    configured_tool,
    evidence_from_result,
    load_tool,
)


def _rag_result(module, monkeypatch, chunks):
    import asyncio

    tool = configured_tool(module, monkeypatch, chunks)
    return asyncio.run(tool.rag_chat(
        query="Wie plane ich einen Termin im WPS?",
        __user__={"id": "user-1"},
        __chat_id__="chat-1",
        __message_id__="message-1",
    ))


def test_rag_context_uses_native_gapless_markers(monkeypatch):
    module = load_tool()
    first = chunk("Öffnen Sie den Werkstattkalender.")
    empty = chunk("")
    second = chunk("Wählen Sie einen freien Termin.")
    second.document_id = "doc-2"
    second.title = "WPS Termine"

    result = _rag_result(module, monkeypatch, [first, empty, second])
    context = result.split("CONTEXT:\n", 1)[1].split("\nSOURCES_JSON:", 1)[0]
    sources = json.loads(result.split("SOURCES_JSON: ", 1)[1].splitlines()[0])

    assert "[Quelle" not in result
    assert context.startswith("[1] KAHLE Systemwissen | WPS\n")
    assert "\n[2] WPS Termine | WPS\n" in context
    assert [source["number"] for source in sources] == [1, 2]
    assert [source["number"] for source in evidence_from_result(result)["sources"]] == [1, 2]
    assert "[1]" in result.split("INSTRUCTION: ", 1)[1].splitlines()[0]
```

- [ ] **Step 2: Run to verify it fails**

Run: `$P -m pytest stack/tests/test_kahle_harness_phase0b.py -q -p no:cacheprovider -k native_gapless`
Expected: FAIL (`[Quelle` im Ergebnis)

- [ ] **Step 3: Implement**

In `rag_chat_hybrid_tool.py`, Methode `rag_chat`:

- `for index, chunk in enumerate(chunks, 1):` ersetzen durch `for chunk in chunks:`
- direkt nach dem Block `if not passage and not contact_error:\n                continue` einfügen:

```python
            # Gapless numbering: OpenWebUI maps [N] to the N-th citation source.
            index = len(sources) + 1
```

- `context.append(f"[Quelle {index}] {chunk.title} | {heading}\n{passage}")` ersetzen durch

```python
                context.append(f"[{index}] {chunk.title} | {heading}\n{passage}")
```

In `_rag_answer_instruction` den Satz `"Antworte nur aus CONTEXT. Belege jede konkrete interne Aussage mit [Quelle N]. "` ersetzen durch

```python
        "Antworte nur aus CONTEXT. Belege jede konkrete interne Aussage mit ihrer "
        "Quellennummer in eckigen Klammern, z. B. [1] oder [1, 2]. "
```

In `stack/tests/test_rag_evidence_bundle_contract.py` die Zeile `assert context.count("[Quelle ") >= 1` ersetzen durch

```python
    assert re.search(r"(?m)^\[\d+\] ", context)
```

und `import re` oben ergänzen.

Danach Bundles bauen: `$P stack/open-webui-tools/build_tools.py` und prüfen: `$P stack/open-webui-tools/build_tools.py --check` → alle `aktuell`.

- [ ] **Step 4: Run tests**

Run: `$P -m pytest stack/tests/test_kahle_harness_phase0b.py stack/tests/test_rag_evidence_bundle_contract.py stack/tests/test_hybrid_retrieval_security.py stack/tests/test_feedback_reference_handoff.py -q -p no:cacheprovider` → alle PASS

- [ ] **Step 5: Commit**

```bash
git add stack/open-webui-tools/rag_chat_hybrid_tool.py stack/open-webui-tools/dist/rag_chat_hybrid_tool.py stack/tests/test_kahle_harness_phase0b.py stack/tests/test_rag_evidence_bundle_contract.py
git commit -m "feat(rag): number passages gaplessly and cite them natively as [N]"
```

### Task 3: Harness liest und erzeugt `[N]`

**Files:**
- Modify: `kahle_knowledge_harness.py` → `_extract_sources`, `_supported_claims`, `rag_result_from_sources`
- Test: `stack/tests/test_kahle_harness_phase0b.py`

- [ ] **Step 1: Write the failing tests**

Anhängen:

```python
NATIVE_RESULT = (
    "KAHLE_RAG_RESULT\nFOUND: true\nCONTEXT:\n"
    "[1] Dokument A | Abschnitt A\nErster Beleg.\n\n"
    "[2] Dokument B | Abschnitt B\nZweiter Beleg.\n"
    "FEEDBACK_LINK: /wissen/?feedback=1"
)


def test_harness_parses_native_numbered_context_blocks():
    evidence = load_harness()._evidence_bundle(NATIVE_RESULT, procedural=False)

    assert [source["source_id"] for source in evidence.sources] == ["#1", "#2"]
    assert evidence.supported_claims == ("Erster Beleg.", "Zweiter Beleg.")


def test_reconstructed_rag_result_uses_native_markers():
    text = load_harness().rag_result_from_sources([
        {"source": {"name": "Dokument A"}, "document": ["Erster Beleg."], "metadata": [{}]},
    ])

    assert "[1] Dokument A\nErster Beleg." in text
    assert "[Quelle" not in text
```

- [ ] **Step 2: Run to verify they fail**

Run: `$P -m pytest stack/tests/test_kahle_harness_phase0b.py -q -p no:cacheprovider -k "native_numbered or reconstructed"`
Expected: 2 failed

- [ ] **Step 3: Implement**

- `_extract_sources`: das Muster `r"(?im)^\[(?:#\s*|Quelle\s+)(\d+)\]\s*([^\n]*)$"` ersetzen durch `r"(?im)^\[(?:#\s*|Quelle\s+)?(\d+)\]\s*([^\n]*)$"`
- `_supported_claims`: `r"(?im)(?=^\[(?:#\s*|Quelle\s+)\d+\])"` ersetzen durch `r"(?im)(?=^\[(?:#\s*|Quelle\s+)?\d+\])"`
- `rag_result_from_sources`: `f"[Quelle {source_number}] {title}\n{passage}"` ersetzen durch `f"[{source_number}] {title}\n{passage}"`

- [ ] **Step 4: Run tests** → neue Tests PASS; Harness-Bestandssuiten → `676 passed`. Bestandstests, die `[Quelle N]` als *Eingabe* verwenden, bleiben gültig, weil der Parser das alte Präfix weiter akzeptiert.

- [ ] **Step 5: Commit**

```bash
git add stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py stack/tests/test_kahle_harness_phase0b.py
git commit -m "feat(harness): parse and emit native [N] passage markers"
```

### Task 4: Quellen-Chips je Textstelle in beiden Pfaden

**Files:**
- Modify: `middleware.py` → `_canonical_kahle_rag_source_events`, neue Funktion `_extract_kahle_rag_citation_sources`, Pre-Route-Quellenreihenfolge, Event-Erzeugung im modellgeführten Pfad
- Test: `stack/tests/test_kahle_harness_phase0b.py`

- [ ] **Step 1: Write the failing tests**

Anhängen:

```python
from test_middleware_internal_rag_routing import (  # noqa: E402
    MIDDLEWARE,
    load_function_from_middleware,
)


def _frontend_source_ids(events):
    """Mirror OpenWebUI ContentRenderer.getSourceIds for citation lookup."""
    names = []
    for source in events:
        for index, _document in enumerate(source.get("document") or []):
            metadata = (source.get("metadata") or [{}])[index] or {}
            names.append(metadata.get("name") or source.get("source", {}).get("name"))
    return list(dict.fromkeys(names))


def test_every_passage_gets_its_own_citation_source_in_marker_order():
    events_for = load_function_from_middleware("_canonical_kahle_rag_source_events")
    sources = [
        {"number": 1, "title": "WPS", "section_heading": "1 Termine", "source_url": "/wissen/api/portal/sources/a", "evidence_text": "A"},
        {"number": 2, "title": "WPS", "section_heading": "1 Termine", "source_url": "/wissen/api/portal/sources/a", "evidence_text": "B"},
        {"number": 3, "title": "Vaudis", "source_url": "https://evil.example/x", "evidence_text": ""},
    ]

    events = events_for(sources)
    ids = _frontend_source_ids(events)

    assert len(events) == 3
    assert ids == ["WPS – 1 Termine", "WPS – 1 Termine (2)", "Vaudis"]
    assert events[2]["document"] == ["Vaudis"]
    assert "url" not in events[2]["metadata"][0]
    assert events[0]["metadata"][0]["url"] == "/wissen/api/portal/sources/a"


def test_citation_sources_keep_passages_without_trusted_links():
    extract = load_function_from_middleware("_extract_kahle_rag_citation_sources")
    result = 'SOURCES_JSON: [{"number": 2, "title": "B"}, {"number": 1, "title": "A", "source_url": "/wissen/api/portal/sources/a"}]\n'

    assert [source["number"] for source in extract(result)] == [1, 2]


def test_rag_citation_sources_come_first_and_are_emitted_in_the_native_tool_path():
    source = MIDDLEWARE.read_text(encoding="utf-8")

    assert "sources[:] = [*canonical_pre_route_events, *[" in source
    assert "tool_call_sources.extend(\n                                _canonical_kahle_rag_source_events(" in source
```

- [ ] **Step 2: Run to verify they fail**

Run: `$P -m pytest stack/tests/test_kahle_harness_phase0b.py -q -p no:cacheprovider -k "citation_source or every_passage"`
Expected: 3 failed

- [ ] **Step 3: Implement**

Direkt vor `def _canonical_kahle_rag_source_events(` einfügen:

```python
def _extract_kahle_rag_citation_sources(tool_result: Any) -> list[dict[str, Any]]:
    """Return every numbered RAG passage in marker order, trusted link or not."""
    text = tool_result if isinstance(tool_result, str) else ''
    match = re.search(r'SOURCES_JSON:\s*(\[.*?\])\s*(?:\n|$)', text, re.DOTALL)
    if not match:
        return []
    try:
        sources = json.loads(match.group(1))
    except (TypeError, ValueError):
        return []
    numbered = [
        source for source in sources
        if isinstance(source, dict) and isinstance(source.get('number'), int)
    ]
    return sorted(numbered, key=lambda source: source['number'])
```

`_canonical_kahle_rag_source_events` vollständig ersetzen:

```python
def _canonical_kahle_rag_source_events(
    sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Expose each numbered RAG passage as one native OpenWebUI citation source.

    OpenWebUI maps a marker [N] to the N-th distinct source name, counted per
    document entry. Every passage therefore needs its own name and exactly one
    document entry, in the order of the tool's passage numbers. Only portal
    source URLs are exposed as links.
    """
    events = []
    used_names: set[str] = set()
    for source in sources:
        title = str(source.get('title') or 'Interne Wissensquelle').strip()
        heading = str(source.get('section_heading') or '').strip()
        base = f'{title} – {heading}' if heading else title
        name, suffix = base, 2
        while name in used_names:
            name = f'{base} ({suffix})'
            suffix += 1
        used_names.add(name)
        url = str(source.get('source_url') or '').strip()
        metadata = {
            key: source.get(key)
            for key in (
                'document_id', 'version_id', 'valid_until', 'knowledgebase_ids',
            )
            if source.get(key) not in (None, '', [])
        }
        metadata.update({'source': name, 'name': name})
        if url.startswith('/wissen/api/portal/sources/'):
            metadata['url'] = url
        evidence_text = str(source.get('evidence_text') or '').strip()
        events.append({
            'source': {'name': name, **({'url': metadata['url']} if 'url' in metadata else {})},
            'document': [evidence_text or title],
            'metadata': [metadata],
        })
    return events
```

Im Pre-Route-Block die Aufrufe umstellen:

```python
                    canonical_pre_route_events = _canonical_kahle_rag_source_events(
                        _extract_kahle_rag_citation_sources(pre_route_rag_result)
                    )
```

(statt `canonical_pre_route_sources` als Argument). Die bestehende Zuweisung

```python
                    sources[:] = [
                        source
                        for source in sources
                        if 'rag_chat' not in str(
                            (source.get('source') or {}).get('name') or ''
                        ).lower()
                    ]
                    if canonical_pre_route_events:
                        sources.extend(canonical_pre_route_events)
```

ersetzen durch

```python
                    sources[:] = [*canonical_pre_route_events, *[
                        source
                        for source in sources
                        if 'rag_chat' not in str(
                            (source.get('source') or {}).get('name') or ''
                        ).lower()
                    ]]
```

Im modellgeführten Pfad direkt nach `canonical_rag_sources.extend(_extract_kahle_rag_sources(tool_result))` einfügen:

```python
                            if citations_enabled:
                                tool_call_sources.extend(
                                _canonical_kahle_rag_source_events(
                                    _extract_kahle_rag_citation_sources(tool_result)
                                ))
```

(Einrückung der inneren Zeilen so, dass die Zeichenkette aus dem Test exakt vorkommt.)

- [ ] **Step 4: Run tests**

Run: neue Tests → PASS. Run: Harness-Bestandssuiten. Bestandstests, die genau ein Event pro Dokument-URL, den Namen ohne Abschnitt oder das Anhängen hinter anderen Quellen erwarten, auf die neue Regel umstellen: ein Event je Textstelle, eindeutiger Name, RAG-Events zuerst. Jede andere Art von Fehlschlag: STOP und nachfragen.

- [ ] **Step 5: Commit**

```bash
git add stack/open-webui-overrides/open_webui/utils/middleware.py stack/tests/test_kahle_harness_phase0b.py stack/tests/test_middleware_internal_rag_routing.py
git commit -m "feat(citations): emit one native citation source per RAG passage"
```

### Task 5: Zitierregel in Vertrag, Middleware-Hinweis, Prompts und Validator

**Files:**
- Modify: `kahle_knowledge_harness.py` → `answer_prompt`, `validate_answer`
- Modify: `middleware.py` → Hinweis `Quellenmarke [#]`
- Modify: beide Prompts, Abschnitt 3.3
- Test: `stack/tests/test_kahle_harness_phase0b.py`

- [ ] **Step 1: Write the failing tests**

Anhängen:

```python
CITATION_RULE = (
    "Zitiere Dokumentbelege mit ihrer Nummer in eckigen Klammern, z. B. [1] oder [1, 2]; "
    "Personio-Belege als [P1]."
)


@pytest.mark.parametrize("prompt_path", PROMPTS, ids=lambda path: path.name)
def test_prompts_state_the_native_citation_rule(prompt_path):
    assert CITATION_RULE in prompt_path.read_text(encoding="utf-8")


def test_answer_contract_states_the_native_citation_rule():
    harness = load_harness()
    decision = harness.build_decision(
        query="Wie plane ich einen Termin im WPS?",
        resolved_query="Wie plane ich einen Termin im WPS?",
        messages=[],
        model_id="test-model",
        permission_scope={"user_id": "u"},
        rag_result=NATIVE_RESULT,
    )

    assert CITATION_RULE in decision.answer_prompt()


def test_middleware_continuation_hint_uses_native_markers():
    source = MIDDLEWARE.read_text(encoding="utf-8")

    assert "Quellenmarke [#]" not in source
    assert "passenden Quellennummer, z. B. [1]" in source


@pytest.mark.parametrize("marker", ["[Quelle 1]", "[#1]", "[R1]"])
def test_legacy_citation_markers_are_advisory(marker):
    decision = {
        "evidence_bundle": {"status": "supported", "supported_claims": [], "sources": [{"number": 1}]},
        "answer_contract": {},
        "retrieval_plan": {"permission_scope": {"user_id": "u"}},
        "resolved_context": {"retrieval_query": "Frage"},
    }

    result = load_harness().validate_answer(f"Belegte Aussage {marker}.", decision)

    assert result.status == "accepted"
    assert [(item["code"], item["severity"]) for item in result.violations] == [
        ("noncanonical_citation", "advisory")
    ]


def test_native_citation_marker_is_accepted_without_findings():
    decision = {
        "evidence_bundle": {"status": "supported", "supported_claims": [], "sources": [{"number": 1}]},
        "answer_contract": {},
        "retrieval_plan": {"permission_scope": {"user_id": "u"}},
        "resolved_context": {"retrieval_query": "Frage"},
    }

    result = load_harness().validate_answer("Belegte Aussage [1].", decision)

    assert result.violations == ()
```

- [ ] **Step 2: Run to verify they fail** → die neuen Tests schlagen fehl, bis auf `test_native_citation_marker_is_accepted_without_findings`

- [ ] **Step 3: Implement**

`answer_prompt()`: im abschließenden Instruktionstext nach `"Jede konkrete interne Aussage benötigt eine vorhandene Quellen-ID. "` einfügen:

```python
            "Zitiere Dokumentbelege mit ihrer Nummer in eckigen Klammern, z. B. [1] oder [1, 2]; "
            "Personio-Belege als [P1]. "
```

`validate_answer()`: direkt vor `permission_scope = _mapping(retrieval_plan.get("permission_scope"))` einfügen:

```python
    if re.search(r"\[(?:Quelle\s*|#\s*)\d+\]|\[R\d+\]", text, re.IGNORECASE):
        add(
            "noncanonical_citation",
            "Die Antwort verwendet ein altes Zitierformat statt [N] bzw. [P1].",
        )
```

`middleware.py`: `'Kennzeichne jede interne Tatsachenaussage mit der passenden Quellenmarke [#]. '` ersetzen durch `'Kennzeichne jede interne Tatsachenaussage mit der passenden Quellennummer, z. B. [1]. '`

Beide Prompts, Abschnitt 3.3: die Zeile `- Wenn das EvidenceBundle Quellen liefert, nenne oder zitiere diese. Bei fehlender oder widersprüchlicher Evidenz benenne genau diese Grenze.` ersetzen durch

```text
- Wenn das EvidenceBundle Quellen liefert, zitiere sie. Zitiere Dokumentbelege mit ihrer Nummer in eckigen Klammern, z. B. [1] oder [1, 2]; Personio-Belege als [P1]. Bei fehlender oder widersprüchlicher Evidenz benenne genau diese Grenze.
```

- [ ] **Step 4: Run tests** → neue Tests PASS; `stack/tests` vollständig PASS. Bestandstests, die ein komplettes Verstoß-Tupel vergleichen und dabei ein altes Zitat enthalten, bekommen `noncanonical_citation` (`advisory`) in der Erwartung ergänzt.

- [ ] **Step 5: Commit**

```bash
git add stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py stack/open-webui-overrides/open_webui/utils/middleware.py stack/open-webui-prompts/kahle-vinci-systemprompt.md stack/open-webui-prompts/kahle-vinci-thinking-systemprompt.md stack/tests/test_kahle_harness_phase0b.py
git commit -m "feat(citations): make [N] and [P1] the single citation contract"
```

Bestandstestdateien, die angepasst wurden, einzeln ergänzen.

---

## Teil 3: Mehrere `rag_chat`-Aufrufe (K5)

### Task 6: Umnummerieren eines RAG-Ergebnisses

**Files:**
- Modify: `kahle_knowledge_harness.py` → neue Funktionen `rag_result_source_count`, `renumber_rag_result`
- Test: `stack/tests/test_kahle_harness_phase0b.py`

- [ ] **Step 1: Write the failing test**

Anhängen:

```python
def _bundle_result(numbers):
    sources = [{"number": n, "title": f"D{n}", "source_url": f"/wissen/api/portal/sources/d{n}"} for n in numbers]
    bundle = {
        "schema_version": "kahle.evidence-bundle.v1",
        "status": "supported",
        "supported_claims": [
            {"claim_id": f"R{n}C1", "source_id": f"#{n}", "text": f"Beleg {n}.", "evidence_span": f"Beleg {n}."}
            for n in numbers
        ],
        "missing_information": [],
        "conflicts": [],
        "sources": [{"number": n, "document_id": f"d{n}"} for n in numbers],
    }
    context = "\n\n".join(f"[{n}] D{n} | A\nBeleg {n}." for n in numbers)
    return (
        "KAHLE_RAG_RESULT\nFOUND: true\n"
        f"EVIDENCE_BUNDLE_JSON: {json.dumps(bundle)}\n"
        "INSTRUCTION: Belege mit [1].\n"
        f"CONTEXT:\n{context}\n"
        f"SOURCES_JSON: {json.dumps(sources)}\n"
        "FEEDBACK_LINK: /wissen/?feedback=1"
    )


def test_renumber_rag_result_shifts_markers_sources_and_claims():
    harness = load_harness()
    shifted = harness.renumber_rag_result(_bundle_result([1, 2]), 3)

    assert harness.rag_result_source_count(_bundle_result([1, 2])) == 2
    assert "[4] D1 | A" in shifted and "[5] D2 | A" in shifted
    assert "INSTRUCTION: Belege mit [1]." in shifted
    bundle = json.loads(shifted.split("EVIDENCE_BUNDLE_JSON: ", 1)[1].splitlines()[0])
    assert [s["number"] for s in bundle["sources"]] == [4, 5]
    assert [(c["claim_id"], c["source_id"]) for c in bundle["supported_claims"]] == [("R4C1", "#4"), ("R5C1", "#5")]
    sources = json.loads(shifted.split("SOURCES_JSON: ", 1)[1].splitlines()[0])
    assert [s["number"] for s in sources] == [4, 5]


def test_renumber_with_zero_offset_is_identity():
    result = _bundle_result([1])

    assert load_harness().renumber_rag_result(result, 0) == result
```

- [ ] **Step 2: Run to verify it fails** → `AttributeError: … renumber_rag_result`

- [ ] **Step 3: Implement**

Direkt vor `def rag_result_from_sources(` einfügen:

```python
def rag_result_source_count(rag_result: str) -> int:
    """Number of numbered passages a rag_chat result exposes to the model."""
    raw = _extract_marker(str(rag_result or ""), "SOURCES_JSON")
    try:
        sources = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return 0
    return sum(
        1 for source in sources
        if isinstance(source, dict) and isinstance(source.get("number"), int)
    )


def renumber_rag_result(rag_result: str, offset: int) -> str:
    """Shift passage numbers so several rag_chat calls never share a [N]."""
    text = str(rag_result or "")
    if offset <= 0:
        return text

    def shift_source(source: Any) -> Any:
        if not isinstance(source, dict):
            return source
        shifted = dict(source)
        if isinstance(shifted.get("number"), int):
            shifted["number"] += offset
        for key in ("id", "source_id"):
            value = shifted.get(key)
            if isinstance(value, str):
                shifted[key] = re.sub(
                    r"^([#R]?)(\d+)$",
                    lambda match: f"{match.group(1)}{int(match.group(2)) + offset}",
                    value,
                )
        return shifted

    def shift_claim(claim: Any) -> Any:
        if not isinstance(claim, dict):
            return claim
        shifted = shift_source(claim)
        claim_id = shifted.get("claim_id")
        if isinstance(claim_id, str):
            shifted["claim_id"] = re.sub(
                r"^R(\d+)C",
                lambda match: f"R{int(match.group(1)) + offset}C",
                claim_id,
            )
        return shifted

    lines = []
    in_context = False
    for line in text.split("\n"):
        if line.startswith("SOURCES_JSON: "):
            in_context = False
            sources = json.loads(line[len("SOURCES_JSON: "):])
            line = "SOURCES_JSON: " + json.dumps(
                [shift_source(source) for source in sources], ensure_ascii=False
            )
        elif line.startswith("EVIDENCE_BUNDLE_JSON: "):
            bundle = json.loads(line[len("EVIDENCE_BUNDLE_JSON: "):])
            bundle["sources"] = [shift_source(item) for item in bundle.get("sources") or ()]
            bundle["supported_claims"] = [
                shift_claim(item) for item in bundle.get("supported_claims") or ()
            ]
            line = "EVIDENCE_BUNDLE_JSON: " + json.dumps(
                bundle, ensure_ascii=False, separators=(",", ":")
            )
        elif re.match(r"^[A-Z_]+:", line):
            in_context = line.startswith("CONTEXT:")
        elif in_context:
            line = re.sub(
                r"^\[(\d+)\] ",
                lambda match: f"[{int(match.group(1)) + offset}] ",
                line,
            )
        lines.append(line)
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests** → neue Tests PASS, Bestandssuiten unverändert

- [ ] **Step 5: Commit**

```bash
git add stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py stack/tests/test_kahle_harness_phase0b.py
git commit -m "feat(harness): renumber rag results for multi-call requests"
```

### Task 7: Evidenzsitzung behält alle Aufrufe

**Files:**
- Modify: `kahle_internal_knowledge.py` → `KnowledgeEvidenceSession.record`, `build_decision`, `_recording_rag_tool`
- Modify: `kahle_knowledge_harness.py` → `build_result_driven_decision` akzeptiert eine Liste von RAG-Ergebnissen
- Test: `stack/tests/test_kahle_harness_phase0b.py`

- [ ] **Step 1: Write the failing test**

Anhängen:

```python
from test_kahle_internal_knowledge import load_internal_knowledge  # noqa: E402


def test_second_rag_call_is_renumbered_and_both_calls_count_as_evidence():
    internal = load_internal_knowledge()
    harness = load_harness()
    session = internal.KnowledgeEvidenceSession(
        model={"id": "m"}, messages=[{"role": "user", "content": "Frage"}]
    )

    first = session.record("rag_chat", _bundle_result([1, 2]))
    second = session.record("rag_chat", _bundle_result([1]))

    assert first == _bundle_result([1, 2])
    assert "[3] D1 | A" in second
    decision = session.build_decision(query="Frage", permission_scope={"user_id": "u"})
    assert [harness._source_identifier(s) for s in decision.evidence_bundle.sources] == ["1", "2", "3"]
    assert len(decision.evidence_bundle.supported_claims) == 3
    # Validate via the serialized payload: the loaders create separate module instances.
    result = harness.validate_answer("Beleg [1]. Beleg [3].", decision.to_dict())
    assert "unknown_source_id" not in [item["code"] for item in result.violations]
```

- [ ] **Step 2: Run to verify it fails** → `second` enthält `[1] D1`, und die Entscheidung kennt nur eine Quelle

- [ ] **Step 3: Implement**

`kahle_internal_knowledge.py`:

- In `__init__`: `self._results: dict[str, Any] = {}` ersetzen durch

```python
        self._results: dict[str, list[Any]] = {}
```

- `record` vollständig ersetzen:

```python
    def record(self, tool_name: str, result: Any) -> Any:
        """Record a result and return what the model must see.

        Several rag_chat calls are renumbered so their [N] markers stay unique.
        """
        name = str(tool_name or "")
        if name not in _INTERNAL_TOOL_NAMES:
            return result
        if name == "rag_chat" and isinstance(result, str):
            offset = sum(
                rag_result_source_count(previous)
                for previous in self._results.get("rag_chat", ())
            )
            result = renumber_rag_result(result, offset)
        self._calls.append(name)
        self._results.setdefault(name, []).append(result)
        return result
```

- In `build_decision` die Argumente ersetzen:

```python
            rag_result=list(self._results.get("rag_chat") or ()),
            personio_result=(self._results.get("personio_directory") or [None])[-1],
```

- In `_personio_tool.search` und `_recording_rag_tool.call_and_record`: `session.record(...)` statt `session.record(...)` gefolgt von `return result` → `return session.record("…", result)`.
- Import ergänzen: `from open_webui.utils.kahle_knowledge_harness import (HarnessDecision, build_result_driven_decision, rag_result_source_count, renumber_rag_result,)`.

`kahle_knowledge_harness.py`, in `build_result_driven_decision`, direkt am Anfang nach der Berechnung von `actual_tools` einfügen:

```python
    rag_results = (
        [str(item or "") for item in rag_result]
        if isinstance(rag_result, (list, tuple))
        else [rag_result] if rag_result else []
    )
```

und die RAG-Auswertung ersetzen:

- `evidence = _result_driven_rag_evidence(rag_result, procedural)` → `evidence = _combined_rag_evidence(rag_results, procedural)`
- `evidence = merge_evidence(rag_result, personio_result, result_driven=True)` → `evidence = merge_evidence(_combined_rag_evidence(rag_results, procedural), personio_result, result_driven=True)`
- in `clarification = …` `str(rag_result or "")` → `"\n".join(rag_results)`; ebenso beim `_extract_marker(...)` für die Rückfrage.

Direkt vor `def build_result_driven_decision(` einfügen:

```python
def _combined_rag_evidence(rag_results: list[str], procedural: bool) -> EvidenceBundle:
    """Merge the already renumbered results of several rag_chat calls."""
    bundles = [_result_driven_rag_evidence(result, procedural) for result in rag_results]
    if not bundles:
        return _result_driven_rag_evidence("", procedural)
    usable = [bundle for bundle in bundles if bundle.status != "unsupported"]
    if not usable:
        return bundles[-1]
    return EvidenceBundle(
        status=(
            "supported"
            if all(bundle.status == "supported" for bundle in usable)
            else "partially_supported"
        ),
        supported_claims=tuple(claim for bundle in usable for claim in bundle.supported_claims),
        missing_information=tuple(dict.fromkeys(
            item for bundle in usable for item in bundle.missing_information
        )),
        conflicts=tuple(dict.fromkeys(item for bundle in bundles for item in bundle.conflicts)),
        sources=tuple(source for bundle in bundles for source in bundle.sources),
    )
```

`merge_evidence(result_driven=True)` akzeptiert bereits ein `EvidenceBundle` über `_result_driven_rag_evidence`.

> **Abweichung bei der Umsetzung (30.09.):** `_combined_rag_evidence` gibt bei genau einem Ergebnis dieses unverändert zurück, damit Einzelaufrufe bitgenau wie bisher ausgewertet werden. Im Task-4-Test prüft eine Regex die Reihenfolge der Aufrufe, statt eine exakte Einrückung zu vergleichen.

- [ ] **Step 4: Run tests** → neuer Test PASS; `test_kahle_internal_knowledge.py` und die Harness-Bestandssuiten PASS. Bestandstests, die `session.record` ohne Rückgabewert nutzen, bleiben gültig.

- [ ] **Step 5: Commit**

```bash
git add stack/open-webui-overrides/open_webui/utils/kahle_internal_knowledge.py stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py stack/tests/test_kahle_harness_phase0b.py
git commit -m "fix(harness): keep evidence from every rag_chat call in a request"
```

---

## Teil 4: Toter Guard-Code

### Task 8: Unerreichbaren RAG-Umschreibpfad entfernen

**Files:**
- Modify: `stack/open-webui-functions/kahle_toolcall_guard.py`
- Modify: `stack/tests/test_kahle_toolcall_guard.py` (nur Tests toter Funktionen)
- Test: `stack/tests/test_kahle_harness_phase0b.py`

- [ ] **Step 1: Tote Funktionen ermitteln**

Run (Python-Skript im Scratchpad): Mit `ast` alle Top-Level-Funktionen des Guards bestimmen. Die Menge der toten Funktionen wird so gebildet:

1. Start mit `_rag_answer_text`.
2. Wiederholt jede Funktion hinzufügen, deren Name nur in bereits toten Funktionen referenziert wird.

Ergebnis in den Commit-Text übernehmen. Erwartet mindestens:

- `_rag_answer_text`
- `_synthesize_rag_answer`
- `_deterministic_opening_hours_answer`
- `_retain_context_supported_answer`
- `_retain_grounded_answer`

- [ ] **Step 2: Write the failing test**

Anhängen (Namensliste = Ergebnis aus Step 1):

```python
GUARD = ROOT / "open-webui-functions" / "kahle_toolcall_guard.py"


def test_guard_has_no_unreachable_rag_rewrite_path():
    source = GUARD.read_text(encoding="utf-8")

    for name in (
        "_rag_answer_text",
        "_synthesize_rag_answer",
        "_deterministic_opening_hours_answer",
        "_retain_context_supported_answer",
        "_retain_grounded_answer",
    ):
        assert f"def {name}(" not in source
```

- [ ] **Step 3: Remove code**: alle in Step 1 ermittelten Funktionen löschen. Tests in `stack/tests/test_kahle_toolcall_guard.py`, die ausschließlich diese Funktionen prüfen, löschen.

- [ ] **Step 4: Run tests**: `stack/tests` vollständig → PASS (Anzahl = vorher + neue − gelöschte Guard-Tests)

- [ ] **Step 5: Commit**

```bash
git add stack/open-webui-functions/kahle_toolcall_guard.py stack/tests/test_kahle_toolcall_guard.py stack/tests/test_kahle_harness_phase0b.py
git commit -m "refactor(guard): remove unreachable RAG answer rewrite path"
```

---

### Task 9: Messen und Full Verify

- [ ] Offline-Eval: `$P eval/harness/offline_routing_eval.py --output eval/harness/results/2026-09-30-offline-phase0b.json` → erwartet unverändert 89/99. 0b ändert kein Routing.
- [ ] `$P stack/open-webui-tools/build_tools.py --check` → alle `aktuell`
- [ ] Full Verify: `.\scripts\run-local-tests.ps1 -Tier Full -Python .\.venv-verify\Scripts\python.exe -Npm npm.cmd` → Exit 0
- [ ] Commit: `test(eval): record offline routing after harness phase 0b`

## Abnahme Phase 0b und Laufzeitprüfung

- Alle neuen Tests grün, Full Verify Exit 0, Bundles synchron.
- Laufzeit, sobald IONOS antwortet (gemeinsam mit Task 12 der Eval-Grundlage):
  1. Prompts und Tools per `scripts/openwebui/register-kahle-workflow-tool.py` in die lokale Open-WebUI-Datenbank übernehmen und `open-webui` neu erstellen.
  2. Im Browser prüfen, dass `[1]` in einer internen Antwort als Chip mit dem Abschnittsnamen erscheint.
  3. Laufzeit-Eval erneut ausführen.

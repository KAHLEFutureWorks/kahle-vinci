# Personio Area Contacts and Portal Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bereichs- und Kontaktfragen zuverlässig mit Personio beziehungsweise belegter RAG-Evidenz beantworten, erfundene Kontaktwerte verhindern und den Rücksprung aus dem Wissensportal reparieren.

**Architecture:** Der Knowledge Harness klassifiziert reine Fragen nach Personen, Rollen und Organisationseinheiten als Personio-Verzeichnisfragen. Zentrale Bereichskontakte bleiben nur dann RAG-gestützt, wenn die Evidenz den angefragten Kontaktwert wörtlich enthält; andernfalls liefert der Harness vor der Modellsynthese eine Nicht-verfügbar-Antwort. Der Portal-Rücksprung verlässt den Next.js-Basispfad `/wissen` über eine explizite Browsernavigation zum Host-Root.

**Tech Stack:** Python 3.11, pytest, Open-WebUI-Middleware, Personio Directory, React 19, Next.js 16 und Node-Renderingtests.

**Spec:** Projektregeln in `AGENTS.md`, `stack/AGENTS.md`, `admin-dashboard/AGENTS.md`, ADR-008 in `DECISIONS.md` und die vom Benutzer am 31.08.2026 bestätigten Abnahmefälle.

## Global Constraints

- Personio bleibt für aktuelle Personen-, Rollen-, Bereichs- und geschäftliche Kontaktdaten autoritativ.
- RAG darf aktuelle Personio-Stammdaten nicht überschreiben.
- E-Mail-Adressen und Telefonnummern dürfen nur aus expliziten Evidence-Claims ausgegeben werden.
- Ohne eindeutige Evidenz bleibt die Antwort fail-closed; Modellwissen und frühere Assistentenantworten sind keine Evidenz.
- Führungskräfte werden ausschließlich über auflösbare `supervisor_personio_id`-Beziehungen ermittelt.
- Namen, Kontakte, IDs und Secrets erscheinen weder in technischen Logs noch in Testreports dieses Plans.
- Keine Produktionsaktivierung, kein Push und kein Rollout ohne gesonderte ausdrückliche Freigabe.

---

### Task 1: Supervisor-Laufzeit und sichere Namensauflösung absichern

**Files:**
- Modify: `stack/personio-directory/tests/test_search.py`
- Modify only if a test exposes a real defect: `stack/personio-directory/app/search.py`
- Modify: `docs/operations/personio-directory.md`

**Interfaces:**
- Consumes: `_exact_person_matches(text, people)` and `supervisor_personio_id`.
- Produces: documented aggregate acceptance checks for indexed and resolvable supervisor relationships.

- [x] **Step 1: Add regression cases using synthetic people**

Add literal fixtures proving that exact two-part names, preferred names with a middle component, and the controlled `ß`/`ss` spelling variant resolve only an explicit supervisor ID. Keep the existing negative case proving that a record without an explicit supervisor remains unavailable.

- [x] **Step 2: Run RED/characterization check**

Run:

```powershell
& .\.venv-verify\Scripts\python.exe -m pytest stack\personio-directory\tests\test_search.py -q -p no:cacheprovider -k "supervisor and name"
```

Expected: Any missing supported normalization fails. If every case already passes, record the result as runtime-parity evidence and do not change production search code.

- [x] **Step 3: Implement only an exposed search defect**

Keep matching bounded to an exact normalized full name, an unambiguous first/last alias for a preferred name with middle components, or one character across the complete name. Never select by position, team, office, order, or semantic similarity.

- [x] **Step 4: Document runtime parity diagnostics**

Document that `health=healthy` is insufficient on its own. The acceptance check records only API version, mapping presence, indexed total, indexed supervisor count, resolvable count, unresolvable count, runtime revision, and sync timestamp.

### Task 2: Organization-unit language and Personio routing

**Files:**
- Modify: `stack/tests/test_kahle_knowledge_harness.py`
- Modify: `stack/tests/test_middleware_internal_rag_routing.py`
- Modify: `stack/personio-directory/tests/test_search.py`
- Modify: `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py`
- Modify: `stack/personio-directory/app/search.py`

**Interfaces:**
- Produces: `_organization_unit_directory_question(query: str) -> bool` in the Harness.
- Consumes: existing structured Personio dimensions `department`, `team`, `position`, and `office`.
- Produces: controlled department aliases inside the Personio service; OR within one dimension and AND across explicitly requested dimensions remain unchanged.

- [x] **Step 1: Write failing routing tests**

Add table-driven tests for `Wie erreiche ich ...`, `Wie komme ich mit ... in Kontakt?`, `Gib mir den Kontakt zu ...`, `Wie lautet die Telefonnummer von ...` and `Welche Mitarbeitenden arbeiten in ...`. Cover the controlled variants `Personalwesen`, `Personalabteilung`, `Personalbereich`, `Personal`, and `HR`, plus representative accounting, disposition, marketing, IT, sales, service, and parts wording. Reine Bereichs-/Personenfragen must plan only `personio_directory`; topic-based responsibility questions keep their existing RAG path.

- [x] **Step 2: Verify RED**

Run:

```powershell
& .\.venv-verify\Scripts\python.exe -m pytest stack\tests\test_kahle_knowledge_harness.py stack\tests\test_middleware_internal_rag_routing.py -q -p no:cacheprovider -k "organization or area_contact"
```

Expected: The currently unrecognized contact formulations fail because the Harness gate is not activated or chooses the wrong source.

- [x] **Step 3: Write failing Directory filter tests**

Use synthetic department labels and assert that all five HR wordings resolve the same department family, while an unknown unit returns zero claims. Assert that an explicitly requested office remains an AND filter.

- [x] **Step 4: Verify Directory RED**

Run:

```powershell
& .\.venv-verify\Scripts\python.exe -m pytest stack\personio-directory\tests\test_search.py -q -p no:cacheprovider -k "department_alias or organization_contact"
```

- [x] **Step 5: Implement minimal controlled normalization**

Recognize the general question forms independently from the unit vocabulary. Resolve exact indexed department/team labels first and add only audited aliases for common short forms. Do not add semantic fuzzy search and do not let an unknown alias degrade into an unfiltered employee list.

- [x] **Step 6: Verify GREEN**

Run the two targeted commands from Steps 2 and 4 and confirm all new and existing routing cases pass.

### Task 3: Evidence-bound contact values

**Files:**
- Modify: `stack/tests/test_kahle_knowledge_harness.py`
- Modify: `stack/tests/test_middleware_internal_rag_routing.py`
- Modify: `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py`
- Modify if evidence construction needs the query distinction: `stack/open-webui-tools/rag_chat_hybrid_tool.py`
- Rebuild/check: `stack/open-webui-tools/dist/rag_chat_hybrid_tool.py`

**Interfaces:**
- Produces: contact-evidence sufficiency derived exclusively from existing `supported_claims` and `evidence_span` values.
- Produces: a pre-answer fail-closed result when a requested e-mail address or telephone number is absent from the evidence.
- Consumes: Personio claims containing `business_email` and `business_phone`, or RAG claims containing the exact requested literal and source ID.

- [x] **Step 1: Write failing unsupported-contact tests**

Build EvidenceBundles whose sources discuss a department but contain no e-mail address or telephone number. Assert that queries asking for either channel become `unsupported` and produce the stable pre-answer result without model synthesis. Add a follow-up case proving that a contact value from an earlier assistant response is not accepted as evidence.

- [x] **Step 2: Verify RED**

Run:

```powershell
& .\.venv-verify\Scripts\python.exe -m pytest stack\tests\test_kahle_knowledge_harness.py stack\tests\test_middleware_internal_rag_routing.py -q -p no:cacheprovider -k "unsupported_contact or contact_evidence"
```

- [x] **Step 3: Write supported-contact tests**

Use reserved synthetic domains and telephone placeholders. Assert that exact Personio business contacts remain supported and that a RAG contact is supported only when the requested literal occurs inside a cited evidence span.

- [x] **Step 4: Implement evidence sufficiency before generation**

Detect requested contact channels from the user query. Derive allowed values only from the current EvidenceBundle. If no value exists for an explicitly requested channel, change the bundle to `unsupported` with a neutral missing-information statement. Extend the answer contract to state that contact literals must be copied exactly from those claims; never infer aliases, extensions, central numbers, or mailbox names.

- [x] **Step 5: Verify GREEN and tool parity**

Run the targeted tests, then:

```powershell
& .\.venv-verify\Scripts\python.exe stack\open-webui-tools\build_tools.py --check
```

### Task 4: Portal root navigation

**Files:**
- Modify: `admin-dashboard/tests/rendered-html.test.mjs`
- Modify: `admin-dashboard/components/KnowledgePortal.tsx`

**Interfaces:**
- Produces: a browser navigation from `/wissen/` to the host root `/`, without Next.js `basePath` rewriting.

- [x] **Step 1: Write the failing rendering contract**

Replace the source-text expectation for a Next `Link` with an expectation for an explicit browser navigation to `/`; assert the back control is neither rendered as the framework Link nor as a basePath-relative anchor.

- [x] **Step 2: Verify RED**

Run:

```powershell
Push-Location admin-dashboard
node.exe tests\rendered-html.test.mjs
Pop-Location
```

Expected: FAIL because the current control is a Next.js `Link` under `basePath=/wissen`.

- [x] **Step 3: Implement the root navigation**

Replace only the back control with a button that calls `window.location.assign("/")`. Keep the icon, label, classes, accessibility label, and all authorization behavior unchanged. This avoids both Next.js `basePath` rewriting and the framework lint rule that forbids native internal anchors.

- [x] **Step 4: Verify GREEN**

Run the rendering test, lint, and production build.

### Task 5: Verification and review

**Files:**
- Modify as required by verified behavior: `docs/operations/personio-directory.md`

**Interfaces:**
- Produces: locally verified, reviewable changes without production mutation.

- [x] **Step 1: Run service-targeted suites**

```powershell
& .\.venv-verify\Scripts\python.exe -m pytest stack\personio-directory\tests -q -p no:cacheprovider
& .\.venv-verify\Scripts\python.exe -m pytest stack\tests\test_kahle_knowledge_harness.py stack\tests\test_middleware_internal_rag_routing.py stack\tests\test_rag_evidence_bundle_contract.py -q -p no:cacheprovider
```

- [x] **Step 2: Run canonical Full Verify**

```powershell
.\scripts\run-local-tests.ps1 -Tier Full -Python .\.venv-verify\Scripts\python.exe -Npm npm.cmd -Node node.exe
```

- [x] **Step 3: Run static checks**

```powershell
& .\.venv-verify\Scripts\python.exe stack\open-webui-tools\build_tools.py --check
& .\.venv-verify\Scripts\python.exe -m compileall -q stack\personio-directory\app stack\open-webui-overrides\open_webui\utils
git diff --check
```

- [x] **Step 4: Review scope and runtime requirements**

Confirm that no employee data, contact values, provider payloads, secrets, unrelated refactors, production commands, deployment artifacts, or generated caches entered the diff. Report that a local live Personio/UI test still requires a fresh runtime with valid local environment variables.

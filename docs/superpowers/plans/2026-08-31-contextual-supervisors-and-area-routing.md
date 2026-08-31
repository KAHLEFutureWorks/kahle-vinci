# Contextual Supervisors and Area Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep consecutive supervisor lookups independent while allowing real contextual follow-ups, and answer organizational contact questions from combined Personio and RAG evidence without inventing contact values.

**Architecture:** The middleware passes prior Personio candidate context only for referential supervisor follow-ups, never as an override for a newly named subject. The Knowledge Harness distinguishes current people data, documented organizational communication channels, and mixed area-contact questions before retrieval. Personio remains authoritative for current people; RAG remains authoritative for functional mailboxes, ticket systems, application channels, and documented responsibilities.

**Tech Stack:** Python 3.11, pytest, Open WebUI middleware, Knowledge Harness, Personio Directory, hybrid RAG.

**Spec:** User-approved routing clarification from 31 August 2026 and the authority boundaries in `docs/operations/personio-directory.md`.

## Global Constraints

- Never infer a supervisor without one explicit resolvable Personio supervisor ID.
- Do not remove or rewrite general conversation history; constrain only the private `candidate_query` passed to Personio.
- A full current person name is resolved from the current supervisor question and is never replaced by a previous supervisor question.
- Referential supervisor follow-ups may use only the immediately relevant prior user request.
- Personio is authoritative for current employees and their business contact fields.
- RAG is authoritative for functional mailboxes, ticket systems, submission paths, and documented responsibilities.
- Contact literals may be emitted only when present verbatim in the current EvidenceBundle.
- Tests use synthetic names and reserved contact values only.

---

### Task 1: Scope supervisor candidate context

**Files:**
- Modify: `stack/tests/test_middleware_internal_rag_routing.py`
- Modify: `stack/open-webui-overrides/open_webui/utils/middleware.py`
- Modify: `stack/personio-directory/tests/test_search.py`
- Modify: `stack/personio-directory/app/search.py`

**Interfaces:**
- Consumes: `_supervisor_candidate_query(messages, query) -> str`
- Produces: an empty candidate for explicit named supervisor questions and a prior query only for referential supervisor follow-ups.

- [x] **Step 1: Write failing sequence tests**

Add literal synthetic conversations proving that a second explicit supervisor question does not receive the first supervisor query as `candidate_query`, while `Wer davon ist die Führungskraft?` retains the preceding directory request. Add a case showing that `Wer ist Erika Beispiel?` followed by `Wer ist deren Führungskraft?` resolves the explicit supervisor relationship from the prior person lookup instead of discarding that non-supervisor context.

- [x] **Step 2: Run RED**

```powershell
& C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest stack\tests\test_middleware_internal_rag_routing.py -q -p no:cacheprovider -k "supervisor_candidate or consecutive_supervisor"
```

Expected: the consecutive explicit-name case fails because the previous user query is currently returned unconditionally.

- [x] **Step 3: Implement the minimal candidate rule**

Return prior context only when the current supervisor question has no explicit named person and contains a controlled referential form such as `davon`, `deren`, `dessen`, `diese Person`, `er`, `sie`, `ihm` or `ihr`. Resolve a prior `person_lookup` only through the exact bounded person matcher before following its explicit supervisor ID. Do not alter `messages`, query expansion, or other follow-up handling.

- [x] **Step 4: Run GREEN**

Run the command from Step 2 and confirm both new and existing supervisor-follow-up tests pass.

### Task 2: Separate people, organizational channels, and mixed area contacts

**Files:**
- Modify: `stack/tests/test_kahle_knowledge_harness.py`
- Modify: `stack/tests/test_middleware_internal_rag_routing.py`
- Modify: `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py`
- Modify if required by the actual gate: `stack/open-webui-overrides/open_webui/utils/middleware.py`

**Interfaces:**
- Produces: an organizational-channel predicate independent of one exhaustive department vocabulary.
- Produces: `personio_directory + rag_chat` for area contact questions, Personio only for employee lists, and RAG only for documented procedures or submission paths without a current-people request.

- [x] **Step 1: Write failing routing-table tests**

Cover these literal expectations:

```text
Wie erreiche ich die IT?                         -> Personio + RAG
Wie ist die E-Mail der Personalabteilung?       -> Personio + RAG
Wer sind die Ansprechpartner im Marketing?      -> Personio + RAG
Welche Kontakte gibt es für Bewerbungen?        -> Personio + RAG
Wer arbeitet in der IT?                         -> Personio
Wer ist die Führungskraft von Erika Beispiel?   -> Personio
Wie läuft der Bewerbungsprozess?                -> RAG
Wohin schicke ich meine Bewerbung?              -> RAG
```

Also cover Personal, Personalwesen, Personalabteilung, Personalbereich, HR, IT, EDV, Marketing, Datenschutz, Krankmeldung, Bewerbung and Karriere wording.

- [x] **Step 2: Run RED**

```powershell
& C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest stack\tests\test_kahle_knowledge_harness.py stack\tests\test_middleware_internal_rag_routing.py -q -p no:cacheprovider -k "area_contact or organizational_channel or functional_contact"
```

Expected: current area-contact questions choose only Personio and application-contact questions do not choose the required mixed or RAG path.

- [x] **Step 3: Implement the minimal intent split**

Identify the target shape before source selection:

- explicit named person contact -> Personio;
- employee/role/department list -> Personio;
- area contact or area point-of-contact -> Personio + RAG;
- process or submission instruction without a current-people request -> RAG.

Keep the original query for both retrieval adapters. Do not encode any actual mailbox or telephone value.

- [x] **Step 4: Run GREEN**

Run the command from Step 2 and verify the complete table.

### Task 3: Merge evidence without cross-source invention

**Files:**
- Modify: `stack/tests/test_kahle_knowledge_harness.py`
- Modify: `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py`

**Interfaces:**
- Consumes: Personio claims and RAG EvidenceBundle claims.
- Produces: a partial mixed answer when only one source supplies evidence and an exact combined answer when both do.

- [x] **Step 1: Write failing mixed-evidence tests**

Use one synthetic Personio employee with `person@example.invalid` and a RAG evidence span containing either `team@example.invalid` or a documented ticket-system statement. Assert that both supported parts survive merging. Assert that a missing RAG mailbox never becomes a generated address and a missing Personio match does not suppress the documented RAG channel.

- [x] **Step 2: Run RED**

```powershell
& C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest stack\tests\test_kahle_knowledge_harness.py -q -p no:cacheprovider -k "mixed_area_contact"
```

- [x] **Step 3: Implement evidence-aware mixed answering**

Format documented organizational channels and current Personio people as separately labelled evidence-backed parts. If only one source is supported, return only that part and disclose the unavailable part. Preserve citations for RAG claims and exact structured Personio contact fields.

- [x] **Step 4: Run GREEN**

Run the command from Step 2.

### Task 4: Documentation and complete verification

**Files:**
- Modify: `docs/operations/personio-directory.md`

**Interfaces:**
- Documents the final routing matrix, active/publication/index prerequisite for portal documents, and local acceptance prompts.

- [x] **Step 1: Update operating documentation**

Document that uploaded portal documents enter RAG only after the current version is active, published and indexed. Add the approved source matrix and consecutive-chat supervisor acceptance case.

- [x] **Step 2: Run targeted service suites**

```powershell
& C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest stack\personio-directory\tests -q -p no:cacheprovider
& C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest stack\tests\test_kahle_knowledge_harness.py stack\tests\test_middleware_internal_rag_routing.py stack\tests\test_rag_evidence_bundle_contract.py -q -p no:cacheprovider
```

- [ ] **Step 3: Run canonical Full Verify**

Attempted on 31 August 2026. All product Python suites, UI lint and rendering
tests passed, but the isolated worktree lacks one ignored historical rollout
script and the UI production build hit the known Windows `spawn EPERM` setup
failure. The affected Stack suite passed with that unrelated artifact test
deselected (617 passed), the five rollout tests passed separately with the
ignored artifact supplied temporarily, and the Personio suite passed
completely (175 passed). UI lint, production build and 19 rendering tests also
passed outside the restricted sandbox.

```powershell
.\scripts\run-local-tests.ps1 -Tier Full -Python C:\kahle-vinci\.venv-test\Scripts\python.exe -Npm npm.cmd -Node node.exe
```

- [x] **Step 4: Review scope**

Run `git diff --check`, confirm the tool bundle is current, and verify that no real employee data, contact values, secrets, deployment artifacts or unrelated changes entered the diff.

# Personio Next Five Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Personio the fail-closed authority for current employee, role, location, onboarding and supervisor queries while keeping documented process responsibility in RAG.

**Architecture:** The directory derives explicit, structured filters from a small controlled vocabulary and evaluates dimensions with AND semantics. The knowledge harness decides source use before retrieval: directory-only for current employee lists, RAG-only for process responsibility, and concurrent sources only for an explicit person plus documented system relation. Supervisor support is modelled as an optional Personio-ID field; without a verified readable source, its dedicated route returns a fixed unavailable result.

**Tech Stack:** Python 3, pytest, FastAPI, Qdrant directory index, OpenWebUI middleware, Docker Compose.

**Spec:** Delegated Personio next-five implementation request, 26 August 2026.

## Global Constraints

- Preserve existing changes. Never reset, push, deploy, or access production.
- Never log, persist, test-report, or chat-report secrets or employee data.
- Use red-green-refactor: each behaviour begins with an isolated failing regression test.
- Index only exact `@kahle.de` business email addresses. Onboarding claims contain only display name, position, department, team, office and source id.
- Personio is authoritative for current master data. RAG may establish only documented functional responsibility or a documented person-system relation.
- Supervisor selection must use explicit Supervisor Personio-ID evidence only. It must never infer a manager from order, title, office, team, or model knowledge.
- Run each service test suite separately because multiple services expose an `app` package.

---

## File structure

- `stack/personio-directory/app/search.py`: query intent, controlled directory filter extraction and supervisor fail-closed result.
- `stack/personio-directory/app/models.py`, `personio.py`, `policy.py`, `index.py`, `main.py`: optional supervisor-ID ingestion, durable index payload and private API schema.
- `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py`: deterministic source planner and functional-responsibility evidence contract.
- `stack/open-webui-overrides/open_webui/utils/middleware.py`, `personio_directory_client.py`: bounded intent transfer and only plan-selected RAG status.
- `stack/personio-directory/tests/` and `stack/tests/`: unit, contract, routing and privacy regressions.
- `scripts/openwebui/kahle-harness-acceptance-matrix.json`, `docs/operations/personio-directory.md`: versioned acceptance evidence and supervisor permission procedure.

### Task 1: Repair explicit onboarding retrieval

**Files:**
- Modify: `stack/personio-directory/tests/test_search.py`
- Modify: `stack/personio-directory/app/search.py`

**Produces:** Onboarding queries use only explicit role/location/team/department filters; conversational function words are never mandatory terms.

- [ ] **Step 1: Write failing tests** for the general onboarding question, a role-limited onboarding question, and the reduced claim field set.
- [ ] **Step 2: Run the focused tests** with `C:\kahle-vinci\.venv-test\Scripts\python.exe -m pytest stack/personio-directory/tests/test_search.py -q -p no:cacheprovider`; confirm the general case fails because `bei` and `uns` are treated as terms.
- [ ] **Step 3: Implement the minimal onboarding filter path** so it evaluates explicit structured dimensions but not residual natural-language terms.
- [ ] **Step 4: Re-run the focused suite** and confirm reduced onboarding claims and ordinary-query non-disclosure remain green.
- [ ] **Step 5: Commit** with `fix(personio): return general onboarding lists safely`.

### Task 2: Add controlled role and location normalization

**Files:**
- Modify: `stack/personio-directory/tests/test_search.py`
- Modify: `stack/personio-directory/app/search.py`

**Produces:** `DirectorySearch._directory_candidates()` applies AND between explicit dimensions and controlled OR variants inside role synonyms.

- [ ] **Step 1: Write failing tests** for Teiledienst plus Hannover, Serviceassistenzen plus Wedemark, Verkäufer plus Seat and Neuwagen, singular/plural and a no-match case.
- [ ] **Step 2: Run the focused tests** and confirm role phrases are currently either misclassified or rejected as unmatched residual tokens.
- [ ] **Step 3: Implement a compact structured query normalizer** that separately extracts position/role, department, team/brand and office; normalize `in der Wedemark`, role variants and German umlauts; retain Seat and Neuwagen as separate explicit AND filters.
- [ ] **Step 4: Re-run the directory suite** and confirm no fuzzy fallback can return unrelated employees.
- [ ] **Step 5: Commit** with `feat(personio): normalize controlled directory role variants`.

### Task 3: Correct source routing for employee lists and process responsibility

**Files:**
- Modify: `stack/tests/test_kahle_knowledge_harness.py`
- Modify: `stack/tests/test_middleware_internal_rag_routing.py`
- Modify: `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py`
- Modify: `stack/open-webui-overrides/open_webui/utils/middleware.py`

**Produces:** Explicit employee role/location lists are directory-only. Mahnung and Kundenbeschwerden are RAG-only functional-responsibility requests. A named person plus a system/project still uses both sources in parallel.

- [ ] **Step 1: Write failing planner and middleware tests** for all five supplied routing examples, including no `rag_chat` status for directory-only plans.
- [ ] **Step 2: Run the focused tests** and confirm role lists are not all planned as directory searches and process contacts are incorrectly planned as person lookups.
- [ ] **Step 3: Add narrow German patterns** for role/location list wording and process-responsibility wording before generic `Ansprechpartner` handling; encode a `functional_responsibility` information need for RAG.
- [ ] **Step 4: Re-run focused harness and middleware tests** and verify mixed person/system retrieval remains concurrent.
- [ ] **Step 5: Commit** with `fix(harness): separate employee lists from process responsibility`.

### Task 4: Prepare optional supervisor evidence and fail closed

**Files:**
- Modify: `stack/personio-directory/tests/test_personio_client.py`
- Modify: `stack/personio-directory/tests/test_policy.py`
- Modify: `stack/personio-directory/tests/test_index.py`
- Modify: `stack/personio-directory/tests/test_search.py`
- Modify: `stack/personio-directory/app/models.py`
- Modify: `stack/personio-directory/app/personio.py`
- Modify: `stack/personio-directory/app/policy.py`
- Modify: `stack/personio-directory/app/index.py`
- Modify: `stack/personio-directory/app/main.py`
- Modify: `stack/open-webui-overrides/open_webui/utils/personio_directory_client.py`
- Modify: `stack/open-webui-overrides/open_webui/utils/middleware.py`

**Produces:** An optional `supervisor_personio_id` can be read from an explicitly authorized source and stored without displaying the ID. The supervisor intent returns a stable not-available result whenever mapping, candidate context or an authorized supervisor relation is unavailable.

- [ ] **Step 1: Write failing service and boundary tests** for safe optional flattening, index round-trip, client schema rejection of ID leakage, and the dedicated supervisor intent without evidence.
- [ ] **Step 2: Run the focused tests** and confirm the current models cannot carry the optional relation and the unknown path has no dedicated safe response.
- [ ] **Step 3: Implement optional ID-only mapping** with explicit v1/v2 source aliases and no required-field escalation; preserve Personio-ID resolution only inside the service and strip it from all claims and metadata.
- [ ] **Step 4: Implement the supervisor intent** as directory-only and fail closed until an authorized relation and approved candidate context exist. Do not use the field for portal rights.
- [ ] **Step 5: Run all Personio directory tests** and commit `feat(personio): add fail-closed supervisor evidence path`.

### Task 5: Encode functional-responsibility acceptance and validate locally

**Files:**
- Modify: `stack/tests/test_kahle_knowledge_harness.py`
- Modify: `scripts/openwebui/kahle-harness-acceptance-matrix.json`
- Modify: `docs/operations/personio-directory.md`

**Produces:** A versioned acceptance matrix distinguishes RAG-established functional responsibility from Personio current persons, with a role-only matrix as the future bridging option and no manual people list.

- [ ] **Step 1: Write failing tests** asserting Mahnung and Beschwerden require only RAG unless a structured, stable role mapping is supplied; ambiguous RAG claims remain unsupported.
- [ ] **Step 2: Run focused tests** to confirm the old generic contact heuristic violates this separation.
- [ ] **Step 3: Implement the evidence contract and matrix cases**: RAG may emit only an approved function/role marker, which is eligible for a later Personio lookup only when the mapping is unambiguous; RAG names are discarded.
- [ ] **Step 4: Update operations documentation** with the sanitized supervisor probe, the external readable-attribute blocker, and the required manual UI checks.
- [ ] **Step 5: Run full verification**: service suite, relevant stack suites, complete local suite, `build_tools.py --check`, `compileall`, `git diff --check`, then narrowly rebuild/restart and health-check only if the local Docker daemon and required environment are available.
- [ ] **Step 6: Commit** with `test(harness): cover Personio routing acceptance cases`.

# Retrieval Planning, Metadata and Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a pre-retrieval, model-independent plan with portal-owned document classification, explicit relationship requirements and claim-level RAG evidence.

**Architecture:** The Knowledge Harness produces a complete `RetrievalPlan` before adapters run. The portal owns additive classification records, kb-sync projects confirmed metadata into Qdrant, and rag_chat applies the plan before reranking and evidence construction. Original uploaded files are immutable.

**Tech Stack:** Python, FastAPI, SQLite, Qdrant, OpenWebUI middleware, pytest

**Spec:** `docs/superpowers/specs/2026-08-25-retrieval-planning-metadata-evidence-design.md`

**Umsetzungsstand 25. August 2026:** Alle sechs Tasks sind lokal umgesetzt und
serviceweise verifiziert. Die Klassifikationslogik liegt gebündelt in
`stack/kb-admin-api/app/retrieval_metadata.py`; der idempotente Backfill und sein
Dry-run verwenden denselben Store. Die ursprünglich geplanten separaten
Backfill-Dateien wurden deshalb nicht angelegt. Die fachliche Personio-Live- und
UI-Abnahme bleibt ein externer Go-live-Nachweis und ist nicht Teil dieses lokalen
Implementierungsabschlusses.

## Global Constraints

- Preserve all existing user changes and the completed Personio implementation.
- Edit files only with `apply_patch`.
- Do not commit or push.
- Never modify uploaded source files to add classification data.
- Do not infer a factual relationship unless one evidence span explicitly states it.
- Keep source and `dist` tool files synchronized through `build_tools.py`.

---

### Task 0: Preserve the accepted RAG hardening baseline

**Files:**
- Modify: `stack/open-webui-tools/rag_chat_hybrid_tool.py`
- Modify: `stack/tests/test_hybrid_retrieval_security.py`
- Modify: `stack/open-webui-overrides/open_webui/utils/middleware.py`
- Modify: `stack/tests/test_middleware_internal_rag_routing.py`

**Interfaces:**
- Produces: the already accepted evidence-relevance and clarification behaviour on the Personio integration base.
- Invariant: Personio routing and merged evidence remain unchanged.

- [ ] Port the failing tests for work-instruction domain separation, person/system relationship coverage, customer-lock follow-up normalization and complete opening-hours scope.
- [ ] Run the focused modules and verify the regressions fail on the Personio branch baseline.
- [ ] Port the minimal model-independent fixes with `apply_patch`.
- [ ] Build `dist` and run the focused modules again.

### Task 1: Deep RetrievalPlan interface

**Files:**
- Modify: `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py`
- Modify: `stack/tests/test_kahle_knowledge_harness.py`

**Interfaces:**
- Produces: `InformationNeed`, `RelationRequirement`, and the extended `RetrievalPlan`.
- Consumes: existing `plan_retrieval(query, resolved_query, messages, model_id, permission_scope)`.

- [ ] Add failing tests for work-instruction domain planning, capability planning, relationship planning and model parity.
- [ ] Run the focused test module and confirm the new assertions fail for missing fields.
- [ ] Add immutable dataclasses and populate them in `plan_retrieval` without using model IDs for business routing.
- [ ] Keep `required_tool` compatibility and Personio multi-source behaviour.
- [ ] Run the focused tests and existing Personio Harness tests.

### Task 2: Portal-owned document classification

**Files:**
- Modify: `stack/kb-admin-api/app/main.py`
- Modify: `stack/kb-admin-api/tests/test_portal_api.py`
- Create: `stack/kb-admin-api/scripts/backfill_document_classification.py`
- Create: `stack/kb-admin-api/tests/test_document_classification_backfill.py`

**Interfaces:**
- Produces: version-bound classification records and an idempotent backfill function.
- Invariant: no source file write and no document checksum change.

- [ ] Add failing migration and repository tests for additive classification storage.
- [ ] Add failing backfill tests for confirmed, inferred and review-required outcomes.
- [ ] Implement controlled vocabularies and additive SQLite migration.
- [ ] Implement deterministic classification from title, headings and content with confidence/status.
- [ ] Prove in tests that the source path and file bytes are never written.
- [ ] Add a read-only listing and admin confirmation path for review-required records.
- [ ] Run portal and backfill tests.

### Task 3: Project classification into the hybrid index

**Files:**
- Modify: `stack/kb-sync/app/hybrid_sync.py`
- Modify: `stack/kb-sync/app/canonical_inventory.py`
- Modify: `stack/kb-sync/tests/test_hybrid_sync.py`
- Modify: `stack/kb-sync/tests/test_portal_inventory.py`
- Modify: `stack/open-webui-tools/hybrid_retrieval.py`
- Modify: `stack/tests/test_hybrid_retrieval_security.py`

**Interfaces:**
- Consumes: portal classification attached to `CanonicalIndexDocument`.
- Produces: Qdrant payload fields and optional plan filters.

- [ ] Add failing inventory tests for classification transport without Markdown mutation.
- [ ] Add failing Qdrant payload tests for domain, document type, capabilities and status/version.
- [ ] Add failing retrieval tests proving only trusted classifications become hard filters.
- [ ] Implement the additive canonical fields and Qdrant payload indexes.
- [ ] Apply plan filters before reranking while retaining ACL and validity filters.
- [ ] Run kb-sync and hybrid retrieval tests.

### Task 4: Explicit relationship coverage and claim-level evidence

**Files:**
- Modify: `stack/open-webui-tools/rag_chat_hybrid_tool.py`
- Modify: `stack/open-webui-tools/hybrid_retrieval.py`
- Modify: `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py`
- Modify: `stack/tests/test_hybrid_retrieval_security.py`
- Modify: `stack/tests/test_rag_evidence_bundle_contract.py`
- Modify: `stack/tests/test_kahle_knowledge_harness.py`

**Interfaces:**
- Consumes: `RetrievalPlan.information_needs` and `RelationRequirement`.
- Produces: supported claims with `claim_id`, `source_id`, `text`, `claim_type`, and `evidence_span`.

- [ ] Add failing tests for split person/system evidence, explicit relationship evidence and unsupported relationships.
- [ ] Add failing tests ensuring a topic-existence passage cannot satisfy a procedure claim.
- [ ] Add failing EvidenceBundle schema tests for claim IDs and exact evidence spans.
- [ ] Implement sentence/window selection and relationship coverage without model-authored facts.
- [ ] Make partial support name the uncovered information need.
- [ ] Extend validation to reject unknown claim/source IDs.
- [ ] Build the distributed tool and run contract tests.

### Task 5: Backfill, compatibility and complete verification

**Files:**
- Modify: `scripts/openwebui/kahle-harness-acceptance-matrix.json`
- Modify: `scripts/openwebui/kahle-harness-acceptance.py`
- Modify: `docs/operations/personio-directory.md`
- Create: `docs/operations/document-classification.md`

**Interfaces:**
- Consumes: all previous tasks.
- Produces: repeatable migration and acceptance instructions.

- [ ] Add acceptance cases for domain separation, relationship coverage, partial procedures and model parity.
- [ ] Run the backfill in dry-run mode and verify counts contain no document content.
- [ ] Run syntax checks, `build_tools.py --check`, focused suites and full `stack/tests`.
- [ ] Run `git diff --check` and verify original uploaded files are unchanged.
- [ ] Document rollout, backup and rollback without preparing or installing a production package.

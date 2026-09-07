# Model-led Knowledge Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace wording-bound pre-routing and deterministic contact answers with model-selected Personio/RAG tools, while preserving authorization, source authority, supervisor safety, exact evidence validation and fail-closed behavior.

**Architecture:** OpenWebUI injects a request-bound `personio_directory` tool next to the existing `rag_chat` tool. The model selects one or both sources through the normal tool loop. A new request-local knowledge module records only actual tool results, lets the existing Harness normalize and validate their evidence, and supplies an AnswerContract before the final model response. RAG retrieval hints remain searchable but can never become answer evidence. The legacy deterministic route remains behind a rollback mode for the first release and is deleted only after acceptance.

**Tech Stack:** Python 3.11, FastAPI, Open WebUI v0.11.0 overrides, Qdrant hybrid retrieval, pytest, Docker Compose, PowerShell.

**Spec:** `docs/superpowers/specs/2026-09-01-model-led-knowledge-routing-design.md`

## Global constraints

- Do not change Personio field permissions, read-only access, sync behavior or Portal ACLs.
- Never infer a supervisor from title, ordering, team, department, RAG or model knowledge.
- Do not expose Personio credentials, raw provider responses or employee data in logs, fixtures or reports.
- Do not add a persisted standalone Personio OpenWebUI tool; bind the existing internal client request-locally.
- Preserve global `kahle_direct_final_content` behavior for file, form and mail paths; remove only Knowledge-Harness ownership of that field.
- Keep `rag_chat` source and generated `dist/` synchronized.
- Run Python service suites in separate pytest processes because their packages share the name `app`.
- No production activation, external live probe, push or server rollout is included.

---

### Task 1: Freeze the safe behavior and expose the current failure modes

**Files:**
- Modify: `stack/tests/test_kahle_knowledge_harness.py`
- Modify: `stack/tests/test_middleware_internal_rag_routing.py`
- Modify: `stack/tests/test_rag_evidence_bundle_contract.py`
- Modify: `stack/tests/test_kahle_harness_reference_matrix.py`
- Modify: `stack/personio-directory/tests/test_search.py`
- Modify: `stack/kb-sync/tests/test_hybrid_index.py`

**Keep as invariants:**
- permissions are bound before any internal adapter call;
- pending/unauthorized users cannot call Personio;
- Personio result validation rejects unknown fields, malformed source IDs and missing sync timestamps;
- supervisor names require one resolvable Personio supervisor ID;
- an explicit new full name never inherits a previous supervisor candidate;
- only referential supervisor follow-ups may use the immediately relevant previous user query;
- exact contact values and cited source IDs must come from the current EvidenceBundle;
- RAG never overrides current Personio master data.

- [ ] **Step 1: Add characterization tests for functionality that must survive**

Use only synthetic records such as `Erika Beispiel`, `Max Muster` and
`team@example.invalid`. Cover one Personio-only query, one RAG-only query, one
explicitly mixed query, supervisor success/fail-closed, unauthorized access,
stale directory evidence, malformed Personio payload and exact contact-value
validation.

- [ ] **Step 2: Add failing regression tests for the observed defects**

Add outcome-focused cases for:

```text
Serviceassistenzen Neustadt
Serviceassistentinnen in Neustadt
Wie erreiche ich die IT?
Wie lautet das Funktionspostfach des Marketings?
Wie ist die E-Mail-Adresse der Personalabteilung?
Welche Kontakte gibt es für Bewerbungen?
Wohin schicke ich meine Bewerbung?
Wo soll ich meine Krankmeldung hinschicken?
Wie lautet das Funktionspostfach und wer arbeitet aktuell im Marketing?
```

The failing assertions must demonstrate the current pre-router's wrong tool
choice, an index/example sentence becoming a claim, an unrelated contact
document surviving retrieval, or a Harness direct answer replacing model output.

- [ ] **Step 3: Run RED in isolated suites**

```powershell
$py = ".\.venv-verify\Scripts\python.exe"
& $py -m pytest stack\tests\test_kahle_knowledge_harness.py stack\tests\test_middleware_internal_rag_routing.py stack\tests\test_rag_evidence_bundle_contract.py stack\tests\test_kahle_harness_reference_matrix.py -q -p no:cacheprovider
& $py -m pytest stack\personio-directory\tests\test_search.py -q -p no:cacheprovider
& $py -m pytest stack\kb-sync\tests\test_hybrid_index.py -q -p no:cacheprovider
```

Expected: the new regression tests fail for the documented reasons while the
new invariant tests pass.

- [ ] **Step 4: Commit only the characterization layer**

```powershell
git add stack/tests/test_kahle_knowledge_harness.py stack/tests/test_middleware_internal_rag_routing.py stack/tests/test_rag_evidence_bundle_contract.py stack/tests/test_kahle_harness_reference_matrix.py stack/personio-directory/tests/test_search.py stack/kb-sync/tests/test_hybrid_index.py
git diff --cached --check
git commit -m "test(knowledge): lock source authority regressions"
```

---

### Task 2: Add adapter-local `auto` intent to the private Personio contract

**Files:**
- Modify: `stack/personio-directory/app/main.py`
- Modify: `stack/personio-directory/app/models.py` only if the resolved intent is carried through the domain object
- Modify: `stack/personio-directory/app/search.py`
- Modify: `stack/personio-directory/tests/test_api.py`
- Modify: `stack/personio-directory/tests/test_search.py`
- Modify: `stack/open-webui-overrides/open_webui/utils/personio_directory_client.py`
- Modify: `stack/tests/test_middleware_internal_rag_routing.py`

**Interfaces:**
- Private request accepts controlled `intent="auto"` in addition to existing explicit intents.
- The API, not the model, resolves `auto` through `classify_directory_query(query)`.
- Private response adds validated `resolved_intent`.
- `PersonioDirectoryClient.search(..., intent="auto")` validates claims against `resolved_intent` and returns only the existing safe fields.

- [ ] **Step 1: Write failing API and client-contract tests**

Prove that `auto` resolves compact role/location phrases to
`directory_search`, exact people to `person_lookup`, onboarding questions to
`onboarding_search` and supervisor questions to `supervisor_lookup`. Prove that
an unknown or missing `resolved_intent` makes the OpenWebUI client return
`directory_unavailable`.

- [ ] **Step 2: Write privacy regression tests**

For an `auto` onboarding query, make the fake service attempt to return
`business_email`, `business_phone`, `employment_status` or Personio IDs as
claims. The client must reject or strip the payload according to the existing
onboarding field contract. Do not weaken `_ONBOARDING_CLAIM_FIELDS`.

- [ ] **Step 3: Run RED**

```powershell
& $py -m pytest stack\personio-directory\tests\test_api.py stack\personio-directory\tests\test_search.py -q -p no:cacheprovider -k "auto or resolved_intent"
& $py -m pytest stack\tests\test_middleware_internal_rag_routing.py -q -p no:cacheprovider -k "personio_client"
```

- [ ] **Step 4: Implement the minimal private-contract change**

Resolve `auto` once in `main.py`, construct `DirectoryQuery` with the resolved
bounded intent, and use the same resolved value for response-field minimization.
Do not add source-routing behavior to the Personio service.

- [ ] **Step 5: Run GREEN and the complete Personio suite**

```powershell
& $py -m pytest stack\personio-directory\tests -q -p no:cacheprovider
& $py -m pytest stack\tests\test_middleware_internal_rag_routing.py -q -p no:cacheprovider -k "personio_client"
```

- [ ] **Step 6: Commit the private API evolution**

```powershell
git add stack/personio-directory/app/main.py stack/personio-directory/app/models.py stack/personio-directory/app/search.py stack/personio-directory/tests/test_api.py stack/personio-directory/tests/test_search.py stack/open-webui-overrides/open_webui/utils/personio_directory_client.py stack/tests/test_middleware_internal_rag_routing.py
git diff --cached --check
git commit -m "feat(personio): support server-resolved directory intent"
```

---

### Task 3: Introduce the deep request-local internal knowledge module

**Files:**
- Create: `stack/open-webui-overrides/open_webui/utils/kahle_internal_knowledge.py`
- Modify: `stack/open-webui-overrides/open_webui/utils/middleware.py`
- Modify: `stack/docker-compose.yml`
- Modify: `stack/tests/test_personio_directory_contracts.py`
- Create: `stack/tests/test_kahle_internal_knowledge.py`

**Interfaces:**

```python
def bind_internal_knowledge_tools(
    *, tools: dict[str, Any], request: Any, user: Any,
    model: dict[str, Any], messages: list[dict[str, Any]],
) -> tuple[dict[str, Any], KnowledgeEvidenceSession]: ...

class KnowledgeEvidenceSession:
    def record(self, tool_name: str, result: Any) -> None: ...
    def called_tools(self) -> tuple[str, ...]: ...
    def build_decision(self, *, query: str, permission_scope: dict[str, Any]) -> HarnessDecision: ...
```

The module must use the existing standard tool shape (`spec`, `callable`,
`type`, `direct`) so both native and legacy OpenWebUI function-calling loops can
execute it without a parallel executor.

- [ ] **Step 1: Write failing tool-binding tests**

Assert that:

- general Vinci models receive `personio_directory`;
- Vinci Admin, unrelated models and roles other than `user`/`admin` do not;
- the model-visible schema accepts only `query`;
- the bound callable sends `intent="auto"`, authenticated user ID and role;
- no secret, candidate query or permission field appears in the tool schema;
- the existing `rag_chat` callable is wrapped, not replaced;
- actual result recording is request-local and cannot leak across concurrent sessions.

- [ ] **Step 2: Move supervisor candidate scoping into this module**

Move the narrow logic currently implemented by
`_supervisor_candidate_query(messages, query)`. It may recognize only a
supervisor relation, an explicit new full name and controlled referential forms.
It must not classify general directory/RAG source needs. Add sequence tests for
`seine`, `ihre`, `deren`, `dessen`, `die Führungskraft`, `er` and `sie`, plus a
new explicit name that clears the candidate.

- [ ] **Step 3: Run RED**

```powershell
& $py -m pytest stack\tests\test_kahle_internal_knowledge.py stack\tests\test_personio_directory_contracts.py -q -p no:cacheprovider
```

- [ ] **Step 4: Implement the minimal deep module and Compose mount**

Add the read-only mount next to `kahle_knowledge_harness.py` and
`personio_directory_client.py`. Bind the Personio tool only after the existing
OpenWebUI tool resolution and before tools are serialized for the model. Wrap
`rag_chat` only to capture its already permission-filtered result.

- [ ] **Step 5: Run GREEN and compile the mounted modules**

```powershell
& $py -m pytest stack\tests\test_kahle_internal_knowledge.py stack\tests\test_personio_directory_contracts.py -q -p no:cacheprovider
& $py -m compileall -q stack\open-webui-overrides\open_webui\utils stack\personio-directory\app
```

- [ ] **Step 6: Commit the model-visible Personio seam**

```powershell
git add stack/open-webui-overrides/open_webui/utils/kahle_internal_knowledge.py stack/open-webui-overrides/open_webui/utils/middleware.py stack/docker-compose.yml stack/tests/test_kahle_internal_knowledge.py stack/tests/test_personio_directory_contracts.py
git diff --cached --check
git commit -m "feat(knowledge): expose request-bound Personio tool"
```

---

### Task 4: Replace RAG-first prompts with explicit source authority

**Files:**
- Modify: `stack/open-webui-prompts/kahle-vinci-systemprompt.md`
- Modify: `stack/open-webui-prompts/kahle-vinci-thinking-systemprompt.md`
- Modify: `scripts/openwebui/register-kahle-workflow-tool.py`
- Modify: `scripts/openwebui/register-vinci-models.py`
- Modify: `stack/tests/test_kahle_max_model_registration.py`
- Modify: `stack/tests/test_rag_evidence_bundle_contract.py`
- Create: `stack/tests/test_vinci_knowledge_source_prompt_contracts.py`

**Prompt contract:**
- current people, person profiles, business contacts, role/team/department/location lists, onboarding and supervisors -> `personio_directory`;
- documented processes, responsibilities, shared mailboxes, ticket systems, submission and contact paths -> `rag_chat`;
- use both only when the question actually asks for both evidence types;
- never use web search as fallback for an absent employee or supervisor result;
- compact noun phrases are complete search requests;
- answer only from returned evidence and disclose missing parts.

- [ ] **Step 1: Write failing prompt and registration tests**

Assert that all known Vinci base prompts and the shared function-calling prompt
contain both source descriptions and no longer state that RAG is the single
source of truth for roles or contacts. Assert that future `kahle-vinci-*` models
still receive the same shared policy.

- [ ] **Step 2: Update tool descriptions and prompts once**

Keep detailed semantics in the two tool descriptions and one concise shared
source matrix. Remove duplicated RAG-first lines instead of appending
contradictory exceptions. Do not add lists of department names or user-phrase
templates.

- [ ] **Step 3: Run targeted tests**

```powershell
& $py -m pytest stack\tests\test_kahle_max_model_registration.py stack\tests\test_rag_evidence_bundle_contract.py stack\tests\test_open_webui_override_contracts.py stack\tests\test_vinci_knowledge_source_prompt_contracts.py -q -p no:cacheprovider
```

- [ ] **Step 4: Commit the shared model policy**

```powershell
git add stack/open-webui-prompts/kahle-vinci-systemprompt.md stack/open-webui-prompts/kahle-vinci-thinking-systemprompt.md scripts/openwebui/register-kahle-workflow-tool.py scripts/openwebui/register-vinci-models.py stack/tests/test_kahle_max_model_registration.py stack/tests/test_rag_evidence_bundle_contract.py stack/tests/test_vinci_knowledge_source_prompt_contracts.py
git diff --cached --check
git commit -m "refactor(knowledge): teach models explicit source authority"
```

---

### Task 5: Make the Harness consume actual tool results instead of choosing tools

**Files:**
- Modify: `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py`
- Modify: `stack/open-webui-overrides/open_webui/utils/kahle_internal_knowledge.py`
- Modify: `stack/open-webui-overrides/open_webui/utils/middleware.py`
- Modify: `stack/tests/test_kahle_knowledge_harness.py`
- Modify: `stack/tests/test_kahle_internal_knowledge.py`
- Modify: `stack/tests/test_middleware_internal_rag_routing.py`

**Keep:**
- validated Personio/RAG parsers;
- `merge_evidence()` and Personio authority over same-field RAG claims;
- EvidenceBundle status, claims, missing information, conflicts and sources;
- AnswerContract, exact contact allow-list and source-ID validation;
- privacy, permission and supervisor checks;
- datensparse technical events and metrics.

**Stop using in `model_led` mode:**
- `_directory_information_need()`;
- `_rag_information_need()`;
- `_information_needs()` for source choice;
- `plan_retrieval()` as a regex-based global router;
- `classify_personio_directory_intent()` in the Harness;
- `_organizational_contact_question()`, `_functional_contact_delivery_question()` and other global phrase predicates used only for source selection;
- `_apply_contact_evidence_requirement()` as query-wording-dependent evidence gating while retaining exact `_contact_values()` extraction;
- `_organization_contact_answer()` and `_cited_contact_instructions()` as answer generators;
- `_knowledge_harness_direct_answer()`;
- `_filter_native_tools_for_kahle_retrieval()`;
- `_planned_rag_tool_calls()` and forced RAG pre-routing.

- [ ] **Step 1: Write failing result-driven Harness tests**

Build decisions from actual recorded results:

- Personio called -> Personio EvidenceBundle only;
- RAG called -> RAG EvidenceBundle only;
- both called -> merged EvidenceBundle;
- neither called -> no internal Harness decision;
- Personio not found -> no RAG or web fallback;
- RAG unsupported -> no Personio fallback;
- mixed evidence keeps current people fields from Personio and documented paths from RAG.

- [ ] **Step 2: Introduce `KAHLE_KNOWLEDGE_ROUTING_MODE`**

Accept only `legacy` and `model_led`, defaulting to `legacy` in the first
release. In `model_led`, bypass deterministic pre-execution, direct knowledge
answers and source-based tool filtering. Compute the legacy plan only as a
side-effect-free comparison metric with no raw query or evidence persisted.

- [ ] **Step 3: Inject the AnswerContract after actual internal tool calls**

Before the next model generation in the existing tool loop, build the decision
from the session's accumulated results and append/update one contract system
message. Rebuilding after a second internal tool call must replace the previous
contract rather than append duplicates.

- [ ] **Step 4: Preserve unrelated direct-final paths**

Add source-level tests proving that file, form and mail assignments to
`kahle_direct_final_content` remain present while no Knowledge-Harness function
writes to it in `model_led` mode.

- [ ] **Step 5: Run targeted GREEN**

```powershell
& $py -m pytest stack\tests\test_kahle_knowledge_harness.py stack\tests\test_kahle_internal_knowledge.py stack\tests\test_middleware_internal_rag_routing.py stack\tests\test_open_webui_override_contracts.py -q -p no:cacheprovider
```

- [ ] **Step 6: Commit the result-driven Harness path**

```powershell
git add stack/open-webui-overrides/open_webui/utils stack/tests
git diff --cached --check
git commit -m "refactor(knowledge): validate actual model-selected sources"
```

---

### Task 6: Separate RAG retrieval hints from answer evidence

**Files:**
- Modify: `stack/kb-sync/app/hybrid_index.py`
- Modify: `stack/kb-sync/app/hybrid_sync.py`
- Modify: `stack/kb-sync/tests/test_hybrid_index.py`
- Modify: `stack/kb-sync/tests/test_hybrid_sync.py`
- Modify: `stack/open-webui-tools/hybrid_retrieval.py`
- Modify: `stack/open-webui-tools/rag_chat_hybrid_tool.py`
- Regenerate: `stack/open-webui-tools/dist/rag_chat_hybrid_tool.py`
- Regenerate: `stack/open-webui-tools/dist/kahle_workflow_orchestrator.py`
- Modify: `stack/tests/test_hybrid_retrieval_security.py`
- Modify: `stack/tests/test_rag_evidence_bundle_contract.py`

**Interfaces:**
- `ChildChunk.kind` adds `retrieval_hint`.
- Qdrant payload continues to use `chunk_kind`; no new source of truth or DB schema is introduced.
- Hint hits can focus an already ACL-filtered document but are removed before final reranking, context and claims.
- `_claim_evidence_spans()` returns no claim when the best substantive overlap is zero.

- [ ] **Step 1: Add a synthetic function-mailbox document fixture**

The fixture must contain a broad „Für Fragen wie“ block, a „Kurzindex“ and
separate substantive sections for IT, Marketing, applications and sickness
notifications. Use reserved addresses only.

- [ ] **Step 2: Write failing chunk and retrieval tests**

Prove that a query can use a hint to locate the document but receives only the
matching substantive section. Prove that an IT query cannot return the
Marketing/application section and that no-overlap passages create no supported
claim.

- [ ] **Step 3: Implement hint classification and same-document expansion**

Recognize only controlled heading labels, not arbitrary text containing
„Frage“. Keep ACL, publication, version and validity filters ahead of expansion.
Do not fetch another document by title alone. Remove hint chunks before
reranking and EvidenceBundle construction.

- [ ] **Step 4: Remove the zero-overlap first-sentence fallback**

Keep exact positive-overlap spans and existing conflict/source handling. A
document-level `contact_details` capability may admit candidates but may not
turn an unrelated sentence into a claim.

- [ ] **Step 5: Build and verify tool bundles**

```powershell
& $py stack\open-webui-tools\build_tools.py
& $py stack\open-webui-tools\build_tools.py --check
```

- [ ] **Step 6: Run isolated retrieval suites**

```powershell
& $py -m pytest stack\kb-sync\tests -q -p no:cacheprovider
& $py -m pytest stack\tests\test_hybrid_retrieval_security.py stack\tests\test_rag_evidence_bundle_contract.py -q -p no:cacheprovider
```

- [ ] **Step 7: Commit source and generated bundles together**

```powershell
git add stack/kb-sync/app/hybrid_index.py stack/kb-sync/app/hybrid_sync.py stack/kb-sync/tests/test_hybrid_index.py stack/kb-sync/tests/test_hybrid_sync.py stack/open-webui-tools/hybrid_retrieval.py stack/open-webui-tools/rag_chat_hybrid_tool.py stack/open-webui-tools/dist/rag_chat_hybrid_tool.py stack/open-webui-tools/dist/kahle_workflow_orchestrator.py stack/tests/test_hybrid_retrieval_security.py stack/tests/test_rag_evidence_bundle_contract.py
git diff --cached --check
git commit -m "fix(rag): keep retrieval hints out of answer evidence"
```

---

### Task 7: Validate the final internal answer before it becomes visible

**Files:**
- Modify: `stack/open-webui-overrides/open_webui/utils/middleware.py`
- Modify: `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py`
- Modify: `stack/tests/test_middleware_internal_rag_routing.py`
- Modify: `stack/tests/test_kahle_knowledge_harness.py`

**Behavior:**
- buffer only the final answer text of turns that actually used an approved internal knowledge tool;
- keep native tool-status and source events visible;
- validate before the first final-text replacement/completion event;
- retry the same model once with the same EvidenceBundle and no tools;
- use a stable neutral fallback after the second failure or timeout;
- never let the validator compose a person, mailbox, path or process.

- [ ] **Step 1: Replace the current “validation only records metadata” test**

Remove the assertion that `validation.retry_prompt()` is absent. Add stream and
non-stream cases for valid first answer, invalid first/valid retry,
invalid-both, retry timeout and no-internal-tool normal streaming.

- [ ] **Step 2: Add event-order regressions**

Assert that the user sees at most one final answer text, citations remain
attached, and no invalid first text is emitted or persisted. Tool status may
precede it. The retry must not emit a second `rag_chat` or
`personio_directory` call.

- [ ] **Step 3: Implement bounded buffering and retry**

Reuse `AnswerValidation.retry_prompt()` and the existing answer timeout helper.
Do not add an LLM call to the outlet filter. The corrective call belongs inside
the answer loop before persistence and receives `tools: []`.

- [ ] **Step 4: Run targeted tests**

```powershell
& $py -m pytest stack\tests\test_middleware_internal_rag_routing.py stack\tests\test_kahle_knowledge_harness.py -q -p no:cacheprovider -k "validation or retry or stream or timeout"
```

- [ ] **Step 5: Commit the pre-display validation path**

```powershell
git add stack/open-webui-overrides/open_webui/utils/middleware.py stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py stack/tests/test_middleware_internal_rag_routing.py stack/tests/test_kahle_knowledge_harness.py
git diff --cached --check
git commit -m "fix(knowledge): validate internal answers before display"
```

---

### Task 8: Make acceptance outcome-based where model choice is legitimately flexible

**Files:**
- Modify: `scripts/openwebui/kahle-harness-acceptance.py`
- Modify: `scripts/openwebui/kahle-harness-acceptance-matrix.json`
- Modify: `stack/tests/test_kahle_harness_acceptance_report.py`
- Modify: `docs/KAHLE-VINCI-UI-ABNAHME-HARNESS.md`

**Matrix contract:**
- strict cases use `required_tools` and `allowed_tools` with the same single value;
- explicit mixed cases require both values;
- legitimately ambiguous area-contact phrasing requires RAG but may allow Personio additionally;
- `actual_tools` always comes from executed tool events, never the legacy plan;
- expected source kinds must be a subset of actual validated source kinds;
- no raw question, answer, evidence, person or contact value enters the report.

- [ ] **Step 1: Write failing schema and report tests**

Cover required subset, allowed superset, forbidden extra tool, missing source,
Personio-to-web fallback, RAG feedback-link requirement and no-tool general
conversation.

- [ ] **Step 2: Migrate the matrix**

Include paraphrases and compact noun phrases, not only complete questions. Add
strict controls for current people, functional mailboxes, explicit mixed need,
supervisor follow-ups, inverted/misspelled names, missing evidence and external
general knowledge.

- [ ] **Step 3: Run acceptance contract tests**

```powershell
& $py -m pytest stack\tests\test_kahle_harness_acceptance_report.py -q -p no:cacheprovider
```

The existing pytest contract loads and validates
`kahle-harness-acceptance-matrix.json`; do not invent a separate CLI mode unless
there is a later operational need for one.

- [ ] **Step 4: Commit the model-aware acceptance contract**

```powershell
git add scripts/openwebui/kahle-harness-acceptance.py scripts/openwebui/kahle-harness-acceptance-matrix.json stack/tests/test_kahle_harness_acceptance_report.py docs/KAHLE-VINCI-UI-ABNAHME-HARNESS.md
git diff --cached --check
git commit -m "test(knowledge): evaluate model-selected source use"
```

---

### Task 9: Enable the local model-led path and run the complete acceptance gate

**Files:**
- Modify: `stack/docker-compose.local-edge.yml`
- Modify: `stack/env.production.template`
- Modify: `stack/tests/test_personio_directory_contracts.py`
- Modify: `docs/operations/personio-directory.md`
- Modify: `ARCHITECTURE.md`
- Modify: `DECISIONS.md`
- Modify if the current test inventory changes: `docs/VERIFICATION.md`

- [ ] **Step 1: Set local-only activation**

Set `KAHLE_KNOWLEDGE_ROUTING_MODE=model_led` in the local edge overlay. Keep the
base/production default `legacy` for Release A and document the exact rollback
to `legacy`. Do not change production runtime state.

- [ ] **Step 2: Run all targeted suites in their required isolation**

```powershell
& $py -m pytest stack\tests -q -p no:cacheprovider
& $py -m pytest stack\personio-directory\tests -q -p no:cacheprovider
& $py -m pytest stack\kb-sync\tests -q -p no:cacheprovider
& $py -m pytest stack\kb-admin-api\tests -q -p no:cacheprovider
& $py stack\tests\compose_static_check.py
& $py stack\open-webui-tools\build_tools.py --check
```

- [ ] **Step 3: Run canonical Full Verify**

```powershell
.\scripts\run-local-tests.ps1 -Tier Full -Python .\.venv-verify\Scripts\python.exe -Npm npm.cmd
```

Do not report completion while a product test fails. Classify a reproducible
sandbox-only UI `spawn EPERM` separately and rerun the same build outside the
restricted sandbox before calling it a setup failure.

- [ ] **Step 4: Rebuild the local affected services and reindex**

Use `scripts/start-stack.ps1` so protected environment values and the canonical
Compose project name are loaded. Recreate `personio-directory` and `open-webui`,
then run the repository-supported controlled KB reindex path because
`chunk_kind` changed. Do not print resolved secrets:

```powershell
$composeArgs = @(
  "-p", "kahle-vinci",
  "-f", "stack/docker-compose.yml",
  "-f", "stack/docker-compose.kahle-ui.yml",
  "-f", "stack/docker-compose.local-edge.yml"
)
docker compose @composeArgs exec -T kb-admin-api python -c "import os,requests; r=requests.post('http://kb-sync:8093/reindex-all',headers={'X-API-Key':os.environ['KB_SYNC_INTERNAL_API_KEY']},timeout=300); print({'status_code':r.status_code,'ok':bool(r.json().get('ok'))})"
```

The command reports only HTTP status and a boolean result. It must not print the
internal API key or resolved Compose configuration.

- [ ] **Step 5: Run the automated model matrix**

Run every strict case against KAHLE-Vinci, KAHLE-Vinci-Thinking and
KAHLE-Vinci-Max-Thinking. Required pass conditions:

- 100% strict source-boundary cases;
- 100% supervisor safety cases;
- 100% contact-literal and source-ID validation cases;
- no Personio/RAG question falls back to web;
- no hint/index sentence appears as answer evidence;
- all explicit mixed cases use both sources;
- no raw PII in the saved report.

- [ ] **Step 6: Perform manual UI acceptance at `http://localhost:3004`**

Confirm visible tool names, source links, feedback link, one stable final answer,
pronoun follow-ups and no answer replacement after the stream settles. Use the
copy-paste prompts from the acceptance document and a fresh chat for independent
name tests.

- [ ] **Step 7: Update architecture and operations docs from verified behavior**

Record the actual model-led data flow, local activation, rollback, reindex
requirement and source matrix. Update ADR-008: department mention alone no
longer forces mixed retrieval; only actual information needs do.

- [ ] **Step 8: Commit Release A documentation and local activation**

```powershell
git add stack/docker-compose.local-edge.yml stack/env.production.template stack/tests/test_personio_directory_contracts.py docs/operations/personio-directory.md ARCHITECTURE.md DECISIONS.md docs/VERIFICATION.md
git diff --cached --check
git commit -m "chore(knowledge): enable model-led local acceptance"
```

---

### Task 10: Remove the legacy semantic router after explicit acceptance

**Prerequisite:** Do not start this task until Task 9 is fully green and the
user has explicitly approved removal based on the local acceptance results.

**Files:**
- Modify: `stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py`
- Modify: `stack/open-webui-overrides/open_webui/utils/middleware.py`
- Modify: `stack/tests/test_kahle_knowledge_harness.py`
- Modify: `stack/tests/test_middleware_internal_rag_routing.py`
- Modify: `stack/docker-compose.yml`
- Modify: `stack/docker-compose.local-edge.yml`
- Modify: `stack/env.production.template`
- Modify: `ARCHITECTURE.md`
- Modify: `DECISIONS.md`
- Modify: `docs/operations/personio-directory.md`

**Delete when no caller remains:**
- global directory/RAG source-selection predicates and their phrase matrices;
- deterministic organization-contact answer assembly;
- Knowledge-Harness direct-answer adapter;
- forced pre-route execution and planned RAG tool calls;
- Personio-only native tool filtering;
- native RAG fallback for missed internal tool calls;
- legacy `_looks_like_internal_rag_request()` and clarification gates where no non-knowledge caller remains;
- legacy comparison telemetry and routing mode.

**Explicitly retain:**
- Personio adapter-local query classification and controlled role/location aliases;
- narrow supervisor candidate context in `kahle_internal_knowledge.py`;
- RAG query normalization that improves retrieval after `rag_chat` was selected;
- EvidenceBundle parsing, merging, source authority and AnswerValidation;
- canonical RAG source/feedback extraction and native tool events;
- technical Toolcall Guard and global direct-final mechanisms for non-knowledge workflows.

- [ ] **Step 1: Prove every removal candidate is unreferenced**

Use `rg` for each function and inspect AST/source-contract tests. Replace tests
that assert implementation strings or exact wording-to-tool tuples with
behavioral source-boundary, tool-event and answer-evidence tests before deleting
production code.

- [ ] **Step 2: Remove the legacy path in small patches**

First delete call sites, run targeted tests, then delete dead functions and
imports. Do not combine this with unrelated middleware cleanup.

- [ ] **Step 3: Re-run targeted, Full and model-matrix verification**

Repeat all commands and acceptance thresholds from Task 9. Additionally run:

```powershell
rg -n "_organization_contact_answer|_cited_contact_instructions|_apply_contact_evidence_requirement|_plan_kahle_retrieval_gate|_execute_kahle_retrieval_plan|_filter_native_tools_for_kahle_retrieval|_build_native_rag_fallback" stack/open-webui-overrides stack/tests
```

Expected: no production caller or obsolete implementation-contract test remains.

- [ ] **Step 4: Commit the deletion separately**

```powershell
git add stack/open-webui-overrides/open_webui/utils/kahle_knowledge_harness.py stack/open-webui-overrides/open_webui/utils/kahle_internal_knowledge.py stack/open-webui-overrides/open_webui/utils/middleware.py stack/tests/test_kahle_knowledge_harness.py stack/tests/test_kahle_internal_knowledge.py stack/tests/test_middleware_internal_rag_routing.py stack/tests/test_open_webui_override_contracts.py stack/docker-compose.yml stack/docker-compose.local-edge.yml stack/env.production.template ARCHITECTURE.md DECISIONS.md docs/operations/personio-directory.md
git diff --cached --check
git commit -m "refactor(knowledge): remove deterministic source router"
```

---

## Final review checklist

- [ ] `git status --short` contains only intended files.
- [ ] `git diff --check` and `git diff --cached --check` pass.
- [ ] No secrets, production env, real employee fixtures, raw tool results or rollout artifacts are tracked.
- [ ] `stack/open-webui-tools/build_tools.py --check` passes.
- [ ] Personio, Stack, KB-Sync and KB-Admin tests ran in separate processes.
- [ ] Canonical Full Verify is green.
- [ ] All three Vinci model variants meet the acceptance thresholds.
- [ ] The UI shows one stable final answer and the actual tool/source events.
- [ ] Local success is reported separately from any production deployment evidence.
- [ ] No push, production rollout or server activation occurs without a new explicit approval.

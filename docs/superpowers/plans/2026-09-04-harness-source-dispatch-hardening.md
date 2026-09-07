# Harness Source Dispatch Hardening Implementation Plan

> **For agentic workers:** Execute inline and test-first. Do not add answer replacement, correction retries, production rollout or push.

**Goal:** Make the existing KAHLE Knowledge Harness reliably prepare Personio, RAG or both before the model writes one final answer, while keeping non-knowledge requests on their dedicated paths.

**Architecture:** The existing model-independent `RetrievalPlan` remains the single source-dispatch contract. In local `model_led` mode middleware executes that plan and records the resulting evidence; the model still composes the only visible answer. Specialized RAG needs fail closed when no suitably classified source exists.

**Tech Stack:** Python 3.11, Open WebUI middleware overrides, KAHLE Knowledge Harness, hybrid RAG retrieval, pytest, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-01-model-led-knowledge-routing-design.md`, amended by the accepted decision that answer validation stays shadow-only and never replaces or retries model output.

## Global Constraints

- No deterministic final answers, post-hoc correction calls or answer replacement.
- Current people and individual business contacts come from Personio.
- Processes, responsibilities and functional contacts come from RAG.
- Explicit mixed needs execute both adapters concurrently.
- General transformations and task commands do not invoke knowledge tools.
- No production activation, push, ACL change or employee data in tests and reports.

### Task 1: Make source dispatch complete and non-invasive

- [ ] Add failing tests for live person, process, functional-contact, mixed, general-text and task examples.
- [ ] Add a bounded non-knowledge exclusion and explicit functional-contact need.
- [ ] Execute the Harness plan in local `model_led` mode.
- [ ] Prove direct answer ownership and answer replacement remain absent.

### Task 2: Fail closed on domain-irrelevant responsibility evidence

- [ ] Add a failing retrieval test with an unrelated trusted source.
- [ ] Require the specialized `approved_functional_responsibility` capability when that need is planned.
- [ ] Regenerate and verify checked-in Open WebUI tool bundles.

### Task 3: Verify structured contacts and the complete local flow

- [ ] Run targeted Harness, middleware and retrieval suites.
- [ ] Run the canonical Full verification tier.
- [ ] Restart affected local services without exposing secrets.
- [ ] Verify the uploaded functional-contact source through counts, schema status and conflict status only.
- [ ] Run a small sanitized smoke set before handing the full UI matrix back for repetition.

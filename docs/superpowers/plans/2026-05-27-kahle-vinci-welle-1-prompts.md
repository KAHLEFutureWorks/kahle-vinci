# KAHLE-Vinci Welle 1 Prompts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first eight specialized KAHLE Vincis as self-contained OpenWebUI system prompt files.

**Architecture:** Store every Vinci prompt as a standalone Markdown file under `stack/open-webui-prompts/vincis/` so admins can copy each prompt into a dedicated OpenWebUI model. Add a local README that maps file names to model names, intended roles, knowledgebases, and setup notes.

**Tech Stack:** Markdown system prompts, existing OpenWebUI prompt folder, existing KAHLE knowledgebase collections (`kahleallgemein`, `kahlekontext`, `kahlerichtlinien`).

---

### Task 1: Create Welle 1 Prompt Directory

**Files:**
- Create: `stack/open-webui-prompts/vincis/README.md`
- Create: `stack/open-webui-prompts/vincis/kahle-email-vinci-systemprompt.md`
- Create: `stack/open-webui-prompts/vincis/kahle-newsletter-vinci-systemprompt.md`
- Create: `stack/open-webui-prompts/vincis/kahle-serviceberater-vinci-systemprompt.md`
- Create: `stack/open-webui-prompts/vincis/kahle-angebotsmail-vinci-systemprompt.md`
- Create: `stack/open-webui-prompts/vincis/kahle-beschwerde-vinci-systemprompt.md`
- Create: `stack/open-webui-prompts/vincis/kahle-onboarding-vinci-systemprompt.md`
- Create: `stack/open-webui-prompts/vincis/kahle-werkstatt-tagesbriefing-vinci-systemprompt.md`
- Create: `stack/open-webui-prompts/vincis/kahle-richtlinien-vinci-systemprompt.md`

- [x] **Step 1: Create the directory and README**

Create `stack/open-webui-prompts/vincis/README.md` with the Welle 1 model mapping, shared operating rules, and recommended knowledgebase attachments.

- [x] **Step 2: Add the eight prompt files**

Each prompt must be self-contained and include identity, target users, working method, question logic, output format, KAHLE style, source/assumption handling, guardrails, escalation, and external KI transparency notice where applicable.

- [x] **Step 3: Verify prompt guardrails**

Run:

```powershell
rg -n "datenschutz@kahle.de|KI-generiert|Annahmen|Fehlende|Entwurf|RAG_Chat" stack\open-webui-prompts\vincis
```

Expected: every file contains the shared safety and quality terms; `RAG_Chat` appears in the Richtlinien prompt and any prompt that can use internal knowledge.

- [x] **Step 4: Scan for placeholders**

Run:

```powershell
rg -n "T[O]DO|T[B]D|lorem|spaeter ausfuellen" stack\open-webui-prompts\vincis
```

Expected: no matches.

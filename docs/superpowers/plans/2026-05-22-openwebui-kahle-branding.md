# OpenWebUI KAHLE Branding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible KAHLE-branded OpenWebUI image with global logo/background branding and reduced settings visibility for non-privileged users.

**Architecture:** Add a small Docker image layer on top of the pinned OpenWebUI image. The layer copies KAHLE assets into OpenWebUI static files, injects a versioned KAHLE branding script into `index.html`, patches the app name suffix behavior, and wires Compose to build/use the local image.

**Tech Stack:** Docker Compose, OpenWebUI v0.9.2 image, static JavaScript/CSS, Python-based image patch script, existing Python static checks.

---

### Task 1: Add KAHLE OpenWebUI Image Layer

**Files:**
- Create: `stack/open-webui-kahle/Dockerfile`
- Create: `stack/open-webui-kahle/patch_openwebui.py`
- Create: `stack/open-webui-kahle/static/kahle-branding.css`
- Create: `stack/open-webui-kahle/static/kahle-branding.js`

- [ ] **Step 1: Create the image Dockerfile**

Create a Dockerfile that starts from `ghcr.io/open-webui/open-webui:v0.9.2`, copies the project assets and KAHLE static files, and runs the patch script.

- [ ] **Step 2: Create the patch script**

Patch `/app/build/index.html` to include `/static/kahle/kahle-branding.js`; patch `/app/backend/open_webui/env.py` so `WEBUI_NAME=KAHLE-Vinci` does not become `KAHLE-Vinci (Open WebUI)`.

- [ ] **Step 3: Add branding CSS**

Add CSS for the global chat background, title/icon replacement helpers, and settings hiding classes.

- [ ] **Step 4: Add branding JavaScript**

Fetch `/api/v1/auths/` and `/api/v1/groups/`, determine whether the user is privileged, apply body classes, set a default background image, replace visible OpenWebUI brand labels, and hide the configured settings areas for non-privileged users.

### Task 2: Wire Compose To Build The Image

**Files:**
- Modify: `stack/docker-compose.yml`
- Modify: `stack/tests/compose_static_check.py`

- [ ] **Step 1: Change open-webui image config**

Set `image: kahle-open-webui:v0.9.2-kahle.1` and add a `build` block using repository root as context and `stack/open-webui-kahle/Dockerfile`.

- [ ] **Step 2: Set the app name**

Add `WEBUI_NAME: KAHLE-Vinci` to the `open-webui` environment block.

- [ ] **Step 3: Extend static compose checks**

Assert that OpenWebUI uses the local KAHLE image, has a build block, and sets `WEBUI_NAME`.

### Task 3: Add Patch Contract Tests

**Files:**
- Create: `stack/tests/test_open_webui_kahle_branding.py`

- [ ] **Step 1: Test static files and script contracts**

Check that the Dockerfile copies the expected assets, the patch script injects `kahle-branding.js`, the JS defines the privileged groups, and the CSS contains the background asset path.

- [ ] **Step 2: Test patch script on a temporary index/env pair**

Run `patch_openwebui.py` against temporary files to prove injection and app-name suffix removal are idempotent.

### Task 4: Verify And Commit

**Files:**
- All files above

- [ ] **Step 1: Run static checks**

Run:

```powershell
python stack/tests/compose_static_check.py
python stack/tests/test_open_webui_kahle_branding.py
```

- [ ] **Step 2: Build the custom image**

Run:

```powershell
docker compose -f stack/docker-compose.yml build open-webui
```

- [ ] **Step 3: Smoke inspect the image**

Run:

```powershell
docker run --rm kahle-open-webui:v0.9.2-kahle.1 sh -lc "test -f /app/build/static/kahle/kahle-branding.js && grep -q kahle-branding.js /app/build/index.html && grep -q 'WEBUI_NAME = os.environ.get' /app/backend/open_webui/env.py"
```

- [ ] **Step 4: Commit**

Commit the implementation on `codex/openwebui-kahle-branding`.

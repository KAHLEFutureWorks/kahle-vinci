# Netcup KAHLE-Vinci Production Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish KAHLE-Vinci on the netcup server as a hardened internal employee system with Microsoft login.

**Architecture:** Keep the current Docker Compose application stack intact and add a production override for HTTPS, public URL, OAuth and file download routing. Harden the Linux host first, then migrate data, then switch DNS/users after smoke tests pass.

**Tech Stack:** Docker Compose, Caddy, Open WebUI, Microsoft Entra ID OAuth/OIDC, IONOS OpenAI-compatible API, Qdrant, n8n.

---

### Task 1: Production Deployment Artifacts

**Files:**
- Create: `stack/docker-compose.prod.yml`
- Create: `stack/caddy/Caddyfile`
- Create: `stack/env.production.template`
- Create: `docs/operations/netcup-production-deployment.md`

- [x] **Step 1: Add the production Compose override**

Create `stack/docker-compose.prod.yml` with a Caddy service, Microsoft OAuth environment variables for `open-webui`, public file proxy URL wiring, and no public exposure of n8n/Qdrant/file-worker services.

- [x] **Step 2: Add the Caddy reverse proxy config**

Create `stack/caddy/Caddyfile` so `/files/*` reaches `owui-file-proxy:8091` and all other requests reach `open-webui:8080`.

- [x] **Step 3: Add the production env template**

Create `stack/env.production.template` with placeholders only and explicit guidance to keep the real `stack/.env.production` uncommitted.

- [x] **Step 4: Add the deployment runbook**

Create `docs/operations/netcup-production-deployment.md` covering hardening, Docker setup, Entra setup, deployment, migration and go-live checks.

### Task 2: Server Hardening

**Files:**
- Use: `docs/operations/netcup-production-deployment.md`

- [ ] **Step 1: SSH into the netcup server as root**

Run:

```bash
ssh root@<server-ip>
```

- [ ] **Step 2: Patch base system and install baseline tools**

Run the hardening commands from the runbook.

- [ ] **Step 3: Create the `deploy` user and install SSH key**

Use the user's public SSH key in `/home/deploy/.ssh/authorized_keys`.

- [ ] **Step 4: Enable firewall, fail2ban and unattended upgrades**

Allow only SSH, HTTP and HTTPS inbound.

- [ ] **Step 5: Disable root/password SSH after deploy login is verified**

Keep the original session open until a second session as `deploy` works.

### Task 3: Runtime Installation

**Files:**
- Use: `docs/operations/netcup-production-deployment.md`

- [ ] **Step 1: Install Docker and Compose plugin**

Use Docker's official apt repository.

- [ ] **Step 2: Verify Docker**

Run:

```bash
docker --version
docker compose version
```

### Task 4: Microsoft Entra App Registration

**Files:**
- Use: `stack/env.production.template`
- Use: `docs/operations/netcup-production-deployment.md`

- [ ] **Step 1: Create the app registration**

Use single-tenant account type and redirect URI `https://<vinci-domain>/oauth/microsoft/callback`.

- [ ] **Step 2: Record OAuth values**

Collect tenant ID, client ID and client secret value.

- [ ] **Step 3: Fill `stack/.env.production` on the server**

Set `WEBUI_URL`, `PUBLIC_HOSTNAME`, `OPENID_PROVIDER_URL`, `MICROSOFT_*`, IONOS and all runtime secrets.

### Task 5: Migration And Launch

**Files:**
- Use: `docs/operations/netcup-production-deployment.md`

- [ ] **Step 1: Decide fresh start vs full data migration**

If existing chats/users/knowledge indexes are required, migrate Docker volumes before first production start.

- [ ] **Step 2: Start production Compose**

Run:

```bash
docker compose --env-file stack/.env.production -f stack/docker-compose.yml -f stack/docker-compose.prod.yml up -d --build
```

- [ ] **Step 3: Verify containers and HTTPS**

Run:

```bash
docker compose --env-file stack/.env.production -f stack/docker-compose.yml -f stack/docker-compose.prod.yml ps
curl -I https://<vinci-domain>
```

- [ ] **Step 4: Verify Microsoft login**

Log in with a KAHLE Microsoft account and confirm the new user is pending or approved according to rollout policy.

- [ ] **Step 5: Verify Vinci features**

Test chat, RAG, file generation/download, n8n websearch if enabled, and IONOS connectivity.

### Task 6: Post-Go-Live Security

**Files:**
- Use: `stack/.env.production`
- Use: `docs/operations/netcup-production-deployment.md`

- [ ] **Step 1: Disable password auth after SSO is proven**

Set:

```env
ENABLE_PASSWORD_AUTH=False
```

Restart:

```bash
docker compose --env-file stack/.env.production -f stack/docker-compose.yml -f stack/docker-compose.prod.yml up -d
```

- [ ] **Step 2: Confirm internet exposure**

Run:

```bash
ufw status
docker ps --format 'table {{.Names}}\t{{.Ports}}'
```

- [ ] **Step 3: Create first backup**

Archive `/opt/kahle-vinci` host-mounted data and Docker volumes before inviting broader employee groups.

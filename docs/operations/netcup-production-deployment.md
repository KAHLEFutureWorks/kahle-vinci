# KAHLE-Vinci Netcup Production Deployment

This runbook prepares and tests KAHLE-Vinci as an internal employee system on a Linux netcup server. A successful server test is not yet the productive go-live. Customer-facing use is explicitly out of scope.

## Target Architecture

- Public HTTPS: `https://<vinci-domain>` via Caddy on ports `80` and `443`.
- App access: Caddy proxies Open WebUI internally to `open-webui:8080`.
- Generated downloads: Caddy proxies `/files/*` internally to `owui-file-proxy:8091`.
- Internal-only services: n8n, Qdrant, file proxy and document worker remain unavailable from the internet.
- Models: no local LLM models on the server; model inference stays with IONOS API.
- Identity: Microsoft Entra ID / Microsoft login for employees.

## Required Inputs

- Server IPv4/IPv6 and initial SSH user.
- Target domain `vinci.kahle.de` with DNS A/AAAA records pointing to the server.
- Microsoft Entra tenant ID.
- Microsoft app registration client ID and client secret with both required redirect URIs.
- Optional for the first server test: Microsoft Graph application credentials with `Mail.Send` and a KAHLE sender mailbox. Without them, messages are retained in the protected local capture file and Graph delivery remains an open acceptance item.
- Allowed login domain, usually `kahle.de`.
- IONOS API key and existing KAHLE-Vinci runtime secrets.
- An encrypted host backup with an external verified copy. The existing systemd backup and Windows SFTP pull satisfy this on `vinci-prod-01`; do not enable the additional portal backup worker there.

The product decision for the first server test is a fresh knowledge setup. Existing Knowledgebases are not copied to the server. Every test document enters through the new portal workflow.

## Server Hardening

The production host is currently hardened as follows:

- Ubuntu 24.04 LTS, fully patched, NTP synchronized.
- Personal admin account `joltmanns`; direct root and password SSH logins disabled.
- SSH public-key authentication only.
- Host firewall UFW: default deny incoming, only TCP/22 currently allowed.
- Upstream netcup firewall: only TCP/22 allowed; implicit ingress action is DROP.
- Fail2ban protects SSH.
- Unattended security upgrades are enabled without automatic reboot.
- AppArmor, persistent journald logs and auditd rules are active.
- netcup CCP uses TOTP MFA and SCP Security Access Mode.
- An offline baseline snapshot exists from before the Docker deployment.

Verify the baseline before every production deployment:

```bash
sudo systemctl --failed --no-pager
sudo ufw status verbose
sudo fail2ban-client status sshd
sudo auditctl -l
sudo ss -tulpn
```

## Docker Runtime

Docker Engine and the Compose plugin are installed from Docker's official Ubuntu repository. The daemon uses `/etc/docker/daemon.json` with live restore, the rotating local log driver and `no-new-privileges` enabled by default.

Do not add `joltmanns` or any deployment account to the `docker` group. Membership grants effective root access. Run operational Docker commands explicitly through `sudo`.

Verify the runtime:

```bash
sudo systemctl is-active docker
sudo docker version
sudo docker compose version
sudo docker info | grep -E 'Logging Driver|Live Restore Enabled'
```
## Microsoft Entra Setup

Create an app registration:

- Name: `KAHLE-Vinci Production`
- Supported account type: single tenant only
- Redirect URI type: Web
- Redirect URI: `https://<vinci-domain>/oauth/microsoft/callback`
- Additional redirect URI: `https://<vinci-domain>/wissen/api/portal/auth/step-up/callback`

Record:

- Application client ID
- Directory tenant ID
- Client secret value

Use this provider URL in production:

```text
https://login.microsoftonline.com/<tenant-id>/v2.0/.well-known/openid-configuration
```

## Deploy App

```bash
sudo mkdir -p /opt/kahle-vinci
sudo chown deploy:deploy /opt/kahle-vinci
cd /opt/kahle-vinci
git clone <repo-url> .
sudo stack/scripts/prepare-production-env.sh stack/.env.smoke stack/.env.production.pending
sudo nano stack/.env.production.pending
sudo mv stack/.env.production.pending stack/.env.production
sudo chmod 600 stack/.env.production
```

Validate every required value, placeholder, redirect URI and the complete Compose model without starting services:

```bash
sudo stack/scripts/start-production.sh stack/.env.production --check-only
```

Only after the check succeeds, start the server test stack. The additional portal backup worker is disabled by default because `vinci-prod-01` already backs up the complete project and Docker volumes every night. Enable it only on hosts without that existing protection:

```bash
sudo stack/scripts/start-production.sh stack/.env.production
curl -I https://vinci.kahle.de/healthz
sudo docker logs --tail 100 caddy
sudo docker logs --tail 100 open-webui
```

## Fresh Knowledge Setup

Do not copy the local Knowledgebases, Qdrant volume or portal database into the first server test. Preserve the existing server state in an encrypted backup before replacing anything. Then:

1. Sign in with the designated Portal-Admin account.
2. Synchronize the required OpenWebUI users.
3. Assign Portal-Admin, Admin, manager and employee roles.
4. Create the initial Knowledgebases and read/upload permissions.
5. Upload a small representative acceptance corpus through the portal.
6. Verify sources in Vinci before adding further documents.

The local legacy inventory remains a test fixture only. Its 51 open migration tasks are not a prerequisite for the fresh server setup.

## Mandatory Server Tests

Before inviting further employees, record the following checks in `docs/WISSENSPORTAL-LOKALE-ABNAHME.md`:

- Microsoft login and fresh step-up for critical admin actions.
- Employee, manager, Admin and Portal-Admin routing with separate real accounts.
- Portal notifications for upload, approval, rejection, escalation and publication. Graph delivery remains a separately documented open test until the IT-managed app registration is available.
- Read isolation between two Knowledgebases and protected original links.
- Clean area upload, KAHLE-Allgemein approval, duplicate/version case and critical two-stage case.
- Concurrent approvals and background publication queue.
- Removal from Vinci after trashing and notification of affected readers.
- Full 21-question runtime evaluation including negative, follow-up, multi-source and conflict questions.
- Desktop and mobile UX timing with employees and managers.
- Encrypted backup, external copy and documented restore verification.

## Go-Live Checklist

- DNS resolves to the netcup server.
- `ufw status` shows only SSH, 80 and 443 open.
- `docker ps` shows no app service published to `0.0.0.0` except Caddy.
- HTTPS certificate is issued by Caddy.
- Microsoft login works with a KAHLE account.
- First new users land in `pending` unless an admin explicitly approves them.
- `/files/download?...` links work through the public hostname.
- n8n and Qdrant are not reachable from the internet.
- IONOS connectivity check succeeds.
- A backup exists and a restore has been verified before inviting employees.
- The 21-question runtime evaluation and multi-user role test are documented as passed.

## Rollout History

Production rollouts are shipped as signed tarballs built from `deploy/`. That
directory is deliberately git-ignored: the packages are build output, and the
repository commits record what went live instead. Each package backs its
targets up to `/opt/kahle-vinci/.rollout-backups/<name>-before-<timestamp>`
and rolls back automatically on any failure.

### 2026-08-21 — Knowledge portal version archive

- Package: `wissen-versionsarchiv-20260821.tar.gz`
- SHA-256: `9a777b3eb643c5f3878ac0efb329864745068bca1ddd2f5ae21a127a18cbb7c7`
- Commits: `dd50ac3`, `66db7ba`
- Rebuilt services: `kb-admin-api`, `kb-maintenance`, `kb-upload-worker`,
  `kb-admin-dashboard`. Open WebUI, Qdrant, kb-sync, n8n and the document
  worker were untouched.
- Contents: version archive with restore and 90-day retention, "replaced by"
  chains across several archived versions, notification replies with visible
  thread history, and hardened ingest (German prompt-injection patterns,
  Unicode obfuscation, Office zip-bomb limits).
- Schema: `document_versions.superseded_at`, `document_versions.purged_at`,
  `portal_case_notifications.sender_user_id` and
  `portal_case_notifications.thread_id` are added by `kb-admin-api` on
  startup. All are additive and nullable, so a code-only rollback does not
  require a database rollback.
- **Not deployed:** the observing knowledge harness (`191b7a3`) stays local
  until it is finished and its tests pass. Middleware, guard, retrieval tools
  and system prompts were not part of this package.
- Result: rollout succeeded, all four services came up, code and schema
  verification passed.

## References

- Open WebUI requires `WEBUI_URL` before OAuth/SSO use and documents Microsoft OAuth variables in its environment configuration.
- Microsoft Entra app registration should be single tenant for internal employee apps.

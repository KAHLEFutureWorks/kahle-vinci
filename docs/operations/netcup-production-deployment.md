# KAHLE-Vinci Netcup Production Deployment

This runbook publishes KAHLE-Vinci as an internal employee system on a Linux netcup server. Customer-facing use is explicitly out of scope.

## Target Architecture

- Public HTTPS: `https://<vinci-domain>` via Caddy on ports `80` and `443`.
- App access: Caddy proxies Open WebUI internally to `open-webui:8080`.
- Generated downloads: Caddy proxies `/files/*` internally to `owui-file-proxy:8091`.
- Internal-only services: n8n, Qdrant, file proxy and document worker remain unavailable from the internet.
- Models: no local LLM models on the server; model inference stays with IONOS API.
- Identity: Microsoft Entra ID / Microsoft login for employees.

## Required Inputs

- Server IPv4/IPv6 and initial SSH user.
- Target domain, for example `vinci.kahle.de`, with DNS A/AAAA records pointing to the server.
- Microsoft Entra tenant ID.
- Microsoft app registration client ID and client secret.
- Allowed login domain, usually `kahle.de`.
- IONOS API key and existing KAHLE-Vinci runtime secrets.
- Decision whether existing local Open WebUI/Qdrant/n8n data must be migrated or whether production starts fresh.

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
cp stack/env.production.template stack/.env.production
chmod 600 stack/.env.production
nano stack/.env.production
```

Start production:

```bash
docker compose \
  --env-file stack/.env.production \
  -f stack/docker-compose.yml \
  -f stack/docker-compose.prod.yml \
  up -d --build
```

Check:

```bash
docker compose --env-file stack/.env.production -f stack/docker-compose.yml -f stack/docker-compose.prod.yml ps
curl -I https://<vinci-domain>
docker logs --tail 100 caddy
docker logs --tail 100 open-webui
```

## Data Migration

For a full migration from the current local host, move these items:

- `knowledgebases/`
- `kb-sync-state/`
- `assets/`
- `n8n/`
- Docker volume `open-webui`
- Docker volume `qdrant_data`
- Docker volume `document_worker_data` if generated worker files should be preserved

Prefer a maintenance window:

```bash
docker compose -f stack/docker-compose.yml down
docker run --rm -v open-webui:/from -v "$PWD/backups:/backup" alpine tar czf /backup/open-webui.tgz -C /from .
docker run --rm -v qdrant_data:/from -v "$PWD/backups:/backup" alpine tar czf /backup/qdrant_data.tgz -C /from .
```

Restore on the server before first production start:

```bash
docker volume create open-webui
docker volume create kahle-vinci_qdrant_data
docker run --rm -v open-webui:/to -v "$PWD/backups:/backup" alpine sh -c 'tar xzf /backup/open-webui.tgz -C /to'
docker run --rm -v kahle-vinci_qdrant_data:/to -v "$PWD/backups:/backup" alpine sh -c 'tar xzf /backup/qdrant_data.tgz -C /to'
```

If the project name differs, verify the real qdrant volume name with `docker volume ls`.

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
- A backup exists before inviting employees.

## References

- Open WebUI requires `WEBUI_URL` before OAuth/SSO use and documents Microsoft OAuth variables in its environment configuration.
- Microsoft Entra app registration should be single tenant for internal employee apps.

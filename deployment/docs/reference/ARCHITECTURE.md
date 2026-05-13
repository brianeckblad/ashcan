# Architecture Reference

System design, component diagram, and technology choices for the shared-server deployment model.

---

## Deployment Architecture

### Overview

```
Local Machine (Ansible)
┌──────────────────────────────────────────┐
│  deployment/                             │
│  ├── playbooks/                          │
│  ├── group_vars/vault.yml  (AES256)      │
│  └── templates/  (Jinja2)               │
└──────────────┬───────────────────────────┘
               │
       ┌───────┴───────────────────────────────────────────────┐
       │                                                        │
       ▼ AWS API calls (localhost)          ▼ SSH (shared server)
┌──────────────────────────┐        ┌────────────────────────────────────────┐
│  AWS                     │        │  Shared Server                         │
│                          │        │                                        │
│  S3 Bucket               │        │  /opt/{app_name}/   ← code + venv      │
│  IAM Managed Policies    │        │  /var/log/apps/{app_name}/  ← logs          │
│  Secrets Manager         │        │                                        │
│  CloudWatch              │        │  Supervisor     ← per-app process mgr  │
└──────────────────────────┘        └────────────────────────────────────────┘
```

**Two deployment phases:**

1. **`provision-app.yml`** — runs locally, makes AWS API calls. Creates S3, IAM policies, Secrets Manager. Run once per application.
2. **`setup.yml`** — SSHes into the shared server and deploys code + services. Safe to re-run.

---

## Infrastructure Components

### Shared Server

- **OS:** Ubuntu 22.04 LTS (pre-existing, not provisioned by this deployment)
- **Python:** Configured by `python_version` in vault.yml (3.10 or 3.12)
- **Services:** Gunicorn (configurable workers), Nginx, Supervisor
- **Multiple apps:** Each app gets its own supervisor process, nginx vhost, and OS user

### IAM Managed Policies (three per app)

| Policy name | Permissions | Scope |
|-------------|------------|-------|
| `{app_name}-s3-access` | Read/write S3 | This app's bucket only |
| `{app_name}-secrets-access` | Read secrets | `{app_name}/` prefix only |
| `{app_name}-cloudwatch-access` | Write logs and metrics | All CloudWatch |

Policies are attached to the existing shared server IAM role (`server_iam_role_name` in vault.yml).

### S3 Bucket

- **Purpose:** Image storage, CSV backups, exports
- **Versioning:** Enabled (point-in-time restore)
- **Access:** Blocked from public; server accesses via IAM role (no keys on disk)
- **Lifecycle:** Configurable version retention

### AWS Secrets Manager

All runtime configuration (Flask secret, eBay API keys, credentials) lives in one secret at `{app_name}/production`. The app reads it at startup via `get_secret()` in `app/config.py`. No `.env` file is needed on the server.

---

## Ansible Playbooks

### AWS Resource Provisioning (localhost, idempotent)

| Playbook | Creates |
|----------|---------|
| `create-s3-bucket.yml` | S3 bucket with versioning and encryption |
| `create-iam-policies.yml` | Three app-scoped IAM managed policies |
| `setup-secrets-manager.yml` | Secrets Manager secret from vault |
| `provision-app.yml` | Orchestrates all of the above |

### Application Deployment (remote server)

| Playbook | Does |
|----------|------|
| `setup.yml` | Full initial deploy: users, dirs, git, venv, supervisor, nginx, SSL |
| `update.yml` | Pull code, update deps, reload nginx, restart app |
| `setup-ssl.yml` | Obtain or renew Let's Encrypt certificate |
| `setup-monitoring.yml` | Install CloudWatch agent, logrotate, monitoring cron |
| `harden-permissions.yml` | Re-apply file permissions (app files only) |

### Secret Management (localhost)

| Playbook | Does |
|----------|------|
| `secret-sync.yml` | Push all vault values to Secrets Manager |
| `secret-rotate.yml` | Stage a new secret as AWSPENDING |
| `secret-promote.yml` | Promote AWSPENDING → AWSCURRENT |

### Teardown (localhost)

| Playbook | Removes |
|----------|---------|
| `delete-iam-policies.yml` | Three app-scoped IAM policies |
| `delete-secrets-manager.yml` | Secrets Manager secret |
| `delete-s3-bucket.yml` | S3 bucket and all contents |
| `decommission.yml` | Orchestrates all of the above |

### Teardown (localhost)

### User separation

```
ubuntu (admin_user)
├── SSH access and deployment
├── sudo privileges
├── Member of {app_name} group
└── Does not run the application

{app_user}  (e.g. myapp_runtime)
├── No SSH access, no login shell
├── Runs gunicorn workers
├── Member of {app_name} group
└── Limited file access (app dir + logs only)
```

Each app on the shared server gets its own `{app_user}` and `{app_name}` group. File permissions use setgid (`2775`) on directories so new files inherit the group automatically.

### File permissions

| Path | Owner | Group | Mode | Purpose |
|------|-------|-------|------|---------|
| `/opt/{app_name}/` | `{app_user}` | `{app_name}` | `2775` | App code |
| `/opt/{app_name}/instance/` | `{app_user}` | `{app_name}` | `2775` | Data |
| `/var/log/apps/{app_name}/` | `{app_user}` | `{app_name}` | `2775` | Logs |

### Secret management

- Secrets in Ansible Vault (`group_vars/vault.yml`, AES256)
- Synced to AWS Secrets Manager; app reads at startup
- IAM managed policies (not static keys) — no AWS credentials on the server
- No `.env` file on the server

### Network security (nginx per-vhost)

- `server_tokens off` — hides nginx version
- Security headers: HSTS, CSP, X-Frame-Options, X-Content-Type-Options
- Rate limiting: per-endpoint zones (login, API, general)
- Gunicorn bound to `127.0.0.1:{gunicorn_port}` — never exposed directly

---

## Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Application | Python 3.10+, Flask | Web framework |
| WSGI server | Gunicorn (configurable workers) | Python app server |
| Web server | Nginx (per-app vhost) | Reverse proxy, SSL, static files |
| Process manager | Supervisor (per-app conf.d) | Auto-restart, log capture |
| OS | Ubuntu 22.04 LTS (shared) | Server operating system |
| Storage | AWS S3 | Images, backups, exports |
| Secrets | AWS Secrets Manager | Runtime configuration |
| Monitoring | AWS CloudWatch (per-app config fragment) | Logs and metrics |
| SSL | Let's Encrypt (certbot, per-domain) | Free SSL certificates |
| Deployment | Ansible 2.9+ | Infrastructure automation |

---

## File Structure

```
deployment/
├── playbooks/              # Ansible playbooks (one concern per file)
│   ├── provision-app.yml   # Orchestrator: provision all AWS resources
│   ├── create-s3-bucket.yml
│   ├── create-iam-policies.yml
│   ├── setup-secrets-manager.yml
│   ├── setup.yml           # Full server deploy
│   ├── update.yml          # Code update + restart
│   ├── setup-ssl.yml
│   ├── setup-monitoring.yml
│   ├── harden-permissions.yml
│   ├── harden-permissions-tasks.yml  # Shared task include
│   ├── decommission.yml    # Full teardown orchestrator
│   ├── delete-*.yml        # Individual resource deletion
│   └── secret-*.yml        # Secret rotation helpers
│
├── templates/              # Jinja2 config templates
│   ├── nginx.conf.j2       # Per-app nginx vhost
│   ├── supervisor.conf.j2  # Per-app supervisor process
│   ├── logrotate.conf.j2   # Per-app log rotation
│   ├── cloudwatch-config.json.j2    # Per-app CloudWatch fragment
│   └── log-monitor.sh.j2   # Per-app log monitoring script
│
├── group_vars/
│   ├── all.yml             # Empty stub (all config in vault.yml)
│   └── vault.yml           # AES256 encrypted — single source of truth
│
├── inventories/
│   └── hosts.yml           # Shared server IP and SSH key (gitignored)
│
├── scripts/
│   ├── app-deploy.sh       # CLI wrapper for common playbook operations
│   ├── infra-complete-setup.sh  # Full setup in one command
│   ├── decommission.sh     # Interactive teardown with confirmation
│   └── load-vars.sh        # Exports vault variables to shell
│
└── docs/
    ├── guides/             # Numbered step-by-step guides (Ch. 1–13)
    └── reference/          # Background and architecture references
```

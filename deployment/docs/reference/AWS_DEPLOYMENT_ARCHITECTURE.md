# AWS Deployment Architecture — Generic Reference

A complete blueprint for deploying a Python/Flask web application on AWS using
Ansible, S3, CloudWatch, and Secrets Manager.

> **This project uses a shared-server model.** There is no per-app EC2 instance.
> The server is pre-existing and shared between multiple applications.
> This document describes the AWS service layer, which is the same regardless
> of whether you use a dedicated or shared server.
> See [Architecture Reference](ARCHITECTURE.md) for the full deployment architecture.

> Replace every `{app_name}` placeholder with your application name
> (e.g. `myapp`). All other variables are defined in `deployment/group_vars/vault.yml`.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [AWS Services Used](#aws-services-used)
3. [Infrastructure Components](#infrastructure-components)
4. [Server-Side Stack](#server-side-stack)
5. [Security Model](#security-model)
6. [Secret Management](#secret-management)
7. [Monitoring and Alerting](#monitoring-and-alerting)
8. [Deployment Toolchain](#deployment-toolchain)
9. [File and Directory Layout](#file-and-directory-layout)
10. [Key Configuration Variables](#key-configuration-variables)
11. [Cost Estimate](#cost-estimate)

---

## Architecture Overview

```
Local Machine (Ansible)
┌─────────────────────────────────────┐
│  deployment/                        │
│  ├── playbooks/                     │
│  ├── group_vars/vault.yml (AES256)  │
│  └── templates/ (Jinja2)            │
└────────────────┬────────────────────┘
                 │ SSH (Ansible)
                 ▼
┌──────────────────────────────────────────────────────────────────┐
│  AWS Cloud                                                        │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  EC2 Instance (Ubuntu 22.04, t3.micro)                      │ │
│  │                                                             │ │
│  │  ┌──────────────┐    ┌──────────────────────────────────┐  │ │
│  │  │  Nginx       │    │  Gunicorn (4 workers)            │  │ │
│  │  │  :80/:443    │───▶│  127.0.0.1:8000                  │  │ │
│  │  │  reverse     │    │  Python/Flask app                │  │ │
│  │  │  proxy + SSL │    │  Supervisor / Systemd managed    │  │ │
│  │  └──────────────┘    └──────────────────────────────────┘  │ │
│  │                                                             │ │
│  │  IAM Instance Role (no static keys on disk)                │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                  │              │              │                  │
│          ┌───────▼──────┐  ┌───▼────────┐  ┌─▼──────────────┐  │
│          │  S3 Bucket   │  │ Secrets    │  │  CloudWatch     │  │
│          │  (images,    │  │ Manager    │  │  (logs,         │  │
│          │   backups,   │  │ (runtime   │  │   metrics,      │  │
│          │   exports)   │  │  secrets)  │  │   alarms)       │  │
│          └──────────────┘  └────────────┘  └────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

### Request flow

```
Browser → Nginx (SSL termination, static files, reverse proxy)
       → Gunicorn (WSGI, 4 workers) → Flask application
       → S3 (object storage) / Secrets Manager (runtime config)
       → CloudWatch (all logs and metrics forwarded)
```

---

## AWS Services Used

| Service | Role | Required |
|---------|------|----------|
| **EC2** | Compute — runs the application | Yes |
| **S3** | Object storage — images, backups, user data exports | Yes |
| **IAM** | Instance role + deploy user + policies | Yes |
| **Secrets Manager** | Runtime secrets (API keys, passwords) | Yes |
| **CloudWatch** | Logs, metrics, alarms | Yes |
| **SNS** | Alert delivery (email/SMS) | Recommended |
| **EBS** | Application data volume (separate from root) | Yes |

---

## Infrastructure Components

### EC2 Instance

| Setting | Value |
|---------|-------|
| AMI | Ubuntu 22.04 LTS (latest) |
| Instance type | `t3.micro` (default — easily resizable) |
| Storage | Root EBS 20 GB (gp3) + separate data EBS volume |
| Python | 3.10 |
| IAM instance profile | `{app_name}-ec2-role` |
| SSH key pair | `{app_name}-key` |
| Security group | `{app_name}-sg` |

The data EBS volume is mounted at `/opt/apps/{app_name}/` and persists independently of
the root volume. If the instance is replaced, data survives.

### IAM Instance Role — `{app_name}-ec2-role`

The EC2 instance authenticates to AWS services via an attached IAM instance profile.
No static access keys are stored on the instance.

| Permission | Why |
|------------|-----|
| `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`, `s3:ListBucket` on `{s3_bucket_name}` | Read/write application data and backups |
| `secretsmanager:GetSecretValue` on `{app_name}/*` | Fetch runtime secrets at startup |
| `cloudwatch:PutMetricData` | Publish custom application metrics |
| `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` | Ship application logs to CloudWatch |
| `ssm:GetParameter` (optional) | SSM Parameter Store access if used |

### IAM Deploy User — `{app_name}-deploy`

A dedicated IAM user used only from your local machine to run Ansible playbooks.
Long-lived access keys are stored in a named AWS CLI profile (`{app_name}-deploy`),
written automatically to vault.yml by `create-deploy-user.yml` — never in the repo.

Policies attached (`create-deploy-user.yml`):

- `AmazonS3FullAccess`
- `IAMFullAccess`
- `SecretsManagerReadWrite`
- `CloudWatchFullAccess` (covers logs, alarms, and metrics)

### S3 Bucket — `{s3_bucket_name}`

| Setting | Value |
|---------|-------|
| Versioning | Enabled — deleted/overwritten objects are recoverable |
| Encryption | AES-256 server-side encryption |
| Public access | All four public-access block settings enabled |
| Region | Same as `aws_region` in vault.yml |
| Lifecycle rules | Configurable retention via Ansible |

Bucket contents are organized by user subdirectory:
```
{s3_bucket_name}/
└── data/
    └── {username}/
        ├── items.csv
        ├── images/
        ├── exports/
        └── snapshots/
```

### Security Group — `{app_name}-sg`

| Direction | Protocol | Port | Source |
|-----------|----------|------|--------|
| Inbound | TCP | 22 (SSH) | Your IP (or `0.0.0.0/0` if dynamic) |
| Inbound | TCP | 80 (HTTP) | `0.0.0.0/0` |
| Inbound | TCP | 443 (HTTPS) | `0.0.0.0/0` |
| Outbound | All | All | `0.0.0.0/0` |

The application process itself binds to `127.0.0.1:8000` and is never exposed
directly — Nginx proxies all traffic to it.

### SSH Key Pair — `{app_name}-key`

Created by Ansible and saved to `~/.ssh/{app_name}-key.pem` (chmod 400).
Used for all SSH access and Ansible connections.

---

## Server-Side Stack

### Process tree

```
systemd / supervisord
└── {app_name} service
    └── gunicorn --workers 4 --bind 127.0.0.1:8000 runapp:app
        └── Flask application (Python 3.10)
```

### Directory layout on the server

```
/opt/apps/{app_name}/     ← EBS data volume mount point
├── .venv/                ← Python virtual environment
├── app/                  ← Application code (git clone)
├── instance/             ← Runtime state (CSV, logs, preferences)
│   └── data/
│       └── {username}/
└── logs/                 ← Symlink or directory to /var/log/apps/{app_name}/

/var/log/apps/{app_name}/      ← Application logs (shipped to CloudWatch)
├── app.log
├── service.log
└── cleanup.log

/etc/nginx/sites-available/{app_name}   ← Nginx vhost config
/etc/supervisor/conf.d/{app_name}.conf  ← Supervisor config (or systemd unit)
/etc/systemd/system/{app_name}.service  ← Systemd service unit
```

### Nginx configuration (summary)

Nginx handles:
- HTTP → HTTPS redirect (301)
- SSL termination (Let's Encrypt certificate, auto-renewed via certbot)
- Static file serving (`/static/` path bypasses Gunicorn)
- Reverse proxy to `127.0.0.1:8000`
- Security headers: `X-Frame-Options`, `X-Content-Type-Options`, `X-XSS-Protection`,
  `Strict-Transport-Security`, `Referrer-Policy`, `Content-Security-Policy`
- Rate limiting (Nginx `limit_req_zone`)

### Gunicorn configuration

```
workers: 4                  # 2 × CPU + 1 rule of thumb for t3.micro
worker_class: sync          # or gevent for async workloads
bind: 127.0.0.1:8000
timeout: 120
keepalive: 5
```

### SSL — Let's Encrypt (certbot)

- Installed via `setup.yml` playbook
- Certificate stored at `/etc/letsencrypt/live/{server_name}/`
- Auto-renewal via certbot systemd timer (renews 30 days before expiry)
- Requires `server_name` in vault.yml to resolve to the server's public IP

### CloudWatch Agent

Installed on the EC2 instance to forward logs and system metrics:

| Log file | CloudWatch log group |
|----------|----------------------|
| `/var/log/apps/{app_name}/app.log` | `/aws/ec2/{app_name}/app` |
| `/var/log/apps/{app_name}/service.log` | `/aws/ec2/{app_name}/service` |
| `/var/log/nginx/access.log` | `/aws/ec2/{app_name}/nginx-access` |
| `/var/log/nginx/error.log` | `/aws/ec2/{app_name}/nginx-error` |

System metrics shipped: CPU utilization, memory, disk usage, network I/O.

---

## Security Model


### Application-level hardening (applied by `setup.yml`)

| Control | Detail |
|---------|--------|
| App runs as dedicated user | `{app_name}` — no login shell, no SSH access |
| File permissions | Owner `ubuntu:{app_name}`, setgid `2775` on shared dirs |
| Nginx security headers | HSTS, X-Frame-Options DENY, X-Content-Type-Options nosniff, CSP |
| Rate limiting | Nginx `limit_req` + Flask application-layer rate limiting |
| CSRF protection | Per-request CSRF tokens on all state-changing routes |
| Session security | Flask sessions invalidated on restart; server-side session scope |

### Two-user privilege model

```
ubuntu (admin)
├── SSH access via key pair
├── sudo rights
├── Owns application code
└── Manages systemd/supervisor services

{app_name} (app user)
├── No SSH access
├── No login shell (/usr/sbin/nologin)
├── Runs the Gunicorn workers
└── Owns instance/data directory
```

---

## Secret Management

### Flow

```
vault.yml (AES256, safe to commit)
    ↓  ansible-vault decrypt (playbook run)
Ansible syncs secrets to AWS Secrets Manager
    ↓  IAM instance role
EC2 app reads secrets via AWS SDK (boto3)
    ↓  get_secret() in config.py
Flask config (never written to disk in plaintext)
```

### Two-tier storage

| Tier | Storage | Access |
|------|---------|--------|
| Source of truth | `deployment/group_vars/vault.yml` (Ansible Vault, AES256 encrypted) | Developer machine only, decrypted by `~/.vault_pass` |
| Runtime | AWS Secrets Manager (`{app_name}/config`) | EC2 instance via IAM role, no static keys |

### Secret rotation workflow

1. Edit the encrypted vault: `ansible-vault edit group_vars/vault.yml --vault-password-file ~/.vault_pass`
2. Run `ansible-playbook playbooks/secret-rotate.yml` — creates `AWSPENDING` version in Secrets Manager
3. Run `ansible-playbook playbooks/secret-promote.yml` — promotes `AWSPENDING → AWSCURRENT`
4. Restart the application: `ansible-playbook playbooks/update.yml`

### Secret precedence in application config

```
AWS Secrets Manager  →  environment variable  →  default value
```

The `get_secret(key, default=None)` helper in `config.py` implements this.
At runtime on EC2, secrets always come from Secrets Manager. In local dev,
they come from a `.env` file generated from the vault.

---

## Monitoring and Alerting

### CloudWatch metrics collected

| Metric | Source | Alarm threshold (recommended) |
|--------|--------|-------------------------------|
| CPU utilization | EC2 | > 80% for 10 min |
| Memory utilization | CloudWatch agent | > 90% for 5 min |
| Disk usage | CloudWatch agent | > 85% |
| Application error rate | Log metric filter on `ERROR` | > 5 in 5 min |
| 5xx response rate | Nginx access log metric filter | > 10 in 5 min |

### Alarms → SNS → Email

All alarms publish to an SNS topic (`{app_name}-alerts`) which delivers to one
or more email/SMS subscribers. The SNS topic ARN is stored in vault.yml as
`sns_topic_arn`.

Alarms are created by `setup-monitoring.yml`:
- `{app_name}-HighCPU`
- `{app_name}-HighMemory`
- `{app_name}-HighDisk`
- `{app_name}-HighErrorRate`

### Log retention

| Log group | Retention |
|-----------|-----------|
| Application logs | 30 days |
| Nginx access logs | 14 days |
| Nginx error logs | 30 days |

Adjust via `cloudwatch_log_retention_days` in vault.yml.

---


## Deployment Toolchain

### Prerequisites (local machine)

| Tool | Minimum version | Install |
|------|-----------------|---------|
| Python | 3.8+ | `brew install python3` |
| Ansible | 2.9+ | `pip3 install ansible` |
| AWS CLI | v2 | [docs.aws.amazon.com/cli](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) |
| Git | Latest | `brew install git` |
| ansible-galaxy collections | `amazon.aws`, `community.aws` | `ansible-galaxy collection install -r deployment/requirements.yml` |

### Playbook inventory

#### AWS resource provisioning

| Playbook | What it creates |
|----------|----------------|
| `create-s3-bucket.yml` | S3 bucket with versioning, encryption, access block |
| `create-iam-policies.yml` | Three app-scoped IAM managed policies |
| `setup-secrets-manager.yml` | Secrets Manager secret (synced from vault) |
| `provision-app.yml` | Orchestrates all of the above in order |

#### Application deployment

| Playbook | What it does |
|----------|-------------|
| `setup.yml` | Create app user, clone repo, venv, pip install, Nginx vhost, Supervisor, SSL, start app |
| `update.yml` | Pull latest code, pip install, reload nginx, restart supervisor process, validate |

#### Operations

| Playbook | What it does |
|----------|-------------|
| `setup-monitoring.yml` | CloudWatch agent (per-app config fragment), logrotate, monitoring cron |
| `setup-ssl.yml` | Obtain or renew Let's Encrypt certificate for this app's domain |
| `secret-rotate.yml` | Create AWSPENDING version in Secrets Manager |
| `secret-promote.yml` | Promote AWSPENDING → AWSCURRENT |
| `secret-sync.yml` | Full vault → Secrets Manager sync |
| `decommission.yml` | Full per-app teardown (S3, IAM policies, Secrets Manager) |

### Standard deployment sequence

```bash
cd deployment
source scripts/load-vars.sh

# Step 1: Create all AWS resources
ansible-playbook playbooks/provision-app.yml \
    --vault-password-file ~/.vault_pass

# Step 2: Deploy the application to the shared server
ansible-playbook playbooks/setup.yml \
    --vault-password-file ~/.vault_pass
```

### Update (code change)

```bash
ansible-playbook playbooks/update.yml --vault-password-file ~/.vault_pass
```

### Teardown

```bash
ansible-playbook playbooks/decommission.yml --vault-password-file ~/.vault_pass
```

---

## File and Directory Layout

### Repository structure (deployment/)

```
deployment/
├── ansible.cfg                     # Ansible settings (inventory path, SSH key)
├── requirements.txt                # Python deps: boto3, botocore, ansible AWS plugins
├── requirements.yml                # Ansible Galaxy collections
│
├── group_vars/
│   ├── all.yml                     # Empty stub (all real config in vault.yml)
│   ├── vault.yml                   # AES256 encrypted — ALL configuration
│   └── vault.yml.example           # Unencrypted template for new deployments
│
├── inventories/
│   └── production/
│       └── hosts.yml               # Shared server IP and SSH key (gitignored)
│
├── playbooks/                      # All Ansible playbooks (see table above)
│
├── templates/
│   ├── nginx.conf.j2               # Nginx vhost (SSL, headers, rate limits)
│   ├── systemd-with-validation.service.j2  # Systemd unit with health-check
│   ├── env.j2                      # .env file for local dev (generated from vault)
│   └── cloudwatch-config.json.j2   # CloudWatch agent config
│
├── scripts/
│   ├── load-vars.sh                # Exports vault vars into shell for CLI use
│   └── decommission.sh             # Interactive teardown with confirmation
│
└── instances/
    └── {app_name}-instance.txt     # Server IP and SSH command (auto-generated)
```

### Ansible variable files

`vault.yml` is the single source of truth. The `all.yml` file is an empty stub —
all variables, including non-secret config, live in the vault so that everything
can be committed safely in encrypted form.

---

## Key Configuration Variables

All of these are set in `deployment/group_vars/vault.yml`.

### Required

| Variable | Example | Purpose |
|----------|---------|---------|
| `app_name` | `myapp` | Used in naming all AWS resources, system user, paths |
| `app_display_name` | `My Application` | Human-readable name (used in logs, emails) |
| `git_repo_url` | `https://github.com/you/myapp.git` | Repository to clone on EC2 |
| `aws_region` | `us-east-2` | AWS region for all resources |
| `s3_bucket_name` | `yourname-myapp-2026` | Globally unique S3 bucket name |
| `s3_folder` | `data` | Top-level prefix within the bucket |
| `server_name` | `myapp.example.com` | Domain name (required for SSL) |
| `ssl_email` | `you@example.com` | Let's Encrypt registration email |
| `app_default_username` | `admin` | Initial application login username |
| `app_default_password` | `Str0ngP@ss!` | Initial application login password |

### Infrastructure sizing

| Variable | Default | Purpose |
|----------|---------|---------|
| `ec2_instance_type` | `t3.micro` | EC2 instance size |
| `ec2_volume_size` | `20` | Root EBS volume (GB) |
| `data_volume_size` | `20` | Data EBS volume (GB) |
| `gunicorn_workers` | `4` | Gunicorn worker count |

### Optional features

| Variable | Default | Purpose |
|----------|---------|---------|
| `sns_topic_arn` | `""` | SNS topic for CloudWatch alarm delivery |
| `cloudwatch_log_retention_days` | `30` | Log retention in CloudWatch |
| `admin_user` | `ubuntu` | SSH/sudo user on EC2 |

---

## Cost Estimate

Costs for the AWS resources managed by this deployment (not EC2 compute, which is shared).

| Service | Monthly cost (approximate) |
|---------|---------------------------|
| S3 (first 5 GB free; typical ~$1–2) | $1–2 |
| Secrets Manager (1 secret) | $0.40 |
| CloudWatch (logs + metrics) | $1–3 |
| Let's Encrypt SSL | Free |
| **Base total** | **~$2–5/month** |

Free-tier eligible for the first 12 months: EC2 t3.micro (750 hrs/month), S3
(5 GB), CloudWatch (basic monitoring). Realistic first-year cost: ~$2–5/month.

---

## Adapting This Architecture for a New Project

1. **Copy the `deployment/` directory** from this project into your new repo.
2. **Copy `vault.yml.example`** to `vault.yml` and fill in your values.
3. **Encrypt the vault:** `ansible-vault encrypt group_vars/vault.yml --vault-password-file ~/.vault_pass`
4. **Implement `get_secret(key, default=None)`** in your `config.py` using `boto3`:
   ```python
   import boto3, json
   def get_secret(key, default=None):
       client = boto3.client('secretsmanager', region_name=AWS_REGION)
       secret = json.loads(client.get_secret_value(SecretId=SECRET_NAME)['SecretString'])
       return secret.get(key, default)
   ```
5. **Add a `runapp.py` entry point** that exposes a WSGI `app` object for Gunicorn.
6. **Provide `requirements.txt`** — the `setup.yml` playbook runs `pip install -r requirements.txt` in the venv.
7. **Run the three provisioning playbooks** in order (see [Standard deployment sequence](#standard-deployment-sequence)).

The Ansible templates (`nginx.conf.j2`, the systemd unit, `cloudwatch-config.json.j2`)
are parameterized entirely via `vault.yml` variables and require no manual editing
for a new project — only the vault values need to change.

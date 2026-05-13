# Application Deployment Guide
**Deploy, operate, and maintain a Python web application on a shared server with AWS backing services.**

Start at Chapter 1 and follow in order. Chapters 9–11 are optional.

---

## Part I — Deploy

| Ch. | Guide | Time |
|-----|-------|------|
| 1 | [Prerequisites](guides/PREREQUISITES.md) | 20 min |
| 2 | [Quick Start](guides/QUICKSTART.md) — automated, recommended | 10–15 min |
| 3 | [Manual Deployment](guides/MANUAL_DEPLOYMENT.md) — step-by-step | 30–60 min |

Complete Chapter 2 or 3. Your application is live.

## Part II — Operate

| Ch. | Guide |
|-----|-------|
| 4 | [Updating Your Application](guides/UPDATING_APPLICATION.md) |
| 5 | [Operations](guides/OPERATIONS.md) — backups, scaling, troubleshooting |
| 6 | [Monitoring](guides/MONITORING.md) — dashboards, alarms, alerting |
| 7 | [Secret Management](guides/SECRET_MANAGEMENT.md) |

## Part III — Harden & Extend

| Ch. | Guide |
|-----|-------|
| 8 | [Security Hardening](guides/SECURITY_HARDENING.md) |
| 9 | [Multi-User Support](guides/MULTI_USER.md) |
| 10 | [Git Configuration](guides/GIT_CONFIGURATION.md) |

## Part IV — Decommission

| Ch. | Guide |
|-----|-------|
| 11 | [Decommission](guides/DECOMMISSION.md) — remove app resources without touching the shared server |

---

## Reference

| Document | Topic |
|----------|-------|
| [Architecture](reference/ARCHITECTURE.md) | System design and technology choices |
| [Application Architecture](reference/APPLICATION_ARCHITECTURE.md) | Flask app internals — structure, services, data model, patterns |
| [Application Security](reference/APPLICATION_SECURITY.md) | Attack detection, rate limiting, security middleware |
| [User Isolation](reference/SECURITY.md) | Two-user privilege model |
| [User Types](reference/USER_MODEL.md) | Admin vs. application user permissions |

---

## Playbook Reference

### AWS Resource Playbooks (run from localhost)

| Create | Delete | Resource |
|--------|--------|----------|
| `create-s3-bucket.yml` | `delete-s3-bucket.yml` | S3 Bucket |
| `create-iam-policies.yml` | `delete-iam-policies.yml` | App-scoped IAM managed policies |
| `setup-secrets-manager.yml` | `delete-secrets-manager.yml` | Secrets Manager secret |

### Application Deployment Playbooks (run against shared server)

| Playbook | Purpose |
|----------|---------|
| `setup.yml` | First-time application deployment (code, venv, nginx, supervisor, SSL) |
| `update.yml` | Update code, restart application |
| `setup-monitoring.yml` | CloudWatch agent integration |
| `setup-ssl.yml` | Obtain or renew SSL certificate only |
| `harden-permissions.yml` | Re-apply application file permissions |

### Master Playbooks

| Playbook | Purpose |
|----------|---------|
| `provision-app.yml` | Orchestrates all AWS resource creation (S3 + IAM + Secrets Manager) |
| `decommission.yml` | Removes all app-level AWS resources |

### Deployer IAM User Playbooks

| Playbook | Purpose |
|----------|---------|
| `create-iam-user.yml` | Create the `{app_name}-deployer` IAM user with access keys |
| `delete-iam-user.yml` | Delete the deployer IAM user |

---

## Common Commands

```bash
cd deployment
source scripts/load-vars.sh

# Step 1: Create AWS resources (S3, IAM policies, Secrets Manager)
ansible-playbook playbooks/provision-app.yml --vault-password-file ~/.vault_pass

# Step 2: Deploy the application to the server (code, nginx, supervisor, SSL)
ansible-playbook playbooks/setup.yml --vault-password-file ~/.vault_pass

# Update (pull new code and restart)
ansible-playbook playbooks/update.yml --vault-password-file ~/.vault_pass

# Teardown app resources only (server unchanged)
ansible-playbook playbooks/decommission.yml --vault-password-file ~/.vault_pass
```

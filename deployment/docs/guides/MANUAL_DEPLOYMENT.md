# Chapter 3: Manual Deployment

Deploy step-by-step with full explanations for each playbook.

> **Prerequisite:** Complete [Chapter 1: Prerequisites](PREREQUISITES.md) before continuing.

---

## Architecture

```
Your Local Machine
       │
       ├─ ansible-playbook provision-app.yml
       │         │
       │    ┌────▼─────────────────────────────────────┐
       │    │   AWS                                     │
       │    │   S3 Bucket          ← app data / images  │
       │    │   IAM Policies       ← attached to server │
       │    │   Secrets Manager    ← all vault secrets  │
       │    └──────────────────────────────────────────┘
       │
       └─ ansible-playbook setup.yml
                 │
            ┌────▼─────────────────────────────────────┐
            │   Shared Server (SSH via server_host)     │
            │                                           │
            │   /opt/{app_name}/       ← code + venv   │
            │   /var/log/apps/{app_name}/   ← logs           │
            │   Supervisor             ← process mgr    │
            │   Nginx vhost            ← web server     │
            │   SSL cert (Let's Encrypt)                │
            └───────────────────────────────────────────┘
```

**Deployment has two phases:**

1. **Provision AWS resources** (`provision-app.yml`) — runs from your local machine, makes AWS API calls. Run once per application.
2. **Deploy to server** (`setup.yml`) — SSHes into the shared server, installs code and services. Safe to re-run.

---

## Load Variables

CLI commands in this guide use shell variables from vault.yml. Load them once per terminal session:

```bash
cd deployment
source scripts/load-vars.sh

echo $app_name      # e.g., myapp
echo $aws_region    # e.g., us-east-2
```

---

## Phase 1: Provision AWS Resources

These playbooks run on `localhost` and make AWS API calls from your machine. They are idempotent — safe to run multiple times.

### Step 1 — Create S3 bucket

**Vault variables used:** `s3_bucket_name`, `aws_region`, `s3_version_retention_days`

**What it creates:**
- S3 bucket named `{s3_bucket_name}` in `{aws_region}`
- Versioning enabled (point-in-time restore for CSV backups)
- All public access blocked
- Server-side AES256 encryption
- Lifecycle policy to expire old object versions after `{s3_version_retention_days}` days

```bash
ansible-playbook playbooks/create-s3-bucket.yml --vault-password-file ~/.vault_pass
```

**Verify:**
```bash
aws s3 ls | grep $s3_bucket_name
aws s3api get-bucket-versioning --bucket $s3_bucket_name
# Should show: "Status": "Enabled"
```

---

### Step 2 — Create IAM policies

**Vault variables used:** `app_name`, `s3_bucket_name`, `aws_region`, `server_iam_role_name`

**What it creates:**
- `{app_name}-s3-access` — read/write access to this app's S3 bucket only
- `{app_name}-secrets-access` — read access to secrets under the `{app_name}/` prefix only
- `{app_name}-cloudwatch-access` — publish metrics and write log groups

If `server_iam_role_name` is set in vault.yml, all three policies are attached to that role automatically. Otherwise, attach them manually in the IAM console.

```bash
ansible-playbook playbooks/create-iam-policies.yml --vault-password-file ~/.vault_pass
```

**Verify:**
```bash
aws iam list-policies \
    --query "Policies[?starts_with(PolicyName, '${app_name}')].[PolicyName,Arn]" \
    --output table
# Should list: {app_name}-s3-access, {app_name}-secrets-access, {app_name}-cloudwatch-access
```

**If `server_iam_role_name` was empty**, attach policies manually:
```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ROLE=<shared-server-role-name>

for policy in s3-access secrets-access cloudwatch-access; do
    aws iam attach-role-policy \
        --role-name $ROLE \
        --policy-arn arn:aws:iam::${ACCOUNT_ID}:policy/${app_name}-${policy}
done
```

---

### Step 3 — Create Secrets Manager secret

**Vault variables used:** `secret_name`, `aws_region`, `secret_key`, `flask_env`, `s3_bucket_name`, `s3_folder`, `aws_region`, `ebay_*`, and all other app credentials

**What it creates/updates:**
- A Secrets Manager secret at path `{app_name}/production`
- Contains a JSON object with all deployment variables the app needs at runtime
- The app reads this secret via `get_secret()` in `app/config.py` — no `.env` file needed on the server

```bash
ansible-playbook playbooks/setup-secrets-manager.yml --vault-password-file ~/.vault_pass
```

**Verify:**
```bash
aws secretsmanager describe-secret --secret-id ${app_name}/production --region $aws_region
aws secretsmanager get-secret-value --secret-id ${app_name}/production --region $aws_region \
    --query SecretString --output text | python3 -m json.tool
```

---

### Run all Phase 1 steps at once

The `provision-app.yml` orchestrator runs Steps 1–3 in order:

```bash
ansible-playbook playbooks/provision-app.yml --vault-password-file ~/.vault_pass
```

---

## Phase 2: Deploy to Server

This phase SSHes into the shared server and deploys the application. It is safe to re-run — each task is idempotent.

**Prerequisite:** `inventories/hosts.yml` must have the correct `ansible_host`. See [Chapter 1: Prerequisites](PREREQUISITES.md#server-inventory).

### Step 4 — Deploy application

**Vault variables used:** all connection, path, service, git, and nginx variables

**What it does, in order:**

1. Creates a system group `{app_name}` and an unprivileged user `{app_user}` (no shell, no login)
2. Adds `{admin_user}` (ubuntu) to the `{app_name}` group for file access
3. Creates `/opt/{app_name}/` and `/var/log/apps/{app_name}/` with correct ownership
4. Clones the git repo (using `git_token`) into `/opt/{app_name}/`
5. Creates a Python virtualenv at `/opt/{app_name}/.venv` and installs `requirements.txt`
6. Installs gunicorn into the virtualenv
7. Writes `/etc/supervisor/conf.d/{app_name}.conf` (process manager config)
8. Writes `/etc/nginx/sites-available/{app_name}` (nginx vhost) and enables it
9. Installs logrotate config at `/etc/logrotate.d/{app_name}`
10. Creates a daily cron job for backup cleanup
11. Deploys the log monitoring script to `/usr/local/bin/{app_name}-log-monitor.sh`
12. Applies file permissions (mode, ownership)
13. Starts the application under Supervisor
14. Installs certbot and obtains an SSL certificate from Let's Encrypt
15. Regenerates nginx config with SSL enabled

```bash
ansible-playbook playbooks/setup.yml --vault-password-file ~/.vault_pass
```

**What to check if it fails:**
- If git clone fails: verify `git_token` has `repo` scope and `git_repo_url` is correct
- If certbot fails: verify `server_name` DNS A record points to the server, port 80 is open
- If supervisor fails to start: check logs at `/var/log/apps/{app_name}/app.log`

**Verify:**
```bash
ssh ubuntu@<server_host>

# Application running?
sudo supervisorctl status {app_name}
# Expected: {app_name}               RUNNING   pid XXXXX, uptime X:XX:XX

# Logs clean?
sudo tail -20 /var/log/apps/{app_name}/app.log

# SSL installed?
ls /etc/letsencrypt/live/{server_name}/fullchain.pem

# HTTPS responding?
curl -I https://{server_name}
# Expected: HTTP/2 200

# HTTP redirects to HTTPS?
curl -I http://{server_name}
# Expected: HTTP/1.1 301 Moved Permanently
```

---

### Step 5 — Harden file permissions (optional, recommended)

Sets secure ownership and mode on all application files. Run after deployment and after any manual file operations on the server.

**Vault variables used:** `app_dir`, `log_dir`, `app_user`, `app_name`, `admin_user`

```bash
ansible-playbook playbooks/harden-permissions.yml --vault-password-file ~/.vault_pass
```

---

### Step 6 — Set up monitoring (optional)

Installs the CloudWatch agent and configures log and metric collection. Each app writes its own config fragment — safe to run alongside other apps on the same server.

**Vault variables used:** `app_name`, `log_dir`, `aws_region`

```bash
ansible-playbook playbooks/setup-monitoring.yml --vault-password-file ~/.vault_pass
```

> **Note:** Running this playbook restarts the CloudWatch agent to reload config for all apps. The restart is brief (a few seconds) and metrics collection resumes immediately.

---

## Verify the Full Deployment

```bash
# From your local machine:
curl -I https://{server_name}                  # HTTP 200
curl -I http://{server_name}                   # HTTP 301 redirect to HTTPS

# On the server (ssh ubuntu@<server_host>):
sudo supervisorctl status {app_name}           # RUNNING
sudo nginx -t                                  # syntax OK
sudo tail -20 /var/log/apps/{app_name}/app.log      # no ERROR lines
sudo certbot certificates                      # certificate valid
```

---

## Day-2 Operations

After initial deployment:

- **Deploy code changes:** See [Chapter 4: Updating Your Application](UPDATING_APPLICATION.md) — run `update.yml`
- **Rotate secrets:** See [Chapter 7: Secret Management](SECRET_MANAGEMENT.md) — run `secret-sync.yml`
- **Add SSL if it failed:** Run `setup-ssl.yml`:
  ```bash
  ansible-playbook playbooks/setup-ssl.yml --vault-password-file ~/.vault_pass
  ```

---

## Next step

Continue to [Chapter 4: Updating Your Application](UPDATING_APPLICATION.md).

## See also

- [Chapter 5: Operations](OPERATIONS.md) — backups, restarts, scaling
- [Chapter 7: Secret Management](SECRET_MANAGEMENT.md) — rotate and sync secrets

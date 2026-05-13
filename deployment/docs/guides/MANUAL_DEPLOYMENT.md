# Chapter 3: Manual Deployment

Deploy the application step-by-step with full explanations for each stage.

> Prerequisite: Complete [Chapter 1: Prerequisites](PREREQUISITES.md) before continuing.
> Your AWS CLI must already be configured as the `{app_name}-deployer` IAM user
> (`create-iam-user.yml` does this automatically on completion).

---

## How deployment works

The deployment is split into two distinct phases that must run in order.

```
Your Local Machine
       │
       ├─ Phase 1:  ansible-playbook provision-app.yml
       │                    │
       │            ┌───────▼──────────────────────────────┐
       │            │  AWS (API calls from your machine)    │
       │            │  S3 Bucket       ← images / CSV data  │
       │            │  IAM Policies    ← server permissions │
       │            │  Secrets Manager ← all vault secrets  │
       │            └──────────────────────────────────────┘
       │
       └─ Phase 2:  ansible-playbook setup.yml
                           │
                    ┌──────▼───────────────────────────────┐
                    │  Shared Server (SSH)                  │
                    │  /opt/{app_name}/     ← code + venv  │
                    │  /var/log/apps/{app_name}/  ← logs   │
                    │  Supervisor       ← process manager  │
                    │  Nginx vhost      ← web server       │
                    │  SSL certificate  ← Let's Encrypt    │
                    └──────────────────────────────────────┘
```

**Phase 1** runs entirely on your local machine and makes AWS API calls. It creates
the storage and credential infrastructure the application needs before the server can
start. Run it once when provisioning a new application instance.

**Phase 2** connects to the shared server over SSH and installs the application. It is
idempotent — safe to re-run if it fails partway through.

---

## Set up your terminal session

CLI verification commands in this guide use shell variables from vault.yml. Load them
once per terminal session:

```bash
cd deployment
source scripts/load-vars.sh
```

This also writes the literal server connection values to `inventories/hosts.yml` so
Ansible can resolve them before vault decryption. Run it once each time you open a
new terminal.

> Playbooks do **not** require `source scripts/load-vars.sh` — they read `vault.yml`
> directly. This command is only needed for the `aws` and `ssh` verification steps below.

---

## Phase 1: Provision AWS resources

These three playbooks run on your local machine and make AWS API calls. Each creates
a distinct piece of infrastructure. The `provision-app.yml` orchestrator runs all
three in order; the individual playbooks let you retry a single step if needed.

Each playbook is idempotent: re-running it is safe if a step fails.

### Step 1 — Create the S3 bucket

The application uses S3 as its primary storage layer: images are uploaded there, CSV
inventory files are backed up there, and the startup sync pulls data from there when
the server restarts. This bucket must exist before the application can run.

The playbook creates the bucket with versioning enabled (so you can restore previous
versions of CSV files), all public access blocked, AES256 server-side encryption, and
a lifecycle rule that expires old object versions after `{s3_version_retention_days}` days.

```bash
cd deployment
ansible-playbook playbooks/create-s3-bucket.yml --vault-password-file ~/.vault_pass
```

Verify the bucket was created and versioning is on:

```bash
aws s3 ls | grep $s3_bucket_name
aws s3api get-bucket-versioning --bucket $s3_bucket_name --region $aws_region
# Expected: "Status": "Enabled"
```

---

### Step 2 — Create IAM policies

The shared server needs permission to read and write this application's S3 objects,
fetch its secrets from Secrets Manager, and publish metrics to CloudWatch. IAM managed
policies are the correct way to grant those permissions — they are scoped precisely
to this application's resources, so a misconfiguration in one app cannot affect another.

Three policies are created, all namespaced with `{app_name}`:

| Policy | Permissions | Scope |
|--------|-------------|-------|
| `{app_name}-s3-access` | Read, write, list, version | This app's bucket only |
| `{app_name}-secrets-access` | Read, describe, update secrets | `{app_name}/` prefix only |
| `{app_name}-cloudwatch-access` | Publish metrics, write log groups | All CloudWatch |

If `server_iam_role_name` is set in vault.yml, all three policies are attached to the
server's existing IAM role automatically. If not, you attach them manually after this
step (instructions below).

```bash
ansible-playbook playbooks/create-iam-policies.yml --vault-password-file ~/.vault_pass
```

Verify the policies were created:

```bash
aws iam list-policies \
    --query "Policies[?starts_with(PolicyName, '${app_name}')].[PolicyName,Arn]" \
    --output table
# Should list three policies: s3-access, secrets-access, cloudwatch-access
```

**If `server_iam_role_name` was empty,** attach the policies to your server's IAM role
manually:

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ROLE=your-shared-server-role-name

for policy in s3-access secrets-access cloudwatch-access; do
    aws iam attach-role-policy \
        --role-name $ROLE \
        --policy-arn arn:aws:iam::${ACCOUNT_ID}:policy/${app_name}-${policy}
done
```

---

### Step 3 — Create the Secrets Manager secret

At runtime, the application fetches all its credentials and configuration from AWS
Secrets Manager using the EC2 instance's IAM role — no `.env` file is written to the
server and no secrets are stored on disk. This playbook creates the secret and
populates it from the values in your encrypted vault.

The secret is stored at the path `{app_name}/production` as a JSON object. Every key
is UPPERCASE, matching the names the application expects when it calls `get_secret()`
in `app/config.py`. If you add a variable to vault.yml and re-run this playbook, the
new value is synced.

```bash
ansible-playbook playbooks/setup-secrets-manager.yml --vault-password-file ~/.vault_pass
```

Verify the secret was created and is readable:

```bash
aws secretsmanager describe-secret \
    --secret-id ${app_name}/production \
    --region $aws_region

aws secretsmanager get-secret-value \
    --secret-id ${app_name}/production \
    --region $aws_region \
    --query SecretString \
    --output text | python3 -m json.tool
# Should show a JSON object with SECRET_KEY, S3_BUCKET_NAME, etc.
```

---

### Run all three Phase 1 steps at once

`provision-app.yml` orchestrates Steps 1–3 in order. It also runs a preflight check
that verifies your AWS CLI is authenticated as the deployer user, not as root, and
fails with a clear message if it detects root credentials.

```bash
ansible-playbook playbooks/provision-app.yml --vault-password-file ~/.vault_pass
```

If the playbook fails partway through, re-run the individual step that failed using
`create-s3-bucket.yml`, `create-iam-policies.yml`, or `setup-secrets-manager.yml`.

---

## Phase 2: Deploy to server

This phase connects to the shared server over SSH and installs the full application
stack. It is safe to re-run at any time — each task checks state before acting, so
completed steps are skipped and only the outstanding work is performed.

Before running, confirm that `inventories/hosts.yml` contains the correct server
address. Running `source scripts/load-vars.sh` writes this file automatically from
vault values (see above). Test connectivity:

```bash
ansible all -m ping --vault-password-file ~/.vault_pass
# Expected: server | SUCCESS => {"changed": false, "ping": "pong"}
```

---

### Step 4 — Deploy the application

This is the core deployment step. It installs everything the application needs to run
on the shared server.

The playbook starts by creating a dedicated OS group named `{app_name}` and an
unprivileged runtime user `{app_runtime_user}` with no shell and no login capability.
The `{server_admin_user}` (ubuntu) is added to this group so both users can read and
write application files. Separate group ownership is what allows the deploy user to
push code while the runtime user runs it — neither has unnecessary access to the other.

It then creates the application directory at `/opt/{app_name}/` and the log directory
at `/var/log/apps/{app_name}/`, clones your git repository into the app directory
(using `git_token` from vault for private repos), and builds a Python virtual
environment at `/opt/{app_name}/.venv` with all dependencies from `requirements.txt`.

With the code in place, it writes the Supervisor process manager configuration so
gunicorn starts automatically and restarts on failure, and the Nginx vhost configuration
so the domain in `server_name` is routed to the application. A logrotate config is
installed to prevent log directories from growing without bound.

File ownership and permissions are applied, the application is started under Supervisor,
and finally certbot obtains a Let's Encrypt SSL certificate. Once the certificate is
installed, the Nginx config is regenerated with SSL enabled and HTTP traffic is
redirected permanently to HTTPS.

```bash
ansible-playbook playbooks/setup.yml --vault-password-file ~/.vault_pass
```

**Duration:** approximately 5–10 minutes on first run.

**If it fails:**

| Symptom | Likely cause |
|---------|-------------|
| Git clone fails | `git_token` missing or expired; `git_repo_url` wrong |
| pip install fails | Network issue, or a package in `requirements.txt` has no wheel for this Python version |
| Certbot fails | `server_name` DNS A record does not point to this server, or port 80 is not open |
| Supervisor shows FATAL | Check `/var/log/apps/{app_name}/app.log` for the Python exception |

Re-run the playbook after fixing the cause. Ansible skips all completed steps and
retries from where it stopped.

---

### Step 5 — Harden file permissions (optional, recommended)

After deployment it is good practice to re-apply the correct ownership and modes to
every application file. This is useful if you have made manual edits on the server,
which can leave files owned by root or with incorrect modes, or as a regular
housekeeping step.

```bash
ansible-playbook playbooks/harden-permissions.yml --vault-password-file ~/.vault_pass
```

See [Chapter 8: Security Hardening](SECURITY_HARDENING.md) for the full permissions
table and what each setting protects.

---

### Step 6 — Set up monitoring (optional)

Installs the CloudWatch agent and configures it to collect logs and metrics from this
application. Each app on the shared server gets its own config fragment, so running
this playbook for a new app does not affect monitoring for existing apps.

```bash
ansible-playbook playbooks/setup-monitoring.yml --vault-password-file ~/.vault_pass
```

> The playbook restarts the CloudWatch agent to reload its config. The restart takes
> a few seconds; all apps resume sending metrics immediately.

See [Chapter 6: Monitoring](MONITORING.md) to configure dashboards and alarms.

---

## Verify the deployment

Run these checks once `setup.yml` completes. All should pass before you consider the
deployment complete.

**From your local machine:**

```bash
# HTTPS responds
curl -I https://$server_name
# Expected: HTTP/2 200

# HTTP redirects to HTTPS
curl -I http://$server_name
# Expected: HTTP/1.1 301 Moved Permanently  →  https://...
```

**On the server:**

```bash
ssh ubuntu@$server_host

# Application is running
sudo supervisorctl status $app_name
# Expected: {app_name}     RUNNING   pid XXXXX, uptime X:XX:XX

# No errors at startup
sudo tail -20 /var/log/apps/$app_name/app.log
# Expected: startup messages, no ERROR or CRITICAL lines

# SSL certificate exists
sudo certbot certificates
# Expected: Certificate Name: {server_name}, VALID: XX days

# Nginx config is valid
sudo nginx -t
# Expected: syntax is ok / test is successful

exit
```

---

## Day-2 operations

With the application live, the most common follow-up tasks are:

- **Deploy a code change:** Push to git, then run `update.yml`.
  See [Chapter 4: Updating Your Application](UPDATING_APPLICATION.md).
- **Sync a vault change to Secrets Manager:** Re-run `setup-secrets-manager.yml`.
  See [Chapter 7: Secret Management](SECRET_MANAGEMENT.md).
- **SSL failed during setup:** Run `setup-ssl.yml` once DNS is correct:
  ```bash
  ansible-playbook playbooks/setup-ssl.yml --vault-password-file ~/.vault_pass
  ```

---

## Next step

Continue to [Chapter 4: Updating Your Application](UPDATING_APPLICATION.md).

## See also

- [Chapter 5: Operations](OPERATIONS.md) — restarts, logs, backups, troubleshooting
- [Chapter 7: Secret Management](SECRET_MANAGEMENT.md) — rotate credentials
- [Chapter 8: Security Hardening](SECURITY_HARDENING.md) — verify permissions and headers

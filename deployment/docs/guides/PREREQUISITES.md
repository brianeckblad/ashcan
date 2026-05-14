# Chapter 1: Prerequisites

Set up your local tools, AWS account, and configuration files before running any playbook.

---

## User and identity model

Three distinct identities are involved in a deployment. Understanding these upfront avoids confusion later.

| Identity | Vault variable | Scope | Who creates it |
|----------|---------------|-------|----------------|
| **AWS deploy IAM user** (`{app_name}-deploy`) | `app_deploy_user` | Per-app. Has S3, IAM, Secrets Manager, and CloudWatch permissions scoped to this app. Used by Ansible via a named CLI profile. | `create-deploy-user.yml` |
| **OS admin user** (`ubuntu` or similar) | `server_admin_user` | Shared across all apps on the server. Used for SSH access. | Pre-existing on the shared server. |
| **OS runtime user** (`{app_name}_runtime`) | `app_runtime_user` | Per-app. Unprivileged OS user that runs gunicorn. | `setup.yml` |

Each app on the shared server gets its own AWS deployer and OS runtime user. This limits blast radius if credentials are compromised — one app's leaked key cannot touch another app's S3 bucket or secrets.

---

## Local tools

| Tool | Purpose | Minimum version |
|------|---------|----------------|
| Python 3 | Ansible runtime, deployment scripts | 3.10+ |
| Ansible | Playbook automation | 2.9+ |
| AWS CLI | Create S3, IAM, Secrets Manager resources | 2.x |
| Git | Source control | 2.x |

**macOS:**
```bash
brew install python3 ansible git awscli
```

**Ubuntu/Debian:**
```bash
sudo apt update && sudo apt install -y python3 python3-pip git ansible awscli
```

**Install deployment Python packages and Ansible collections:**
```bash
cd /path/to/project/deployment
pip3 install -r requirements.txt
ansible-galaxy collection install -r requirements.yml --upgrade
```

---

## AWS account setup

**If you already have an AWS account and CLI configured with admin-level credentials, skip to [Bootstrap credentials](#bootstrap-credentials).**

### Create an AWS account

Go to [aws.amazon.com](https://aws.amazon.com) → **Create an AWS Account**.

> Never use the root account for daily work. You will create a scoped deployer user below and then delete the root access key.

### Bootstrap credentials

You need temporary admin-level AWS credentials to create the deployer IAM user. Use root credentials or an existing admin-level IAM user.

1. Sign in to the AWS Console as root (or admin)
2. Click your account name (top-right) → **Security credentials**
3. Under **Access keys**, click **Create access key** and save the values

```bash
aws configure
# Enter: Access Key ID, Secret Access Key, region (e.g. us-east-2), format: json

aws sts get-caller-identity
# Confirm the Arn includes :root or an admin user
```

---

## Vault password file

Create the vault password file before anything else — it is needed to encrypt and decrypt all secrets.

```bash
echo "your-secure-passphrase" > ~/.vault_pass
chmod 600 ~/.vault_pass
```

Save this passphrase in a password manager. If it is lost, the encrypted vault cannot be recovered.

---

## Deployment configuration

### Step 1: Copy the vault template

```bash
cd deployment
cp group_vars/vault.yml.example group_vars/vault.yml
```

### Step 2: Fill in all variables

Edit `group_vars/vault.yml`. Every variable is required unless marked optional.

#### Application identity

| Variable | Description | Example |
|----------|-------------|---------|
| `app_name` | Short technical identifier. Used in paths, service names, and IAM resource names. No spaces. | `myapp` |
| `app_display_name` | Human-readable name shown in logs and supervisor output. | `My Inventory App` |
| `server_name` | Fully qualified domain name for nginx and SSL. | `myapp.example.com` |
| `ssl_email` | Email address for Let's Encrypt certificate renewal notifications. | `you@example.com` |

#### Server connection

| Variable | Description | Example |
|----------|-------------|---------|
| `server_host` | SSH hostname or IP address of the shared server. | `13.58.136.177` |
| `server_admin_user` | OS user used for SSH. Pre-existing on the shared server — usually `ubuntu` on AWS. Shared across all apps. | `ubuntu` |
| `app_deploy_user` | AWS IAM user name used by Ansible to create and manage app resources. Created by `create-deploy-user.yml`. | `myapp-deploy` |
| `app_runtime_user` | Dedicated per-app OS user that runs gunicorn. Created by `setup.yml` if it does not exist. | `myapp_runtime` |

#### AWS credentials and resources

| Variable | Description | How to get it |
|----------|-------------|---------------|
| `aws_region` | AWS region where all resources are created. | Choose based on your users' geography (e.g. `us-east-2`). |
| `s3_bucket_name` | S3 bucket for app images and CSV backups. Must be globally unique. | Choose a name like `yourname-appname-2026`. |
| `s3_folder` | Top-level prefix inside the bucket. | Use `data` (default). |
| `secret_name` | AWS Secrets Manager secret path. | Leave as the default: `"{{ app_name }}/production"` |
| `sns_topic_arn` | Optional SNS topic for error alerts. | Leave empty if not using alerts: `""` |
| `server_iam_role_name` | IAM instance role currently attached to the shared EC2 server. `provision-app.yml` attaches this app's IAM policies to that role automatically. Find it in: EC2 Console → Instances → your server → **IAM role**. Leave empty (`""`) to skip auto-attach and attach manually. | `shared-server-role` |

#### Git repository

| Variable | Description | Example |
|----------|-------------|---------|
| `git_repo_url` | HTTPS URL of the application repository. | `https://github.com/user/myapp.git` |
| `git_branch` | Branch to deploy. | `main` |
| `git_token` | GitHub personal access token with `repo` scope. Required for private repositories. Create at: GitHub → Settings → Developer settings → Personal access tokens. | `ghp_xxxxxxxxxxxx` |

#### Application credentials

| Variable | Description | Notes |
|----------|-------------|-------|
| `app_default_username` | Default login username created on first run. | `admin` |
| `app_default_password` | Default login password. **Do not use a weak password.** | Min 12 chars, include symbols. |
| `users` | Space-separated `username:password` pairs for additional accounts. | `alice:Pass1! brian:Pass2!` |

#### Flask runtime

| Variable | Description | Notes |
|----------|-------------|-------|
| `secret_key` | Flask session signing key. Must be random and kept secret. | Generate: `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `flask_env` | Flask environment. | Always `production` on the server. |

#### Port allocation (critical on shared servers)

| Variable | Description | Notes |
|----------|-------------|-------|
| `gunicorn_port` | Port gunicorn listens on (localhost only). **Must be unique across all apps on this server.** | Assign sequentially: `8000`, `8001`, `8002`, … Check with: `ss -tlnp | grep 80` on the server. |
| `gunicorn_workers` | Number of gunicorn worker processes. Keep at `1` on a shared server — each worker forks a full Python process. Use threads for concurrency instead. | `1` |
| `gunicorn_threads` | Threads per worker. 4 threads give 4 concurrent request slots without the memory cost of forking. | `4` |
| `gunicorn_timeout` | Request timeout in seconds. | `120` (default) |

> When adding a second app to the same server, assign the next unused port. All other server-connection fields stay the same.


#### eBay API (if using eBay integration)

| Variable | Description | Where to get it |
|----------|-------------|-----------------|
| `ebay_environment` | `production` or `sandbox`. | Use `production` for live sales. |
| `ebay_production_dev_id` | eBay Developer Program Dev ID. | [eBay Developers Program](https://developer.ebay.com) → My Account → Application Keys |
| `ebay_production_cert_id` | eBay Cert ID (client secret). | Same page as Dev ID. |
| `ebay_production_app_id` | eBay App ID (client ID). | Same page as Dev ID. |
| `ebay_production_token` | Per-user eBay auth token. | Generated via the eBay token flow. See `scripts/util-generate-ebay-token.sh`. |
| `ebay_verification_token` | Token for the eBay Marketplace Account Deletion webhook. | eBay Developer Console → Notifications. |

#### Logging and retention

| Variable | Default | Description |
|----------|---------|-------------|
| `log_retention_days` | `20` | How many rotated log files to keep. |
| `log_max_size` | `10M` | Rotate log when it exceeds this size. |
| `backup_retention_days` | `30` | Delete S3 snapshots older than this many days. |

#### SSH access control


Port 22 access is managed directly in the EC2 security group via the AWS Console. Add your IP manually before running any server playbook.

### Step 3: Encrypt the vault

```bash
cd deployment
ansible-vault encrypt group_vars/vault.yml --vault-password-file ~/.vault_pass
```

Verify:

```bash
head -1 group_vars/vault.yml
# Should output: $ANSIBLE_VAULT;1.1;AES256
```

### Step 4: Create the per-app AWS deploy user

With your bootstrap (root or admin) AWS credentials still active, run:

```bash
cd deployment
ansible-playbook playbooks/create-deploy-user.yml --vault-password-file ~/.vault_pass
```

This one playbook does everything needed before provisioning:

1. Creates `{app_name}-deploy` with `AmazonS3FullAccess`, `IAMFullAccess`, `SecretsManagerReadWrite`, `CloudWatchLogsFullAccess` (idempotent — re-running is safe).
2. **Auto-rotates** any existing access keys (deletes them, issues a fresh one). The secret of an existing key cannot be retrieved, so rotation is the only safe path.
3. Saves `deploy_aws_access_key_id` and `deploy_aws_secret_access_key` into `vault.yml` (re-encrypted; secrets are passed via environment variables, never shell-interpolated).
4. Configures a dedicated **named AWS CLI profile** (`{app_name}-deploy`) — your default profile is untouched.
5. Verifies the profile with `aws sts get-caller-identity` (retry loop — IAM is eventually consistent and fresh keys can throw `InvalidClientTokenId` for 10–30 seconds).

All subsequent deployment playbooks read the profile via `environment.AWS_PROFILE` — no further configuration needed.

> Requires `~/.vault_pass`.

### Step 5: Verify the deploy identity (optional)

```bash
aws sts get-caller-identity --profile {app_name}-deploy
# Arn should show: arn:aws:iam::ACCOUNT_ID:user/{app_name}-deploy
```

Then **delete the temporary root access key** in the AWS Console.

`provision-app.yml` includes two preflight checks that fail fast if `deploy_aws_access_key_id` is missing from vault or if the active identity is the root account.

On any future machine, run `configure-local-aws.yml` to restore the named profile from vault — no IAM API calls, just local CLI config:

```bash
ansible-playbook playbooks/configure-local-aws.yml --vault-password-file ~/.vault_pass
```


---

## Server inventory

Ansible requires literal values (not Jinja2 templates) for connection keywords. The `load-vars.sh` script writes these from the vault into `inventories/hosts.yml` automatically.

```bash
cd deployment
source scripts/load-vars.sh
```

This rewrites `inventories/hosts.yml` with the literal `server_host` and `server_admin_user` values from vault. Run it once per terminal session before any playbook that connects to the server. SSH key selection is handled by your local `~/.ssh/config` or SSH agent.

Test connectivity:

```bash
ansible all -m ping --vault-password-file ~/.vault_pass
# Should return: server | SUCCESS
```

> `inventories/hosts.yml` is gitignored — it contains literal IPs and key paths. Never commit it.

---

## Load variables for CLI use

Many shell commands in these guides use variables from vault.yml. Load them once per terminal session:

```bash
cd deployment
source scripts/load-vars.sh
echo $app_name              # e.g., dockyard
echo $aws_region            # e.g., us-east-2
echo $server_admin_user     # e.g., ubuntu
```

This also writes literal connection values to `inventories/hosts.yml` so Ansible can resolve them before vault decryption.

---

## Verification checklist

Run these checks before continuing. Every command should succeed.

```bash
# AWS credentials (deploy user profile)
aws sts get-caller-identity --profile {app_name}-deploy
# Arn should show: arn:aws:iam::ACCOUNT_ID:user/{app_name}-deploy

# Local tools
ansible --version       # 2.9 or higher
python3 --version       # 3.10 or higher

# Vault is encrypted
head -1 deployment/group_vars/vault.yml   # $ANSIBLE_VAULT;1.1;AES256

# Vault password file exists and is private
ls -la ~/.vault_pass                      # -rw-------

# Server reachable
cd deployment && ansible all -m ping --vault-password-file ~/.vault_pass
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Unable to locate credentials` | Run `aws configure` |
| `ansible: command not found` | `pip3 install ansible` |
| `No module named boto3` | `cd deployment && pip3 install -r requirements.txt` |
| `Permission denied (publickey)` | Verify your SSH key is loaded (`ssh-add ~/.ssh/your-key.pem`) or configure `~/.ssh/config` for the server host |
| `Cannot access vault.yml` | `chmod 600 ~/.vault_pass` |
| Vault shows plaintext | `ansible-vault encrypt group_vars/vault.yml --vault-password-file ~/.vault_pass` |
| `server_admin_user is undefined` | Run `source scripts/load-vars.sh` — Ansible cannot read vault variables for SSH connection keywords; the script writes literal values to `hosts.yml` |
| `host unreachable` | Confirm `server_host` in vault.yml is correct and that your IP is allowed on port 22 in the EC2 security group |
| `gunicorn_port already in use` | SSH to server, run `ss -tlnp \| grep 80xx`, assign the next free port |

---

## Next step

Continue to [Chapter 2: Quick Start](QUICKSTART.md) (automated, 10–15 min) or [Chapter 3: Manual Deployment](MANUAL_DEPLOYMENT.md) (step-by-step with full explanations).

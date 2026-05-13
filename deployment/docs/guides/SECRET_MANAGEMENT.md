# Chapter 7: Secret Management

Rotate passwords, API keys, and credentials without downtime.

---

## How secrets are stored and used

Secrets flow through two layers:

```
Your Machine
  └── group_vars/vault.yml  (Ansible Vault — AES256, safe to commit)
          │
          │  ansible-playbook setup-secrets-manager.yml
          ▼
  AWS Secrets Manager  (runtime — path: {app_name}/production)
          │
          │  EC2 IAM role (no credentials on disk)
          ▼
  Application  →  app/config.py get_secret()
```

**vault.yml** is the source of truth for all secrets. It is encrypted with AES256 and
safe to commit to git. Edit it with `ansible-vault edit`, then re-sync to AWS.

**AWS Secrets Manager** holds the runtime copy. The application fetches it at startup
via the EC2 instance's IAM role. No `.env` file is written to the server.

---

## Editing secrets

```bash
cd deployment
ansible-vault edit group_vars/vault.yml --vault-password-file ~/.vault_pass
```

After saving, sync the changes to AWS Secrets Manager:

```bash
ansible-playbook playbooks/setup-secrets-manager.yml --vault-password-file ~/.vault_pass
```

Then restart the application so it picks up the new values:

```bash
ansible-playbook playbooks/update.yml --vault-password-file ~/.vault_pass
```

---

## Adding a new secret

1. Edit vault.yml and add the new key-value pair (e.g., `new_api_key: "value"`)
2. Add the corresponding entry to the `aws_secrets` dict in `setup-secrets-manager.yml`
   (key name must be UPPERCASE to match what `get_secret()` expects in `app/config.py`)
3. Sync to AWS:
   ```bash
   ansible-playbook playbooks/setup-secrets-manager.yml --vault-password-file ~/.vault_pass
   ```
4. Commit the vault change and the updated playbook:
   ```bash
   git add group_vars/vault.yml playbooks/setup-secrets-manager.yml
   git commit -m "feat: add new_api_key secret"
   git push
   ```

---

## Zero-downtime rotation

AWS Secrets Manager uses staging labels to support zero-downtime rotation:

```
Secret versions
  AWSCURRENT  ← application reads this
  AWSPENDING  ← new value staged for testing
  AWSPREVIOUS ← previous value kept for rollback
```

### Rotate a secret

**Step 1 — Add the new value to vault.yml with a `_new` suffix:**

```bash
ansible-vault edit group_vars/vault.yml --vault-password-file ~/.vault_pass
```

```yaml
# Example: rotating the eBay token
ebay_production_token: "v^1.1#i^1#...old-token..."
ebay_production_token_new: "v^1.1#i^1#...new-token..."   # ← add this
```

**Step 2 — Stage the new value as AWSPENDING:**

```bash
ansible-playbook playbooks/secret-rotate.yml \
    -e secret_key=ebay_production_token \
    --vault-password-file ~/.vault_pass
```

The old value is still AWSCURRENT. The application is unaffected.

**Step 3 — Test the new value works as expected with your application.**

**Step 4 — Promote AWSPENDING to AWSCURRENT:**

```bash
ansible-playbook playbooks/secret-promote.yml \
    -e secret_key=ebay_production_token \
    --vault-password-file ~/.vault_pass
```

The new value is now live. The old value becomes AWSPREVIOUS (kept for rollback).

**Step 5 — Clean up vault.yml:**

```bash
ansible-vault edit group_vars/vault.yml --vault-password-file ~/.vault_pass
```

```yaml
# Remove the _new key; replace the main value with the new token
ebay_production_token: "v^1.1#i^1#...new-token..."
# Delete the ebay_production_token_new line
```

Commit:

```bash
git add group_vars/vault.yml
git commit -m "rotate: eBay production token"
git push
```

---

## Rotation schedule

| Credential | Frequency | Playbook |
|-----------|-----------|---------|
| eBay API token | When eBay requires it | `secret-rotate.yml` + `secret-promote.yml` |
| `app_default_password` / `users` | Quarterly | Edit vault → `setup-secrets-manager.yml` → restart |
| `secret_key` (Flask session key) | Annually (invalidates all sessions) | Edit vault → `setup-secrets-manager.yml` → restart |
| `git_token` | On expiry | Edit vault; no AWS sync needed |
| `aws_access_key_id` / `aws_secret_access_key` | Annually | Delete old key in IAM console → re-run `create-iam-user.yml` |

---

## Vault password management

- Store `~/.vault_pass` locally only. Never commit it.
- Back it up in a password manager. If it is lost, the vault cannot be recovered.
- To share with another team member, share the passphrase via a password manager,
  never over email or chat.

Rotate the vault password itself:

```bash
ansible-vault rekey group_vars/vault.yml --vault-password-file ~/.vault_pass
# Prompts for new password. Update ~/.vault_pass with the new value.
```

---

## Verify Secrets Manager is in sync

```bash
cd deployment
source scripts/load-vars.sh

aws secretsmanager get-secret-value \
    --secret-id ${app_name}/production \
    --region $aws_region \
    --query SecretString \
    --output text | python3 -m json.tool
```

Compare the output against your current vault.yml values. If they differ, re-run
`setup-secrets-manager.yml` to sync.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Decryption failed` | Wrong vault password. Verify `cat ~/.vault_pass` matches what you used when encrypting. |
| `Secret not found` in Secrets Manager | Run `setup-secrets-manager.yml` to create or repopulate it. |
| Application reports missing secret at startup | New key added to code but not yet in Secrets Manager — sync and restart. |
| IAM permission denied on `GetSecretValue` | Run `create-iam-policies.yml` and confirm `server_iam_role_name` is set. |

---

## Next step

Continue to [Chapter 8: Security Hardening](SECURITY_HARDENING.md).

## See also

- [Chapter 5: Operations](OPERATIONS.md) — operational procedures
- [Chapter 6: Monitoring](MONITORING.md) — track secret rotation events in CloudWatch

## Overview

This document describes the complete secret management workflow using:
- **Ansible Vault** - Encrypted secrets in git (safe to commit)
- **AWS Secrets Manager** - Runtime secrets (fetched by application)
- **Rotation Process** - Zero-downtime secret rotation

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Development Workflow                      │
└─────────────────────────────────────────────────────────────┘

Developer's Machine:
  ├── group_vars/vault.yml (Ansible Vault encrypted)
  ├── .vault_pass (never commit!)
  └── git commit (encrypted vault is safe)
       ↓
GitHub Repository:
  └── vault.yml (encrypted, safe in git)
       ↓
Deployment:
  ├── Ansible decrypts vault.yml
  ├── Uploads secrets to AWS Secrets Manager
  └── Application fetches from Secrets Manager
       ↓
Production:
  ├── No secrets on disk
  ├── Secrets Manager provides values
  └── IAM role authentication
```

---

## Secret Storage Locations

### 1. Ansible Vault (Source of Truth)

**File:** `deployment/group_vars/vault.yml`

**Contains:**
- All production secrets
- eBay API credentials
- Admin passwords
- GitHub tokens
- Secret keys

**Security:**
- ✅ Encrypted with AES256
- ✅ Safe to commit to git
- ✅ Requires password to decrypt
- ✅ Password stored locally only (`.vault_pass`)

### 2. AWS Secrets Manager (Runtime)

**Secret Name:** `{app_name}/secrets`

**Contains:**
- Same values as Ansible Vault
- Fetched by application at runtime
- Updated via deployment process

**Security:**
- ✅ No secrets on server disk
- ✅ IAM role authentication
- ✅ Automatic encryption at rest
- ✅ CloudTrail audit logs

---

## Workflow

### Sync Secrets to AWS Secrets Manager

The `setup-secrets-manager.yml` playbook automatically syncs secrets from Ansible Vault to AWS Secrets Manager:

```bash
cd deployment
source scripts/load-vars.sh
ansible-playbook playbooks/setup-secrets-manager.yml --vault-password-file ~/.vault_pass
```

**This playbook:**
1. ✅ Extracts `vault_`-prefixed variables (AWS config, SNS, etc.)
2. ✅ Maps application secrets to UPPERCASE keys (eBay credentials, app passwords, verification token)
3. ✅ Creates AWS Secrets Manager secret via Ansible AWS module
4. ✅ Stores all secrets as JSON
5. ✅ Enables automatic 30-day rotation
6. ✅ Tags resources for tracking

**Secrets synced to Secrets Manager:**

Vault variables are synced as UPPERCASE keys matching `config.py` `get_secret()` calls
(e.g., `secret_key` → `SECRET_KEY`, `s3_bucket_name` → `S3_BUCKET_NAME`).
The mapping is defined inline in `secret-sync.yml` and `setup-secrets-manager.yml`.

**Technical Details:**
- Uses `amazon.aws.secretsmanager_secret` module for AWS operations
- No passwords needed on EC2 instance (IAM role handles authentication)


---

### Initial Setup

```bash
# 1. Create vault password (OPTIONAL but RECOMMENDED)
#    Skip this if you prefer to enter password when prompted
echo "your-secure-vault-password" > ~/.vault_pass
chmod 600 ~/.vault_pass

# 2. Create encrypted vault file
#    You'll be prompted for password if ~/.vault_pass doesn't exist
ansible-vault create deployment/group_vars/vault.yml \
  --vault-password-file ~/.vault_pass

# 3. Add secrets (see template below)

# 4. Commit to git (encrypted)
git add deployment/group_vars/vault.yml
git commit -m "Add encrypted secrets"
git push
```

### Editing Secrets

```bash
# Edit encrypted vault
ansible-vault edit deployment/group_vars/vault.yml \
  --vault-password-file ~/.vault_pass

# After saving, commit changes
git add deployment/group_vars/vault.yml
git commit -m "Update secrets"
git push
```

### Deployment Process

```bash
# Deploy with vault
cd deployment
./scripts/app-deploy.sh setup --vault-password-file ~/.vault_pass

# Or with password prompt
./scripts/app-deploy.sh setup --ask-vault-pass
```

**What happens:**
1. Ansible decrypts `vault.yml`
2. Secrets uploaded to AWS Secrets Manager
3. Application fetches from Secrets Manager
4. No secrets stored on server disk

---

## Secret Rotation Strategy

### Zero-Downtime Rotation Process

AWS Secrets Manager supports **versioning** with staging labels:

```
Secret Versions:
├── AWSCURRENT (active version)
└── AWSPENDING (new version being tested)
```

### Rotation Workflow

#### Option 1: Automatic Rotation (AWS Managed)

For compatible secrets (RDS, etc.), AWS can rotate automatically.

#### Option 2: Manual Rotation (Our Process)

For eBay tokens, API keys, etc.:

**Step 1: Add new secret value to vault**
```yaml
# vault.yml — add the _new suffix with the replacement value
ebay_production_token: "v^1.1#i^1#...old-token..."
vault_ebay_production_token_new: "v^1.1#i^1#...new-token..."  # ← Add this
```

**Step 2: Rotate via playbook**
```bash
ansible-playbook playbooks/secret-rotate.yml \
  -e secret_key=ebay_production_token \
  --vault-password-file ~/.vault_pass
```
This creates an AWSPENDING version in Secrets Manager.

**Step 3: Test your application**
```bash
curl https://yourdomain.com/api/ebay/test
```

**Step 4: Promote if successful**
```bash
ansible-playbook playbooks/secret-promote.yml \
  -e secret_key=ebay_production_token \
  --vault-password-file ~/.vault_pass
```

**Step 5: Clean up vault**
```yaml
# vault.yml — move new value to main key, remove _new
ebay_production_token: "v^1.1#i^1#...new-token..."
# Remove vault_ebay_production_token_new
```


---

## Vault File Template

**File:** `deployment/group_vars/vault.yml`

```yaml
---
# Production Secrets (Ansible Vault Encrypted)
# Edit with: ansible-vault edit group_vars/vault.yml --vault-password-file ~/.vault_pass

# Git Repository
git_repo_url: "https://github.com/youruser/yourapp.git"

# AWS Configuration
aws_region: "us-east-2"
s3_bucket_name: "your-bucket-name"
s3_folder: "data"

# Application Credentials
app_default_username: "admin"
app_default_password: "secure-password-here"
users: "admin:secure-password-here"

# Flask
secret_key: "your-secret-key-here"
flask_port: "8000"
flask_env: "production"


# eBay Production Credentials
ebay_environment: "production"
ebay_production_app_id: "YourApp-PRD-1234567890-a1b2c3d4"
ebay_production_dev_id: "a1b2c3d4-e5f6-7890-a1b2-c3d4e5f67890"
ebay_production_cert_id: "PRD-1234567890ab-cdef-1234-5678"
ebay_production_token: "v^1.1#i^1#...long-token-here"
ebay_verification_token: "your-64-char-token"

# SNS (optional)
sns_topic_arn: ""
```

---

## Deployment Integration

### Updated app-deploy.sh

The deployment script now:
1. Decrypts Ansible Vault
2. Extracts secrets
3. Uploads to AWS Secrets Manager
4. Application fetches from Secrets Manager

### Playbook Integration

Secrets are synced to AWS Secrets Manager during deployment via `setup-secrets-manager.yml`. The `setup.yml` playbook generates the `.env` file with non-secret configuration, and the application fetches secrets from Secrets Manager at runtime using the `SECRET_NAME` environment variable.

---

## Security Best Practices

### Vault Password Management

**DO:**
- ✅ Store `.vault_pass` locally only
- ✅ Add to `.gitignore`
- ✅ Use strong, unique password
- ✅ Share via secure channel (1Password, etc.)
- ✅ Rotate vault password periodically

**DON'T:**
- ❌ Commit `.vault_pass` to git
- ❌ Share password via email/Slack
- ❌ Use same password as other systems
- ❌ Store in plaintext notes

### Secret Rotation Schedule

**Quarterly (Every 3 months):**
- eBay API tokens
- Admin passwords
- GitHub tokens
- Application secret keys

**Annually:**
- Vault encryption password
- AWS access keys
- SSL certificates

### Audit Trail

All secret access logged:
- **CloudTrail**: AWS Secrets Manager API calls
- **CloudWatch**: Application secret fetches
- **Ansible logs**: Deployment secret updates

View logs:
```bash
# CloudTrail - Secrets Manager access
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=ResourceType,AttributeValue=AWS::SecretsManager::Secret

# CloudWatch - Application logs
aws logs filter-log-events \
  --log-group-name /{app_name}/application \
  --filter-pattern "Secret"
```

---

## Disaster Recovery

### Backup Secrets

```bash
# 1. Vault file is in git (encrypted)
git log deployment/group_vars/vault.yml

# 2. Export from Secrets Manager
aws secretsmanager get-secret-value \
  --secret-id {app_name}/secrets \
  --query SecretString \
  --output text > secrets-backup-$(date +%Y%m%d).json

# Encrypt backup
gpg --encrypt --recipient your@email.com secrets-backup-*.json
```

### Restore Secrets

```bash
# 1. From git (if vault file lost)
git checkout deployment/group_vars/vault.yml

# 2. From backup
aws secretsmanager put-secret-value \
  --secret-id <app_name>/production \
  --secret-string file://secrets-backup.json
```

---

## Common Workflows

### Add New Secret

```bash
# 1. Edit vault
ansible-vault edit deployment/group_vars/vault.yml \
  --vault-password-file ~/.vault_pass

# Add new secret:
# vault_new_api_key: "your-new-api-key"

# 2. Commit
git add deployment/group_vars/vault.yml
git commit -m "Add new API key"
git push

# 3. Deploy
cd deployment
./scripts/app-deploy.sh update --vault-password-file ~/.vault_pass
```

### Rotate eBay Token

```bash
cd deployment

# 1. Get new token from eBay Developer Portal
#    https://developer.ebay.com/my/auth
NEW_TOKEN="v^1.1#i^1#...new-token..."

# 2. Add to vault as _new
ansible-vault edit group_vars/vault.yml \
  --vault-password-file ~/.vault_pass
# Add: vault_ebay_production_token_new: "v^1.1#i^1#...new-token..."

# 3. Rotate secret
ansible-playbook playbooks/secret-rotate.yml \
  -e secret_key=ebay_production_token \
  --vault-password-file ~/.vault_pass

# 4. Test application
curl https://yourdomain.com/api/ebay/test

# 5. If successful, promote
ansible-playbook playbooks/secret-promote.yml \
  -e secret_key=ebay_production_token \
  --vault-password-file ~/.vault_pass

# 6. Clean up vault
ansible-vault edit group_vars/vault.yml --vault-password-file ~/.vault_pass
# Move _new to main, remove _new suffix

# 7. Commit
git add deployment/group_vars/vault.yml
git commit -m "Rotate eBay production token"
git push
```

### Share Secrets with Team

```bash
# 1. Export vault password securely
echo "Vault password: $(cat ~/.vault_pass)"
# Share via 1Password, LastPass, etc.

# 2. New team member sets up
echo "received-password" > ~/.vault_pass
chmod 600 ~/.vault_pass

# 3. Test access
ansible-vault view deployment/group_vars/vault.yml \
  --vault-password-file ~/.vault_pass
```

---

## Troubleshooting

### "Decryption failed"

**Cause:** Wrong vault password

**Fix:**
```bash
# Verify password
cat ~/.vault_pass

# Try with prompt
ansible-vault view deployment/group_vars/vault.yml
```

### "Secret not found in Secrets Manager"

**Cause:** Secrets not uploaded during deployment

**Fix:**
```bash
# Manually sync secrets from vault to Secrets Manager
cd deployment
ansible-playbook playbooks/setup-secrets-manager.yml --vault-password-file ~/.vault_pass
```

### "Application can't fetch secrets"

**Cause:** IAM role missing permissions

**Fix:**
```bash
# Add Secrets Manager permissions
aws iam put-role-policy \
  --role-name <app_name>-ec2-role \
  --policy-name SecretsManagerAccess \
  --policy-document file://secrets-policy.json
```

---


## Next step

Continue to [Chapter 8: Security Hardening](SECURITY_HARDENING.md).

## See also

- [Chapter 5: Operations](OPERATIONS.md) — operational procedures
- [Chapter 6: Monitoring](MONITORING.md) — track secret rotation events


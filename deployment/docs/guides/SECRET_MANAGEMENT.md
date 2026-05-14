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
| `deploy_aws_access_key_id` / `deploy_aws_secret_access_key` | Annually | Re-run `create-deploy-user.yml` — it auto-deletes the old key and issues a fresh one |

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
- **Ansible Vault** - Encrypted secrets in git (safe to commit)
- **AWS Secrets Manager** - Runtime secrets (fetched by application)
- **Rotation Process** - Zero-downtime secret rotation

---

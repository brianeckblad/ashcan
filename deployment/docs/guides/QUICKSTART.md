# Chapter 2: Quick Start

Deploy the application in 10–15 minutes using automation.

> **Prerequisite:** Complete [Chapter 1: Prerequisites](PREREQUISITES.md) before continuing.

---


## Deploy in Two Steps

```bash
cd deployment
source scripts/load-vars.sh   # writes literal connection values to inventories/hosts.yml

# Step 1: Create AWS resources
# Creates S3 bucket, IAM policies (S3, Secrets Manager, CloudWatch), Secrets Manager secret
ansible-playbook playbooks/provision-app.yml \
    --vault-password-file ~/.vault_pass

# Step 2: Deploy the application to the server
# Clones code, installs dependencies, configures nginx + supervisor, installs SSL
ansible-playbook playbooks/setup.yml \
    --vault-password-file ~/.vault_pass
```

**What each step does:**

`provision-app.yml`:
1. Creates S3 bucket for application data
2. Creates three app-scoped IAM managed policies (S3, Secrets Manager, CloudWatch) and attaches them to the server's IAM role (if `server_iam_role_name` is set)
3. Creates Secrets Manager secret (synced from vault)

`setup.yml`:
4. Creates application user and group on the server
5. Creates application directories
6. Clones the git repository and installs Python dependencies
7. Configures Supervisor (process manager) and Nginx (web server)
8. Installs SSL certificate via Let's Encrypt (auto-renewal enabled)
9. Starts the application


**Duration:** 10–15 minutes

---

## After Deployment

### Test your application

```bash
# In your browser:
https://{server_name}

# Or from terminal:
curl https://{server_name}
```

### Connect to the server

```bash
ssh ubuntu@{server_host}

# Check app status
sudo supervisorctl status {app_name}

# View logs
sudo tail -f /var/log/apps/{app_name}/app.log
```

> **Tip:** To use shell variables for ad-hoc CLI commands (`ssh ubuntu@$server_host`, `aws s3 ls $s3_bucket_name`), load them once per terminal session:
> ```bash
> cd deployment && source scripts/load-vars.sh
> ```
> Playbooks do **not** require this — they read `vault.yml` directly.

### Verify SSL

```bash
# Test HTTPS
curl -I https://{server_name}
# Should show: HTTP/2 200

# HTTP redirects to HTTPS
curl -I http://{server_name}
# Should show: 301 → https://...
```

---

## Troubleshooting

### Common pre-flight issues

1. **AWS CLI profile not configured:**
   ```bash
   aws sts get-caller-identity --profile {app_name}-deploy
   # If this fails, run: ansible-playbook playbooks/configure-local-aws.yml \
   #                          --vault-password-file ~/.vault_pass
   ```

2. **Vault not encrypted:**
   ```bash
   head -1 deployment/group_vars/vault.yml
   # Should show: $ANSIBLE_VAULT;1.1;AES256
   ```

3. **Vault password file missing:**
   ```bash
   ls -la ~/.vault_pass
   # Should show: -rw------- (600 permissions)
   ```

4. **Ansible not installed:**
   ```bash
   cd deployment
   pip install -r requirements.txt
   ansible-galaxy collection install -r requirements.yml --upgrade
   ```

### Playbook fails partway through

Ansible is idempotent — re-run the same playbook. It skips completed steps and retries only the failed one.

For individual steps, use the single-resource playbooks instead:

```bash
# AWS resources individually
ansible-playbook playbooks/create-s3-bucket.yml --vault-password-file ~/.vault_pass
ansible-playbook playbooks/create-iam-policies.yml --vault-password-file ~/.vault_pass
ansible-playbook playbooks/setup-secrets-manager.yml --vault-password-file ~/.vault_pass
```

See [Chapter 3: Manual Deployment](MANUAL_DEPLOYMENT.md) for full step-by-step instructions.

---

## Next step

Continue to [Chapter 4: Updating Your Application](UPDATING_APPLICATION.md).

## See also

- [Chapter 3: Manual Deployment](MANUAL_DEPLOYMENT.md) — deploy step-by-step instead
- [Chapter 6: Monitoring](MONITORING.md) — set up CloudWatch dashboards and alarms
- [Chapter 8: Security Hardening](SECURITY_HARDENING.md) — verify and tune hardening settings

# Chapter 11: Decommission

Remove all app-level AWS resources. The shared server and other applications on it are not affected.

> **Warning:** This is destructive and irreversible. All data in S3 will be permanently deleted.

---

## Table of Contents

1. [Before You Begin](#before-you-begin)
2. [Full Automated Teardown](#full-automated-teardown)
3. [Step-by-Step Teardown](#step-by-step-teardown)
4. [Verify Everything Is Gone](#verify-everything-is-gone)
5. [Single Resource Removal](#single-resource-removal)
6. [Troubleshooting](#troubleshooting)

---

## Before You Begin

```
Before deleting anything, confirm:

  [ ] All application data has been backed up from S3
  [ ] All logs have been archived
  [ ] Users have been notified of the shutdown
  [ ] You have the vault password (needed for playbooks)
  [ ] You know your S3 bucket name (from vault)
```

### What gets deleted

This decommission removes only this application's AWS resources:

```
DELETE ORDER
─────────────
1. IAM managed policies (detached from server role, then deleted)
2. Secrets Manager secret
3. S3 Bucket (ALL DATA — cannot be undone)
```

The shared server remains running. Other applications on the same server are not affected.

To also remove the application code from the server (stop supervisor process, remove nginx vhost, remove app directory), do that manually before running the decommission playbook.

---

## Full Automated Teardown

Run the interactive decommission wrapper:

```bash
cd deployment
./scripts/decommission.sh
```

The script shows what exists, asks for confirmation, and runs `decommission.yml`.

**To run without the wrapper:**

```bash
ansible-playbook playbooks/decommission.yml \
    --vault-password-file ~/.vault_pass \
    -e decommission_confirmed=true
```

**Duration:** 2–5 minutes.

---

## Step-by-Step Teardown

Run individual playbooks for complete control.

### Step 1: Delete IAM Policies

```bash
ansible-playbook playbooks/delete-iam-policies.yml --vault-password-file ~/.vault_pass
```

Detaches the three app policies from the server role (if `server_iam_role_name` is set), then deletes them:

- `{app_name}-s3-access`
- `{app_name}-secrets-access`
- `{app_name}-cloudwatch-access`

**CLI:**
```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)

for policy in s3-access secrets-access cloudwatch-access; do
    # Detach from server role first (if applicable)
    aws iam detach-role-policy \
        --role-name $server_iam_role_name \
        --policy-arn arn:aws:iam::${ACCOUNT}:policy/${app_name}-${policy} 2>/dev/null
    # Delete the policy
    aws iam delete-policy \
        --policy-arn arn:aws:iam::${ACCOUNT}:policy/${app_name}-${policy}
done
```

### Step 2: Delete Secrets Manager Secret

```bash
ansible-playbook playbooks/delete-secrets-manager.yml --vault-password-file ~/.vault_pass
```

**CLI:**
```bash
aws secretsmanager delete-secret \
    --secret-id ${app_name}/production \
    --force-delete-without-recovery \
    --region $aws_region
```

### Step 3: Delete S3 Bucket

> **This permanently deletes all application data.**

```bash
ansible-playbook playbooks/delete-s3-bucket.yml --vault-password-file ~/.vault_pass
```

**CLI:**
```bash
# Empty and delete all versioned objects first
aws s3api delete-objects \
    --bucket $s3_bucket_name \
    --delete "$(aws s3api list-object-versions \
        --bucket $s3_bucket_name \
        --query '{Objects: Versions[].{Key: Key, VersionId: VersionId}}' \
        --output json)" 2>/dev/null

aws s3 rm s3://$s3_bucket_name --recursive
aws s3api delete-bucket --bucket $s3_bucket_name --region $aws_region
```


---

## Verify Everything Is Gone

```bash
source scripts/load-vars.sh

# S3 — should return "NoSuchBucket" or empty
aws s3 ls s3://$s3_bucket_name 2>&1

# IAM policies — should return empty
aws iam list-policies \
    --query "Policies[?starts_with(PolicyName, '${app_name}-')].[PolicyName]" \
    --output text

# Secrets Manager — should return error
aws secretsmanager describe-secret \
    --secret-id ${app_name}/production \
    --region $aws_region 2>&1
```

---

## Single Resource Removal

To remove a specific resource without running the full decommission:

| Resource | Command |
|----------|---------|
| IAM policies | `ansible-playbook playbooks/delete-iam-policies.yml --vault-password-file ~/.vault_pass` |
| Secrets Manager | `ansible-playbook playbooks/delete-secrets-manager.yml --vault-password-file ~/.vault_pass` |
| S3 Bucket | `ansible-playbook playbooks/delete-s3-bucket.yml --vault-password-file ~/.vault_pass` |

---

## Troubleshooting

### IAM policy cannot be deleted — still attached to a role

Detach manually before deleting:

```bash
aws iam detach-role-policy \
    --role-name <role-name> \
    --policy-arn arn:aws:iam::<account-id>:policy/${app_name}-s3-access
```

Then re-run the delete playbook.

### S3 bucket is not empty

The delete-s3-bucket playbook empties versioned buckets automatically. If it fails, empty the bucket manually:

```bash
aws s3 rm s3://$s3_bucket_name --recursive
```

Then re-run the delete playbook.


---

## Recreate

To start fresh after a full decommission:

```bash
ansible-playbook playbooks/provision-app.yml --vault-password-file ~/.vault_pass
ansible-playbook playbooks/setup.yml --vault-password-file ~/.vault_pass
```

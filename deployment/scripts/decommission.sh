#!/bin/bash
#
d# Decommission -- App Resource Discovery and Teardown
# Supported shells: bash, zsh
#
# Interactive wrapper that checks for existing app-level AWS resources
# (S3, IAM policies, Secrets Manager) before calling the decommission playbook.
#
# Usage:
#   cd deployment
#   ./scripts/decommission.sh
#
# The shared server is NOT touched — only app-level AWS resources are removed.

set -e

# ── Shell compatibility ──────────────────────────────────────────────
current_shell=$(ps -p $$ -o comm= 2>/dev/null)
current_shell=$(basename "$current_shell" 2>/dev/null)
current_shell=$(echo "$current_shell" | tr -d '-')
if [[ -z "$current_shell" ]]; then
    current_shell=$(basename "$SHELL" 2>/dev/null)
    current_shell=$(echo "$current_shell" | tr -d '-')
fi
case "$current_shell" in
    bash|zsh) ;;
    *)
        echo "Unsupported shell: $current_shell (need bash or zsh)" >&2
        exit 1
        ;;
esac

# ── Resolve paths ────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
GROUP_VARS_DIR="$DEPLOYMENT_DIR/group_vars"

# ── Colors ───────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

# ── Load app_name and aws_region ─────────────────────────────────────
if [[ ! -f "$GROUP_VARS_DIR/vault.yml" ]]; then
    echo -e "${RED}ERROR: $GROUP_VARS_DIR/vault.yml not found${NC}"
    echo "Run ./scripts/local-dev-setup.sh first."
    exit 1
fi

app_name=""
if head -1 "$GROUP_VARS_DIR/vault.yml" 2>/dev/null | grep -q "ANSIBLE_VAULT"; then
    if [[ -f "$HOME/.vault_pass" ]]; then
        app_name=$(ansible-vault view "$GROUP_VARS_DIR/vault.yml" \
            --vault-password-file "$HOME/.vault_pass" 2>/dev/null \
            | grep -E "^app_name:" | head -1 \
            | sed 's/^app_name:[[:space:]]*//' | sed 's/#.*//' \
            | sed 's/[[:space:]]*$//' | tr -d '"' | tr -d "'")
    fi
else
    app_name=$(grep -E "^app_name:" "$GROUP_VARS_DIR/vault.yml" | head -1 \
        | sed 's/^app_name:[[:space:]]*//' | sed 's/#.*//' \
        | sed 's/[[:space:]]*$//' | tr -d '"' | tr -d "'")
fi

if [[ -z "$app_name" ]]; then
    echo -e "${RED}ERROR: app_name not set in vault.yml${NC}"
    exit 1
fi

aws_region=""
if [[ -f "$HOME/.vault_pass" ]] && [[ -f "$GROUP_VARS_DIR/vault.yml" ]]; then
    aws_region=$(ansible-vault view "$GROUP_VARS_DIR/vault.yml" \
        --vault-password-file "$HOME/.vault_pass" 2>/dev/null \
        | grep -E "^aws_region:" | head -1 \
        | sed 's/^aws_region:[[:space:]]*//' | sed 's/#.*//' \
        | sed 's/[[:space:]]*$//' | tr -d '"' | tr -d "'")
fi
if [[ -z "$aws_region" ]]; then
    aws_region="us-east-2"
fi

s3_bucket=""
if [[ -f "$HOME/.vault_pass" ]] && [[ -f "$GROUP_VARS_DIR/vault.yml" ]]; then
    s3_bucket=$(ansible-vault view "$GROUP_VARS_DIR/vault.yml" \
        --vault-password-file "$HOME/.vault_pass" 2>/dev/null \
        | grep -E "^s3_bucket_name:" | head -1 \
        | sed 's/^s3_bucket_name:[[:space:]]*//' | sed 's/#.*//' \
        | sed 's/[[:space:]]*$//' | tr -d '"' | tr -d "'")
fi

# ── Discover existing resources ───────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║          Decommission — Resource Discovery               ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  App:    $app_name"
echo "  Region: $aws_region"
echo ""
echo "Querying AWS for app resources..."
echo ""

found_resources=0

# S3 bucket
if [[ -n "$s3_bucket" ]]; then
    if aws s3api head-bucket --bucket "$s3_bucket" --region "$aws_region" 2>/dev/null; then
        echo -e "  ${GREEN}FOUND${NC}  S3 bucket:        $s3_bucket"
        found_resources=$((found_resources + 1))
    else
        echo "  MISSING  S3 bucket:        $s3_bucket"
    fi
fi

# IAM policies
ACCOUNT=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "")
if [[ -n "$ACCOUNT" ]]; then
    for policy_suffix in s3-access secrets-access cloudwatch-access; do
        policy_name="${app_name}-${policy_suffix}"
        if aws iam get-policy --policy-arn "arn:aws:iam::${ACCOUNT}:policy/${policy_name}" 2>/dev/null | grep -q PolicyName; then
            echo -e "  ${GREEN}FOUND${NC}  IAM policy:       $policy_name"
            found_resources=$((found_resources + 1))
        else
            echo "  MISSING  IAM policy:       $policy_name"
        fi
    done
fi

# Secrets Manager
secret_exists=$(aws secretsmanager describe-secret \
    --secret-id "${app_name}/production" \
    --region "$aws_region" 2>/dev/null | grep -c '"Name"' || true)
if [[ "$secret_exists" -gt 0 ]]; then
    echo -e "  ${GREEN}FOUND${NC}  Secrets Manager:  ${app_name}/production"
    found_resources=$((found_resources + 1))
else
    echo "  MISSING  Secrets Manager:  ${app_name}/production"
fi

echo ""

if [[ "$found_resources" -eq 0 ]]; then
    echo "  No app resources found for '$app_name'. Nothing to decommission."
    echo ""
    exit 0
fi

echo "  Found $found_resources resource(s) to remove."
echo ""

# ── Confirm before calling the playbook ──────────────────────────────
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  DESTRUCTIVE OPERATION -- ALL DATA WILL BE DELETED      ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  S3 bucket data, Secrets Manager secrets, IAM policies will be"
echo "  permanently deleted. The shared server is NOT affected."
echo ""
printf "  Type the app name to confirm (%s): " "$app_name"
read -r confirm

if [[ "$confirm" != "$app_name" ]]; then
    echo ""
    echo -e "${RED}Confirmation failed.${NC} You typed '$confirm' but app_name is '$app_name'."
    echo "Run again and type '$app_name' to confirm."
    exit 1
fi

echo ""
echo "Starting decommission..."
echo ""

# ── Run the playbook ─────────────────────────────────────────────────
cd "$DEPLOYMENT_DIR"
ansible-playbook playbooks/decommission.yml \
    --vault-password-file ~/.vault_pass \
    -e "decommission_confirmed=true"


#!/bin/bash
#
# Application Complete Setup
# Supported shells: bash, zsh
# Runs both deployment playbooks: provision-app (AWS resources) + setup (application)
#
# Usage: ./deployment/scripts/infra-complete-setup.sh

set -e

# Shell compatibility check
current_shell=$(ps -p $$ -o comm= 2>/dev/null)
current_shell=$(basename "$current_shell" 2>/dev/null)
current_shell=$(echo "$current_shell" | tr -d '-')
if [[ -z "$current_shell" ]]; then
    current_shell=$(basename "$SHELL" 2>/dev/null)
    current_shell=$(echo "$current_shell" | tr -d '-')
fi
case "$current_shell" in
    bash|zsh)
        ;; # Supported shell
    *)
        echo "WARNING: Unsupported shell detected!" >&2
        echo "   Current shell: $current_shell" >&2
        echo "   Supported shells: bash, zsh" >&2
        echo "" >&2
        echo "   Please run with: bash ./deployment/scripts/infra-complete-setup.sh" >&2
        exit 1
        ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║   Application Deployment                                 ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# Check prerequisites
echo "Checking prerequisites..."

if ! command -v ansible-playbook &> /dev/null; then
    echo "ERROR: Ansible not installed. Run: pip install ansible"
    exit 1
fi

if ! command -v aws &> /dev/null; then
    echo "ERROR: AWS CLI not installed."
    exit 1
fi

if ! aws sts get-caller-identity &> /dev/null; then
    echo "ERROR: AWS CLI not configured. Run: aws configure"
    exit 1
fi

echo "All prerequisites met"
echo ""

# Run the playbooks
cd "$DEPLOYMENT_DIR"

echo "Step 1/2: Creating AWS resources (S3, IAM policies, Secrets Manager)..."
echo ""
ansible-playbook playbooks/provision-app.yml --vault-password-file ~/.vault_pass

echo ""
echo "Step 2/2: Deploying application to server (code, nginx, supervisor, SSL)..."
echo ""
ansible-playbook playbooks/setup.yml --vault-password-file ~/.vault_pass

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║   Deployment Complete!                                   ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "Configured:"
echo "  S3 bucket, IAM policies, Secrets Manager"
echo "  Application code, nginx vhost, supervisor process, SSL certificate"
echo ""
echo "Next steps:"
echo "  1. Test: curl https://\$(grep 'server_name:' group_vars/vault.yml 2>/dev/null | head -1 | awk '{print \$2}')"
echo "  2. Check logs: sudo tail -f /var/log/apps/\$(grep 'app_name:' group_vars/vault.yml 2>/dev/null | head -1 | awk '{print \$2}')/app.log"
echo ""

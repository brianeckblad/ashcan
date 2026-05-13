#!/bin/bash
#
# Application Deployment Helper
# Supported shells: bash, zsh
#
# Wraps common ansible-playbook commands for convenience.
# All it does is pass the right flags — you can always call ansible-playbook directly.
#
# Usage:
#   ./deployment/scripts/app-deploy.sh setup      # Initial server deploy
#   ./deployment/scripts/app-deploy.sh update      # Update code + restart
#   ./deployment/scripts/app-deploy.sh logs        # Tail app logs
#   ./deployment/scripts/app-deploy.sh status      # Check supervisor status
#   ./deployment/scripts/app-deploy.sh rollback <hash>  # Roll back one commit

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
        echo "⚠️  WARNING: Unsupported shell detected!" >&2
        echo "   Current shell: $current_shell" >&2
        echo "   Supported shells: bash, zsh" >&2
        echo "" >&2
        echo "   Please run with: bash ./deployment/scripts/app-deploy.sh" >&2
        exit 1
        ;;
esac

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/get-app-name.sh"

if [ -z "$APP_NAME" ]; then
    APP_NAME=$(get_app_name) || exit 1
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

DEPLOYMENT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
INVENTORY="${DEPLOYMENT_DIR}/inventories/hosts.yml"
VAULT_FILE="${DEPLOYMENT_DIR}/group_vars/vault.yml"
VAULT_FLAGS="--vault-password-file ~/.vault_pass"

usage() {
    cat << EOF
${BLUE}Application Deployment Helper${NC}

Usage: $0 <command> [options]

Commands:
  setup           Deploy the application to the server (one-time initial setup)
  update          Pull latest code and restart (most common — run after git push)
  logs            Tail application logs on the server
  status          Check supervisor process status
  rollback        Roll back to a specific git commit hash

Examples:
  $0 setup
  $0 update
  $0 logs
  $0 status
  $0 rollback abc1234

For full step-by-step instructions, see:
  deployment/docs/guides/MANUAL_DEPLOYMENT.md
  deployment/docs/guides/UPDATING_APPLICATION.md

${YELLOW}Prerequisites:${NC}
  ~/.vault_pass must exist  (echo 'password' > ~/.vault_pass && chmod 600 ~/.vault_pass)
  inventories/hosts.yml must have the correct ansible_host
  Code must be pushed to git before running update/rollback

EOF
    exit 1
}

print_section() {
    echo ""
    echo -e "${BLUE}▶${NC} $1"
    echo ""
}

success() { echo -e "${GREEN}✓${NC} $1"; }
error()   { echo -e "${RED}✗${NC} $1"; exit 1; }
warning() { echo -e "${YELLOW}⚠${NC} $1"; }

check_prerequisites() {
    print_section "Checking prerequisites..."

    command -v ansible-playbook &> /dev/null || error "Ansible not installed. Run: pip install ansible"
    success "Ansible found"

    [[ -f "$INVENTORY" ]] || error "Inventory not found: $INVENTORY"
    success "Inventory found"

    [[ -f "$VAULT_FILE" ]] || error "Vault not found: $VAULT_FILE"
    success "Vault found"

    [[ -f "$HOME/.vault_pass" ]] || error "~/.vault_pass not found. See Chapter 1: Prerequisites."
    success "Vault password file found"

    git rev-parse --git-dir > /dev/null 2>&1 || error "Not in a git repository. Run from the project root."
    success "In git repository"
}

cmd_setup() {
    print_section "Deploying application to server (initial setup)..."
    warning "Run provision-app.yml first if AWS resources are not yet created."
    echo ""
    read -p "Continue with server setup? (type 'yes' to confirm): " confirm
    [[ "$confirm" == "yes" ]] || { echo "Cancelled."; exit 0; }

    check_prerequisites

    ansible-playbook -i "$INVENTORY" \
        "${DEPLOYMENT_DIR}/playbooks/setup.yml" \
        $VAULT_FLAGS

    success "Setup complete!"
    echo ""
    echo "  Check status:  $0 status"
    echo "  View logs:     $0 logs"
}

cmd_update() {
    print_section "Pulling latest code and restarting ${APP_NAME}..."

    check_prerequisites

    if git status --porcelain | grep -q .; then
        warning "You have uncommitted changes. Commit and push first:"
        echo "  git add . && git commit -m 'message' && git push origin main"
        exit 1
    fi

    if [[ $(git rev-parse HEAD) != $(git ls-remote origin main 2>/dev/null | awk '{print $1}') ]]; then
        warning "Local HEAD is not pushed. Run: git push origin main"
        exit 1
    fi

    ansible-playbook -i "$INVENTORY" \
        "${DEPLOYMENT_DIR}/playbooks/update.yml" \
        $VAULT_FLAGS

    success "Update complete!"
    echo ""
    echo "  Check status:  $0 status"
    echo "  View logs:     $0 logs"
}

cmd_logs() {
    print_section "Tailing logs for ${APP_NAME}..."

    check_prerequisites

    ansible -i "$INVENTORY" all \
        -m shell \
        -a "tail -30 /var/log/apps/${APP_NAME}/app.log 2>/dev/null || echo 'No logs yet — app may still be starting'" \
        --become \
        $VAULT_FLAGS

    echo ""
    echo "For live logs, SSH to server and run:"
    echo "  sudo tail -f /var/log/apps/${APP_NAME}/app.log"
}

cmd_status() {
    print_section "Checking supervisor status for ${APP_NAME}..."

    check_prerequisites

    ansible -i "$INVENTORY" all \
        -m shell \
        -a "supervisorctl status ${APP_NAME}" \
        --become \
        $VAULT_FLAGS

    echo ""
    echo "To SSH and check manually:"
    echo "  ssh ubuntu@<server_host>"
    echo "  sudo supervisorctl status ${APP_NAME}"
}

cmd_rollback() {
    [[ -z "$1" ]] && error "Rollback requires a commit hash. Usage: $0 rollback <commit-hash>"

    COMMIT_HASH="$1"
    print_section "Rolling back ${APP_NAME} to commit: ${COMMIT_HASH}"
    warning "This will check out that commit and restart the application."
    echo ""
    read -p "Continue? (type 'yes' to confirm): " confirm
    [[ "$confirm" == "yes" ]] || { echo "Cancelled."; exit 0; }

    check_prerequisites

    # Check out the specific commit on the server
    ansible -i "$INVENTORY" all \
        -m shell \
        -a "cd /opt/${APP_NAME} && git checkout ${COMMIT_HASH}" \
        --become \
        $VAULT_FLAGS

    # Restart via supervisor (not systemd — this project uses supervisor)
    ansible -i "$INVENTORY" all \
        -m shell \
        -a "supervisorctl restart ${APP_NAME}" \
        --become \
        $VAULT_FLAGS

    success "Rolled back to: ${COMMIT_HASH}"
    echo ""
    echo "  Verify with:  $0 status"
    echo "  View logs:    $0 logs"
    echo ""
    echo "  To return to the latest code: $0 update"
}

# Main dispatcher
[[ $# -eq 0 ]] && usage

COMMAND="$1"
shift

case "$COMMAND" in
    setup)    cmd_setup ;;
    update)   cmd_update ;;
    logs)     cmd_logs ;;
    status)   cmd_status ;;
    rollback) cmd_rollback "$@" ;;
    *)        usage ;;
esac

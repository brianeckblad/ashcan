#!/bin/bash
# Configure git user email based on app name
# Supported shells: bash, zsh
# Reusable for any project - automatically sets email to app_name@brianeckblad.dev
#
# Usage:
#   ./scripts/configure-git.sh                    # Auto-detect from vault.yml
#   ./scripts/configure-git.sh myapp              # Set for specific app name
#   ./scripts/configure-git.sh --global myapp     # Set globally for all repos

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
        echo "⚠️  WARNING: Unsupported shell detected!" >&2
        echo "   Current shell: $current_shell" >&2
        echo "   Supported shells: bash, zsh" >&2
        echo "" >&2
        echo "   Please run with: bash ./deployment/scripts/configure-git.sh" >&2
        exit 1
        ;;
esac

# Configuration - personalize this section for your identity
GIT_USER_NAME="Brian Eckblad"
EMAIL_DOMAIN="brianeckblad.dev"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_DIR="$(dirname "$SCRIPT_DIR")"
GROUP_VARS_DIR="$DEPLOYMENT_DIR/group_vars"

# Parse arguments
GLOBAL_CONFIG=false
APP_NAME=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --global|-g)
            GLOBAL_CONFIG=true
            shift
            ;;
        --local|-l)
            GLOBAL_CONFIG=false
            shift
            ;;
        *)
            APP_NAME="$1"
            shift
            ;;
    esac
done

# If app name not provided, try to read from vault config
if [ -z "$APP_NAME" ]; then
    if [ -f "$GROUP_VARS_DIR/vault.yml" ]; then
        # Check if vault is encrypted
        if head -1 "$GROUP_VARS_DIR/vault.yml" 2>/dev/null | grep -q "ANSIBLE_VAULT"; then
            # Try decrypting with vault password file
            if [ -f "$HOME/.vault_pass" ]; then
                APP_NAME=$(ansible-vault view "$GROUP_VARS_DIR/vault.yml" --vault-password-file "$HOME/.vault_pass" 2>/dev/null | grep "^app_name:" | awk '{print $2}' | tr -d '"' | tr -d ' ')
            fi
        else
            APP_NAME=$(grep "^app_name:" "$GROUP_VARS_DIR/vault.yml" | awk '{print $2}' | tr -d '"' | tr -d ' ')
        fi
    fi

    if [ -z "$APP_NAME" ]; then
        echo "❌ Error: Could not determine app name"
        echo ""
        echo "Usage:"
        echo "  $0                          # Auto-detect from vault.yml"
        echo "  $0 myapp                    # Set for myapp (myapp@brianeckblad.dev)"
        echo "  $0 --global myapp           # Set globally for all repositories"
        echo ""
        exit 1
    fi
fi

# Construct email
GIT_EMAIL="${APP_NAME}@${EMAIL_DOMAIN}"

echo "=================================================="
echo "Git Configuration Setup"
echo "=================================================="
echo ""
echo "📝 Configuration:"
echo "   Name: $GIT_USER_NAME"
echo "   Email: $GIT_EMAIL"
echo "   Scope: $([ "$GLOBAL_CONFIG" = true ] && echo 'Global' || echo 'Local (this repo)')"
echo ""

if [ "$GLOBAL_CONFIG" = true ]; then
    # Global configuration
    echo "Setting git config globally..."
    git config --global user.name "$GIT_USER_NAME"
    git config --global user.email "$GIT_EMAIL"

    echo ""
    echo "✅ Global git config set"
    echo ""
    echo "Your commits will now use:"
    echo "   Author: $(git config --global user.name) <$(git config --global user.email)>"
else
    # Local (per-repository) configuration
    # Must be run from repository root
    REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "")

    if [ -z "$REPO_ROOT" ]; then
        echo "❌ Error: Not in a git repository"
        echo "   Change to repository root and try again"
        exit 1
    fi

    echo "Setting git config for this repository..."

    cd "$REPO_ROOT"
    git config user.name "$GIT_USER_NAME"
    git config user.email "$GIT_EMAIL"

    echo ""
    echo "✅ Local git config set (.git/config)"
    echo ""
    echo "Your commits will now use:"
    echo "   Author: $(git config user.name) <$(git config user.email)>"
fi

echo ""
echo "=================================================="
echo "✅ Git configuration complete!"
echo "=================================================="
echo ""
echo "View your settings:"
if [ "$GLOBAL_CONFIG" = true ]; then
    echo "   git config --global user.name"
    echo "   git config --global user.email"
else
    echo "   git config user.name"
    echo "   git config user.email"
fi
echo ""
echo "To change later:"
echo "   git config user.email \"newaddress@example.com\""
echo ""

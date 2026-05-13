#!/bin/bash
#
# Get App Name from Configuration
# Supported shells: bash, zsh
# This script reads app_name from group_vars/vault.yml
# Used by other scripts to ensure consistency
#

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
        return 1 2>/dev/null || exit 1
        ;;
esac

# Find the deployment directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VAULT_FILE="$DEPLOYMENT_DIR/group_vars/vault.yml"

# Function to extract app_name from vault config
get_app_name() {
    if [ -f "$VAULT_FILE" ]; then
        # Check if vault is encrypted
        if head -1 "$VAULT_FILE" 2>/dev/null | grep -q "ANSIBLE_VAULT"; then
            # Decrypt and extract
            if [ -f "$HOME/.vault_pass" ]; then
                APP_NAME=$(ansible-vault view "$VAULT_FILE" --vault-password-file "$HOME/.vault_pass" 2>/dev/null | grep -E "^app_name:" | head -1 | sed 's/^app_name:[[:space:]]*//' | sed 's/#.*//' | sed 's/[[:space:]]*$//' | tr -d '"' | tr -d "'")
            else
                echo "ERROR: Vault is encrypted and ~/.vault_pass not found" >&2
                return 1
            fi
        else
            APP_NAME=$(grep -E "^app_name:" "$VAULT_FILE" | head -1 | sed 's/^app_name:[[:space:]]*//' | sed 's/#.*//' | sed 's/[[:space:]]*$//' | tr -d '"' | tr -d "'")
        fi

        # Validate we got something
        if [ -n "$APP_NAME" ] && [ "$APP_NAME" != "CHANGEME" ]; then
            echo "$APP_NAME"
            return 0
        else
            echo "ERROR: app_name not set in $VAULT_FILE (currently: $APP_NAME)" >&2
            echo "Edit vault.yml and set app_name to your application name" >&2
            return 1
        fi
    else
        echo "ERROR: Config file not found: $VAULT_FILE" >&2
        return 1
    fi
}

# If script is sourced, just define the function
# If script is executed directly, call the function
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    get_app_name
fi


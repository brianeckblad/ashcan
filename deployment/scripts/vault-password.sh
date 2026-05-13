#!/bin/bash
# Vault password script for Ansible
# Supported shells: bash, zsh
# Reads password from ~/.vault_pass file
# If file doesn't exist, prompts user to enter password
# This allows ansible.cfg to reference it without tilde expansion issues

# Shell compatibility check
# Get shell from ps output and extract basename (handles /bin/bash)
current_shell=$(ps -p $$ -o comm= 2>/dev/null)
current_shell=$(basename "$current_shell" 2>/dev/null)
current_shell=$(echo "$current_shell" | tr -d '-')  # Remove leading dash

# Fallback to SHELL env var if ps failed
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
        echo "   Please run with: bash ./deployment/scripts/vault-password.sh" >&2
        exit 1
        ;;
esac

VAULT_PASS_FILE="$HOME/.vault_pass"

if [ -f "$VAULT_PASS_FILE" ]; then
    # File exists - read password from it
    cat "$VAULT_PASS_FILE"
else
    # File doesn't exist - prompt user for password
    # Use /dev/tty to ensure we can read from terminal even if stdin is redirected
    read -s -p "Vault password: " VAULT_PASSWORD < /dev/tty
    echo "$VAULT_PASSWORD"
fi



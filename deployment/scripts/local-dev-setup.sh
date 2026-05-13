#!/bin/bash
# Setup local development configuration
# Handles both new setup and merging with existing configurations
# Supported shells: bash, zsh
#
# Usage:
#   ./scripts/local-dev-setup.sh              # Interactive mode (detect existing files)
#   ./scripts/local-dev-setup.sh -new         # Create fresh from templates
#   ./scripts/local-dev-setup.sh -merge       # Merge existing values with new templates
#   ./scripts/local-dev-setup.sh --no-backup  # Skip backup creation

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
        echo "   Please run with: bash ./scripts/local-dev-setup.sh" >&2
        exit 1
        ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_DIR="$(dirname "$SCRIPT_DIR")"
GROUP_VARS_DIR="$DEPLOYMENT_DIR/group_vars"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
MODE="auto"  # auto, new, or merge
NO_BACKUP=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -new|--new)
            MODE="new"
            shift
            ;;
        -merge|--merge)
            MODE="merge"
            shift
            ;;
        --no-backup)
            NO_BACKUP=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo ""
            echo "Usage:"
            echo "  $0              # Auto-detect (interactive)"
            echo "  $0 -new         # Create fresh from templates"
            echo "  $0 -merge       # Merge existing values with templates"
            echo "  $0 --no-backup  # Skip backup creation"
            exit 1
            ;;
    esac
done

echo "=================================================="
echo "Configuration Setup"
echo "=================================================="
echo ""

# Check if templates exist
if [ ! -f "$GROUP_VARS_DIR/all.yml.example" ]; then
    echo "❌ Error: all.yml.example not found"
    exit 1
fi

if [ ! -f "$GROUP_VARS_DIR/vault.yml.example" ]; then
    echo "❌ Error: vault.yml.example not found"
    exit 1
fi

# Auto-detect mode if not specified
if [ "$MODE" = "auto" ]; then
    HAS_ALL_YML=false
    HAS_VAULT_YML=false

    if [ -f "$GROUP_VARS_DIR/all.yml" ]; then
        HAS_ALL_YML=true
    fi

    if [ -f "$GROUP_VARS_DIR/vault.yml" ]; then
        HAS_VAULT_YML=true
    fi

    if [ "$HAS_ALL_YML" = true ] || [ "$HAS_VAULT_YML" = true ]; then
        echo "📋 Detected existing configuration files"
        echo ""
        echo "Choose an option:"
        echo "  1. Create fresh from templates (overwrites existing)"
        echo "  2. Merge existing values with new templates (preserves values)"
        echo ""
        read -p "Enter 1 or 2 [default: 2]: " -r CHOICE
        CHOICE=${CHOICE:-2}

        if [ "$CHOICE" = "1" ]; then
            MODE="new"
        else
            MODE="merge"
        fi
    else
        MODE="new"
    fi
fi

# Convert MODE to uppercase for display (compatible with all shells)
MODE_DISPLAY=$(echo "$MODE" | tr '[:lower:]' '[:upper:]')
echo "Mode: ${BLUE}${MODE_DISPLAY}${NC}"
echo ""

# ============================================================================
# NEW MODE - Create fresh from templates
# ============================================================================

if [ "$MODE" = "new" ]; then
    echo "📝 Creating fresh configuration files from templates..."
    echo ""

    cp "$GROUP_VARS_DIR/all.yml.example" "$GROUP_VARS_DIR/all.yml"
    echo "✅ Created: group_vars/all.yml"

    cp "$GROUP_VARS_DIR/vault.yml.example" "$GROUP_VARS_DIR/vault.yml"
    echo "✅ Created: group_vars/vault.yml (unencrypted, ready to edit)"

    if [ ! -f "$SCRIPT_DIR/../inventories/hosts.yml" ]; then
        cp "$SCRIPT_DIR/../inventories/hosts.yml.example" "$SCRIPT_DIR/../inventories/hosts.yml"
        echo "✅ Created: inventories/hosts.yml (auto-updated on deploy)"
    fi

    # Fresh environment — remove stale instance info
    if [ -f "$DEPLOYMENT_DIR/instance-info.txt" ]; then
        rm -f "$DEPLOYMENT_DIR/instance-info.txt"
        echo "✅ Removed: instance-info.txt (will be created on next launch)"
    fi

    echo ""
    echo "=================================================="
    echo "✅ New Configuration Files Created!"
    echo "=================================================="
    echo ""
    echo "Next steps:"
    echo "  1. Edit your configuration:"
    echo "     nano group_vars/vault.yml"
    echo ""
    echo "  2. Create vault password (optional but recommended):"
    echo "     echo 'your-password' > ~/.vault_pass"
    echo "     chmod 600 ~/.vault_pass"
    echo ""
    echo "  3. Encrypt the vault:"
    echo "     ansible-vault encrypt group_vars/vault.yml --vault-password-file ~/.vault_pass --encrypt-vault-id default"
    echo ""
    echo "  4. Configure git:"
    echo "     ./scripts/configure-git.sh"
    echo ""
    echo "  5. Deploy!"
    echo "     ./scripts/infra-complete-setup.sh"
    echo ""
    exit 0
fi

# ============================================================================
# MERGE MODE - Merge existing values with new templates
# ============================================================================

if [ "$MODE" = "merge" ]; then
    echo "📋 Checking for existing configuration files..."
    echo ""

    HAS_ALL_YML=false
    HAS_VAULT_YML=false

    if [ -f "$GROUP_VARS_DIR/all.yml" ]; then
        echo "✅ Found: all.yml (will merge values)"
        HAS_ALL_YML=true
    fi

    if [ -f "$GROUP_VARS_DIR/vault.yml" ]; then
        echo "✅ Found: vault.yml (will merge values)"
        HAS_VAULT_YML=true
    fi

    echo ""

    if [ "$HAS_ALL_YML" = false ] && [ "$HAS_VAULT_YML" = false ]; then
        echo "ℹ️  No existing files found. Creating from templates..."
        cp "$GROUP_VARS_DIR/all.yml.example" "$GROUP_VARS_DIR/all.yml"
        echo "✅ Created: all.yml"

        cp "$GROUP_VARS_DIR/vault.yml.example" "$GROUP_VARS_DIR/vault.yml"
        echo "✅ Created: vault.yml (unencrypted, ready to edit)"

        if [ ! -f "$SCRIPT_DIR/../inventories/hosts.yml" ]; then
            cp "$SCRIPT_DIR/../inventories/hosts.yml.example" "$SCRIPT_DIR/../inventories/hosts.yml"
            echo "✅ Created: inventories/hosts.yml (auto-updated on deploy)"
        fi

        echo ""
        echo "=================================================="
        echo "✅ Configuration Files Created!"
        echo "=================================================="
        exit 0
    fi

    # Create backups if files exist
    if [ "$NO_BACKUP" = false ]; then
        echo "📦 Creating backups..."

        if [ "$HAS_ALL_YML" = true ]; then
            BACKUP_FILE="$GROUP_VARS_DIR/all.yml.backup.$(date +%s)"
            cp "$GROUP_VARS_DIR/all.yml" "$BACKUP_FILE"
            echo "  ✅ Backed up: all.yml → $(basename "$BACKUP_FILE")"
        fi

        if [ "$HAS_VAULT_YML" = true ]; then
            # Decrypt vault if encrypted
            if head -1 "$GROUP_VARS_DIR/vault.yml" | grep -q "ANSIBLE_VAULT"; then
                echo "  🔓 Decrypting vault.yml..."
                VAULT_PASS_FILE="$HOME/.vault_pass"

                if [ ! -f "$VAULT_PASS_FILE" ]; then
                    # File doesn't exist - prompt for password
                    echo "     Vault password file not found. Please enter your vault password:"
                    read -s -p "     Vault password: " VAULT_PASSWORD < /dev/tty
                    echo ""
                    # Create temp file with password for ansible-vault
                    TEMP_PASS=$(mktemp)
                    echo "$VAULT_PASSWORD" > "$TEMP_PASS"
                    VAULT_PASS_FILE="$TEMP_PASS"
                    TEMP_PASS_CREATED=true
                fi

                DECRYPTED_BACKUP="$GROUP_VARS_DIR/vault.yml.decrypted.$(date +%s)"
                ansible-vault decrypt "$GROUP_VARS_DIR/vault.yml" --vault-password-file "$VAULT_PASS_FILE" --output "$DECRYPTED_BACKUP" 2>/dev/null
                BACKUP_FILE="$DECRYPTED_BACKUP"

                # Clean up temp password file if we created one
                if [ "$TEMP_PASS_CREATED" = true ]; then
                    rm -f "$TEMP_PASS"
                fi
            else
                BACKUP_FILE="$GROUP_VARS_DIR/vault.yml.backup.$(date +%s)"
                cp "$GROUP_VARS_DIR/vault.yml" "$BACKUP_FILE"
            fi
            echo "  ✅ Backed up: vault.yml → $(basename "$BACKUP_FILE")"
        fi

        echo ""
    fi

    # Merge all.yml
    if [ "$HAS_ALL_YML" = true ]; then
        echo "🔄 Merging all.yml..."

        # Use Python helper for reliable YAML merging
        python3 "$SCRIPT_DIR/merge_yaml.py" \
            "$GROUP_VARS_DIR/all.yml.example" \
            "$GROUP_VARS_DIR/all.yml" \
            "$GROUP_VARS_DIR/all.yml.merged"

        mv "$GROUP_VARS_DIR/all.yml.merged" "$GROUP_VARS_DIR/all.yml"
        echo "  ✅ Merged existing values into all.yml"
    else
        cp "$GROUP_VARS_DIR/all.yml.example" "$GROUP_VARS_DIR/all.yml"
        echo "  ✅ Created all.yml from template"
    fi

    # Merge vault.yml
    if [ "$HAS_VAULT_YML" = true ]; then
        echo "🔄 Merging vault.yml..."

        # If vault is encrypted, decrypt it first
        OLD_VAULT_FILE="$GROUP_VARS_DIR/vault.yml"
        TEMP_VAULT=""
        VAULT_WAS_ENCRYPTED=false

        if head -1 "$OLD_VAULT_FILE" 2>/dev/null | grep -q "ANSIBLE_VAULT"; then
            VAULT_WAS_ENCRYPTED=true
            echo "  🔓 Decrypting existing vault.yml..."
            VAULT_PASS_FILE="$HOME/.vault_pass"
            if [ ! -f "$VAULT_PASS_FILE" ]; then
                echo "     Vault password file not found. Please enter your vault password:"
                read -s -p "     Vault password: " VAULT_PASSWORD < /dev/tty
                echo ""
                # Create temp file with password for ansible-vault
                TEMP_PASS=$(mktemp)
                echo "$VAULT_PASSWORD" > "$TEMP_PASS"
                VAULT_PASS_FILE="$TEMP_PASS"
                TEMP_PASS_CREATED=true
            fi

            # Create temp decrypted file
            TEMP_VAULT=$(mktemp)
            ansible-vault decrypt "$OLD_VAULT_FILE" --vault-password-file "$VAULT_PASS_FILE" --output "$TEMP_VAULT" 2>/dev/null || true
            OLD_VAULT_FILE="$TEMP_VAULT"

            # Clean up temp password file if we created one
            if [ "$TEMP_PASS_CREATED" = true ]; then
                rm -f "$TEMP_PASS"
            fi
        fi

        # Use Python helper for reliable YAML merging
        python3 "$SCRIPT_DIR/merge_yaml.py" \
            "$GROUP_VARS_DIR/vault.yml.example" \
            "$OLD_VAULT_FILE" \
            "$GROUP_VARS_DIR/vault.yml.merged"

        mv "$GROUP_VARS_DIR/vault.yml.merged" "$GROUP_VARS_DIR/vault.yml"

        # Clean up temp file if we created one
        if [ -n "$TEMP_VAULT" ] && [ -f "$TEMP_VAULT" ]; then
            rm -f "$TEMP_VAULT"
        fi

        echo "  ✅ Merged existing values into vault.yml"
        echo "  ✅ Vault is unencrypted (ready to edit)"
    else
        cp "$GROUP_VARS_DIR/vault.yml.example" "$GROUP_VARS_DIR/vault.yml"
        echo "  ✅ Created vault.yml from template (unencrypted)"
    fi

    echo ""
    echo "=================================================="
    echo "✅ Configuration Merge Complete!"
    echo "=================================================="

    # Check for stale instance-info.txt
    if [ -f "$DEPLOYMENT_DIR/instance-info.txt" ]; then
        echo ""
        echo -e "${YELLOW}ℹ️  Found instance-info.txt from a previous deployment.${NC}"
        read -p "Delete it? (y = fresh start, n = keep current instance) [y/N]: " -r DELETE_INFO < /dev/tty
        if [[ "$DELETE_INFO" =~ ^[Yy]$ ]]; then
            rm -f "$DEPLOYMENT_DIR/instance-info.txt"
            echo "✅ Removed: instance-info.txt"
        else
            echo "  Kept: instance-info.txt"
        fi
    fi
    echo ""
    echo "Your existing values have been merged into the new templates."
    echo "Only NEW values (from template updates) need to be configured."
    echo ""
    echo "Next steps:"
    echo "  1. Review the merged vault file:"
    echo "     nano group_vars/vault.yml"
    echo ""
    echo "  2. Add any NEW configuration values from the template"
    echo "     (Look for comments marked as NEW or changed)"
    echo ""
    echo "  3. When ready, encrypt the vault:"
    echo "     ansible-vault encrypt group_vars/vault.yml --vault-password-file ~/.vault_pass --encrypt-vault-id default"
    echo ""
    echo "  4. Configure git (if needed):"
    echo "     ./scripts/configure-git.sh"
    echo ""
    echo "  5. Deploy:"
    echo "     ./scripts/infra-complete-setup.sh"
    echo ""
    exit 0
fi

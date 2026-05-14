#!/bin/bash
# Load Ansible variables from YAML files for CLI usage
# This script reads group_vars and EXPORTS them as shell variables
#
# Supported shells: bash, zsh
#
# ⚠️  IMPORTANT: You MUST source this script, don't run it directly!
# Usage: source scripts/load-vars.sh
# NOT: ./scripts/load-vars.sh
#
# After sourcing, variables are available:
#   echo $app_name
#   aws s3 ls | grep $app_name

# Shell compatibility check
{
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
            echo "   Please run with: bash -c 'source scripts/load-vars.sh'" >&2
            return 1 2>/dev/null || exit 1
            ;;
    esac
}

# Check if being sourced or executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "⚠️  ERROR: You must SOURCE this script, don't run it directly!"
    echo ""
    echo "❌ WRONG: ./scripts/load-vars.sh"
    echo "✅ CORRECT: source scripts/load-vars.sh"
    echo ""
    echo "Usage:"
    echo "  cd deployment"
    echo "  source scripts/load-vars.sh"
    echo ""
    echo "Then variables will be available:"
    echo "  echo \$app_name"
    echo "  aws s3 ls | grep \$app_name"
    exit 1
fi

# Script directory and path resolution
# Handle both: sourced from deployment/ and sourced from other locations
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_DIR="$(dirname "$SCRIPT_DIR")"

# Verify we're in the right place (DEPLOYMENT_DIR should end with /deployment)
if [[ ! "$DEPLOYMENT_DIR" =~ deployment$ ]]; then
    # If not, we're probably being sourced from deployment directory
    # Try one level up
    if [ -d "group_vars" ]; then
        # group_vars exists in current directory, so current dir IS deployment
        DEPLOYMENT_DIR="$(pwd)"
    else
        # Try assuming we're at deployment level
        DEPLOYMENT_DIR="$(pwd)"
    fi
fi

GROUP_VARS_DIR="$DEPLOYMENT_DIR/group_vars"

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check if vault.yml exists (single source of truth for all configuration)
if [ ! -f "$GROUP_VARS_DIR/vault.yml" ]; then
    echo -e "${RED}❌ Configuration file not found: $GROUP_VARS_DIR/vault.yml${NC}"
    echo ""
    echo "You need to create it from the template. Run:"
    echo "  ./scripts/local-dev-setup.sh"
    echo ""
    echo "This will create vault.yml from vault.yml.example"
    echo ""
    return 1 2>/dev/null || exit 1
fi

# Function to safely parse simple YAML key-value pairs
parse_yaml_simple() {
    local file=$1
    local export_count=0
    local line_count=0

    # Read file line by line without subshell (works in bash AND zsh)
    while IFS= read -r line || [[ -n "$line" ]]; do
        line_count=$((line_count+1))

        # Skip empty lines and comments
        [[ -z "$line" ]] && continue
        [[ "$line" =~ ^[[:space:]]*# ]] && continue

        # Extract lines with key: value format (simple values only)
        if [[ "$line" =~ ^([a-z0-9_]+):[[:space:]]*(.+)$ ]]; then
            # Handle both bash (BASH_REMATCH) and zsh (match) regex arrays
            if [[ -n "${BASH_REMATCH[1]}" ]]; then
                local key="${BASH_REMATCH[1]}"
                local value="${BASH_REMATCH[2]}"
            elif [[ -n "${match[1]}" ]]; then
                local key="${match[1]}"
                local value="${match[2]}"
            else
                continue
            fi

            # Skip complex values (Jinja2, lists, dicts)
            if [[ "$value" == *"{{"* ]] || [[ "$value" == *"}}"* ]] || \
               [[ "$value" == "["* ]] || [[ "$value" == "{"* ]]; then
                continue
            fi

            # Remove inline comments
            value="${value%% #*}"

            # Remove quotes (double and single)
            value="${value//\"/}"
            value="${value//\'/}"

            # Simple trim using sed
            value=$(echo "$value" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')

            # Skip empty values
            [[ -z "$value" ]] && continue

            # Export the variable
            export "$key"="$value"
            export_count=$((export_count+1))
        fi
    done < "$file"
}

# Check vault status and load vault variables
vault_encrypted=false
vault_loaded=false
if [ -f "$GROUP_VARS_DIR/vault.yml" ]; then
    if head -1 "$GROUP_VARS_DIR/vault.yml" 2>/dev/null | grep -q "ANSIBLE_VAULT"; then
        vault_encrypted=true
        # Decrypt vault to load variables
        vault_content=""
        if [ -f "$HOME/.vault_pass" ]; then
            vault_content=$(ansible-vault view "$GROUP_VARS_DIR/vault.yml" \
                --vault-password-file "$HOME/.vault_pass" 2>/dev/null)
        else
            echo -e "${YELLOW}ℹ️  ~/.vault_pass not found — enter vault password to load secrets${NC}"
            vault_content=$(ansible-vault view "$GROUP_VARS_DIR/vault.yml" \
                --ask-vault-pass 2>/dev/null)
        fi
        if [ -n "$vault_content" ]; then
            # Parse decrypted content line by line (same logic as parse_yaml_simple)
            while IFS= read -r line || [[ -n "$line" ]]; do
                [[ -z "$line" ]] && continue
                [[ "$line" =~ ^[[:space:]]*# ]] && continue
                if [[ "$line" =~ ^([a-z0-9_]+):[[:space:]]*(.+)$ ]]; then
                    if [[ -n "${BASH_REMATCH[1]}" ]]; then
                        key="${BASH_REMATCH[1]}"
                        value="${BASH_REMATCH[2]}"
                    elif [[ -n "${match[1]}" ]]; then
                        key="${match[1]}"
                        value="${match[2]}"
                    else
                        continue
                    fi
                    [[ "$value" == *"{{"* ]] && continue
                    value="${value%% #*}"
                    value="${value//\"/}"
                    value="${value//\'/}"
                    value=$(echo "$value" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
                    # Export even empty values (overrides inherited env vars)
                    export "$key"="$value"
                fi
            done <<< "$vault_content"
            vault_loaded=true
        else
            echo -e "${RED}⚠️  Could not decrypt vault.yml — vault variables not loaded${NC}"
        fi
    else
        # Load vault variables if not encrypted
        parse_yaml_simple "$GROUP_VARS_DIR/vault.yml"
        vault_loaded=true
    fi
fi

# all.yml is an empty stub — all config is in vault.yml
# Parse it anyway for backwards compatibility (no-op on an empty file)
if [ -f "$GROUP_VARS_DIR/all.yml" ]; then
    parse_yaml_simple "$GROUP_VARS_DIR/all.yml"
fi

# =========================================================================
# Second pass: resolve Jinja2 templates ({{ var }}) using loaded variables
# =========================================================================
# vault.yml stores derived fields as Jinja2 templates, e.g.:
#   app_deploy_user: "{{ app_name }}-deployer"
# The first pass skips these lines. This pass resolves them now that base
# variables (app_name, etc.) are exported, so stale env vars from a previous
# project's load-vars.sh session are overwritten with the correct values.
# =========================================================================
_resolve_jinja2_string() {
    python3 -c "
import re, os, sys
val = sys.argv[1]
def replace(m):
    varname = m.group(1).strip()
    return os.environ.get(varname, '')
print(re.sub(r'\{\{([^}]+)\}\}', replace, val))
" "$1"
}

_raw_vault_content=""
if [ "$vault_encrypted" = true ] && [ -n "${vault_content:-}" ]; then
    _raw_vault_content="$vault_content"
elif [ "$vault_encrypted" != true ] && [ -f "$GROUP_VARS_DIR/vault.yml" ]; then
    _raw_vault_content=$(cat "$GROUP_VARS_DIR/vault.yml")
fi

if [ -n "$_raw_vault_content" ]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ -z "$line" ]] && continue
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        if [[ "$line" =~ ^([a-z0-9_]+):[[:space:]]*(.+)$ ]]; then
            if [[ -n "${BASH_REMATCH[1]}" ]]; then
                _j2_key="${BASH_REMATCH[1]}"
                _j2_val="${BASH_REMATCH[2]}"
            elif [[ -n "${match[1]}" ]]; then
                _j2_key="${match[1]}"
                _j2_val="${match[2]}"
            else
                continue
            fi
            if [[ "$_j2_val" == *"{{"* ]]; then
                _j2_val="${_j2_val//\"/}"
                _j2_val="${_j2_val//\'/}"
                _j2_val=$(echo "$_j2_val" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
                _j2_resolved=$(_resolve_jinja2_string "$_j2_val")
                [[ -n "$_j2_resolved" ]] && export "$_j2_key"="$_j2_resolved"
            fi
        fi
    done <<< "$_raw_vault_content"
    unset _raw_vault_content _j2_key _j2_val _j2_resolved
fi

# =========================================================================
# Write inventories/hosts.yml from vault values
# =========================================================================
# Ansible cannot resolve vault variable templates for connection keywords
# (ansible_host, ansible_user, ansible_ssh_private_key_file) at SSH setup
# time. hosts.yml is gitignored; this script writes it from scratch using
# plain literal values so vault is always the single source of truth.
# =========================================================================
INVENTORY_FILE="$DEPLOYMENT_DIR/inventories/hosts.yml"

if [ -n "${server_host:-}" ] && [ "$server_host" != "YOUR_SERVER_IP" ] && \
   [ -n "${server_admin_user:-}" ]; then

    export SERVER_IP="$server_host"

    # Check current values to avoid unnecessary rewrites
    _cur_host=$(python3 -c "
import re
try:
    for line in open('$INVENTORY_FILE'):
        m = re.search(r'ansible_host:\s*(\S+)', line)
        if m: print(m.group(1)); break
except: pass
" 2>/dev/null)
    _cur_user=$(python3 -c "
import re
try:
    for line in open('$INVENTORY_FILE'):
        m = re.search(r'ansible_user:\s*(\S+)', line)
        if m: print(m.group(1)); break
except: pass
" 2>/dev/null)

    if [ "$_cur_host" != "$server_host" ] || \
       [ "$_cur_user" != "$server_admin_user" ]; then

        python3 << PYEOF
content = """\
# ===========================================================================
# Server Inventory  — LOCAL FILE, NOT COMMITTED (gitignored)
# ===========================================================================
# DO NOT add Jinja2 templates here. Ansible resolves connection keywords
# before vault variables are available, so any {{ var }} reference fails.
# All values are plain literals written from vault.yml by load-vars.sh.
# To regenerate:  source scripts/load-vars.sh
# ===========================================================================

all:
  children:
    app_servers:
      children:
        production:
          hosts:
            server:
              ansible_host: ${server_host}
              ansible_connection: ssh
              ansible_user: ${server_admin_user}

  vars:
    ansible_python_interpreter: /usr/bin/python3
"""
open("$INVENTORY_FILE", "w").write(content)
PYEOF
        echo -e "${YELLOW}ℹ️  Wrote inventories/hosts.yml from vault (host=$server_host user=$server_admin_user)${NC}"
    fi
fi

# ---- Display results ----

echo ""
echo -e "${GREEN}✅ Variables loaded${NC}"
echo ""
echo -e "  ${YELLOW}Identity${NC}"
echo "    app_name=$app_name"
echo "    app_display_name=${app_display_name:-}"
echo "    service_name=${service_name:-${app_name}}"
echo ""
echo -e "  ${YELLOW}Server${NC}"
echo "    server_host=${server_host:-  (not set — update in vault.yml)}"
echo "    server_name=${server_name:-}"
echo "    server_admin_user=${server_admin_user:-ubuntu}"
echo "    app_deploy_user=${app_deploy_user:-${app_name}-deployer}"
echo "    app_runtime_user=${app_runtime_user:-${app_name}_runtime}"
if [ -n "${SERVER_IP:-}" ]; then
    echo "    SERVER_IP=$SERVER_IP"
fi
echo ""
echo -e "  ${YELLOW}Paths${NC}"
echo "    app_dir=${app_dir:-/opt/apps/${app_name}}"
echo "    log_dir=${log_dir:-/var/log/apps/${app_name}}"
echo "    logs_root=${logs_root:-/var/log/apps}"
echo ""
echo -e "  ${YELLOW}AWS${NC}"
echo "    aws_region=$aws_region"
echo "    s3_bucket_name=${s3_bucket_name:-}"
echo "    secret_name=${secret_name:-${app_name}/production}"
echo "    aws_profile=${app_name}-deploy"
echo ""
echo -e "  ${YELLOW}SSL / Domain${NC}"
echo "    ssl_email=${ssl_email:-}"
echo ""

# Show vault status only if there is a problem
if [ "$vault_encrypted" = true ] && [ "$vault_loaded" != true ]; then
    echo -e "${YELLOW}⚠️  vault.yml is encrypted but could not be decrypted${NC}"
    echo "  Create ~/.vault_pass or run: source scripts/load-vars.sh (will prompt)"
elif [ "$vault_encrypted" != true ] && [ -f "$GROUP_VARS_DIR/vault.yml" ]; then
    echo -e "${YELLOW}⚠️  vault.yml is NOT encrypted${NC}"
    echo "  ansible-vault encrypt group_vars/vault.yml --vault-password-file ~/.vault_pass"
fi


#!/bin/bash
# Generate local .env file from vault.yml
#
# This script pulls secrets from vault.yml and creates a .env file
# for local development. AWS credentials are commented out by default
# (use IAM roles in production, optional for local dev).
#
# Usage:
#   python scripts/local_dev_setup_env.py
#   (or manually: bash scripts/generate-local-env.sh)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VAULT_FILE="$PROJECT_ROOT/deployment/group_vars/vault.yml"
ENV_FILE="$PROJECT_ROOT/.env"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if vault.yml exists
if [ ! -f "$VAULT_FILE" ]; then
    echo -e "${RED}❌ Error: vault.yml not found at $VAULT_FILE${NC}"
    echo ""
    echo "Please set up vault.yml first:"
    echo "  cd deployment"
    echo "  cp group_vars/vault.yml.example group_vars/vault.yml"
    echo "  nano group_vars/vault.yml"
    echo "  ansible-vault encrypt group_vars/vault.yml --vault-password-file ~/.vault_pass"
    exit 1
fi

# Check if vault is encrypted
if ! head -1 "$VAULT_FILE" | grep -q "ANSIBLE_VAULT"; then
    echo -e "${RED}❌ Error: vault.yml is not encrypted${NC}"
    echo ""
    echo "Please encrypt your vault:"
    echo "  cd deployment"
    echo "  ansible-vault encrypt group_vars/vault.yml --vault-password-file ~/.vault_pass"
    exit 1
fi

# Check if .vault_pass exists
if [ ! -f "$HOME/.vault_pass" ]; then
    echo -e "${YELLOW}⚠️  Warning: ~/.vault_pass not found${NC}"
    echo ""
    echo "The script will prompt you for the vault password"
    VAULT_PASS_OPTION="--ask-vault-pass"
else
    VAULT_PASS_OPTION="--vault-password-file $HOME/.vault_pass"
fi

# Decrypt and extract variables using ansible-vault
VAULT_CONTENT=$(ansible-vault view "$VAULT_FILE" $VAULT_PASS_OPTION 2>/dev/null)

# Function to extract value from vault
extract_var() {
    local var_name="$1"
    echo "$VAULT_CONTENT" | grep "^$var_name:" | head -1 | sed 's/^[^:]*:[[:space:]]*//' | sed 's/#.*//' | sed 's/[[:space:]]*$//' | sed 's/^"\(.*\)"$/\1/' | sed "s/^'\(.*\)'$/\1/"
}

# Create .env file
cat > "$ENV_FILE" << 'ENVEOF'
# ============================================================================
# LOCAL DEVELOPMENT .env FILE - AUTO-GENERATED
# ============================================================================
# Generated from vault.yml on $(date)
# Do NOT commit this file to git (already in .gitignore)
#
# To regenerate from vault.yml:
#   bash scripts/generate-local-env.sh
# ============================================================================

ENVEOF

# Extract and add Flask configuration
echo "" >> "$ENV_FILE"
echo "# Flask Configuration" >> "$ENV_FILE"
FLASK_SECRET=$(extract_var "secret_key")
FLASK_PORT=$(extract_var "flask_port")
FLASK_ENV=$(extract_var "flask_env")

echo "FLASK_ENV=${FLASK_ENV:-development}" >> "$ENV_FILE"
echo "SECRET_KEY=${FLASK_SECRET:-dev-secret-key}" >> "$ENV_FILE"
echo "PORT=${FLASK_PORT:-8000}" >> "$ENV_FILE"

# Extract and add user authentication
echo "" >> "$ENV_FILE"
echo "# User Authentication" >> "$ENV_FILE"
USERS=$(extract_var "users")
echo "USERS=${USERS:-admin:admin123}" >> "$ENV_FILE"

# Extract and add eBay configuration
echo "" >> "$ENV_FILE"
echo "# eBay API Configuration" >> "$ENV_FILE"
EBAY_ENV=$(extract_var "ebay_environment")
EBAY_SANDBOX_APP=$(extract_var "ebay_sandbox_app_id")
EBAY_SANDBOX_CERT=$(extract_var "ebay_sandbox_cert_id")
EBAY_SANDBOX_DEV=$(extract_var "ebay_sandbox_dev_id")
EBAY_SANDBOX_TOKEN=$(extract_var "ebay_sandbox_token")
EBAY_PROD_APP=$(extract_var "ebay_production_app_id")
EBAY_PROD_CERT=$(extract_var "ebay_production_cert_id")
EBAY_PROD_DEV=$(extract_var "ebay_production_dev_id")
EBAY_PROD_TOKEN=$(extract_var "ebay_production_token")
EBAY_VERIFY=$(extract_var "ebay_verification_token")

echo "EBAY_ENVIRONMENT=${EBAY_ENV:-sandbox}" >> "$ENV_FILE"
echo "EBAY_SANDBOX_APP_ID=${EBAY_SANDBOX_APP}" >> "$ENV_FILE"
echo "EBAY_SANDBOX_CERT_ID=${EBAY_SANDBOX_CERT}" >> "$ENV_FILE"
echo "EBAY_SANDBOX_DEV_ID=${EBAY_SANDBOX_DEV}" >> "$ENV_FILE"
echo "EBAY_SANDBOX_TOKEN=${EBAY_SANDBOX_TOKEN}" >> "$ENV_FILE"
echo "EBAY_PRODUCTION_APP_ID=${EBAY_PROD_APP}" >> "$ENV_FILE"
echo "EBAY_PRODUCTION_CERT_ID=${EBAY_PROD_CERT}" >> "$ENV_FILE"
echo "EBAY_PRODUCTION_DEV_ID=${EBAY_PROD_DEV}" >> "$ENV_FILE"
echo "EBAY_PRODUCTION_TOKEN=${EBAY_PROD_TOKEN}" >> "$ENV_FILE"
echo "EBAY_VERIFICATION_TOKEN=${EBAY_VERIFY}" >> "$ENV_FILE"


# Add commented out AWS configuration
echo "" >> "$ENV_FILE"
echo "# AWS S3 Configuration (optional for local dev, uses IAM in production)" >> "$ENV_FILE"
echo "# Uncomment and fill in if testing S3 locally" >> "$ENV_FILE"
echo "# AWS_ACCESS_KEY_ID=your_access_key_here" >> "$ENV_FILE"
echo "# AWS_SECRET_ACCESS_KEY=your_secret_key_here" >> "$ENV_FILE"
echo "# AWS_REGION=us-east-2" >> "$ENV_FILE"
echo "# S3_BUCKET=your-s3-bucket-name" >> "$ENV_FILE"

# Success message
echo -e "${GREEN}✅ .env file generated successfully!${NC}"
echo ""
echo "Created: $ENV_FILE"
echo ""
echo "Next steps:"
echo "  1. Review the .env file (check it has your values)"
echo "  2. Install dependencies: pip install -r requirements.txt"
echo "  3. Run the app: python -m app"
echo ""
echo "Note:"
echo "  - This file is in .gitignore and will not be committed"
echo "  - Regenerate anytime by running this script again"
echo "  - For production, secrets come from AWS Secrets Manager (no .env needed)"


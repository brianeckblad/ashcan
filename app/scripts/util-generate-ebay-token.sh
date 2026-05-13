#!/bin/bash
# Generate eBay Verification Token
# This token is required for marketplace account deletion endpoint validation
# Must be between 32-80 characters
#
# Production: Store in vault.yml → synced to AWS Secrets Manager during deployment
# Local dev:  Store in .env (optional, for testing the endpoint locally)

set -e

echo "======================================"
echo "eBay Verification Token Generator"
echo "======================================"
echo ""

# Generate new token (64 characters)
echo "Generating new 64-character verification token..."
echo ""
NEW_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(48)[:64])")

echo "Your eBay Verification Token:"
echo ""
echo "  $NEW_TOKEN"
echo ""
echo "======================================"
echo ""
echo "Next steps:"
echo ""
echo "  1. Add to vault.yml (for production deployment):"
echo "     ebay_verification_token: \"$NEW_TOKEN\""
echo ""
echo "  2. Paste into eBay Developer Portal:"
echo "     https://developer.ebay.com/my/keys"
echo "     - Click your app title to expand details"
echo "     - Scroll to Marketplace Account Deletion section"
echo "     - Paste the token into the Verification token field"
echo "     - Set endpoint URL: https://your-domain.com/api/ebay/marketplace-account-deletion"
echo ""
echo "  3. Deploy (syncs token to AWS Secrets Manager):"
echo "     ansible-playbook playbooks/setup-secrets-manager.yml --vault-password-file ~/.vault_pass"
echo ""
echo "For local development only:"
echo "  Add to .env: EBAY_VERIFICATION_TOKEN=$NEW_TOKEN"
echo ""
echo "This token persists across deployments. Do NOT regenerate it"
echo "after configuring in the eBay Developer Portal."
echo ""

#!/usr/bin/env python3
"""
Generate local .env file from vault.yml for development

This script decrypts vault.yml and generates a .env file for local development.
All secrets are pulled from the encrypted vault, making it safe to share
deployment configuration while keeping secrets out of git.

Usage:
    python scripts/local_dev_setup_env.py

The generated .env file is:
    - Added to .gitignore (never committed)
    - Safe for local development
    - Auto-generated from vault.yml
    - Can be regenerated anytime
"""

import os
import sys
import subprocess
import yaml
from pathlib import Path

# Colors
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
RED = '\033[0;31m'
BLUE = '\033[0;34m'
NC = '\033[0m'

def run_command(cmd, check=True):
    """Run a shell command and return output."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            check=check
        )
        return result.stdout.strip(), result.returncode
    except subprocess.CalledProcessError as e:
        return e.stderr, e.returncode

def get_vault_password_option():
    """Determine how to pass vault password to ansible-vault."""
    vault_pass_file = Path.home() / '.vault_pass'
    if vault_pass_file.exists():
        return f'--vault-password-file {vault_pass_file}'
    else:
        return '--ask-vault-pass'

def decrypt_vault(vault_file, vault_pass_option):
    """Decrypt vault.yml and return its contents."""
    cmd = f'ansible-vault view {vault_file} {vault_pass_option} 2>/dev/null'
    content, returncode = run_command(cmd, check=False)

    if returncode != 0:
        print(f"{RED}❌ Failed to decrypt vault.yml{NC}")
        print(f"Error: {content}")
        return None

    return content

def parse_vault_yaml(content):
    """Parse YAML content from vault."""
    try:
        data = yaml.safe_load(content)
        return data if data else {}
    except yaml.YAMLError as e:
        print(f"{RED}❌ Failed to parse vault.yml{NC}")
        print(f"Error: {e}")
        return None

def generate_env_file(vault_data, env_file):
    """Generate .env file from vault data."""
    lines = [
        "# ============================================================================",
        "# LOCAL DEVELOPMENT .env FILE - AUTO-GENERATED",
        "# ============================================================================",
        "# Generated from vault.yml",
        "# Do NOT commit this file to git (already in .gitignore)",
        "#",
        "# To regenerate from vault.yml:",
        "#   python scripts/local_dev_setup_env.py",
        "# ============================================================================",
        "",
    ]

    # Flask Configuration
    lines.extend([
        "",
        "# Flask Configuration",
        f"FLASK_ENV={vault_data.get('flask_env', 'development')}",
        f"SECRET_KEY={vault_data.get('secret_key', 'dev-secret-key')}",
        f"PORT={vault_data.get('flask_port', '8000')}",
    ])

    # User Authentication
    lines.extend([
        "",
        "# User Authentication",
        f"USERS={vault_data.get('users', 'admin:admin123')}",
    ])

    # eBay Configuration
    lines.extend([
        "",
        "# eBay API Configuration",
        f"EBAY_ENVIRONMENT={vault_data.get('ebay_environment', 'sandbox')}",
        f"EBAY_SANDBOX_APP_ID={vault_data.get('ebay_sandbox_app_id', '')}",
        f"EBAY_SANDBOX_CERT_ID={vault_data.get('ebay_sandbox_cert_id', '')}",
        f"EBAY_SANDBOX_DEV_ID={vault_data.get('ebay_sandbox_dev_id', '')}",
        f"EBAY_SANDBOX_TOKEN={vault_data.get('ebay_sandbox_token', '')}",
        f"EBAY_PRODUCTION_APP_ID={vault_data.get('ebay_production_app_id', '')}",
        f"EBAY_PRODUCTION_CERT_ID={vault_data.get('ebay_production_cert_id', '')}",
        f"EBAY_PRODUCTION_DEV_ID={vault_data.get('ebay_production_dev_id', '')}",
        f"EBAY_PRODUCTION_TOKEN={vault_data.get('ebay_production_token', '')}",
        f"EBAY_VERIFICATION_TOKEN={vault_data.get('ebay_verification_token', '')}",
    ])


    # AWS Configuration (commented out)
    lines.extend([
        "",
        "# AWS S3 Configuration (optional for local dev, uses IAM in production)",
        "# Uncomment and fill in if testing S3 locally",
        "# AWS_ACCESS_KEY_ID=your_access_key_here",
        "# AWS_SECRET_ACCESS_KEY=your_secret_key_here",
        "# AWS_REGION=us-east-2",
        "# S3_BUCKET=your-s3-bucket-name",
    ])

    # Write to file
    with open(env_file, 'w') as f:
        f.write('\n'.join(lines))
        f.write('\n')

def main():
    # Get project root
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    vault_file = project_root / 'deployment' / 'group_vars' / 'vault.yml'
    env_file = project_root / '.env'

    print(f"{BLUE}🔧 Generating local .env file from vault.yml{NC}\n")

    # Check if vault.yml exists
    if not vault_file.exists():
        print(f"{RED}❌ Error: vault.yml not found at {vault_file}{NC}\n")
        print("Please set up vault.yml first:")
        print("  cd deployment")
        print("  cp group_vars/vault.yml.example group_vars/vault.yml")
        print("  nano group_vars/vault.yml")
        print("  ansible-vault encrypt group_vars/vault.yml --vault-password-file ~/.vault_pass")
        sys.exit(1)

    # Check if vault is encrypted
    with open(vault_file) as f:
        first_line = f.readline()
        if 'ANSIBLE_VAULT' not in first_line:
            print(f"{RED}❌ Error: vault.yml is not encrypted{NC}\n")
            print("Please encrypt your vault:")
            print("  cd deployment")
            print("  ansible-vault encrypt group_vars/vault.yml --vault-password-file ~/.vault_pass")
            sys.exit(1)

    # Get vault password option
    vault_pass_option = get_vault_password_option()
    if '--ask-vault-pass' in vault_pass_option:
        print(f"{YELLOW}⚠️  ~/.vault_pass not found - you will be prompted for password{NC}\n")

    # Decrypt vault
    print("Decrypting vault.yml...")
    vault_content = decrypt_vault(vault_file, vault_pass_option)
    if not vault_content:
        sys.exit(1)

    # Parse vault
    print("Parsing vault configuration...")
    vault_data = parse_vault_yaml(vault_content)
    if vault_data is None:
        sys.exit(1)

    # Generate .env
    print(f"Generating .env file...")
    generate_env_file(vault_data, env_file)

    # Success
    print(f"\n{GREEN}✅ .env file generated successfully!{NC}\n")
    print(f"Created: {env_file}\n")
    print("Next steps:")
    print(f"  1. Review the .env file: {GREEN}nano .env{NC}")
    print(f"  2. Install dependencies: {GREEN}pip install -r requirements.txt{NC}")
    print(f"  3. Run the app: {GREEN}python -m app{NC}\n")
    print("Note:")
    print("  - This file is in .gitignore and will not be committed")
    print("  - Regenerate anytime with: python scripts/local_dev_setup_env.py")
    print("  - For production, secrets come from AWS Secrets Manager (no .env needed)\n")

if __name__ == '__main__':
    main()


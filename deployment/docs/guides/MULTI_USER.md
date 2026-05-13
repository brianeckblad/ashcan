# Chapter 9: Multi-User Support

Add user accounts and manage access.

---

## Table of Contents

1. [Overview](#overview)
2. [How It Works](#how-it-works)
3. [Setup Instructions](#setup-instructions)
   - [Create User Accounts](#1-create-user-accounts)
   - [User Password Management](#user-password-management)
   - [Configure eBay Credentials](#2-configure-ebay-credentials)
   - [Grant IAM Permissions](#3-grant-iam-permissions)
4. [Adding Users After Deployment](#adding-users-after-deployment)
   - [Quick Add User (Recommended)](#quick-add-user-recommended)
   - [Add User via Script](#add-user-via-script-alternative)
   - [Bulk Add Users](#bulk-add-users)
5. [Web Interface Features](#web-interface-features)
   - [Admin Capabilities](#admin-capabilities-via-account-page)
   - [User Capabilities](#user-capabilities-via-account-page)
   - [First-Time User Workflow](#first-time-user-workflow)
6. [User Experience](#user-experience)
7. [Migration from Single User](#migration-from-single-user)
8. [Technical Details](#technical-details)
9. [Troubleshooting](#troubleshooting)
10. [Security Considerations](#security-considerations)
11. [Future Enhancements](#future-enhancements)

---

## Overview

The application now supports multiple users, each with their own:
- **CSV file** for items (e.g., `data/brian/items.csv`, `data/sarah/items.csv`)
- **SKU counter** (e.g., `data/brian/sku.txt`, `data/sarah/sku.txt`)
- **eBay API credentials** (optional, can share app-level credentials)

Each user logs in with username/password and sees only their own items.

---

## How It Works

### File Structure

**Local Storage:**
```
instance/
├── user_preferences.json  # All users' accounts (shared)
├── app_defaults.json      # App-level defaults (shared)
├── ebay_category_cache.json  # eBay category cache (shared)
└── data/                  # Multi-user data directory
    ├── brian/             # Brian's complete data
    │   ├── items.csv          # Brian's items
    │   ├── sku.txt            # Brian's SKU counter
    │   ├── snapshots/         # Brian's manual backups
    │   ├── trash/             # Brian's deleted items (30-day retention)
    │   ├── analytics/         # Brian's usage analytics
    │   ├── exports/           # Brian's local CSV exports
    │   ├── uploads/           # Brian's temporary uploads
    │   └── images/            # Brian's local images (if not using S3)
    └── sarah/             # Sarah's complete data
        ├── items.csv          # Sarah's items
        ├── sku.txt            # Sarah's SKU counter
        ├── snapshots/         # Sarah's manual backups
        ├── trash/             # Sarah's deleted items
        ├── analytics/         # Sarah's usage analytics
        ├── exports/           # Sarah's local CSV exports
        ├── uploads/           # Sarah's temporary uploads
        └── images/            # Sarah's local images
```

**S3 Storage (User-Specific):**
```
S3 Bucket: your-bucket-name/
├── production/            # Legacy/default user (backward compatible)
│   ├── images/
│   ├── backups/
│   └── exports/
└── users/                 # Multi-user storage
    ├── brian/
    │   ├── images/        # Brian's product images
    │   │   ├── product-001.jpg
    │   │   ├── product-001_thumb.webp
    │   │   └── ...
    │   ├── backups/       # Brian's automated backups
    │   │   ├── csv/items.csv
    │   │   └── sku.txt
    │   ├── exports/       # Brian's CSV export history
    │   │   └── 2026-02-09_1430_comics_export.csv
    │   ├── snapshots/     # Brian's manual snapshots
    │   │   └── 20260209_143000/
    │   │       ├── comics_export.csv
    │   │       └── images/
    │   └── trash/         # Brian's deleted images (recoverable)
    └── sarah/
        ├── images/        # Sarah's product images (separate from Brian)
        ├── backups/       # Sarah's automated backups
        ├── exports/       # Sarah's CSV export history
        ├── snapshots/     # Sarah's manual snapshots
        └── trash/         # Sarah's deleted images
```

**Key Features:**
- ✅ **Complete isolation** - Users cannot see each other's data at ANY level
- ✅ **Automatic organization** - All paths based on username
- ✅ **Backward compatible** - Default user uses root paths
- ✅ **No cross-contamination** - All operations scoped to user

### eBay Credentials (Per User)

**Option 1: User-Specific Credentials (Recommended)**

Each user has their own eBay developer account:

```
AWS Secrets Manager:
  brian/secrets
    ├── EBAY_PRODUCTION_APP_ID
    ├── EBAY_PRODUCTION_CERT_ID
    ├── EBAY_PRODUCTION_DEV_ID
    └── EBAY_PRODUCTION_TOKEN

  sarah/secrets
    ├── EBAY_PRODUCTION_APP_ID
    ├── EBAY_PRODUCTION_CERT_ID
    ├── EBAY_PRODUCTION_DEV_ID
    └── EBAY_PRODUCTION_TOKEN
```

**Option 2: Shared Credentials (Simpler)**

All users share one eBay developer account. Items are tracked by username in CSV files.

```
AWS Secrets Manager:
  app-item-listing-tool/secrets
    ├── EBAY_PRODUCTION_APP_ID    # Shared by all users
    ├── EBAY_PRODUCTION_CERT_ID
    ├── EBAY_PRODUCTION_DEV_ID
    └── EBAY_PRODUCTION_TOKEN
```

### eBay Webhook (Shared Endpoint)

**eBay requires ONE webhook endpoint per application:**

```
https://yourdomain.com/api/ebay/webhook
```

When eBay sends notifications, the payload includes which user's item was affected:

```json
{
  "itemId": "123456789",
  "userId": "brian_ebay_username",
  "notificationEventName": "ItemSold"
}
```

The application maps the eBay username to your app username and updates the correct CSV file.

---

## S3 Storage (Multi-User)

### How S3 Prefixes Work

Each user gets their own S3 prefix (folder structure) for complete isolation:

**User Brian's S3 Structure:**
```
users/brian/images/           # Product images
users/brian/backups/csv/      # CSV backups
users/brian/backups/sku.txt   # SKU counter backups
users/brian/exports/          # CSV export history
```

**User Sarah's S3 Structure:**
```
users/sarah/images/           # Product images (separate from Brian)
users/sarah/backups/csv/      # CSV backups (separate from Brian)
users/sarah/backups/sku.txt   # SKU counter backups (separate from Brian)
users/sarah/exports/          # CSV export history (separate from Brian)
```

### Automatic Operations

All S3 operations are automatically scoped to the logged-in user:

**Image Uploads:**
```python
# User brian uploads image
# Automatically saved to: users/brian/images/{filename}.jpg
```

**CSV Backups:**
```python
# User brian's CSV is backed up
# Automatically saved to: users/brian/backups/csv/items.csv
```

**SKU Backups:**
```python
# User brian's SKU is backed up
# Automatically saved to: users/brian/backups/sku.txt
```

**CSV Exports:**
```python
# User brian exports CSV
# Automatically saved to: users/brian/exports/2026-02-09_1430_comics_export.csv
```

### S3 Isolation Benefits

✅ **Complete Privacy:**
- Users cannot access other users' images
- Users cannot see other users' backups
- Users cannot download other users' exports

✅ **Independent Operations:**
- User deletions only affect their own files
- User backups don't conflict
- User exports are separated

✅ **Easy Management:**
- IAM policies can restrict by prefix
- S3 lifecycle rules can be per-user
- Storage metrics per user

### S3 IAM Policy (User Isolation)

To restrict users to their own S3 prefixes (optional advanced security):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:ListBucket"
      ],
      "Resource": "arn:aws:s3:::your-bucket-name",
      "Condition": {
        "StringLike": {
          "s3:prefix": [
            "users/${aws:userid}/*",
            "users/${aws:userid}"
          ]
        }
      }
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::your-bucket-name/users/${aws:userid}/*"
    }
  ]
}
```

**Note:** Current implementation uses IAM role at EC2 level, so all users on the same server share S3 access. The isolation is application-level (users can only see their own files through the app).

---

## Setup Instructions

### 1. Create User Accounts

Users are managed in `instance/user_preferences.json` or via environment variable:

**Option A: AWS Secrets Manager (Initial Setup)**

The `users` variable in `vault.yml` is synced to Secrets Manager by `secret-sync.yml`:

```yaml
# In vault.yml
users: "brian:password123,sarah:password456,john:password789"
```

```bash
# Sync to Secrets Manager
cd deployment
ansible-playbook playbooks/secret-sync.yml --vault-password-file ~/.vault_pass
```

**⚠️ IMPORTANT:** These are temporary default passwords. Users MUST change them after first login!

**After first login, users are stored in `instance/user_preferences.json`** — the Secrets Manager value is only used as a fallback.

**Option B: Web Interface (Preferred)**
- Log in as admin
- Go to `/account` (Account settings page)
- Find "User Management" or "Add User" section
- Enter new username and temporary password
- Click "Add User"
- System automatically creates:
  - User account in `user_preferences.json`
  - Empty CSV file: `instance/data/{username}/items.csv`
  - SKU counter file: `instance/data/{username}/sku.txt`
- Notify user of their temporary credentials

**What happens automatically:**
```
When admin creates user "sarah":
✓ User account created in user_preferences.json
✓ Local directory structure created:
  - instance/data/sarah/
  - instance/data/sarah/sarah-items.csv (empty CSV)
  - instance/data/sarah/sarah-sku.txt (starts at 1000)
  - instance/data/sarah/snapshots/
  - instance/data/sarah/trash/
  - instance/data/sarah/analytics/
  - instance/data/sarah/exports/
  - instance/data/sarah/uploads/
  - instance/data/sarah/images/
✓ S3 structure auto-created on first use:
  - users/sarah/images/ (on first image upload)
  - users/sarah/backups/ (on first backup)
  - users/sarah/exports/ (on first export)
  - users/sarah/snapshots/ (on first snapshot)
  - users/sarah/trash/ (on first delete)
✓ User can immediately log in
```

**User completes setup:**
1. User logs in with temporary password
2. User goes to `/account` → Change Password
3. User updates their password
4. User goes to `/account` → eBay Settings (optional)
5. User enters their eBay API credentials
6. System stores credentials in AWS Secrets Manager: `sarah/secrets`

**Option C: Direct Edit (Advanced)**
```bash
# Edit user_preferences.json
{
  "brian": {
    "username": "brian",
    "password_hash": "$2b$12$...",  # Hashed password
    "preferences": {}
  },
  "sarah": {
    "username": "sarah",
    "password_hash": "$2b$12$...",
    "preferences": {}
  }
}
```

**Generate password hash:**
```bash
python3 -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('your_password_here'))"
```

### User Password Management

**First Login Process:**

1. **Admin creates user** with temporary password (e.g., `TempPass123`)
2. **User logs in** with temporary password
3. **User immediately changes password:**
   - Go to Account settings
   - Click "Change Password"
   - Enter current password (temporary)
   - Enter new strong password
   - Confirm new password
   - Save

**Password Requirements:**
- Minimum 8 characters (recommended 12+)
- Mix of uppercase, lowercase, numbers, symbols
- Not a common password
- Unique per user

**Change Password (For Users):**

Via Web Interface (Recommended):
1. Log in to application
2. Go to `/account` (Account page)
3. Find "Change Password" section
4. Fill in form:
   - Current Password
   - New Password
   - Confirm New Password
5. Click "Change Password"
6. Success message appears
7. You can continue using the app with new password

**Note:** Password change is immediate - no need to log out/in again.

**Reset Password (For Users - Self Service):**

Users can reset their own password if they remember their current password:
1. Log in with current password
2. Go to `/account`
3. Use "Change Password" section
4. Enter current password and new password
5. Save

**Reset Password (For Admins - When User Forgot):**

If a user completely forgets their password, admin must reset it:

**Option 1: Via Environment Variable (Temporary)**
```bash
# Add to .env temporarily
USERS=brian:newpassword123

# Restart app
sudo supervisorctl restart {app_name}

# Remove from .env after user logs in and changes password
```

**Option 2: Via Python (More Secure)**
```bash
# Connect to server
aws ssm start-session --target i-xxxxxxxxxxxxx

# Run password reset script
cd /opt/{app_name}
source ~/.venv/bin/activate
python3 << 'EOF'
from app.models.user import user_manager
username = 'brian'
new_password = 'TempPass123'  # User must change this on login
user_manager.update_password(username, new_password)
print(f"✓ Password reset for {username}")
EOF

# Notify user of temporary password
```

**Option 3: Direct Edit (Advanced)**
```bash
# Generate new hash
NEW_HASH=$(python3 -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('TempPass123'))")

# Edit user_preferences.json
cd /opt/{app_name}/instance
cp user_preferences.json user_preferences.json.bak
# Manually update the password_hash for the user
nano user_preferences.json

# Restart app
sudo supervisorctl restart {app_name}
```

**Best Practices:**

✅ **DO:**
- Use strong, unique passwords for each user
- Change default passwords immediately
- Require password changes every 90 days
- Store temporary passwords securely (password manager)
- Use 2FA if available (future enhancement)
- Log password changes for audit trail

❌ **DON'T:**
- Share passwords between users
- Store passwords in plain text
- Use common passwords (Password123, etc.)
- Leave default passwords unchanged
- Email passwords in plain text
- Reuse old passwords

### 2. Configure eBay Credentials

**NEW (February 2026):** Users can manage their own eBay API credentials through the web interface!

#### Method 1: Web Interface (Recommended)

Each user can configure their own credentials:

1. **User logs in** to the application
2. **Navigate to** `/account` (Account settings page)
3. **Find** "eBay API Credentials" section
4. **Click** "Manage Credentials" button
5. **Enter** eBay API credentials from [developer.ebay.com](https://developer.ebay.com/):
   - Production: App ID, Cert ID, Dev ID, User Token
   - Sandbox (optional): Same fields
6. **Click** "Save Credentials"

**Credentials stored at:** `{username}/production` in AWS Secrets Manager

**Benefits:**
- ✅ Users manage their own credentials
- ✅ No admin intervention needed
- ✅ Secure storage in AWS Secrets Manager
- ✅ Easy credential updates
- ✅ Complete isolation between users

#### Method 2: AWS CLI (Advanced)

**For User-Specific Credentials:**

```bash
# Create secret for brian
aws secretsmanager create-secret \
  --name brian/secrets \
  --secret-string '{
    "EBAY_PRODUCTION_APP_ID": "brian-app-id",
    "EBAY_PRODUCTION_CERT_ID": "brian-cert-id",
    "EBAY_PRODUCTION_DEV_ID": "brian-dev-id",
    "EBAY_PRODUCTION_TOKEN": "brian-token"
  }'

# Create secret for sarah
aws secretsmanager create-secret \
  --name sarah/secrets \
  --secret-string '{
    "EBAY_PRODUCTION_APP_ID": "sarah-app-id",
    "EBAY_PRODUCTION_CERT_ID": "sarah-cert-id",
    "EBAY_PRODUCTION_DEV_ID": "sarah-dev-id",
    "EBAY_PRODUCTION_TOKEN": "sarah-token"
  }'
```

**For Shared Credentials:**

Keep the existing `app-item-listing-tool/secrets` secret. All users will use it automatically if their user-specific secret doesn't exist.

### 3. Grant IAM Permissions

Update the EC2 IAM role to allow access to user secrets:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": [
        "arn:aws:secretsmanager:us-east-2:*:secret:app-item-listing-tool/secrets-*",
        "arn:aws:secretsmanager:us-east-2:*:secret:*/production-*"
      ]
    }
  ]
}
```

---

## Adding Users After Deployment

### Quick Add User (Recommended)

**Step 1: Add user via web interface**
1. Log in as admin
2. Navigate to Account settings
3. Add new user with temporary password

**Step 2: Notify user**
```
Username: sarah
Temporary Password: TempPass789

Please log in and change your password immediately at:
https://yourdomain.com/login

After login, go to Account → Change Password
```

**Step 3: User changes password on first login**

---

### Add User via Script (Alternative)

Create a helper script for adding users:

**File:** `scripts/add-user.sh`

```bash
#!/bin/bash
# Add a new user to the application

if [ -z "$1" ] || [ -z "$2" ]; then
    echo "Usage: ./add-user.sh <username> <temporary-password>"
    echo "Example: ./add-user.sh sarah TempPass123"
    exit 1
fi

USERNAME="$1"
TEMP_PASSWORD="$2"

echo "Adding user: $USERNAME"
echo "Temporary password: $TEMP_PASSWORD"
echo ""
echo "⚠️  User MUST change password on first login!"
echo ""

# Connect to server and add user
ssh ubuntu@your-server.com << EOF
cd /opt/{app_name}
source ~/.venv/bin/activate

python3 << PYTHON
from app.models.user import user_manager
from werkzeug.security import generate_password_hash

username = '$USERNAME'
password = '$TEMP_PASSWORD'

# Check if user exists
if user_manager.get_user(username):
    print(f"✗ User {username} already exists!")
    exit(1)

# Add user
user_manager._users_cache[username.lower()] = {
    'username': username,
    'password_hash': generate_password_hash(password),
    'preferences': user_manager._default_preferences()
}
user_manager._save_users(user_manager._users_cache)
print(f"✓ User {username} created successfully!")
print(f"  Temporary password: {password}")
print(f"  User must change password on first login!")
PYTHON
EOF

echo ""
echo "✓ User added. Notify user:"
echo "  Username: $USERNAME"
echo "  Temporary Password: $TEMP_PASSWORD"
echo "  Login URL: https://yourdomain.com/login"
```

**Usage:**
```bash
chmod +x scripts/add-user.sh
./scripts/add-user.sh sarah TempPass123
```

---

### Bulk Add Users

For adding multiple users at once:

**File:** `users-to-add.txt`
```
brian:TempPass001
sarah:TempPass002
john:TempPass003
```

**Script:** `scripts/bulk-add-users.sh`

```bash
#!/bin/bash
# Bulk add users from file

if [ ! -f "users-to-add.txt" ]; then
    echo "✗ users-to-add.txt not found!"
    echo "Create file with format: username:password (one per line)"
    exit 1
fi

echo "Adding users from users-to-add.txt..."
echo ""

while IFS=: read -r username password; do
    # Skip empty lines and comments
    [[ -z "$username" || "$username" =~ ^# ]] && continue
    
    echo "Adding: $username"
    ./scripts/add-user.sh "$username" "$password"
    echo ""
done < users-to-add.txt

echo "✓ Bulk user creation complete!"
echo ""
echo "⚠️  IMPORTANT:"
echo "  1. Notify all users of their temporary passwords"
echo "  2. Users MUST change passwords on first login"
echo "  3. Delete users-to-add.txt after completion (contains passwords!)"
```

**Usage:**
```bash
# Create users file
cat > users-to-add.txt << EOF
brian:TempPass001
sarah:TempPass002
john:TempPass003
EOF

# Run bulk add
chmod +x scripts/bulk-add-users.sh
./scripts/bulk-add-users.sh

# Delete password file
rm users-to-add.txt
```

---

### Add User via Environment Variable (Legacy)

**For initial deployment only:**

```bash
# Edit .env
USERS=existing_user:pass,new_user:TempPass123

# Restart app
sudo supervisorctl restart {app_name}

# IMPORTANT: Remove from .env after users are created!
# Users are now stored in user_preferences.json
```

**⚠️ Warning:** This method is for initial setup only. After deployment, use web interface or scripts.

---

## Web Interface Features

### Admin Capabilities (via `/account` page)

**User Management:**
1. **Create New User**
   - Click "Add User" button
   - Enter username (e.g., `sarah`)
   - Enter temporary password (e.g., `TempPass789`)
   - Click "Create User"
   - System automatically:
     - Creates user account
     - Creates `instance/data/sarah-items.csv`
     - Creates `instance/data/sarah-sku.txt` (starts at 1000)
     - Saves to `user_preferences.json`
   - Admin notifies user of credentials

2. **View All Users**
   - See list of all registered users
   - View username, account status
   - See last login date (if tracked)

3. **Delete User** (if implemented)
   - Remove user account
   - Archive user's CSV file (don't delete data!)
   - Revoke access

**Admin Account Settings:**
- Change own password
- Update preferences
- View system status

### User Capabilities (via `/account` page)

**Password Management:**
1. **Change Password**
   - Section: "Change Password"
   - Enter current password
   - Enter new password
   - Confirm new password
   - Click "Change Password"
   - Immediate effect (no re-login needed)

**eBay Credentials Configuration:**
1. **Enter eBay API Credentials**
   - Section: "eBay Settings" or "API Configuration"
   - Enter eBay Production App ID
   - Enter eBay Production Cert ID
   - Enter eBay Production Dev ID
   - Enter eBay Production Token
   - Click "Save eBay Credentials"
   - System stores in AWS Secrets Manager: `{username}/production`

2. **Update eBay Credentials**
   - Same form, update any field
   - Click "Update Credentials"
   - System updates secret in AWS Secrets Manager

3. **View Current eBay Environment**
   - See if using production or sandbox
   - See if credentials are configured
   - Test eBay connection

**User Preferences:**
- Items per page
- Default sort order
- eBay listing defaults
- UI preferences

**Account Information:**
- View username
- View account creation date
- View storage usage
- View item count

### First-Time User Workflow

**Step 1: Admin Creates User**
```
Admin logs in → /account
├── Clicks "Add User"
├── Enters: username: sarah, password: TempPass789
├── Clicks "Create User"
└── ✓ User created, files created automatically
```

**Step 2: Admin Notifies User**
```
Email/Message to sarah:
───────────────────────────────────────
Your account has been created!

Login URL: https://yourdomain.com/login
Username: sarah
Temporary Password: TempPass789

⚠️ IMPORTANT:
1. Log in immediately
2. Change your password: /account → Change Password
3. (Optional) Configure eBay credentials: /account → eBay Settings
───────────────────────────────────────
```

**Step 3: User First Login**
```
User logs in with temporary credentials
├── Goes to /account
├── Changes password (required!)
│   ├── Current: TempPass789
│   ├── New: MySecurePassword123!
│   └── Confirm: MySecurePassword123!
├── (Optional) Configures eBay credentials
│   ├── Enters eBay App ID
│   ├── Enters Cert ID, Dev ID, Token
│   └── Saves (stored in AWS Secrets Manager)
└── ✓ Account setup complete!
```

**Step 4: User Starts Working**
```
User can now:
├── Add items to their inventory
├── Upload images
├── Export CSV files
├── List items on eBay (with their credentials)
└── Manage their own items (isolated from other users)
```

---

## User Experience

### Login

1. User goes to `/login`
2. Enters username and password
3. Session stores username

### Item Management

- User sees only their own items from `{username}/items.csv`
- SKU counter is per-user (no conflicts)
- eBay listings use user's credentials (if configured)

### eBay Integration

- Each user can list items with their own eBay account
- OR all users share one eBay account
- Webhook notifications work for all users

---

## Migration from Single User

### Existing Users

If you have existing data in `items.csv`:

**Option 1: Keep as "default" user**
```bash
# Existing items.csv continues to work
# New users get their own files
```

**Option 2: Migrate to named user**
```bash
# Backup
cp instance/items.csv instance/items.csv.bak
cp instance/sku.txt instance/sku.txt.bak

# Move to user-specific files
mkdir -p instance/data/brian
mv instance/items.csv instance/data/brian/items.csv
mv instance/sku.txt instance/data/brian/sku.txt

# Create new default files (empty)
touch instance/items.csv
echo "1000" > instance/sku.txt
```

---

## Technical Details

### Code Changes

**New File:** `app/utils/user_context.py`
- `get_current_username()` - Get logged-in user
- `get_user_csv_file(username)` - Get user's CSV file path
- `get_user_sku_file(username)` - Get user's SKU file path
- `get_user_secret_name(username)` - Get user's secret name
- `get_ebay_credentials(username)` - Get user's eBay credentials

**Updated Files:**
- `app/services/comic_service.py` - Uses user-specific CSV and SKU files
- `app/services/ebay_service.py` - Uses user-specific eBay credentials
- `app/__init__.py` - Creates multi-user data directory

**No Changes Needed:**
- `app/routes/auth.py` - Already stores username in session
- `app/models/user.py` - User management already exists

### Session Management

```python
# After login
session['username'] = 'brian'

# During requests
from app.utils.user_context import get_current_username
username = get_current_username()  # Returns 'brian'
csv_file = get_user_csv_file(username)  # Returns 'instance/data/brian/items.csv'
```

### Backward Compatibility

- **Default user:** If no user is logged in, username is 'default'
- **Legacy files:** `items.csv` and `sku.txt` continue to work for 'default' user
- **Existing data:** No migration required unless you want named users

---

## Troubleshooting

### User can't see their items

**Check:**
1. User is logged in: `session['username']`
2. CSV file exists: `instance/data/{username}/items.csv`
3. File permissions are correct

**Fix:**
```bash
# Check if file exists
ls -la instance/data/brian/

# Create directory and empty file if missing
mkdir -p instance/data/brian
touch instance/data/brian/items.csv

# Fix permissions
chown -R ubuntu:{app_name} instance/data/brian
chmod 664 instance/data/brian/items.csv
```

### eBay API errors

**Check:**
1. User has credentials in Secrets Manager: `{username}/production`
2. Or app-level credentials exist: `app-item-listing-tool/secrets`
3. IAM role has permissions

**Fix:**
```bash
# Check if user secret exists
aws secretsmanager describe-secret --secret-id brian/secrets

# If not, create it or use shared credentials
```

### SKU conflicts between users

**Not possible** - Each user has their own SKU counter.

### eBay webhook not working

**Webhook is shared** - eBay sends notifications to one endpoint for all users.

The payload includes `userId` to identify which user's item was affected.

---

## Security Considerations

### User Isolation

- ✅ Users cannot see other users' items (CSV files are separate)
- ✅ Users cannot access other users' eBay credentials
- ✅ Session-based authentication prevents cross-user access

### eBay Credentials

**User-Specific Secrets:**
- ✅ Each user has separate eBay account
- ✅ No credential sharing
- ✅ Easier to revoke access (delete user's secret)

**Shared Secrets:**
- ⚠️ All users share one eBay account
- ⚠️ Cannot distinguish which user listed an item (unless tracked separately)
- ✅ Simpler setup (fewer eBay developer accounts)

### Recommendations

1. **Use user-specific credentials** if users need separate eBay accounts
2. **Use shared credentials** if all users work for the same business
3. **Rotate credentials** quarterly (see `OPERATIONS.md`)
4. **Monitor access** via CloudTrail logs

---

## Future Enhancements

### Already Implemented ✅

- ✅ **User registration via web interface** - Admin creates users on `/account` page
- ✅ **Password reset via web interface** - Users can change password on `/account` page
- ✅ **eBay credential configuration via web** - Users can enter eBay credentials on `/account` page
- ✅ **Automatic file creation** - CSV and SKU files created when user is added

### Possible Future Improvements

- [ ] Admin dashboard to view all users' items
- [ ] User quotas (limit items per user)
- [ ] User roles (admin, seller, viewer)
- [ ] eBay username mapping configuration UI
- [ ] Bulk user import from CSV via web interface
- [ ] User analytics dashboard (items listed, sold, revenue)
- [ ] Email notifications for password resets
- [ ] 2FA/MFA authentication

### Design Decisions (Keeping Simple)

- ✅ **CSV storage** - No database needed, simple file-based storage
- ✅ **Admin-created users** - No public registration (security)
- ✅ **Manual password reset** - Admin intervention required (security)
- ✅ **Session-based auth** - Simple, no OAuth complexity

---

## Next step

Continue to [Chapter 10: Git Configuration](GIT_CONFIGURATION.md).

## See also

- [Chapter 8: Security Hardening](SECURITY_HARDENING.md) — server permissions
- [User Types](../reference/USER_MODEL.md) — admin vs. application user capabilities


# Instance Directory

**Location:** `/opt/{app_name}/instance/`  
**Purpose:** Application runtime data and persistent storage  
**Created:** Automatically during deployment

**Note:** `{app_name}` is configured in `deployment/group_vars/vault.yml`

---

## Directory Structure

```
instance/
├── README.md                    # This file
├── .env                         # Environment configuration (created by deployment)
├── items.csv                    # Main product database
├── items.csv.bak               # Automatic backup of items.csv
├── sku.txt                     # SKU counter (auto-incremented)
├── app.log                     # Application runtime logs
├── cleanup.log                 # Backup cleanup logs
├── service.log                 # Service health check logs
├── blocked_ips.json            # Security: Blocked IP addresses
├── user_preferences.json       # User settings and preferences
├── ebay_category_cache.json    # Cached eBay category data
├── app_defaults.json           # Application default settings
├── analytics/                  # Analytics data and reports
│   ├── daily/                  # Daily analytics snapshots
│   ├── weekly/                 # Weekly analytics reports
│   └── monthly/                # Monthly analytics aggregates
├── exports/                    # CSV/data export files
├── images/                     # Uploaded product images
│   └── [product-images]        # Organized by upload date
├── item_images/                # Legacy/alternative image storage
├── snapshots/                  # Database snapshots
│   ├── YYYYMMDD_HHMMSS_items.csv
│   └── [dated snapshots]       # Automatic daily snapshots
├── trash/                      # Soft-deleted items (recoverable)
│   └── [deleted items]         # Retained for 30 days by default
└── uploads/                    # Temporary upload staging area
    └── [temp files]            # Cleaned up after processing
```

---

## Core Files

### `.env`
**Created:** By Ansible playbook during deployment  
**Purpose:** Non-secret configuration only (all secrets in AWS Secrets Manager)  
**Contains:**
- Flask configuration (FLASK_ENV, DEBUG)
- AWS Secrets Manager pointer (SECRET_NAME, AWS_REGION)
- S3 configuration (S3_BUCKET_NAME, S3_FOLDER)
- Application paths (COMIC_IMAGE_PATH, APP_SERVICE_NAME)

**Format:**
```bash
# Flask Configuration
FLASK_ENV=production
DEBUG=False

# Server Configuration
PORT=8000
HOST=0.0.0.0

# AWS Secrets Manager Configuration
# EC2 instance uses IAM role to access Secrets Manager (no AWS credentials!)
SECRET_NAME={app_name}/production
AWS_REGION=us-east-2

# S3 Configuration  
# EC2 instance uses IAM role to access S3 (no AWS credentials!)
S3_BUCKET_NAME=your-bucket-name
S3_FOLDER=production

# Application Configuration
COMIC_IMAGE_PATH=/opt/{app_name}/instance/item_images

# Note: All secrets (SECRET_KEY, eBay credentials, admin passwords)
# are fetched from AWS Secrets Manager at runtime.
# The IAM role attached to the EC2 instance provides access.
```

**Security:** 
- Permissions: `0600` (read/write owner only)
- Not in version control
- Persists across updates
- No AWS credentials stored — EC2 uses IAM role
- No secrets on disk — all secrets fetched from Secrets Manager at runtime

---

### AWS Secrets Manager (Production Secrets)
**Location:** AWS Secrets Manager (not on disk)  
**Secret Name:** `{app_name}/production`  
**Access Method:** IAM role attached to EC2 instance  

All application secrets (Flask secret key, eBay credentials, admin passwords,
CloudFront tokens) are stored in Secrets Manager. The key names match
the UPPERCASE names used by `config.py` `get_secret()` calls. See
`secret-sync.yml` for the full list.

**How it works:**
1. Application starts, reads `SECRET_NAME` from .env
2. Uses boto3 with IAM role (no credentials needed)
3. Fetches all secrets from Secrets Manager
4. Secrets available via `config.get_secret('KEY_NAME')`

**Benefits:**
- No credentials on disk (except .env minimal config)
- Secrets encrypted at rest in AWS
- Centralized secret management
- Easy secret rotation without redeploying app
- IAM role controls access (no keys to leak)

---

### `items.csv`
**Purpose:** Main product database (CSV format)  
**Schema:**
```csv
SKU,Title,Category,Price,Quantity,Condition,Description,Location,Image URLs,Status
```

**Characteristics:**
- Primary data storage for all products
- Automatically backed up before modifications
- Can be edited directly (with caution)
- Supports bulk import/export
- Maximum recommended size: 100,000 items

**Backup Strategy:**
- Automatic backup to `items.csv.bak` before changes
- Daily snapshots in `snapshots/` directory
- S3 backups (if configured)

---

### `items.csv.bak`
**Purpose:** Automatic backup of items.csv  
**Created:** Before any write operation to items.csv  
**Retention:** Overwritten on each save (single backup)  
**Restore:** Manual - copy back to `items.csv`

---

### `sku.txt`
**Purpose:** Auto-incrementing SKU counter  
**Format:** Single integer (e.g., `12345`)  
**Behavior:**
- Increments automatically when creating new items
- Ensures unique SKU generation
- Can be manually adjusted (with caution)

**Example:**
```
12346
```

---

### `blocked_ips.json`
**Purpose:** Security middleware - blocked IP addresses  
**Format:** JSON with IP and expiration timestamps  
**Auto-managed:** By `app/security.py`

**Structure:**
```json
{
  "192.168.1.100": 1738886400.0,
  "10.0.0.50": 1738890000.0
}
```

**Behavior:**
- IPs blocked for 24 hours (attacks) or 1 hour (rate limit)
- Expired entries automatically cleaned up
- Persists across application restarts
- Admin can manually unblock via API

---

### `user_preferences.json`
**Purpose:** User interface settings and preferences  
**Format:** JSON key-value pairs  
**Examples:**
- Items per page
- Default sort order
- UI theme preferences
- Hidden/shown columns

---

### `ebay_category_cache.json`
**Purpose:** Cached eBay category hierarchy  
**Benefit:** Reduces API calls to eBay  
**TTL:** 24 hours (configurable)  
**Size:** ~500KB - 2MB

---

### `app_defaults.json`
**Purpose:** Application-wide default settings  
**Created:** Automatically on first run  
**Examples:**
- Default product condition
- Default location
- Default pricing rules

---

## Log Files

### `app.log`
**Purpose:** Application runtime logs  
**Rotation:** Daily via logrotate (keep 14 days)  
**Max Size:** 10MB per file  
**Location:** Also copied to `/var/log/apps/{app_name}/app.log`

**Contents:**
- Application errors and warnings
- User actions (create, update, delete)
- Security events (blocked IPs, attacks)
- Performance metrics

---

### `cleanup.log`
**Purpose:** Backup cleanup operation logs  
**Written By:** Cron job (`cleanup_old_backups.py`)  
**Rotation:** Weekly (keep 4 weeks)

**Contents:**
- Files deleted from snapshots/
- Files deleted from trash/
- Disk space freed

---

### `service.log`
**Purpose:** Service health check logs  
**Rotation:** Weekly  
**Contents:**
- Health check results
- Service status
- Resource usage

---

## Directories

### `analytics/`
**Purpose:** Analytics data and reports  
**Subdirectories:**
- `daily/` - Daily snapshots (JSON format)
- `weekly/` - Weekly aggregates
- `monthly/` - Monthly reports

**Retention:**
- Daily: 90 days
- Weekly: 1 year
- Monthly: 3 years

**Files:**
```
daily/YYYY-MM-DD.json
weekly/YYYY-WW.json
monthly/YYYY-MM.json
```

---

### `exports/`
**Purpose:** User-generated CSV exports  
**Retention:** 7 days (auto-cleanup)  
**Naming:** `export_YYYYMMDD_HHMMSS.csv`

**Use Cases:**
- Bulk data export
- Backup before major changes
- Integration with external tools

---

### `images/`
**Purpose:** Uploaded product images (if not using S3)  
**Organization:** By upload date subdirectories  
**Formats:** PNG, JPG, JPEG, GIF, WebP

**Structure:**
```
images/
├── YYYY-MM-DD/
│   ├── product1_001.jpg
│   ├── product1_002.jpg
│   └── product2_001.png
```

**Note:** In production with S3, images are stored in S3 bucket, not locally.

---

### `item_images/`
**Purpose:** Legacy image directory (backward compatibility)  
**Note:** May be empty if using `images/` or S3

---

### `snapshots/`
**Purpose:** Automatic database snapshots  
**Format:** `YYYYMMDD_HHMMSS_items.csv`  
**Frequency:** Daily (via cron job at 3 AM)  
**Retention:** 30 days (configurable)

**Naming Convention:**
```
20260209_030000_items.csv
20260208_030000_items.csv
20260207_030000_items.csv
```

**Cleanup:** Automatic via `cleanup_old_backups.py`

---

### `trash/`
**Purpose:** Soft-deleted items (recoverable)  
**Retention:** 30 days (configurable)  
**Format:** JSON files with deletion timestamp

**Structure:**
```json
{
  "deleted_at": "2026-02-09T10:30:00",
  "deleted_by": "admin",
  "item": {
    "SKU": "12345",
    "Title": "Product Name",
    ...
  }
}
```

**Recovery:** Via admin interface or manual restore

---

### `uploads/`
**Purpose:** Temporary upload staging  
**Lifecycle:**
1. File uploaded by user
2. Validated and processed
3. Moved to permanent location (`images/` or S3)
4. Temporary file deleted

**Cleanup:** Automatic after processing (< 1 hour)

---

## Security and Permissions

### File Permissions
```bash
# Directory
drwxr-xr-x  {app_user}:{app_user}  instance/

# Configuration (sensitive)
-rw-------  {app_user}:{app_user}  .env
-rw-------  {app_user}:{app_user}  blocked_ips.json

# Data files
-rw-r--r--  {app_user}:{app_user}  items.csv
-rw-r--r--  {app_user}:{app_user}  items.csv.bak
-rw-r--r--  {app_user}:{app_user}  sku.txt

# Logs
-rw-r--r--  {app_user}:{app_user}  *.log

# Subdirectories
drwxr-xr-x  {app_user}:{app_user}  analytics/
drwxr-xr-x  {app_user}:{app_user}  exports/
drwxr-xr-x  {app_user}:{app_user}  images/
drwxr-xr-x  {app_user}:{app_user}  snapshots/
drwxr-xr-x  {app_user}:{app_user}  trash/
drwxr-xr-x  {app_user}:{app_user}  uploads/
```

### Protected Files
- `.env` - Contains configuration (0600 permissions)
- `blocked_ips.json` - Security data (0600 permissions)
- All other files readable by app user

---

## Backup Strategy

### Automatic Backups

**Daily Snapshots:**
```bash
# Cron job (3:00 AM daily)
0 3 * * * cd /opt/{app_name} && .venv/bin/python scripts/cleanup_old_backups.py
```

**Before Changes:**
- `items.csv` → `items.csv.bak` (automatic)

**S3 Backups (if configured):**
- Images uploaded to S3 in real-time
- Database snapshots can be uploaded to S3

### Manual Backup
```bash
# Backup entire instance directory
cp -r instance/ instance_backup_$(date +%Y%m%d)/

# Backup just the database
cp instance/items.csv items_backup_$(date +%Y%m%d).csv
```

---

## Disk Usage

**Typical Usage:**
- Fresh install: ~10 MB
- With 1,000 items: ~50 MB
- With 10,000 items: ~200 MB
- Images (local): 10-50 MB per 100 products

**Growth Rate:**
- CSV data: ~2 KB per item
- Logs: ~10 MB per month (with rotation)
- Snapshots: ~size of items.csv × 30 days
- Analytics: ~1 MB per month

**Monitoring:**
```bash
du -sh /opt/{app_name}/instance
df -h
```

---

## Maintenance

### Daily
- Automatic snapshot creation (3 AM)
- Automatic log rotation
- Automatic cleanup of old backups

### Weekly
- Review `cleanup.log` for cleanup operations
- Check disk usage

### Monthly
- Review analytics data growth
- Archive old exports if needed
- Verify backup integrity

### Commands
```bash
APP_DIR="/opt/{app_name}"

# View recent logs
tail -f $APP_DIR/instance/app.log

# Check blocked IPs
cat $APP_DIR/instance/blocked_ips.json

# List snapshots
ls -lh $APP_DIR/instance/snapshots/

# Clean up old exports manually
find $APP_DIR/instance/exports/ -mtime +7 -delete

# Check disk usage
du -sh $APP_DIR/instance
```

---

## Important Notes

### Do NOT Delete
- `.env` - Application will not start
- `items.csv` - Primary database
- `sku.txt` - SKU generation will break

### Safe to Delete
- `uploads/*` - Temporary files only
- Old files in `exports/` (> 7 days)
- Old files in `trash/` (> 30 days)
- Old files in `snapshots/` (> 30 days)

### Edit with Caution
- `items.csv` - Backup first, validate CSV format
- `sku.txt` - Ensure it is an integer
- `blocked_ips.json` - Maintain JSON structure

### Never Edit
- `.env` - Managed by deployment (except manual fixes)
- Log files - Read-only, managed by application

---

## Troubleshooting

### Issue: Application will not start
**Check:**
1. `.env` file exists and is readable
2. `items.csv` exists (create empty if missing)
3. Directory permissions correct

### Issue: Images not loading
**Check:**
1. S3 bucket configuration (if using S3)
2. `images/` directory permissions
3. Image file paths in `items.csv`

### Issue: Disk space full
**Check:**
```bash
APP_DIR="/opt/{app_name}"
du -sh $APP_DIR/instance/snapshots/
du -sh $APP_DIR/instance/exports/
du -sh /var/log/apps/{app_name}/
```

**Clean up:**
```bash
cd /opt/{app_name}
.venv/bin/python scripts/cleanup_old_backups.py
```

### Issue: Cannot create new items
**Check:**
1. `sku.txt` is a valid integer
2. `items.csv` is writable
3. Disk space available


# Application Utility Scripts

**Location:** `app/scripts/`

These are application-level utility scripts for data maintenance, validation, and tooling. They operate on application data (images, CSVs, labels) and are NOT part of deployment.

For deployment and operational scripts, see `deployment/scripts/`.

---

## Scripts

### `util_check_comic_images.py`
**Purpose:** Verify comic images exist and are valid

### `util_fix_missing_thumbnails.py`
**Purpose:** Regenerate missing thumbnail images

### `util_generate_page_images.py`
**Purpose:** Generate page images from source files

### `util_validate_csv_schema.py`
**Purpose:** Validate CSV data files against expected schema

### `util-generate-ebay-token.sh`
**Purpose:** Generate eBay verification token for Marketplace Account Deletion endpoint

### `generate_avery_labels.py`
**Purpose:** Generate printable Avery label sheets (SKU labels)

### `cleanup_old_backups.py`
**Purpose:** Clean up old backup files beyond retention period (runs via cron on server)

---

## Usage

These scripts are run manually when needed, either locally or on the server:

```bash
# Run locally
python app/scripts/util_validate_csv_schema.py

# Run on server
ssh user@server
cd /opt/{app_name}
python app/scripts/util_fix_missing_thumbnails.py
```

---

## Naming Convention

| Type | Convention | Example |
|------|-----------|---------|
| Python scripts | `snake_case.py` | `util_check_comic_images.py` |
| Shell scripts | `kebab-case.sh` | `util-generate-ebay-token.sh` |

---

## Script Locations

| Location | Purpose |
|----------|---------|
| `app/scripts/` | Application data utilities (this directory) |
| `deployment/scripts/` | Deployment, configuration, and operational scripts |

#!/usr/bin/env python3
"""
Cleanup old backup files from local storage and S3.

This script removes backup folders older than the specified retention period
from both the local instance directory and S3 bucket.

Backup types cleaned:
- all_comic_delete/ - Full inventory deletion backups
- single_comic_delete/ - Individual comic deletion backups
- 
Retention period: 30 days (configurable)
"""

import os
import sys
import shutil
from datetime import datetime, timedelta
from pathlib import Path

# Add project root directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from app.services.s3_service import s3_service
    from dotenv import load_dotenv
except ImportError as e:
    print(f"Error importing required modules: {e}")
    print("Make sure you're running from the application directory with venv activated")
    sys.exit(1)

# Load environment variables
load_dotenv()

# Configuration
RETENTION_DAYS = int(os.getenv('BACKUP_RETENTION_DAYS', 30))
# __file__ = app/scripts/cleanup_old_backups.py; .parent.parent.parent = project root
INSTANCE_DIR = Path(__file__).parent.parent.parent / 'instance'
BACKUP_TYPES = ['all_comic_delete', 'single_comic_delete']


def parse_backup_timestamp(folder_name):
    """
    Parse timestamp from backup folder name.

    Formats:
    - all_comic_delete: YYYYMMDD_HHMMSS
    - single_comic_delete: YYYYMMDD_HHMMSS_SKUXXXX
    """
    try:
        # Extract timestamp part (first 15 chars: YYYYMMDD_HHMMSS)
        timestamp_str = folder_name[:15]
        return datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S')
    except (ValueError, IndexError):
        return None


def cleanup_local_backups(backup_type, cutoff_date):
    """Remove old backup folders from local storage."""
    backup_dir = INSTANCE_DIR / backup_type

    if not backup_dir.exists():
        print(f"Local backup directory not found: {backup_dir}")
        return 0

    deleted_count = 0

    for folder in backup_dir.iterdir():
        if not folder.is_dir():
            continue

        timestamp = parse_backup_timestamp(folder.name)
        if timestamp and timestamp < cutoff_date:
            try:
                shutil.rmtree(folder)
                deleted_count += 1
                print(f"Deleted local backup: {backup_type}/{folder.name}")
            except Exception as e:
                print(f"Error deleting {folder}: {e}")

    return deleted_count


def cleanup_s3_backups(backup_type, cutoff_date):
    """Remove old backup folders from S3."""
    prefix = f"backups/{backup_type}/"

    try:
        # List all folders in this backup type
        folders = set()
        files = s3_service.list_files_with_prefix(prefix)

        for file_key in files:
            # Extract folder name from path: backups/TYPE/FOLDER/...
            parts = file_key.split('/')
            if len(parts) >= 3:
                folders.add(parts[2])  # FOLDER name

        deleted_count = 0

        for folder in folders:
            timestamp = parse_backup_timestamp(folder)
            if timestamp and timestamp < cutoff_date:
                # Delete all files in this folder
                folder_prefix = f"{prefix}{folder}/"
                folder_files = s3_service.list_files_with_prefix(folder_prefix)

                for file_key in folder_files:
                    try:
                        s3_service.delete_file(file_key)
                        deleted_count += 1
                    except Exception as e:
                        print(f"Error deleting {file_key}: {e}")

                print(f"Deleted S3 backup: {backup_type}/{folder} ({len(folder_files)} files)")

        return deleted_count

    except Exception as e:
        print(f"Error cleaning S3 backups for {backup_type}: {e}")
        return 0


def main():
    """Main cleanup routine."""
    print(f"Starting backup cleanup (retention: {RETENTION_DAYS} days)")
    print(f"Cutoff date: {datetime.now() - timedelta(days=RETENTION_DAYS)}")
    print("-" * 60)

    cutoff_date = datetime.now() - timedelta(days=RETENTION_DAYS)

    total_local = 0
    total_s3 = 0

    for backup_type in BACKUP_TYPES:
        print(f"\nCleaning {backup_type}...")

        # Cleanup local backups
        local_count = cleanup_local_backups(backup_type, cutoff_date)
        total_local += local_count
        print(f"  Local: {local_count} folders deleted")

        # Cleanup S3 backups
        s3_count = cleanup_s3_backups(backup_type, cutoff_date)
        total_s3 += s3_count
        print(f"  S3: {s3_count} files deleted")

    print("-" * 60)
    print(f"Cleanup complete!")
    print(f"Total: {total_local} local folders, {total_s3} S3 files deleted")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nCleanup interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)

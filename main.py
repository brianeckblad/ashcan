#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Command-line interface tool for batch processing comic book inventory.

This module provides utilities to process CSV files, validate comic listings,
upload images to AWS S3, manage SKU generation, and handle bulk deletion
of inventory items. It integrates with the Flask application's validation
and storage services.
"""

import warnings
# Suppress warnings about Boto3 Python version compatibility
warnings.filterwarnings('ignore', message='.*Boto3 will no longer support Python.*')

import csv
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Import validation and storage utilities from the application
from app.utils.whatnot_validators import WHATNOT_FIELD_VALIDATION, validate_whatnot_data
from app.services.s3_service import s3_service

# Configuration paths and settings
# Directory where comic images are stored locally before uploading
COMIC_IMAGE_PATH = os.environ.get('COMIC_IMAGE_PATH', 'instance/item_images')
# Supported image file formats
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
# Path to the CSV file containing the comic inventory
EXPORT_FILE = Path('instance/items.csv')
# Path to the file that tracks the highest SKU number issued
SKU_TRACKER_FILE = Path('instance/sku.txt')


def get_next_sku():
    """
    Generate the next sequential SKU number and persist it to file and S3.

    This function reads the current highest SKU from the tracker file,
    increments it, saves the new value, and backs it up to S3 for durability.
    Starts from SKU 1001 if no tracker file exists.

    Returns:
        str: The next available SKU number as a string.
    """
    # Ensure the tracker file directory exists
    SKU_TRACKER_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Default starting SKU if no file exists
    last_sku = 1000
    if SKU_TRACKER_FILE.exists():
        try:
            with open(SKU_TRACKER_FILE, 'r') as f:
                last_sku = int(f.read().strip())
        except (ValueError, IOError):
            # Invalid file content - use default
            last_sku = 1000

    # Increment to get the next SKU
    next_sku = last_sku + 1

    # Persist the new SKU value locally
    with open(SKU_TRACKER_FILE, 'w') as f:
        f.write(f"{next_sku}\n")

    # Backup to S3 for durability across deployments
    try:
        s3_service.backup_sku_to_s3(next_sku)
    except Exception as e:
        pass  # Silently fail if S3 backup unavailable

    return str(next_sku)


def get_item_images(comic_number):
    """
    Retrieve the list of image files for a specific comic from the local filesystem.

    Looks for images in the directory named 'comic<number>' under COMIC_IMAGE_PATH.
    Returns up to 8 images (the Whatnot limit) in sorted order.

    Args:
        comic_number (int): The sequential comic number (e.g., 1 for comic1).

    Returns:
        list: List of image file paths, or empty list if directory doesn't exist.
    """
    # Construct the path to the comic's image directory
    comic_dir = Path(COMIC_IMAGE_PATH) / f'comic{comic_number}'

    if not comic_dir.exists():
        return []

    images = []
    try:
        # Read all valid image files from the directory, up to 8 total
        for file_path in sorted(comic_dir.iterdir()):
            if file_path.is_file() and file_path.suffix.lower() in IMAGE_EXTENSIONS:
                images.append(str(file_path))
                if len(images) >= 8:
                    break
    except (PermissionError, OSError):
        return []

    return images


def apply_defaults(row):
    """
    Apply default values to a comic row for any missing required fields.

    Uses the field defaults defined in WHATNOT_FIELD_VALIDATION to fill
    in missing values. This ensures new comics have sensible defaults
    before validation and upload.

    Args:
        row (dict): The comic data row to update with defaults.
    """
    for field_name, rules in WHATNOT_FIELD_VALIDATION.items():
        if 'default' in rules:
            # Only apply default if field is empty or missing
            if not row.get(field_name) or str(row.get(field_name)).strip() == '':
                row[field_name] = rules['default']


def populate_image_placeholders(row, images):
    """
    Fill image URL fields with placeholder values for validation purposes.

    This allows the CSV to pass validation before actual image uploads.
    Placeholders are later replaced with real S3 URLs during upload.

    Args:
        row (dict): The comic data row to update.
        images (list): List of local image file paths.
    """
    from app.utils.whatnot_validators import WHATNOT_FIELD_NAMES as WFN

    for i in range(1, 9):
        field_name = WFN[f'IMAGE_URL_{i}']
        # Use placeholder if image exists, empty string otherwise
        row[field_name] = 'placeholder' if i <= len(images) else ''


def upload_and_populate_images(row, images, comic_number):
    """
    Upload images to S3 and populate the row with the resulting S3 URLs.

    For each local image file, uploads both a full-size and thumbnail version
    to S3, then updates the row with the S3 URLs for storage in the CSV.

    Args:
        row (dict): The comic data row to update with S3 image URLs.
        images (list): List of local image file paths to upload.
        comic_number (int): The comic number (for logging purposes).
    """
    from app.utils.whatnot_validators import WHATNOT_FIELD_NAMES as WFN

    for i in range(1, 9):
        field_name = WFN[f'IMAGE_URL_{i}']
        if i <= len(images):
            local_image_path = images[i - 1]
            filename = Path(local_image_path).name
            # S3 key is auto-prefixed with '{s3_folder}/images/' by upload_file()
            s3_key = filename

            result = s3_service.upload_file(local_image_path, s3_key, create_thumb=True)

            if result and result.get('full'):
                # Store the full-size S3 URL in the CSV
                row[field_name] = result['full']
            else:
                # Upload failed - leave field empty
                row[field_name] = ''
        else:
            # No image for this slot
            row[field_name] = ''


def process_and_validate_csv(input_file, output_file=None):
    """
    Process a CSV file: apply defaults, validate, upload images, and save to inventory.

    This function performs a two-pass approach:
    1. First pass: reads, applies defaults, validates (no uploads yet)
    2. Second pass: uploads images and updates rows with S3 URLs

    This ensures validation happens before any costly S3 operations, allowing
    early error detection without partial uploads.

    Args:
        input_file (str/Path): Path to the input CSV file to process.
        output_file (str/Path, optional): Path to output CSV. Defaults to instance/items.csv.

    Exits with code 1 if validation fails.
    """
    if output_file is None:
        output_file = EXPORT_FILE
    else:
        output_file = Path(output_file)

    # Use the field names from validation rules as the CSV column headers
    headers = list(WHATNOT_FIELD_VALIDATION.keys())
    rows = []
    images_by_row = {}
    has_errors = False

    # First pass: Read CSV, apply defaults, validate (no uploads yet)
    with open(input_file, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)

        for idx, row in enumerate(reader, start=2):
            from app.utils.whatnot_validators import WHATNOT_FIELD_NAMES as WFN

            comic_number = idx - 1

            # Create a clean row with only expected fields, preserving existing CSV values
            clean_row = {field: row.get(field, '').strip() for field in headers}

            # Determine if this is a re-export (has SKU) or a new comic (no SKU)
            has_existing_sku = clean_row.get(WFN['SKU'], '').strip() != ''
            has_existing_images = any(clean_row.get(WFN[f'IMAGE_URL_{i}'], '').strip() for i in range(1, 9))

            if has_existing_sku:
                # This is a re-export - preserve all existing values
                # Only look for new local images if CSV has no images
                if not has_existing_images:
                    images = get_item_images(comic_number)
                    images_by_row[idx] = images
                else:
                    # CSV already has images - no need for local lookup
                    images_by_row[idx] = []
            else:
                # This is a new comic - generate SKU and look for local images
                # Fill in missing fields with default values
                apply_defaults(clean_row)

                # Generate a new unique SKU for this comic
                clean_row[WFN['SKU']] = get_next_sku()

                # Get images from local directory
                images = get_item_images(comic_number)
                images_by_row[idx] = images

                # Add placeholder image URLs for validation
                populate_image_placeholders(clean_row, images)

            # Validate the row against Whatnot requirements
            is_valid, errors = validate_whatnot_data(clean_row)
            if not is_valid:
                has_errors = True
            rows.append(clean_row)

    # Stop if validation failed to prevent partial uploads
    if has_errors:
        sys.exit(1)

    # Second pass: Upload images and update rows with S3 URLs
    has_uploads = any(images_by_row.values())
    if has_uploads:
        for idx, row in enumerate(rows, start=2):
            comic_number = idx - 1
            images = images_by_row[idx]
            if images:
                upload_and_populate_images(row, images, comic_number)

    # Ensure output directory exists
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Determine if we need to write the CSV header
    file_exists = output_file.exists()
    write_header = not file_exists or output_file.stat().st_size == 0

    # Append rows to the output CSV file
    with open(output_file, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)

    print(f"\n✓ Processed {len(rows)} rows and appended to {output_file}")


def delete_all_s3():
    """
    Delete all images from the S3 bucket and clear the local inventory file.

    Retrieves the bucket name from the application configuration, deletes all
    objects in the bucket's images folder, and then removes the local CSV
    inventory file to maintain consistency.

    Returns:
        bool: True if deletion succeeded, False otherwise.
    """
    try:
        # Get S3 bucket name from the application configuration
        from app.config import Config
        bucket = Config.S3_BUCKET

        if not bucket:
            print("❌ Error: S3_BUCKET not configured in environment variables")
            sys.exit(1)

        print(f"📦 Fetching objects from bucket {bucket}...")

        # Delete all files from the S3 bucket using the service
        success, count = s3_service.delete_all_files()

        if success:
            print(f"\n✓ Successfully deleted {count} images from {bucket}/images/")

            # Also delete the local CSV file to maintain consistency
            if EXPORT_FILE.exists():
                EXPORT_FILE.unlink()
                print(f"✓ Deleted {EXPORT_FILE}")

            return True
        else:
            print(f"\n❌ Failed to delete objects from {bucket}")
            return False

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def format_size(size_bytes):
    """
    Convert a size in bytes to a human-readable format.

    Automatically converts to the appropriate unit (B, KB, MB, GB, TB)
    based on the magnitude of the size.

    Args:
        size_bytes (int): The number of bytes to format.

    Returns:
        str: Human-readable size string (e.g., "1.5 MB").
    """
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def get_single_key():
    """
    Read a single keyboard input without waiting for Enter key.

    Works on Unix-like systems (using termios) and Windows (using msvcrt).
    Allows the user to press a single key and have it registered immediately.

    Returns:
        str: The character that was pressed.
    """
    try:
        # Unix/Linux/Mac implementation using termios
        import tty
        import termios
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            # Switch terminal to raw mode (no line buffering)
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            # Handle Ctrl+C gracefully
            if ch == '\x03':
                raise KeyboardInterrupt
        finally:
            # Restore original terminal settings
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch
    except ImportError:
        # Windows fallback using msvcrt
        import msvcrt
        return msvcrt.getch().decode('utf-8', errors='ignore')


def get_input_with_esc(prompt, mask=False):
    """
    Read user input from the terminal, with ESC key to cancel.

    Prompts the user for input and returns it, or returns None if the
    user presses the Escape key to cancel the operation.

    Args:
        prompt (str): The prompt message to display to the user.
        mask (bool): If True, mask the input (e.g., for passwords). Defaults to False.

    Returns:
        str: The user's input, or None if ESC was pressed to cancel.
    """
    sys.stdout.write(prompt)
    sys.stdout.flush()
    
    result = ""
    while True:
        # Get a single character without waiting for Enter
        ch = get_single_key()
        if ch == '\x1b':  # ESC key

            print("\n❌ Cancelled.")
            return None
        if ch in ('\r', '\n'): # ENTER
            print()
            break
        if ord(ch) == 127: # Backspace
            if len(result) > 0:
                result = result[:-1]
                sys.stdout.write('\b \b')
                sys.stdout.flush()
        elif ord(ch) >= 32:
            result += ch
            if mask:
                sys.stdout.write('*')
            else:
                sys.stdout.write(ch)
            sys.stdout.flush()
            
    return result.strip()


def s3_management_menu():
    """Interactive S3 management menu."""
    from app.config import Config
    bucket = Config.S3_BUCKET

    if not bucket:
        print("❌ Error: S3_BUCKET not configured in environment variables")
        sys.exit(1)

    while True:
        try:
            print("\n" + "="*60)
            print("🗄️  S3 MANAGEMENT MENU")
            print("="*60)
            print("\n1. Delete Pending Inventory - Remove pending CSV export and all images")
            print("2. Delete Backups           - Remove all backups in /backups folder")
            print("3. Delete Exports           - Remove all CSV exports in /exports folder")
            print("4. Manage SKU               - View/reset/change comic SKU in S3")
            print("5. Exit")
            print("\n" + "-"*60)
            print("(Press Ctrl+C or ESC to exit)")
            sys.stdout.write("\nSelect option (1-5): ")
            sys.stdout.flush()
            
            choice = get_single_key()
            
            # Show the choice if it's a valid digit, or handle ESC
            if choice == '\x1b':
                print("\n\n👋 Exiting S3 Management")
                break
            
            if choice in ('1', '2', '3', '4', '5'):
                print(choice)  # Echo the valid choice
            else:
                if ord(choice) >= 32: # Printable
                    print(choice)
                else:
                    print()
            
            if choice == '1':
                delete_s3_images(bucket)
            elif choice == '2':
                delete_s3_backups(bucket)
            elif choice == '3':
                delete_s3_exports(bucket)
            elif choice == '4':
                reset_s3_sku(bucket)
            elif choice == '5' or choice == '':
                print("\n👋 Exiting S3 Management")
                break
            else:
                print("❌ Invalid option. Please select 1-5.")

        except (KeyboardInterrupt, EOFError):
            print("\n\n👋 Exiting S3 Management")
            break


def delete_s3_backups(bucket):
    """Delete all backup folders from S3."""
    try:
        print("\n📦 Fetching backup objects from bucket...")
        all_objects = s3_service.list_all_files()
        objects = [obj for obj in all_objects if obj['Key'].startswith('backups/')]

        if not objects:
            print("✓ No backup objects found. Nothing to delete.")
            return

        total_size = sum(obj['Size'] for obj in objects)
        print(f"\n📋 Found {len(objects)} backup objects ({format_size(total_size)}):\n")
        print("-" * 80)

        # Show sample of files (first 20)
        for obj in objects[:20]:
            size_str = format_size(obj['Size'])
            date_str = obj['LastModified'].strftime('%Y-%m-%d %H:%M')
            print(f"  {obj['Key']:<50} {size_str:>10}  {date_str}")

        if len(objects) > 20:
            print(f"  ... and {len(objects) - 20} more files")
        print("-" * 80)

        print("\n⚠️  WARNING: This will permanently delete all backups from S3!")
        confirm = get_input_with_esc("Type 'DELETE' to confirm (or ESC to cancel): ")
        if confirm is None:
            return

        confirm = confirm.upper()

        if confirm in ('DELETE', 'D'):
            print("\n🗑️  Deleting backups...")
            keys_to_delete = [obj['Key'] for obj in objects]
            s3_service.delete_files(keys_to_delete)
            print(f"✓ Deleted {len(objects)} backup objects")
        else:
            print("❌ Cancelled.")
    except (KeyboardInterrupt, EOFError):
        print("\n❌ Cancelled.")


def delete_s3_exports(bucket):
    """Delete all CSV exports from S3."""
    try:
        print("\n📦 Fetching export objects from bucket...")
        all_objects = s3_service.list_all_files()
        objects = [obj for obj in all_objects if obj['Key'].startswith('exports/')]

        if not objects:
            print("✓ No export objects found. Nothing to delete.")
            return

        total_size = sum(obj['Size'] for obj in objects)
        print(f"\n📋 Found {len(objects)} export objects ({format_size(total_size)}):\n")
        print("-" * 80)

        # Show sample of files (first 20)
        for obj in objects[:20]:
            size_str = format_size(obj['Size'])
            date_str = obj['LastModified'].strftime('%Y-%m-%d %H:%M')
            print(f"  {obj['Key']:<50} {size_str:>10}  {date_str}")

        if len(objects) > 20:
            print(f"  ... and {len(objects) - 20} more files")
        print("-" * 80)

        print("\n⚠️  WARNING: This will permanently delete all CSV exports from S3!")
        confirm = get_input_with_esc("Type 'DELETE' to confirm (or ESC to cancel): ")
        if confirm is None:
            return

        confirm = confirm.upper()

        if confirm in ('DELETE', 'D'):
            print("\n🗑️  Deleting exports...")
            keys_to_delete = [obj['Key'] for obj in objects]
            s3_service.delete_files(keys_to_delete)
            print(f"✓ Deleted {len(objects)} export objects")
        else:
            print("❌ Cancelled.")
    except (KeyboardInterrupt, EOFError):
        print("\n❌ Cancelled.")


def delete_s3_images(bucket):
    """Delete all images from S3 and clear local pending CSV export."""
    try:
        print("\n📦 Fetching image objects from bucket...")
        all_objects = s3_service.list_all_files()
        objects = [obj for obj in all_objects if obj['Key'].startswith('images/')]

        if not objects:
            print("✓ No image objects found in S3.")
        else:
            total_size = sum(obj['Size'] for obj in objects)
            print(f"\n📋 Found {len(objects)} image objects ({format_size(total_size)}):\n")
            print("-" * 80)

            # Show sample of files (first 20)
            for obj in objects[:20]:
                size_str = format_size(obj['Size'])
                date_str = obj['LastModified'].strftime('%Y-%m-%d %H:%M')
                print(f"  {obj['Key']:<50} {size_str:>10}  {date_str}")

            if len(objects) > 20:
                print(f"  ... and {len(objects) - 20} more files")
            print("-" * 80)

        print("\n⚠️  WARNING: This will permanently delete:")
        print("   • All comic images from S3 (/images folder)")
        print("   • Local pending CSV export (items.csv)")
        confirm = get_input_with_esc("\nType 'DELETE' to confirm (or ESC to cancel): ")
        if confirm is None:
            return

        confirm = confirm.upper()

        if confirm in ('DELETE', 'D'):
            # Delete images from S3
            if objects:
                print("\n🗑️  Deleting images from S3...")
                keys_to_delete = [obj['Key'] for obj in objects]
                s3_service.delete_files(keys_to_delete)
                print(f"✓ Deleted {len(objects)} image objects from S3")

            # Clear local CSV export file
            try:
                from app.config import Config
                csv_path = Config.CSV_FILE if hasattr(Config, 'CSV_FILE') else 'instance/items.csv'
                if os.path.exists(csv_path):
                    # Clear the CSV but keep the header
                    from app.services.csv_service import CSVService
                    csv_service = CSVService(csv_path)
                    csv_service.clear_all()
                    print(f"✓ Cleared local pending CSV export")
                else:
                    print("✓ No local CSV export to clear")
            except Exception as e:
                print(f"⚠️  Could not clear local CSV: {e}")

            print("\n✅ Pending inventory cleared successfully!")
        else:
            print("❌ Cancelled.")
    except (KeyboardInterrupt, EOFError):
        print("\n❌ Cancelled.")


def restart_application():
    """Restart the application and wait for it to come back online."""
    import subprocess
    import time

    # Get service name from environment or use default
    # This should match the service name configured in deployment/group_vars/all.yml
    service_name = os.environ.get('APP_SERVICE_NAME', os.environ.get('APP_NAME', 'your_app_name'))

    try:
        # Send restart command
        result = subprocess.run(['supervisorctl', 'restart', service_name],
                              capture_output=True, text=True, timeout=10)

        if result.returncode != 0:
            print(f"⚠️  Could not restart application: {result.stderr}")
            print(f"   Please manually restart with: sudo supervisorctl restart {service_name}")
            return False

        print("✓ Restart command sent")

        # Wait for application to restart
        print("⏳ Waiting for application to restart", end="", flush=True)
        max_wait = 30  # seconds
        check_interval = 2  # seconds
        elapsed = 0

        while elapsed < max_wait:
            time.sleep(check_interval)
            elapsed += check_interval
            print(".", end="", flush=True)

            # Check if application is running
            try:
                status_result = subprocess.run(['supervisorctl', 'status', service_name],
                                             capture_output=True, text=True, timeout=5)
                if 'RUNNING' in status_result.stdout:
                    print("\n✅ Application restarted successfully!")
                    return True
            except Exception:
                pass

        print(f"\n⚠️  Application restart timed out after 30 seconds")
        print(f"   Please check status with: sudo supervisorctl status {service_name}")
        return False

    except FileNotFoundError:
        print("⚠️  supervisorctl not found - please manually restart the application")
        print(f"   Run: sudo supervisorctl restart {service_name}")
        return False
    except subprocess.TimeoutExpired:
        print("⚠️  Restart command timed out - please check application status")
        return False
    except Exception as restart_err:
        print(f"⚠️  Could not restart application: {restart_err}")
        print(f"   Please manually restart with: sudo supervisorctl restart {service_name}")
        return False


def reset_s3_sku(bucket):
    """Reset or change the SKU file in S3."""
    try:
        print("\n📦 SKU Management in S3...")

        try:
            # Get current SKU from S3
            sku_data = s3_service.restore_sku_from_s3()

            if sku_data is not None:
                current_sku = sku_data['sku']
                print(f"\n📋 Current SKU in S3: {current_sku}")
            else:
                print("\n📋 No SKU file found in S3")
                current_sku = 1000
        except Exception as e:
            print(f"\n⚠️  Could not read current SKU: {e}")
            current_sku = 1000

        print("\nOptions:")
        print("1. Reset to 1000 (default - next SKU will be 1001)")
        print("2. Set to custom value (e.g., set to 1029 if that's the last used SKU)")
        print("3. Delete images for specific SKU")
        print("4. Cancel")

        sys.stdout.write("\nSelect option (1-4, or ESC to cancel): ")
        sys.stdout.flush()
        
        choice = get_single_key()
        if choice == '\x1b':
            print("\n❌ Cancelled.")
            return
        
        if choice in ('1', '2', '3', '4'):
            print(choice)
        else:
            if ord(choice) >= 32:
                print(choice)
            else:
                print()
        
        if choice == '1':
            # ... (reset to 1000 logic)
            new_sku = 1000
            print(f"\n⚠️  WARNING: This will change the SKU from {current_sku} to {new_sku}!")
            confirm = get_input_with_esc("Type 'YES' to confirm (or ESC to cancel): ")
            if confirm is None:
                return
            
            confirm = confirm.upper()

            if confirm in ('YES', 'Y'):
                try:
                    # Update local SKU file first
                    from app.config import Config
                    from pathlib import Path
                    sku_file = Path(Config.SKU_FILE) if hasattr(Config, 'SKU_FILE') else Path('instance/sku.txt')
                    sku_file.parent.mkdir(parents=True, exist_ok=True)

                    with open(sku_file, 'w') as f:
                        f.write(f"{new_sku}\n")
                    print(f"✓ Local SKU file updated to {new_sku}")

                    # Upload to S3 using the backup function
                    s3_service.backup_sku_to_s3(new_sku)
                    print(f"✓ SKU backed up to S3: {new_sku}")

                    # Verify the update
                    verify_data = s3_service.restore_sku_from_s3()
                    if verify_data and verify_data['sku'] == new_sku:
                        print(f"✅ SKU successfully updated to {new_sku}")

                        # Restart the application if running under supervisor
                        print("\n🔄 Restarting application to apply SKU change...")
                        restart_application()
                    else:
                        verify_sku_val = verify_data['sku'] if verify_data else 'None'
                        print(f"⚠️  Verification mismatch - S3 shows: {verify_sku_val}")
                except Exception as e:
                    print(f"❌ Error updating SKU: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                print("❌ Cancelled.")

        elif choice == '2':
            custom_value = get_input_with_esc("\nEnter the LAST USED SKU number (next SKU will be +1) or ESC to cancel: ")
            if custom_value is None:
                return

            try:
                new_sku = int(custom_value)
                if new_sku < 1:
                    print("❌ SKU must be a positive number")
                    return

                print(f"\n⚠️  WARNING: This will set last used SKU from {current_sku} to {new_sku}!")
                print(f"           The NEXT SKU assigned will be {new_sku + 1}")
                confirm = get_input_with_esc("Type 'YES' to confirm (or ESC to cancel): ")
                if confirm is None:
                    return
                
                confirm = confirm.upper()

                if confirm in ('YES', 'Y'):
                    # Update local SKU file first
                    from app.config import Config
                    from pathlib import Path
                    sku_file = Path(Config.SKU_FILE) if hasattr(Config, 'SKU_FILE') else Path('instance/sku.txt')
                    sku_file.parent.mkdir(parents=True, exist_ok=True)

                    with open(sku_file, 'w') as f:
                        f.write(f"{new_sku}\n")
                    print(f"✓ Local SKU file updated to {new_sku}")

                    # Upload to S3 using the backup function
                    s3_service.backup_sku_to_s3(new_sku)
                    print(f"✓ SKU backed up to S3: {new_sku}")

                    # Verify the update
                    verify_data = s3_service.restore_sku_from_s3()
                    if verify_data and verify_data['sku'] == new_sku:
                        print(f"✅ SKU successfully updated to {new_sku}")

                        # Restart the application if running under supervisor
                        print("\n🔄 Restarting application to apply SKU change...")
                        restart_application()
                    else:
                        verify_sku_val = verify_data['sku'] if verify_data else 'None'
                        print(f"⚠️  Verification mismatch - S3 shows: {verify_sku_val}")
                else:
                    print("❌ Cancelled.")
            except ValueError:
                print("❌ Invalid number. Please enter a valid SKU number.")
            except Exception as e:
                print(f"❌ Error updating SKU: {e}")

        elif choice == '3':
            # Delete images for specific SKU
            try:
                # 1. Load all SKUs from CSV
                from app.config import Config
                from pathlib import Path
                import csv
                
                # Use a more robust path discovery
                basedir = Path(__file__).parent
                csv_file = basedir / 'instance' / 'items.csv'
                
                # If that fails, try the config value
                if not csv_file.exists() and hasattr(Config, 'CSV_FILE'):
                    csv_file = Path(Config.CSV_FILE)
                
                print(f"🔍 Checking inventory file: {csv_file}")
                
                skus_with_titles = []
                if csv_file.exists():
                    with open(csv_file, 'r', encoding='utf-8-sig') as f:
                        # Use DictReader which handles headers
                        reader = csv.DictReader(f)
                        # Normalize headers to handle case differences
                        fieldnames = [fn.strip().upper() for fn in reader.fieldnames] if reader.fieldnames else []
                        
                        sku_col = 'SKU' if 'SKU' in fieldnames else None
                        title_col = 'TITLE' if 'TITLE' in fieldnames else None
                        
                        # If headers aren't normalized, try finding the index
                        if not sku_col:
                            for idx, fn in enumerate(reader.fieldnames or []):
                                if fn.strip().upper() == 'SKU':
                                    sku_col = fn
                                    break
                        
                        if not title_col:
                            for idx, fn in enumerate(reader.fieldnames or []):
                                if fn.strip().upper() == 'TITLE':
                                    title_col = fn
                                    break

                        # Reset file pointer and re-read if we found columns
                        f.seek(0)
                        next(reader) # skip header
                        
                        for row in reader:
                            sku_val = row.get('SKU') or row.get(sku_col) if sku_col else None
                            title_val = row.get('Title') or row.get(title_col) if title_col else 'No Title'
                            
                            if sku_val and sku_val.strip():
                                skus_with_titles.append({
                                    'sku': sku_val.strip(),
                                    'title': title_val.strip()[:40] if title_val else 'No Title'
                                })
                else:
                    print(f"⚠️  Inventory file not found at: {csv_file}")
                
                if not skus_with_titles:
                    print("\n⚠️  No SKUs found in the inventory CSV.")
                    sku_to_delete = get_input_with_esc("\nEnter SKU manually (or ESC to cancel): ")
                    if not sku_to_delete:
                        return
                else:
                    # Sort by SKU
                    skus_with_titles.sort(key=lambda x: x['sku'])
                    
                    print(f"\n📋 Available SKUs ({len(skus_with_titles)} found):")
                    
                    # Display in pages if many
                    page_size = 20
                    current_page = 0
                    total_pages = (len(skus_with_titles) + page_size - 1) // page_size
                    
                    sku_to_delete = None
                    while sku_to_delete is None:
                        start_idx = current_page * page_size
                        end_idx = min(start_idx + page_size, len(skus_with_titles))
                        
                        print(f"\n--- Page {current_page + 1} of {total_pages} ---")
                        for i in range(start_idx, end_idx):
                            item = skus_with_titles[i]
                            print(f"{i+1:3}. SKU: {item['sku']:6} | {item['title']}")
                        
                        print("\nOptions: (Enter number to select, 'N' for next, 'P' for previous, 'M' for manual, ESC to cancel)")
                        cmd = get_input_with_esc("Selection: ")
                        
                        if cmd is None: # ESC
                            return
                        
                        cmd = cmd.strip().upper()
                        if cmd == 'N':
                            if current_page < total_pages - 1:
                                current_page += 1
                            else:
                                print("ℹ️  Already at last page.")
                        elif cmd == 'P':
                            if current_page > 0:
                                current_page -= 1
                            else:
                                print("ℹ️  Already at first page.")
                        elif cmd == 'M':
                            sku_to_delete = get_input_with_esc("\nEnter SKU manually: ")
                            if not sku_to_delete:
                                return
                        else:
                            try:
                                idx = int(cmd) - 1
                                if 0 <= idx < len(skus_with_titles):
                                    sku_to_delete = skus_with_titles[idx]['sku']
                                else:
                                    print(f"❌ Invalid selection. Please enter 1-{len(skus_with_titles)}")
                            except ValueError:
                                print("❌ Invalid command.")

                print(f"\n🔍 Searching for images for SKU: {sku_to_delete}...")
                
                # 2. Find local images
                instance_path = Path(Config.UPLOAD_FOLDER).parent if hasattr(Config, 'UPLOAD_FOLDER') else Path('instance')
                local_images_dir = instance_path / 'images'
                
                local_files_to_delete = []
                if local_images_dir.exists():
                    prefix = f"{sku_to_delete}_"
                    local_files_to_delete = [f for f in local_images_dir.iterdir() if f.is_file() and f.name.startswith(prefix)]

                # 3. Find S3 images
                bucket_name = s3_service.bucket_name
                s3_keys_to_delete = []
                if bucket_name:
                    paginator = s3_service.client().get_paginator('list_objects_v2')
                    pages = paginator.paginate(Bucket=bucket_name, Prefix=f"images/{sku_to_delete}_")
                    for page in pages:
                        if 'Contents' in page:
                            for obj in page['Contents']:
                                s3_keys_to_delete.append(obj['Key'])

                if not local_files_to_delete and not s3_keys_to_delete:
                    print(f"ℹ️  No images found for SKU {sku_to_delete} (Local or S3)")
                    return

                print(f"\nFound:")
                print(f"   - {len(local_files_to_delete)} local files")
                print(f"   - {len(s3_keys_to_delete)} S3 objects")
                
                confirm = get_input_with_esc(f"\n⚠️  Are you sure you want to delete ALL images for SKU {sku_to_delete}? Type 'YES' to confirm: ")
                if confirm and confirm.upper() in ('YES', 'Y'):
                    # Delete local
                    deleted_local = 0
                    for f in local_files_to_delete:
                        try:
                            f.unlink()
                            deleted_local += 1
                        except Exception as e:
                            print(f"   ❌ Error deleting local file {f.name}: {e}")
                    
                    # Delete S3
                    deleted_s3 = 0
                    if s3_keys_to_delete:
                        deleted_s3 = s3_service.delete_files(s3_keys_to_delete)
                    
                    print(f"\n✅ Deletion complete:")
                    print(f"   - {deleted_local} local files deleted")
                    print(f"   - {deleted_s3} S3 objects deleted")
                else:
                    print("❌ Cancelled.")

            except Exception as e:
                print(f"❌ Error during SKU image deletion: {e}")

        else:
            print("❌ Cancelled.")

    except (KeyboardInterrupt, EOFError):
        print("\n❌ Cancelled.")


def account_management_menu():
    """Interactive account management menu."""
    from app import create_app
    from werkzeug.security import generate_password_hash
    
    app = create_app()
    
    with app.app_context():
        from app.models.user import user_manager
        
        while True:
            try:
                print("\n" + "="*60)
                print("👤 ACCOUNT MANAGEMENT")
                print("="*60)
                print("\n1. List Users       - Show all configured users")
                print("2. Create User      - Add a new user account")
                print("3. Reset Password   - Change password for existing user")
                print("4. Delete User      - Remove a user account")
                print("5. Reset to Default - Reset all users to admin:admin123")
                print("6. Exit")
                print("\n" + "-"*60)
                print("(Press Ctrl+C or ESC to exit)")
                sys.stdout.write("\nSelect option (1-6): ")
                sys.stdout.flush()
                
                choice = get_single_key()
                
                # Handle ESC
                if choice == '\x1b':
                    print("\n\n👋 Exiting Account Management")
                    break
                
                if choice in ('1', '2', '3', '4', '5', '6'):
                    print(choice)  # Echo the choice
                else:
                    if ord(choice) >= 32:
                        print(choice)
                    else:
                        print()
                
                if choice == '1':
                    # List users
                    users = user_manager.list_users()
                    if not users:
                        print("\n📋 No users configured")
                    else:
                        print(f"\n📋 Configured users ({len(users)}):")
                        for username in users:
                            print(f"   • {username}")
                
                elif choice == '2':
                    # Create user
                    print("\n➕ Create New User")
                    username = get_input_with_esc("Username (or ESC to cancel): ")
                    if username is None:
                        continue
                    
                    username = username.strip()
                    if not username:
                        print("❌ Username cannot be empty")
                        continue
                    
                    password = get_input_with_esc("Password (or ESC to cancel): ", mask=True)
                    if password is None:
                        continue
                    
                    password2 = get_input_with_esc("Confirm password: ", mask=True)
                    if password2 is None:
                        continue
                    
                    if password != password2:
                        print("❌ Passwords do not match")
                        continue
                    
                    success, message = user_manager.create_user(username, password)
                    if success:
                        print(f"✅ {message}")
                    else:
                        print(f"❌ {message}")
                
                elif choice == '3':
                    # Reset password
                    print("\n🔑 Reset Password")
                    username = get_input_with_esc("Username (or ESC to cancel): ")
                    if username is None:
                        continue
                    
                    username = username.strip()
                    if not username:
                        print("❌ Username cannot be empty")
                        continue
                    
                    # Check if user exists
                    users = user_manager._load_users()
                    if username.lower() not in users:
                        print(f"❌ User '{username}' not found")
                        continue
                    
                    new_password = get_input_with_esc("New password (or ESC to cancel): ", mask=True)
                    if new_password is None:
                        continue
                    
                    new_password2 = get_input_with_esc("Confirm new password: ", mask=True)
                    if new_password2 is None:
                        continue
                    
                    if new_password != new_password2:
                        print("❌ Passwords do not match")
                        continue
                    
                    # Force reset password
                    users[username.lower()]['password_hash'] = generate_password_hash(new_password)
                    user_manager._save_users(users)
                    print(f"✅ Password for '{username}' has been reset")
                
                elif choice == '4':
                    # Delete user
                    print("\n🗑️  Delete User")
                    username = get_input_with_esc("Username to delete (or ESC to cancel): ")
                    if username is None:
                        continue
                    
                    username = username.strip()
                    if not username:
                        print("❌ Username cannot be empty")
                        continue
                    
                    confirm = get_input_with_esc(f"Type '{username}' to confirm deletion: ")
                    if confirm != username:
                        print("❌ Cancelled - username did not match")
                        continue
                    
                    success, message = user_manager.delete_user(username)
                    if success:
                        print(f"✅ {message}")
                    else:
                        print(f"❌ {message}")
                
                elif choice == '5':
                    # Reset all users
                    print("\n⚠️  Reset All Users to Default")
                    print("This will delete all users and create default admin account:")
                    print("   Username: admin")
                    print("   Password: admin123")
                    
                    confirm = get_input_with_esc("\nType 'YES' to confirm (or ESC to cancel): ")
                    if confirm is None or confirm.upper() not in ('YES', 'Y'):
                        print("❌ Cancelled")
                        continue
                    
                    try:
                        users_file = user_manager._get_users_file()
                        if users_file.exists():
                            users_file.unlink()
                        
                        # Trigger initialization from env
                        user_manager._initialize_from_env()
                        
                        print("\n✅ Users reset to default:")
                        for username in user_manager.list_users():
                            print(f"   • {username}")
                    except Exception as e:
                        print(f"❌ Error resetting users: {e}")
                
                elif choice == '6':
                    print("\n👋 Exiting Account Management")
                    break
                else:
                    print("❌ Invalid option. Please select 1-6.")
            
            except (KeyboardInterrupt, EOFError):
                print("\n\n👋 Exiting Account Management")
                break


def main():
    """Main entry point."""
    # Handle -s3 flag for S3 management menu
    if len(sys.argv) > 1 and sys.argv[1] == '-s3':
        s3_management_menu()
        sys.exit(0)
    
    # Handle -account flag for account management
    if len(sys.argv) > 1 and sys.argv[1] == '-account':
        account_management_menu()
        sys.exit(0)

    # Process CSV file
    if len(sys.argv) > 1:
        input_csv = sys.argv[1]

        # Check if it looks like a command (starts with -)
        if input_csv.startswith('-'):
            print(f"❌ Error: Command not found: '{input_csv}'")
            print("\n📋 Available commands:")
            print("   python main.py <input_csv_file>    - Process and validate a CSV file")
            print("   python main.py -s3                 - S3 management menu (delete backups/exports/images, reset SKU)")
            print("   python main.py -account            - Account management (create/delete users, reset passwords)")
            sys.exit(1)

        # Check if file exists
        if not os.path.exists(input_csv):
            print(f"❌ Error: File not found: '{input_csv}'")
            print("\n📋 Usage:")
            print("   python main.py <input_csv_file>    - Process and validate a CSV file")
            print("   python main.py -s3                 - S3 management menu")
            print("   python main.py -account            - Account management")
            sys.exit(1)

        process_and_validate_csv(input_csv)
    else:
        print("❌ Error: No input file or command specified")
        print("\n📋 Usage:")
        print("   python main.py <input_csv_file>    - Process and validate a CSV file")
        print("   python main.py -s3                 - S3 management menu")
        print("   python main.py -account            - Account management")
        print("\n📖 For more information, see the documentation.")
        sys.exit(1)


if __name__ == '__main__':
    main()

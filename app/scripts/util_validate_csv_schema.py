#!/usr/bin/env python3
"""
CSV Schema Validation Script

This script validates that the CSV file schema matches the Comic model fields
and the validation dictionaries. It prevents data loss by catching schema
mismatches BEFORE the application starts.

Usage:
    python validate_csv_schema.py [--csv-path PATH] [--fix]

Exit codes:
    0 = All validations passed
    1 = Validation failed (missing fields)
    2 = CSV file not found or unreadable
"""

import sys
import csv
import argparse
from pathlib import Path

# Add project root to path so we can import app modules
script_dir = Path(__file__).parent
project_root = script_dir.parent.parent  # Go up from scripts/ to deployment/ to project root
sys.path.insert(0, str(project_root))

from app.utils.whatnot_validators import (
    WHATNOT_FIELD_VALIDATION,
    WHATNOT_FIELD_NAMES,
    METADATA_FIELDS
)
from app.services.csv_service import (
    EBAY_METADATA_FIELDS,
    WHATNOT_LISTING_FIELDS,
    EBAY_ITEM_FIELDS,
    EBAY_ITEM_SPECIFICS_FIELDS,
)


def get_expected_fields():
    """Get all expected CSV field names from validation dictionaries."""
    expected_fields = set()

    # Add metadata fields
    expected_fields.update(METADATA_FIELDS)

    # Add eBay metadata fields
    expected_fields.update(EBAY_METADATA_FIELDS)

    # Add WhatNot listing fields
    expected_fields.update(WHATNOT_LISTING_FIELDS)

    # Add eBay item fields
    expected_fields.update(EBAY_ITEM_FIELDS)

    # Add eBay item specifics fields (C:*)
    expected_fields.update(EBAY_ITEM_SPECIFICS_FIELDS)

    # Add all WhatNot validated fields
    expected_fields.update(WHATNOT_FIELD_VALIDATION.keys())

    return expected_fields


def get_comic_model_fields():
    """Get all fields that Comic model's to_dict() can produce."""
    try:
        from app.models.comic import Comic
        from app.utils.whatnot_validators import WHATNOT_FIELD_NAMES as WN

        # Create minimal valid data dict for from_dict()
        minimal_data = {
            WN['SKU']: 'TEST',
            WN['CATEGORY']: 'Comics & Manga',
            WN['SUB_CATEGORY']: 'Modern Comics',
            WN['TITLE']: 'Test Comic',
            WN['DESCRIPTION']: 'Test Description',
            WN['PRICE']: '10.00',
            WN['QUANTITY']: '1',
            WN['SHIPPING_PROFILE']: 'Dynamic (Gemeni Mailer)',
            WN['OFFERABLE']: 'TRUE',
            WN['HAZMAT']: 'Not Hazmat',
            WN['CONDITION']: 'Near Mint'
        }

        # Use from_dict which handles all type conversions
        dummy_comic = Comic.from_dict(minimal_data)

        # Get all fields from to_dict()
        comic_dict = dummy_comic.to_dict()
        return set(comic_dict.keys())
    except Exception as e:
        # Silently fail - validation will still work with empty set
        return set()


def read_csv_headers(csv_path):
    """Read the CSV file headers."""
    try:
        with open(csv_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            headers = next(reader)
            return set(headers)
    except FileNotFoundError:
        print(f"❌ CSV file not found: {csv_path}")
        return None
    except Exception as e:
        print(f"❌ Error reading CSV file: {e}")
        return None


def validate_field_registration():
    """
    Validate that all fields are properly registered across all required locations.

    Checks:
    1. All Comic.to_dict() fields are in WHATNOT_FIELD_VALIDATION
    2. All validation fields are properly named
    3. Comic.from_dict() can handle all fields

    Returns:
        tuple: (is_valid, errors_list)
    """
    errors = []

    try:
        from app.models.comic import Comic
        from app.utils.whatnot_validators import WHATNOT_FIELD_NAMES as WN

        # Get Comic model fields from to_dict()
        minimal_data = {
            WN['SKU']: 'TEST',
            WN['CATEGORY']: 'Comics & Manga',
            WN['SUB_CATEGORY']: 'Modern Comics',
            WN['TITLE']: 'Test',
            WN['DESCRIPTION']: 'Test',
            WN['PRICE']: '10.00',
            WN['QUANTITY']: '1',
            WN['SHIPPING_PROFILE']: 'Dynamic (Gemeni Mailer)',
            WN['OFFERABLE']: 'TRUE',
            WN['HAZMAT']: 'Not Hazmat',
            WN['CONDITION']: 'Near Mint'
        }

        test_comic = Comic.from_dict(minimal_data)
        comic_dict_fields = set(test_comic.to_dict().keys())

        # Get validation fields
        validation_fields = get_expected_fields()

        # Check 1: All Comic.to_dict() fields must be in validation
        missing_from_validation = comic_dict_fields - validation_fields
        if missing_from_validation:
            errors.append({
                'severity': 'CRITICAL',
                'check': 'Comic.to_dict() → Validation Dict',
                'message': f'Fields in Comic.to_dict() but NOT in validation ({len(missing_from_validation)})',
                'fields': sorted(missing_from_validation),
                'fix': 'Add these fields to WHATNOT_FIELD_VALIDATION in app/utils/whatnot_validators.py'
            })

        # Check 2: All validation fields should have proper names
        field_names_set = set(WHATNOT_FIELD_NAMES.values())
        non_whatnot_fields = (
            set(METADATA_FIELDS)
            | set(EBAY_METADATA_FIELDS)
            | set(WHATNOT_LISTING_FIELDS)
            | set(EBAY_ITEM_FIELDS)
            | set(EBAY_ITEM_SPECIFICS_FIELDS)
        )
        validation_not_in_names = validation_fields - field_names_set - non_whatnot_fields

        if validation_not_in_names:
            errors.append({
                'severity': 'WARNING',
                'check': 'Validation Dict → WHATNOT_FIELD_NAMES',
                'message': f'Fields in validation but not in WHATNOT_FIELD_NAMES ({len(validation_not_in_names)})',
                'fields': sorted(validation_not_in_names),
                'fix': 'Add these fields to WHATNOT_FIELD_NAMES dictionary'
            })

        # Check 3: from_dict() can handle all validation fields
        try:
            test_data = minimal_data.copy()
            # Add all validation fields with empty strings
            for field in validation_fields:
                if field not in test_data:
                    test_data[field] = ''

            test_comic2 = Comic.from_dict(test_data)
        except Exception as e:
            errors.append({
                'severity': 'WARNING',
                'check': 'Comic.from_dict() compatibility',
                'message': f'Comic.from_dict() may not handle all fields properly',
                'fields': [],
                'fix': f'Review Comic.from_dict() method: {str(e)}'
            })

        return len([e for e in errors if e['severity'] == 'CRITICAL']) == 0, errors

    except Exception as e:
        errors.append({
            'severity': 'ERROR',
            'check': 'Field Registration',
            'message': f'Could not perform field registration checks: {str(e)}',
            'fields': [],
            'fix': 'Review Comic model and validation dictionaries'
        })
        return False, errors


def print_registration_errors(errors):
    """Print field registration validation errors."""
    if not errors:
        return

    print("\n" + "=" * 70)
    print("FIELD REGISTRATION VALIDATION")
    print("=" * 70)

    for error in errors:
        severity_color = {
            'CRITICAL': '🔴',
            'WARNING': '🟡',
            'ERROR': '⚠️',
            'INFO': '🔵'
        }.get(error['severity'], '•')

        print(f"\n{severity_color} {error['severity']}: {error['check']}")
        print(f"   {error['message']}")

        if error['fields']:
            print(f"   Fields:")
            for field in error['fields'][:10]:  # Limit to first 10
                print(f"      - {field}")
            if len(error['fields']) > 10:
                print(f"      ... and {len(error['fields']) - 10} more")

        print(f"   Fix: {error['fix']}")

    print("\n" + "=" * 70)


def validate_schema(csv_path, verbose=True):
    """
    Validate that CSV schema matches expected fields.

    Returns:
        tuple: (is_valid, missing_in_csv, missing_in_validation, extra_in_csv, registration_errors)
    """
    # Run field registration validation first
    registration_valid, registration_errors = validate_field_registration()

    expected_fields = get_expected_fields()
    comic_model_fields = get_comic_model_fields()
    csv_headers = read_csv_headers(csv_path)

    if csv_headers is None:
        return False, set(), set(), set(), registration_errors

    # Find discrepancies
    missing_in_csv = expected_fields - csv_headers
    missing_in_validation = comic_model_fields - expected_fields
    extra_in_csv = csv_headers - expected_fields

    # Fields in CSV but not expected (could be legacy or custom fields - OK)
    legacy_fields = {'ID', 'added_by', 'date_added', 'last_modified', 'ebay_item_id', 'last_exported'}
    unexpected_extra = extra_in_csv - legacy_fields

    is_valid = len(missing_in_csv) == 0 and len(missing_in_validation) == 0 and registration_valid

    if verbose:
        print("=" * 70)
        print("CSV SCHEMA VALIDATION REPORT")
        print("=" * 70)
        print(f"\n📁 CSV File: {csv_path}")
        print(f"📊 CSV Columns: {len(csv_headers)}")
        print(f"📋 Expected Fields: {len(expected_fields)}")
        print(f"💾 Comic Model Fields: {len(comic_model_fields)}")

        if is_valid:
            print(f"\n✅ VALIDATION PASSED - All fields match!")
        else:
            print(f"\n❌ VALIDATION FAILED - Schema mismatch detected!")

        if missing_in_csv:
            print(f"\n🔴 CRITICAL: Fields in validation but MISSING in CSV ({len(missing_in_csv)}):")
            for field in sorted(missing_in_csv):
                print(f"   - {field}")
            print("\n⚠️  These fields will cause CSV write failures!")
            print("   Run with --fix to add missing columns")

        if missing_in_validation:
            print(f"\n🟡 WARNING: Fields in Comic model but NOT in validation ({len(missing_in_validation)}):")
            for field in sorted(missing_in_validation):
                print(f"   - {field}")
            print("\n⚠️  These fields need to be added to WHATNOT_FIELD_VALIDATION!")
            print("   See: app/utils/whatnot_validators.py")

        if unexpected_extra:
            print(f"\n🟢 INFO: Extra columns in CSV (not validated, OK) ({len(unexpected_extra)}):")
            for field in sorted(unexpected_extra):
                print(f"   - {field}")
            print("   These are custom fields and will be preserved.")

        if extra_in_csv & legacy_fields:
            print(f"\n🟠 NOTICE: Legacy columns found (will be removed on migration):")
            for field in sorted(extra_in_csv & legacy_fields):
                print(f"   - {field}")

        # Print registration errors
        if registration_errors:
            print_registration_errors(registration_errors)

        print("\n" + "=" * 70)

    return is_valid, missing_in_csv, missing_in_validation, extra_in_csv, registration_errors


def fix_csv_schema(csv_path):
    """Add missing columns to CSV file."""
    print("\n🔧 Attempting to fix CSV schema...")

    expected_fields = get_expected_fields()

    # Read existing data
    try:
        with open(csv_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            original_headers = list(reader.fieldnames or [])
            rows = list(reader)
    except Exception as e:
        print(f"❌ Error reading CSV: {e}")
        return False

    # Build new headers (preserve order, add missing at end)
    new_headers = original_headers.copy()
    missing_fields = expected_fields - set(original_headers)

    for field in sorted(missing_fields):
        new_headers.append(field)

    # Add missing fields to rows with empty values
    for row in rows:
        for field in missing_fields:
            row[field] = ''

    # Create backup
    backup_path = Path(csv_path).with_suffix('.csv.bak')
    try:
        import shutil
        shutil.copy2(csv_path, backup_path)
        print(f"✓ Created backup: {backup_path}")
    except Exception as e:
        print(f"⚠️  Could not create backup: {e}")

    # Write updated CSV
    try:
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=new_headers, quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()
            writer.writerows(rows)

        print(f"✓ Added {len(missing_fields)} missing columns to CSV")
        for field in sorted(missing_fields):
            print(f"  + {field}")

        return True
    except Exception as e:
        print(f"❌ Error writing CSV: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Validate CSV schema matches Comic model and validation dictionaries'
    )
    parser.add_argument(
        '--csv-path',
        default='instance/items.csv',
        help='Path to CSV file (default: instance/items.csv)'
    )
    parser.add_argument(
        '--fix',
        action='store_true',
        help='Attempt to fix CSV by adding missing columns'
    )
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Suppress detailed output'
    )

    args = parser.parse_args()

    # Resolve CSV path
    csv_path = Path(args.csv_path)
    if not csv_path.is_absolute():
        # Relative to project root (not script directory)
        csv_path = project_root / csv_path

    if not csv_path.exists():
        print(f"❌ CSV file not found: {csv_path}")
        print(f"   This might be a fresh installation.")
        print(f"   CSV will be created on first use.")
        return 0  # Don't fail on missing CSV for fresh installs

    # Run validation
    is_valid, missing_in_csv, missing_in_validation, extra_in_csv, registration_errors = validate_schema(
        csv_path,
        verbose=not args.quiet
    )

    # If fix requested and there are missing fields
    if args.fix and (missing_in_csv or missing_in_validation):
        if missing_in_csv:
            success = fix_csv_schema(csv_path)
            if success:
                # Re-validate
                is_valid, _, _, _, _ = validate_schema(csv_path, verbose=True)

        if missing_in_validation:
            print("\n⚠️  Fields missing from validation dictionary cannot be auto-fixed.")
            print("   You must manually add them to WHATNOT_FIELD_VALIDATION")
            print("   in app/utils/whatnot_validators.py")
            return 1

    if not is_valid:
        if not args.quiet:
            print("\n" + "=" * 70)
            print("RECOMMENDATION:")
            print("=" * 70)
            print("1. Run with --fix to add missing CSV columns:")
            print(f"   python {Path(__file__).name} --fix")
            print()
            print("2. For fields missing from validation, add them to:")
            print("   app/utils/whatnot_validators.py → WHATNOT_FIELD_VALIDATION")
            print()
            print("3. See deployment/CSV_DATA_LOSS_BUG_FIX.md for details")
            print("=" * 70)
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())

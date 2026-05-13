#!/usr/bin/env python3
"""Fix comics whose Description field contains leaked eBay HTML template markup.

Run on the server:
    cd /home/ubuntu/dockyard
    source .venv/bin/activate
    python app/scripts/fix_html_in_descriptions.py [--csv-path PATH]

What it does:
    1. Discovers all items.csv files (single-user and multi-user layouts)
       OR operates on a specific CSV if --csv-path is given.
    2. Finds rows where Description contains HTML tags (<div>, <li>, <strong>)
    3. Strips all HTML, leaving only the plain text
    4. Writes the cleaned CSV back
    5. Reports what was changed
"""
import argparse
import csv
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Resolve paths relative to project root
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))


def discover_csv_paths(project_root):
    """Return all inventory CSV paths found under project_root/instance/."""
    paths = []
    root = Path(project_root)

    # Single-user fallback
    single = root / 'instance' / 'items.csv'
    if single.exists():
        paths.append(single)

    # Multi-user: instance/data/*/items.csv
    data_dir = root / 'instance' / 'data'
    if data_dir.exists():
        for user_dir in sorted(p for p in data_dir.iterdir() if p.is_dir()):
            candidate = user_dir / 'items.csv'
            if candidate.exists():
                paths.append(candidate)

    return paths


def strip_html(text):
    """Remove HTML tags and collapse whitespace."""
    cleaned = re.sub(r'<[^>]+>', ' ', text)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def has_html(text):
    """Check if text contains HTML markup."""
    return bool(text and ('<div>' in text or '<li>' in text or '<strong>' in text or '<ul>' in text))


def fix_csv(csv_path):
    """Fix HTML in Description fields for a single CSV file."""
    print(f"\nReading CSV: {csv_path}")

    # Backup first
    backup_path = str(csv_path) + f'.backup-{datetime.now().strftime("%Y%m%d-%H%M%S")}'
    shutil.copy2(csv_path, backup_path)
    print(f"Backup saved: {backup_path}")

    # Read all rows
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    fixed_count = 0
    for row in rows:
        desc = row.get('Description', '')
        if has_html(desc):
            original = desc
            cleaned = strip_html(desc)
            row['Description'] = cleaned
            sku = row.get('SKU', '?')
            print(f"\nSKU {sku}:")
            print(f"  BEFORE ({len(original)} chars): {original[:120]}...")
            print(f"  AFTER  ({len(cleaned)} chars): {cleaned[:120]}")
            fixed_count += 1

    if fixed_count == 0:
        print("\nNo HTML found in any Description fields. Nothing to fix.")
        os.remove(backup_path)
        return

    # Write cleaned CSV
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nFixed {fixed_count} row(s). CSV updated.")
    print(f"Backup at: {backup_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Fix eBay HTML template markup leaked into Description fields'
    )
    parser.add_argument(
        '--csv-path',
        help='Specific CSV file to fix. Defaults to auto-discovering all CSVs under instance/.',
        default=None,
    )
    args = parser.parse_args()

    if args.csv_path:
        csv_path = Path(args.csv_path)
        if not csv_path.is_absolute():
            csv_path = Path(PROJECT_ROOT) / csv_path
        if not csv_path.exists():
            print(f"ERROR: CSV not found at {csv_path}")
            sys.exit(1)
        csv_paths = [csv_path]
    else:
        csv_paths = discover_csv_paths(PROJECT_ROOT)
        if not csv_paths:
            print("ERROR: No items.csv files found under instance/")
            sys.exit(1)

    for csv_path in csv_paths:
        fix_csv(csv_path)


if __name__ == '__main__':
    main()


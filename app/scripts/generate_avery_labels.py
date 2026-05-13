#!/usr/bin/env python3
"""
Generate Avery 94102-RMP15 label CSV with smart positioning.

Avery 94102-RMP15 Specifications:
- 80 labels per sheet (10 rows × 8 columns)
- Label size: 0.666" × 1.75"
- Perfect for SKU labels

Features:
- Start printing at any position (for partial sheets)
- Auto-pagination across multiple sheets
- Reads SKU data from Whatnot export CSV

Usage:
    python generate_avery_labels.py <input_csv>

Example:
    python generate_avery_labels.py instance/whatnot_upload.csv
"""

import csv
import sys
from pathlib import Path


LABELS_PER_SHEET = 80
COLUMNS = 8
ROWS = 10


def read_whatnot_export(input_file):
    """
    Read SKU data from Whatnot export CSV.

    Args:
        input_file: Path to Whatnot export CSV

    Returns:
        list: List of dicts with SKU, Title, Price
    """
    comics = []

    try:
        with open(input_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)

            for row in reader:
                sku = row.get('SKU', '').strip()
                title = row.get('Title', '').strip()
                price = row.get('Start Price', '').strip()

                if sku:
                    # Truncate title for small label
                    if len(title) > 25:
                        title = title[:22] + '...'

                    comics.append({
                        'SKU': sku,
                        'Title': title,
                        'Price': price
                    })

        return comics

    except FileNotFoundError:
        print(f"❌ Error: File not found: {input_file}")
        return None
    except Exception as e:
        print(f"❌ Error reading file: {e}")
        return None


def get_start_position():
    """
    Ask user what label position to start at.

    Returns:
        int: Starting position (1-80)
    """
    print("\n" + "="*60)
    print("AVERY 94102-RMP15 LABEL SHEET")
    print("="*60)
    print(f"Sheet layout: {ROWS} rows × {COLUMNS} columns = {LABELS_PER_SHEET} labels")
    print()
    print("Label positions:")
    print("  Row 1:   1   2   3   4   5   6   7   8")
    print("  Row 2:   9  10  11  12  13  14  15  16")
    print("  Row 3:  17  18  19  20  21  22  23  24")
    print("  ...")
    print(" Row 10:  73  74  75  76  77  78  79  80")
    print("="*60)
    print()

    while True:
        try:
            start = input("Start printing at which position? (1-80, or Enter for 1): ").strip()

            if start == '':
                return 1

            start_pos = int(start)

            if 1 <= start_pos <= LABELS_PER_SHEET:
                return start_pos
            else:
                print(f"❌ Please enter a number between 1 and {LABELS_PER_SHEET}")

        except ValueError:
            print("❌ Please enter a valid number")
        except KeyboardInterrupt:
            print("\n\n❌ Cancelled by user")
            sys.exit(0)


def generate_label_csv(comics, start_position, output_file='avery_labels.csv'):
    """
    Generate label CSV with positioning.

    Args:
        comics: List of comic data
        start_position: Starting label position (1-80)
        output_file: Output CSV filename

    Returns:
        dict: Statistics about generation
    """
    labels = []

    # Calculate how many blank labels needed before first SKU
    blanks_needed = start_position - 1

    # Add blank labels for positioning
    for i in range(blanks_needed):
        labels.append({
            'SKU': '',
            'Title': '',
            'Price': ''
        })

    # Add actual comic data
    for comic in comics:
        labels.append(comic)

    # Calculate pagination
    total_labels = len(labels)
    sheets_needed = (total_labels + LABELS_PER_SHEET - 1) // LABELS_PER_SHEET
    labels_on_last_sheet = total_labels % LABELS_PER_SHEET
    if labels_on_last_sheet == 0 and sheets_needed > 0:
        labels_on_last_sheet = LABELS_PER_SHEET

    # Write CSV
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['SKU', 'Title', 'Price'])
        writer.writeheader()
        writer.writerows(labels)

    return {
        'total_comics': len(comics),
        'blank_labels': blanks_needed,
        'total_labels': total_labels,
        'sheets_needed': sheets_needed,
        'labels_on_last_sheet': labels_on_last_sheet,
        'output_file': output_file
    }


def print_summary(stats):
    """Print generation summary."""
    print("\n" + "="*60)
    print("✓ LABELS GENERATED SUCCESSFULLY")
    print("="*60)
    print(f"Comics to print:      {stats['total_comics']}")
    print(f"Blank labels (start): {stats['blank_labels']}")
    print(f"Total labels:         {stats['total_labels']}")
    print(f"Sheets needed:        {stats['sheets_needed']}")
    print(f"Last sheet uses:      {stats['labels_on_last_sheet']}/{LABELS_PER_SHEET} labels")
    print(f"Output file:          {stats['output_file']}")
    print("="*60)
    print()
    print("Next steps:")
    print("1. Open Microsoft Word")
    print("2. Set up Avery 94102-RMP15 label template")
    print(f"3. Mail merge with {stats['output_file']}")
    print("4. Print on Avery 94102-RMP15 sheets")
    print()

    if stats['blank_labels'] > 0:
        start_row = (stats['blank_labels'] // COLUMNS) + 1
        start_col = (stats['blank_labels'] % COLUMNS) + 1
        print(f"📍 First SKU will print at: Row {start_row}, Column {start_col}")
        print()


def main():
    """Main entry point."""
    print()
    print("="*60)
    print("SKU LABEL GENERATOR - AVERY 94102-RMP15")
    print("="*60)

    # Check arguments
    if len(sys.argv) < 2:
        print()
        print("Usage: python generate_avery_labels.py <input_csv>")
        print()
        print("Example:")
        print("  python generate_avery_labels.py instance/whatnot_upload.csv")
        print()
        sys.exit(1)

    input_file = sys.argv[1]

    # Verify input file exists
    if not Path(input_file).exists():
        print(f"\n❌ Error: File not found: {input_file}\n")
        sys.exit(1)

    # Read comics data
    print(f"\n📖 Reading comics from: {input_file}")
    comics = read_whatnot_export(input_file)

    if comics is None:
        sys.exit(1)

    if len(comics) == 0:
        print("❌ No comics found in file\n")
        sys.exit(1)

    print(f"✓ Found {len(comics)} comics")

    # Get starting position
    start_position = get_start_position()

    # Generate labels
    output_file = 'avery_labels.csv'
    print(f"\n⚙️  Generating labels starting at position {start_position}...")

    stats = generate_label_csv(comics, start_position, output_file)

    # Print summary
    print_summary(stats)


if __name__ == '__main__':
    main()

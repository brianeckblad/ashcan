#!/usr/bin/env python3
"""
Fix Missing Thumbnails Script

This script scans the instance/images directory for image files that are missing
their corresponding thumbnail files and generates them.

Thumbnails are expected to be in WebP format with the naming convention:
  original_image.jpg -> original_image_thumb.webp

Usage:
    python fix_missing_thumbnails.py [--dry-run]

Options:
    --dry-run    Show what would be done without actually creating thumbnails
"""

import sys
import io
import argparse
from pathlib import Path
from PIL import Image, ImageCms


# Configuration
# __file__ = app/scripts/util_fix_missing_thumbnails.py; .parent.parent.parent = project root
IMAGES_DIR = Path(__file__).parent.parent.parent / 'instance' / 'images'
THUMBNAIL_SIZE = (300, 300)
THUMBNAIL_QUALITY = 85
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}


def create_thumbnail(source_path, thumbnail_size=(300, 300), quality=85):
    """
    Generate a WebP thumbnail from a source image file.

    Args:
        source_path (Path): Path to the source image file
        thumbnail_size (tuple): Target (width, height) in pixels
        quality (int): Output quality (1-100)

    Returns:
        bytes or None: The thumbnail image data as bytes, or None on error
    """
    try:
        with Image.open(source_path) as img:
            # Handle embedded color profiles for accurate color rendering
            icc_profile = img.info.get("icc_profile")

            if icc_profile:
                try:
                    # Convert from embedded profile to sRGB
                    input_profile = io.BytesIO(icc_profile)
                    output_profile = ImageCms.createProfile("sRGB")

                    # Apply the color space transformation
                    img = ImageCms.profileToProfile(
                        img, input_profile, output_profile,
                        renderingIntent=0, outputMode='RGB'
                    )
                except Exception as cms_error:
                    # Fallback if color profile conversion fails
                    print(f"    Warning: Color profile conversion failed, using fallback: {cms_error}")
                    if img.mode not in ('RGB', 'RGBA'):
                        img = img.convert('RGB')
            elif img.mode not in ('RGB', 'RGBA'):
                # Convert to RGB if not already (e.g., CMYK to RGB)
                img = img.convert('RGB')

            # Resize image maintaining aspect ratio
            img.thumbnail(thumbnail_size, Image.Resampling.LANCZOS)

            # Save to bytes buffer as WebP
            buffer = io.BytesIO()
            img.save(buffer, format='WEBP', quality=quality, method=6)
            buffer.seek(0)

            return buffer.getvalue()

    except Exception as e:
        print(f"    Error creating thumbnail: {e}")
        return None


def find_missing_thumbnails(images_dir):
    """
    Find all image files that are missing their thumbnail counterparts.

    Args:
        images_dir (Path): Directory containing images

    Returns:
        list: List of Path objects for images missing thumbnails
    """
    if not images_dir.exists():
        print(f"Error: Directory does not exist: {images_dir}")
        return []

    # Find all image files (excluding thumbnails)
    all_images = []
    for file_path in images_dir.iterdir():
        if (file_path.is_file() and
            file_path.suffix.lower() in IMAGE_EXTENSIONS and
            '_thumb' not in file_path.name):
            all_images.append(file_path)

    # Check which ones are missing thumbnails
    missing_thumbnails = []
    for img_path in all_images:
        thumb_name = f"{img_path.stem}_thumb.webp"
        thumb_path = images_dir / thumb_name

        if not thumb_path.exists():
            missing_thumbnails.append(img_path)

    return sorted(missing_thumbnails)


def generate_thumbnails(image_paths, dry_run=False):
    """
    Generate thumbnails for the given image files.

    Args:
        image_paths (list): List of Path objects for images
        dry_run (bool): If True, only show what would be done

    Returns:
        tuple: (success_count, failure_count)
    """
    success_count = 0
    failure_count = 0

    for i, img_path in enumerate(image_paths, 1):
        thumb_name = f"{img_path.stem}_thumb.webp"
        thumb_path = img_path.parent / thumb_name

        print(f"[{i}/{len(image_paths)}] Processing: {img_path.name}")

        if dry_run:
            print(f"    Would create: {thumb_name}")
            success_count += 1
            continue

        # Generate thumbnail
        thumb_data = create_thumbnail(img_path, THUMBNAIL_SIZE, THUMBNAIL_QUALITY)

        if thumb_data:
            try:
                # Write thumbnail to disk
                with open(thumb_path, 'wb') as f:
                    f.write(thumb_data)
                print(f"    ✓ Created: {thumb_name} ({len(thumb_data)} bytes)")
                success_count += 1
            except Exception as e:
                print(f"    ✗ Failed to write thumbnail: {e}")
                failure_count += 1
        else:
            print(f"    ✗ Failed to generate thumbnail")
            failure_count += 1

    return success_count, failure_count


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description='Generate missing thumbnails for images in instance/images directory'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without actually creating thumbnails'
    )
    args = parser.parse_args()

    print("=" * 70)
    print("Fix Missing Thumbnails Script")
    print("=" * 70)
    print(f"Images directory: {IMAGES_DIR.absolute()}")
    print(f"Thumbnail size: {THUMBNAIL_SIZE}")
    print(f"Quality: {THUMBNAIL_QUALITY}")
    if args.dry_run:
        print("Mode: DRY RUN (no files will be created)")
    print()

    # Check if directory exists
    if not IMAGES_DIR.exists():
        print(f"Error: Images directory does not exist: {IMAGES_DIR}")
        return 1

    # Find images missing thumbnails
    print("Scanning for images missing thumbnails...")
    missing = find_missing_thumbnails(IMAGES_DIR)

    if not missing:
        print("✓ All images have thumbnails! Nothing to do.")
        return 0

    print(f"\nFound {len(missing)} image(s) missing thumbnails:")
    for img in missing[:10]:
        print(f"  - {img.name}")
    if len(missing) > 10:
        print(f"  ... and {len(missing) - 10} more")
    print()

    # Ask for confirmation if not in dry-run mode
    if not args.dry_run:
        response = input(f"Generate {len(missing)} thumbnail(s)? [y/N]: ")
        if response.lower() != 'y':
            print("Cancelled.")
            return 0
        print()

    # Generate thumbnails
    success, failure = generate_thumbnails(missing, dry_run=args.dry_run)

    print()
    print("=" * 70)
    print("Summary:")
    print(f"  Total processed: {len(missing)}")
    print(f"  Success: {success}")
    print(f"  Failed: {failure}")
    print("=" * 70)

    return 0 if failure == 0 else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

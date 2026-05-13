#!/usr/bin/env python3
"""
Diagnostic script to check image URLs for a specific SKU in the CSV file.
"""
import sys
from pathlib import Path

# Add the project root directory to sys.path so app.* imports resolve.
# __file__ = app/scripts/util_check_comic_images.py → .parent.parent.parent = project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

def check_comic_images(sku):
    """Check what images are stored for a given SKU."""
    from app.services.comic_service import comic_service
    from flask import Flask

    # Create minimal Flask app context
    app = Flask(__name__)
    app.config['CSV_FILE'] = 'instance/items.csv'
    app.config['SKU_FILE'] = 'instance/sku.txt'
    app.config['UPLOAD_FOLDER'] = 'instance/uploads'

    with app.app_context():
        comic = comic_service.get_comic(sku)

        if not comic:
            print(f"❌ Comic with SKU {sku} not found in CSV")
            return

        print(f"\n✅ Found comic: {comic.title}")
        print(f"   SKU: {comic.sku}")
        print(f"   eBay Item ID: {comic.ebay_item_id or '(none)'}")
        print(f"\n📸 Image URLs (from comic.image_urls list):")

        if hasattr(comic, 'image_urls') and comic.image_urls:
            print(f"   Total images: {len(comic.image_urls)}")
            for idx, url in enumerate(comic.image_urls, 1):
                print(f"   {idx}. {url}")
        else:
            print("   ⚠️ No images found in comic.image_urls")

        print(f"\n📋 Raw CSV data (to_dict):")
        comic_dict = comic.to_dict()
        for i in range(1, 9):
            field_key = f'Image URL {i}'
            url = comic_dict.get(field_key, '')
            if url:
                print(f"   {field_key}: {url}")
            else:
                print(f"   {field_key}: (empty)")

        print("\n" + "="*80)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python check_comic_images.py <SKU>")
        print("Example: python check_comic_images.py 1035")
        sys.exit(1)

    sku = sys.argv[1]
    check_comic_images(sku)

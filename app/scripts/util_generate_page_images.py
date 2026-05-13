#!/usr/bin/env python3
"""
Generate page mockup images for analytics heatmap visualization.
Creates PNG images representing each page of the app with accurate layouts.Can be run directly from the project root:
    python app/scripts/util_generate_page_images.py

Or imported and called programmatically (no side effects on import):
    from app.scripts.util_generate_page_images import generate_all_pages
    generate_all_pages('/path/to/output')
"""

from PIL import Image, ImageDraw
import os
import glob
from pathlib import Path

# Script/output path resolution
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DEFAULT_OUTPUT_DIR = str(PROJECT_ROOT / 'app' / 'static' / 'analytics')

# Canvas size (matches typical viewport)
WIDTH = 1200
HEIGHT = 800

# Colors (matching current design system tokens from app/static/css/tokens.css)
BG_DARK = '#1B1A1B'         # --color-bg
BG_MEDIUM = '#242223'       # --color-surface
BG_LIGHT = '#2D2B2C'        # --color-elevated
BORDER = '#5A5758'          # --color-border
BORDER_HOVER = '#7A7778'    # --color-border-hover
ACCENT = '#E2E800'          # --color-accent (bright yellow)
ACCENT_HOVER = '#D1D700'    # --color-accent-hover
TEXT = '#E8E8E6'             # --color-text
TEXT_MUTED = '#C5C2BE'       # --color-text-muted
TEXT_DIM = '#ADADAD'         # --color-text-dim
EBAY_BLUE = '#00BFFF'       # --color-ebay
WHATNOT_MAGENTA = '#FF00FF'  # --color-whatnot
GREEN = '#5C8A5C'           # --color-success
RED = '#C45C5C'             # --color-danger


def hex_to_rgb(hex_color):
    """Convert hex color to RGB tuple."""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

def create_base_page(title="Page"):
    """Create base page template with accurate header and navigation."""
    img = Image.new('RGB', (WIDTH, HEIGHT), hex_to_rgb(BG_DARK))
    draw = ImageDraw.Draw(img)

    # Header bar (matches actual app)
    draw.rectangle([0, 0, WIDTH, 80], fill=hex_to_rgb(BG_LIGHT), outline=hex_to_rgb(BORDER), width=1)

    # Logo (comic book icon - yellow square with stylized design)
    logo_x, logo_y = 30, 15
    draw.rectangle([logo_x, logo_y, logo_x + 50, logo_y + 50], fill=hex_to_rgb(ACCENT))
    # Add comic "pages" effect
    draw.line([logo_x + 15, logo_y, logo_x + 15, logo_y + 50], fill=hex_to_rgb(BG_DARK), width=2)
    draw.line([logo_x + 35, logo_y, logo_x + 35, logo_y + 50], fill=hex_to_rgb(BG_DARK), width=2)

    # Bottom navigation bar (8 icons matching actual nav)
    draw.rectangle([0, HEIGHT - 80, WIDTH, HEIGHT], fill=hex_to_rgb(BG_MEDIUM), outline=hex_to_rgb(BORDER), width=1)

    # Bottom nav items with icons (matching actual nav)
    nav_items = [
        ('⚡', 100),   # Home
        ('📊', 230),   # Browse
        ('➕', 360),   # Add
        ('🗑️', 490),  # Trash
        ('💰', 620),   # Prices
        ('📈', 750),   # Analytics
        ('👤', 880),   # Account
        ('🚪', 1010),  # Logout
    ]

    for icon, x in nav_items:
        # Icon circle/button
        draw.rectangle([x - 20, HEIGHT - 60, x + 20, HEIGHT - 20],
                      fill=hex_to_rgb(BG_LIGHT), outline=hex_to_rgb(BORDER), width=1)

    return img, draw

def create_browse_page():
    """Create browse/comic list page mockup - matches current filter tab layout."""
    img, draw = create_base_page("Browse Comics")

    # Filter tabs row (matches actual page: All, Not Listed, For Sale eBay, WhatNot, Giveaway)
    filters = [
        ('All', 40, BG_LIGHT),
        ('Not Listed', 180, ACCENT),         # example active state
        ('For Sale eBay', 330, BG_LIGHT),
        ('WhatNot', 500, BG_LIGHT),
        ('Giveaway', 630, BG_LIGHT),
    ]

    for label, x, color in filters:
        btn_width = 140
        draw.rectangle([x, 100, x + btn_width, 135],
                      fill=hex_to_rgb(color),
                      outline=hex_to_rgb(BORDER), width=2)

    # Comic cards grid - 3 columns, 2 rows (matches actual browse page)
    card_width = 360
    card_height = 260
    spacing = 30
    start_x = 40
    start_y = 160

    for row in range(2):
        for col in range(3):
            x = start_x + (col * (card_width + spacing))
            y = start_y + (row * (card_height + spacing))

            # Card container with border
            draw.rectangle([x, y, x + card_width, y + card_height],
                          fill=hex_to_rgb(BG_LIGHT),
                          outline=hex_to_rgb(BORDER), width=2)

            # Image/thumbnail area (top 70% of card)
            img_height = 180
            draw.rectangle([x + 10, y + 10, x + card_width - 10, y + img_height],
                          fill=hex_to_rgb(BG_MEDIUM),
                          outline=hex_to_rgb(BORDER), width=1)

            # SKU badge (bottom left)
            sku_num = 1001 + (row * 3) + col
            draw.rectangle([x + 15, y + img_height + 10, x + 75, y + img_height + 32],
                          fill=hex_to_rgb(ACCENT),
                          outline=hex_to_rgb(BORDER), width=1)

            # Status indicators (eBay blue circle, WhatNot magenta circle)
            draw.ellipse([x + 85, y + img_height + 12, x + 100, y + img_height + 27],
                        fill=hex_to_rgb(EBAY_BLUE))
            draw.ellipse([x + 110, y + img_height + 12, x + 125, y + img_height + 27],
                        fill=hex_to_rgb(WHATNOT_MAGENTA))

            # Action buttons at bottom
            btn_y = y + img_height + 45
            # View/Edit button
            draw.rectangle([x + 15, btn_y, x + 170, btn_y + 30],
                          fill=hex_to_rgb(BG_MEDIUM),
                          outline=hex_to_rgb(BORDER), width=1)
            # Delete button
            draw.rectangle([x + 185, btn_y, x + card_width - 15, btn_y + 30],
                          fill=hex_to_rgb(BG_MEDIUM),
                          outline=hex_to_rgb(BORDER), width=1)

    return img

def create_add_page():
    """Create add/edit comic page mockup - matches two-column layout."""
    img, draw = create_base_page("Add/Edit Comic")

    # LEFT COLUMN: Image upload area
    left_x = 40
    left_width = 400

    # Main image upload box
    draw.rectangle([left_x, 100, left_x + left_width, 520],
                  fill=hex_to_rgb(BG_LIGHT),
                  outline=hex_to_rgb(BORDER), width=2)

    # Large preview area
    draw.rectangle([left_x + 15, 120, left_x + left_width - 15, 420],
                  fill=hex_to_rgb(BG_MEDIUM),
                  outline=hex_to_rgb(BORDER), width=1)

    # Thumbnail strip (4 thumbnails)
    thumb_y = 440
    thumb_size = 85
    for i in range(4):
        thumb_x = left_x + 20 + (i * 95)
        draw.rectangle([thumb_x, thumb_y, thumb_x + thumb_size, thumb_y + thumb_size],
                      fill=hex_to_rgb(BG_MEDIUM),
                      outline=hex_to_rgb(BORDER), width=1)

    # Action buttons section (below image area)
    actions_y = 540
    btn_width = 180
    btn_height = 36
    btn_gap = 12

    # First row: Google Lens and Delete Comic
    draw.rectangle([left_x, actions_y, left_x + btn_width, actions_y + btn_height],
                  fill=hex_to_rgb(BG_LIGHT),
                  outline=hex_to_rgb(BORDER), width=1)
    draw.rectangle([left_x + btn_width + btn_gap, actions_y, left_x + btn_width * 2 + btn_gap, actions_y + btn_height],
                  fill=hex_to_rgb(RED),
                  outline=hex_to_rgb(BORDER), width=1)

    # Second row: Google Image Search and Search eBay
    actions_y2 = actions_y + btn_height + 8
    draw.rectangle([left_x, actions_y2, left_x + btn_width, actions_y2 + btn_height],
                  fill=hex_to_rgb(BG_LIGHT),
                  outline=hex_to_rgb(BORDER), width=1)
    draw.rectangle([left_x + btn_width + btn_gap, actions_y2, left_x + btn_width * 2 + btn_gap, actions_y2 + btn_height],
                  fill=hex_to_rgb(BG_LIGHT),
                  outline=hex_to_rgb(BORDER), width=1)

    # RIGHT COLUMN: Form fields
    right_x = 470
    right_width = 690
    field_height = 50
    field_spacing = 15

    fields = [
        'Title', 'Publisher', 'Issue Number', 'Grade/Condition',
        'Price', 'Listing Type', 'Description', 'Notes',
    ]

    for i, field in enumerate(fields):
        y = 100 + (i * (field_height + field_spacing))
        draw.rectangle([right_x, y, right_x + right_width, y + field_height],
                      fill=hex_to_rgb(BG_LIGHT),
                      outline=hex_to_rgb(BORDER), width=1)

    # BOTTOM SECTION: Footer buttons
    footer_y = 640

    # Grading icon button (left side)
    draw.rectangle([40, footer_y, 120, footer_y + 50],
                  fill=hex_to_rgb(BG_LIGHT),
                  outline=hex_to_rgb(BORDER), width=2)

    # WhatNot menu button
    draw.rectangle([680, footer_y, 820, footer_y + 50],
                  fill=hex_to_rgb(BG_LIGHT),
                  outline=hex_to_rgb(BORDER), width=2)

    # eBay menu button
    draw.rectangle([840, footer_y, 980, footer_y + 50],
                  fill=hex_to_rgb(BG_LIGHT),
                  outline=hex_to_rgb(BORDER), width=2)

    # Save button (green)
    draw.rectangle([1000, footer_y, 1160, footer_y + 50],
                  fill=hex_to_rgb(GREEN),
                  outline=hex_to_rgb(BORDER), width=2)

    return img

def create_add_from_image_page():
    """Create add-from-image page mockup — upload cover, pick eBay match, pre-fill form."""
    img, draw = create_base_page("Add From Image")

    # LEFT COLUMN: Image upload / capture area
    left_x = 40
    left_width = 420

    # Upload box
    draw.rectangle([left_x, 100, left_x + left_width, 480],
                  fill=hex_to_rgb(BG_LIGHT),
                  outline=hex_to_rgb(BORDER), width=2)

    # Large preview area (dashed border style)
    draw.rectangle([left_x + 15, 120, left_x + left_width - 15, 380],
                  fill=hex_to_rgb(BG_MEDIUM),
                  outline=hex_to_rgb(BORDER_HOVER), width=1)

    # Upload / camera buttons
    btn_y = 400
    btn_w = 190
    draw.rectangle([left_x + 20, btn_y, left_x + 20 + btn_w, btn_y + 50],
                  fill=hex_to_rgb(ACCENT),
                  outline=hex_to_rgb(BORDER), width=1)
    draw.rectangle([left_x + 220, btn_y, left_x + 220 + btn_w, btn_y + 50],
                  fill=hex_to_rgb(BG_LIGHT),
                  outline=hex_to_rgb(BORDER), width=1)

    # Search eBay button (full width below)
    draw.rectangle([left_x + 20, btn_y + 70, left_x + left_width - 20, btn_y + 120],
                  fill=hex_to_rgb(EBAY_BLUE),
                  outline=hex_to_rgb(BORDER), width=2)

    # RIGHT COLUMN: eBay match results
    right_x = 500
    right_width = 660
    result_height = 130
    result_gap = 12

    # Section label
    draw.rectangle([right_x, 95, right_x + right_width, 130],
                  fill=hex_to_rgb(BG_MEDIUM),
                  outline=hex_to_rgb(BORDER), width=1)

    # Result cards (4 items)
    for i in range(4):
        ry = 145 + i * (result_height + result_gap)
        draw.rectangle([right_x, ry, right_x + right_width, ry + result_height],
                      fill=hex_to_rgb(BG_LIGHT),
                      outline=hex_to_rgb(BORDER), width=1)
        # Thumbnail
        draw.rectangle([right_x + 10, ry + 10, right_x + 110, ry + result_height - 10],
                      fill=hex_to_rgb(BG_MEDIUM),
                      outline=hex_to_rgb(BORDER), width=1)
        # Title bar
        draw.rectangle([right_x + 125, ry + 15, right_x + right_width - 10, ry + 50],
                      fill=hex_to_rgb(BG_MEDIUM),
                      outline=hex_to_rgb(BORDER), width=1)
        # Price
        draw.rectangle([right_x + 125, ry + 60, right_x + 220, ry + 88],
                      fill=hex_to_rgb(ACCENT),
                      outline=hex_to_rgb(BORDER), width=1)
        # Use This button
        draw.rectangle([right_x + right_width - 140, ry + 55, right_x + right_width - 10, ry + 95],
                      fill=hex_to_rgb(GREEN),
                      outline=hex_to_rgb(BORDER), width=1)

    return img

def create_home_page():
    """Create home/landing/dashboard page mockup."""
    img, draw = create_base_page("Dashboard")

    # Top stats row (4 cards)
    stats = [
        ('Total Comics', 40),
        ('For Sale', 340),
        ('eBay Listed', 640),
        ('Disk Space', 940),
    ]

    for label, x in stats:
        # Stat card
        draw.rectangle([x, 100, x + 270, 220],
                      fill=hex_to_rgb(BG_LIGHT),
                      outline=hex_to_rgb(BORDER), width=2)
        # Value area (bottom half - yellow accent)
        draw.rectangle([x + 10, 170, x + 260, 210],
                      fill=hex_to_rgb(ACCENT),
                      outline=hex_to_rgb(BORDER), width=1)

    # Action buttons grid (3x2)
    actions = [
        ('Add Comic', 40, 250, ACCENT),
        ('Browse Comics', 430, 250, BG_LIGHT),
        ('Price Lookup', 820, 250, BG_LIGHT),
        ('eBay Listings', 40, 420, BG_LIGHT),
        ('Export Comics', 430, 420, BG_LIGHT),
        ('Snapshots', 820, 420, BG_LIGHT),
    ]

    for label, x, y, color in actions:
        draw.rectangle([x, y, x + 360, y + 150],
                      fill=hex_to_rgb(color) if color == ACCENT else hex_to_rgb(BG_LIGHT),
                      outline=hex_to_rgb(BORDER), width=2)
        # Icon/title area at top
        draw.rectangle([x + 10, y + 10, x + 350, y + 60],
                      fill=hex_to_rgb(BG_MEDIUM),
                      outline=hex_to_rgb(BORDER), width=1)

    # System status bar at bottom
    draw.rectangle([40, 600, 1160, 690],
                  fill=hex_to_rgb(BG_LIGHT),
                  outline=hex_to_rgb(BORDER), width=2)
    # Mini stats/indicators
    for i in range(4):
        x = 60 + (i * 280)
        draw.rectangle([x, 615, x + 250, 675],
                      fill=hex_to_rgb(BG_MEDIUM),
                      outline=hex_to_rgb(BORDER), width=1)

    return img

def create_account_page():
    """Create account settings page mockup."""
    img, draw = create_base_page("Account Settings")

    # Settings sections (stacked vertically)
    sections = [
        ('User Profile', 100),
        ('Default Preferences', 240),
        ('eBay Integration', 380),
        ('Danger Zone', 520),
    ]

    for label, y in sections:
        # Section container
        section_height = 120
        draw.rectangle([40, y, 1160, y + section_height],
                      fill=hex_to_rgb(BG_LIGHT),
                      outline=hex_to_rgb(BORDER), width=2)

        # Section title bar
        draw.rectangle([50, y + 10, 1150, y + 50],
                      fill=hex_to_rgb(BG_MEDIUM),
                      outline=hex_to_rgb(BORDER), width=1)

        # Form fields in section (2 columns)
        field_y = y + 65
        draw.rectangle([50, field_y, 590, field_y + 40],
                      fill=hex_to_rgb(BG_MEDIUM),
                      outline=hex_to_rgb(BORDER), width=1)
        draw.rectangle([610, field_y, 1150, field_y + 40],
                      fill=hex_to_rgb(BG_MEDIUM),
                      outline=hex_to_rgb(BORDER), width=1)

    # Save buttons at bottom
    draw.rectangle([800, 660, 1000, 710],
                  fill=hex_to_rgb(GREEN),
                  outline=hex_to_rgb(BORDER), width=2)
    draw.rectangle([1020, 660, 1160, 710],
                  fill=hex_to_rgb(BG_LIGHT),
                  outline=hex_to_rgb(BORDER), width=2)

    return img

def create_price_lookup_page():
    """Create eBay price lookup page mockup."""
    img, draw = create_base_page("eBay Price Lookup")

    # Search bar with search button
    search_width = 850
    draw.rectangle([40, 100, 40 + search_width, 160],
                  fill=hex_to_rgb(BG_LIGHT),
                  outline=hex_to_rgb(BORDER), width=2)
    # Search button
    draw.rectangle([910, 100, 1160, 160],
                  fill=hex_to_rgb(ACCENT),
                  outline=hex_to_rgb(BORDER), width=2)

    # Grading scale icon button
    draw.rectangle([40, 180, 200, 230],
                  fill=hex_to_rgb(BG_LIGHT),
                  outline=hex_to_rgb(BORDER), width=2)

    # Results grid (4 columns x 2 rows)
    card_width = 275
    card_height = 200
    spacing = 20
    start_y = 260

    for row in range(2):
        for col in range(4):
            x = 40 + (col * (card_width + spacing))
            y = start_y + (row * (card_height + spacing))

            # Result card
            draw.rectangle([x, y, x + card_width, y + card_height],
                          fill=hex_to_rgb(BG_LIGHT),
                          outline=hex_to_rgb(BORDER), width=1)

            # Thumbnail image area
            draw.rectangle([x + 10, y + 10, x + card_width - 10, y + 110],
                          fill=hex_to_rgb(BG_MEDIUM),
                          outline=hex_to_rgb(BORDER), width=1)

            # Price tag
            draw.rectangle([x + 10, y + 125, x + 100, y + 155],
                          fill=hex_to_rgb(ACCENT),
                          outline=hex_to_rgb(BORDER), width=1)

            # Condition/Grade
            draw.rectangle([x + 110, y + 125, x + card_width - 10, y + 155],
                          fill=hex_to_rgb(BG_MEDIUM),
                          outline=hex_to_rgb(BORDER), width=1)

            # Sold date
            draw.rectangle([x + 10, y + 165, x + card_width - 10, y + 190],
                          fill=hex_to_rgb(BG_MEDIUM),
                          outline=hex_to_rgb(BORDER), width=1)

    return img

def create_trash_page():
    """Create trash/deleted items page mockup."""
    img, draw = create_base_page("Trash (Deleted Items)")

    # Action buttons at top
    draw.rectangle([40, 100, 300, 155],
                  fill=hex_to_rgb(GREEN),
                  outline=hex_to_rgb(BORDER), width=2)
    draw.rectangle([320, 100, 580, 155],
                  fill=hex_to_rgb(RED),
                  outline=hex_to_rgb(BORDER), width=2)

    # Trash items list (6 items)
    item_height = 90
    start_y = 180

    for i in range(6):
        y = start_y + (i * (item_height + 10))

        draw.rectangle([40, y, 1160, y + item_height],
                      fill=hex_to_rgb(BG_LIGHT),
                      outline=hex_to_rgb(BORDER), width=1)
        # Thumbnail
        draw.rectangle([50, y + 10, 140, y + item_height - 10],
                      fill=hex_to_rgb(BG_MEDIUM),
                      outline=hex_to_rgb(BORDER), width=1)
        # Info lines
        draw.rectangle([160, y + 15, 520, y + 40],
                      fill=hex_to_rgb(BG_MEDIUM),
                      outline=hex_to_rgb(BORDER), width=1)
        draw.rectangle([160, y + 50, 520, y + 75],
                      fill=hex_to_rgb(BG_MEDIUM),
                      outline=hex_to_rgb(BORDER), width=1)
        # Restore button (green)
        draw.rectangle([920, y + 20, 1070, y + 70],
                      fill=hex_to_rgb(GREEN),
                      outline=hex_to_rgb(BORDER), width=1)
        # Delete button (red)
        draw.rectangle([1080, y + 20, 1150, y + 70],
                      fill=hex_to_rgb(RED),
                      outline=hex_to_rgb(BORDER), width=1)

    return img

def create_ebay_listings_page():
    """Create eBay listings management page mockup."""
    img, draw = create_base_page("eBay Listings")

    # Summary stats row (4 stat cards)
    stats_labels = ['Active', 'Scheduled', 'Ended', 'Total Revenue']
    for i, label in enumerate(stats_labels):
        x = 40 + i * 290
        draw.rectangle([x, 100, x + 260, 175],
                      fill=hex_to_rgb(BG_LIGHT),
                      outline=hex_to_rgb(BORDER), width=2)
        draw.rectangle([x + 10, 145, x + 250, 168],
                      fill=hex_to_rgb(EBAY_BLUE),
                      outline=hex_to_rgb(BORDER), width=1)

    # Action bar (Bulk Actions button + filter)
    draw.rectangle([40, 195, 230, 240],
                  fill=hex_to_rgb(EBAY_BLUE),
                  outline=hex_to_rgb(BORDER), width=2)
    draw.rectangle([250, 195, 600, 240],
                  fill=hex_to_rgb(BG_LIGHT),
                  outline=hex_to_rgb(BORDER), width=1)

    # Listing cards grid (3 columns x 2 rows)
    card_width = 365
    card_height = 210
    spacing = 20
    start_x = 40
    start_y = 260

    for row in range(2):
        for col in range(3):
            x = start_x + col * (card_width + spacing)
            y = start_y + row * (card_height + spacing)

            draw.rectangle([x, y, x + card_width, y + card_height],
                          fill=hex_to_rgb(BG_LIGHT),
                          outline=hex_to_rgb(BORDER), width=1)

            # Thumbnail
            draw.rectangle([x + 10, y + 10, x + 115, y + 120],
                          fill=hex_to_rgb(BG_MEDIUM),
                          outline=hex_to_rgb(BORDER), width=1)

            # eBay status badge
            draw.rectangle([x + 130, y + 15, x + 260, y + 45],
                          fill=hex_to_rgb(EBAY_BLUE),
                          outline=hex_to_rgb(BORDER), width=1)

            # Title area
            draw.rectangle([x + 130, y + 55, x + card_width - 10, y + 85],
                          fill=hex_to_rgb(BG_MEDIUM),
                          outline=hex_to_rgb(BORDER), width=1)

            # Price
            draw.rectangle([x + 130, y + 95, x + 230, y + 120],
                          fill=hex_to_rgb(ACCENT),
                          outline=hex_to_rgb(BORDER), width=1)

            # Action buttons (end / relist)
            draw.rectangle([x + 10, y + 160, x + 170, y + 195],
                          fill=hex_to_rgb(BG_MEDIUM),
                          outline=hex_to_rgb(BORDER), width=1)
            draw.rectangle([x + 185, y + 160, x + card_width - 10, y + 195],
                          fill=hex_to_rgb(BG_MEDIUM),
                          outline=hex_to_rgb(BORDER), width=1)

    return img


_ALL_PAGES = {
    'home': create_home_page,
    'browse': create_browse_page,
    'add': create_add_page,
    'add-from-image': create_add_from_image_page,
    'account': create_account_page,
    'price-lookup': create_price_lookup_page,
    'trash': create_trash_page,
    'ebay-listings': create_ebay_listings_page,
}

# Expected PNG filenames — used by the startup check in app/__init__.py
EXPECTED_PNGS = [f"{name}.png" for name in _ALL_PAGES]


def generate_all_pages(output_dir=None, verbose=False):
    """Generate all page mockup images and save to *output_dir*.

    Args:
        output_dir: Destination directory.  Defaults to
            ``app/static/analytics/`` relative to the project root.
        verbose: When True, print a status line for each image.

    Returns:
        dict mapping page name → True (created) / False (error).
    """
    if output_dir is None:
        output_dir = DEFAULT_OUTPUT_DIR

    os.makedirs(output_dir, exist_ok=True)

    # Remove stale PNG files before regenerating
    for old_img in glob.glob(os.path.join(output_dir, '*.png')):
        try:
            os.remove(old_img)
        except Exception as exc:
            if verbose:
                print(f"  Could not remove {os.path.basename(old_img)}: {exc}")

    results = {}
    for page_name, create_func in _ALL_PAGES.items():
        try:
            page_img = create_func()
            output_path = os.path.join(output_dir, f'{page_name}.png')
            page_img.save(output_path, 'PNG')
            if verbose:
                size_kb = os.path.getsize(output_path) / 1024
                print(f"  Created {page_name}.png ({size_kb:.1f} KB)")
            results[page_name] = True
        except Exception as exc:
            if verbose:
                print(f"  Error creating {page_name}.png: {exc}")
            results[page_name] = False

    return results


if __name__ == '__main__':
    print("Generating page mockup images for analytics heatmap...")
    print(f"Output directory: {DEFAULT_OUTPUT_DIR}")
    print()
    results = generate_all_pages(verbose=True)
    ok = sum(1 for v in results.values() if v)
    failed = sum(1 for v in results.values() if not v)
    print()
    print(f"Done: {ok} created, {failed} failed.")
    print("These images are used in the analytics heatmap visualization.")

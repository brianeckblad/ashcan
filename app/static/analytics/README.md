# Analytics Page Image Generation

## Overview

This script generates mockup images of each page in the app for use in the analytics heatmap visualization. The images show realistic page layouts that serve as backgrounds for click heatmap overlays.

## Requirements

```bash
pip install Pillow
```

## Usage

```bash
python3 generate_page_images.py
```

This will generate PNG images in `app/static/analytics/` for:
- `home.png` - Dashboard/landing page
- `browse.png` - Comic browse/list page
- `add.png` - Add/edit comic page
- `account.png` - Account settings page
- `price-lookup.png` - eBay price lookup page
- `trash.png` - Deleted items/trash page

## Image Specifications

- **Size**: 1200x800 pixels
- **Format**: PNG
- **Colors**: Match app theme (dark mode)
- **Layout**: Shows header, navigation, content areas, and bottom nav

## How It Works

1. Uses PIL (Pillow) to draw page mockups
2. Each page function creates realistic layout elements:
   - Header bar with logo and navigation
   - Content-specific elements (cards, forms, buttons)
   - Bottom navigation bar
3. Saves as PNG images in static directory
4. Analytics dashboard loads these as heatmap backgrounds

## Customization

To add new pages or modify existing ones:

1. Edit `generate_page_images.py`
2. Create a new `create_XXX_page()` function
3. Add it to the `pages` dictionary
4. Run the script to regenerate images

## Analytics Dashboard Integration

The analytics dashboard (`app/templates/analytics_dashboard.html`) automatically:
1. Attempts to load the corresponding page image
2. Falls back to wireframe drawing if image not found
3. Overlays click heatmap data on top of the page image
4. Shows where users actually click on each page

## Benefits

- **Visual Context**: See exactly where users click on actual UI elements
- **Professional**: Looks like real analytics software
- **Accurate**: Reflects actual page layouts
- **Flexible**: Easy to regenerate when pages change
- **Lightweight**: Static PNG files, no runtime overhead

## File Sizes

Each image is approximately 20-40 KB, well-optimized for web delivery.

## Regeneration

Regenerate images whenever:
- Page layouts change significantly
- New pages are added
- UI redesign occurs
- Analytics visualization needs updating

Simply run the script again - it overwrites existing images.

## Production Deployment

Include these images in your deployment:
- Commit them to git, or
- Generate them during deployment, or
- Include generation in your build process

The analytics dashboard works with or without them (has fallback wireframe).

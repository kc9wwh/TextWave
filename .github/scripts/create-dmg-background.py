#!/usr/bin/env python3
"""
Generate custom DMG background images for TextWave installer.
Creates both standard (600x400) and Retina (1200x800) versions with:
- Clean gradient background
- Stylish arrow pointing from app to Applications folder
- Apple-style design similar to Firefox DMG
"""

import os

from PIL import Image, ImageDraw

# Configuration
OUTPUT_DIR = ".github/assets"
BACKGROUND_COLOR = (240, 240, 240)  # Light gray #f0f0f0

# Window and icon positions
WINDOW_WIDTH = 600
WINDOW_HEIGHT = 400
APP_ICON_X = 175
APP_ICON_Y = 120
APPS_ICON_X = 425
APPS_ICON_Y = 120
ICON_SIZE = 100


def create_gradient_background(width, height):
    """Create a subtle gradient background similar to macOS DMG style."""
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)

    # Create subtle vertical gradient from lighter to slightly darker
    for y in range(height):
        # Gradient from #f5f5f5 to #e8e8e8
        color_value = int(245 - (y / height) * 13)
        draw.line([(0, y), (width, y)], fill=(color_value, color_value, color_value))

    return img


def draw_arrow(img, scale=1):
    """Draw a stylish arrow similar to Firefox DMG - larger and more prominent."""
    # Create a separate RGBA image for the arrow with transparency
    arrow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(arrow_layer)

    # Scale coordinates
    app_x = int(APP_ICON_X * scale)
    app_y = int(APP_ICON_Y * scale)
    apps_x = int(APPS_ICON_X * scale)
    apps_y = int(APPS_ICON_Y * scale)
    icon_size = int(ICON_SIZE * scale)

    # Position arrow vertically - move up to be more centered
    arrow_y = app_y + icon_size // 2 - int(30 * scale)

    # Arrow positioning - between the two icons
    # App icon is at x=175, size=100, so right edge is at 275
    # Apps icon is at x=425, size=100, so left edge is at 425
    # Arrow should go from ~285 to ~415
    start_x = app_x + icon_size - int(25 * scale)  # Start even further left
    end_x = apps_x - int(80 * scale)  # End well before Apps folder

    # Make arrow larger and more visible (like Firefox style)
    arrow_width = int(20 * scale)  # Width of the arrow shaft
    arrow_height = int(50 * scale)  # Height of the arrowhead

    # Define the arrow shape as a polygon (pointing right)
    # This creates a chunky arrow similar to the Firefox example
    shaft_length = end_x - start_x - arrow_height

    arrow_points = [
        # Top of shaft
        (start_x, arrow_y - arrow_width // 2),
        # Top right of shaft (before arrowhead)
        (start_x + shaft_length, arrow_y - arrow_width // 2),
        # Top outer point of arrowhead
        (start_x + shaft_length, arrow_y - arrow_height // 2),
        # Tip of arrow
        (end_x, arrow_y),
        # Bottom outer point of arrowhead
        (start_x + shaft_length, arrow_y + arrow_height // 2),
        # Bottom right of shaft
        (start_x + shaft_length, arrow_y + arrow_width // 2),
        # Bottom left of shaft
        (start_x, arrow_y + arrow_width // 2),
    ]

    # Draw the arrow with semi-transparency (like the Firefox style)
    # Using a light gray/blue color with alpha for a modern look
    arrow_color = (120, 150, 180, 200)  # Slightly blue-gray with transparency
    draw.polygon(arrow_points, fill=arrow_color)

    # Add a subtle outline for definition
    outline_color = (100, 130, 160, 220)
    draw.line(
        arrow_points + [arrow_points[0]],
        fill=outline_color,
        width=max(1, int(2 * scale)),
    )

    # Composite the arrow onto the background
    img.paste(arrow_layer, (0, 0), arrow_layer)


def create_background_image(scale=1):
    """Create a complete DMG background image at the specified scale."""
    width = int(WINDOW_WIDTH * scale)
    height = int(WINDOW_HEIGHT * scale)

    # Create gradient background
    img = create_gradient_background(width, height)

    # Convert to RGBA to support transparency in arrow
    img = img.convert("RGBA")

    # Draw arrow
    draw_arrow(img, scale)

    # Convert back to RGB for final output
    final_img = Image.new("RGB", img.size, BACKGROUND_COLOR)
    final_img.paste(img, (0, 0), img)

    return final_img


def main():
    """Generate both standard and Retina background images."""
    # Create output directory
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("Generating TextWave DMG background images...")
    print(f"Output directory: {OUTPUT_DIR}")

    # Generate standard resolution (600x400)
    print("\n1. Generating standard resolution (600x400)...")
    img_std = create_background_image(scale=1)
    output_std = os.path.join(OUTPUT_DIR, "dmg-background.png")
    img_std.save(output_std, "PNG", optimize=True)
    print(f"   Saved: {output_std}")
    print(f"   Size: {img_std.width}x{img_std.height}")

    # Generate Retina resolution (1200x800)
    print("\n2. Generating Retina resolution (1200x800)...")
    img_2x = create_background_image(scale=2)
    output_2x = os.path.join(OUTPUT_DIR, "dmg-background@2x.png")
    img_2x.save(output_2x, "PNG", optimize=True)
    print(f"   Saved: {output_2x}")
    print(f"   Size: {img_2x.width}x{img_2x.height}")

    print("\n✓ Background images generated successfully!")
    print("\nNext steps:")
    print("  1. Run: .github/scripts/create-dmg-background.sh")
    print("  2. This will create the multi-resolution TIFF file")


if __name__ == "__main__":
    main()

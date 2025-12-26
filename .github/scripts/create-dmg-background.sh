#!/bin/bash
set -e

echo "Creating multi-resolution TIFF for DMG background..."

ASSETS_DIR=".github/assets"
STD_RES="$ASSETS_DIR/dmg-background.png"
RETINA_RES="$ASSETS_DIR/dmg-background@2x.png"
OUTPUT_TIFF="$ASSETS_DIR/dmg-background.tiff"

# Check if source images exist
if [ ! -f "$STD_RES" ]; then
    echo "Error: Standard resolution image not found at $STD_RES"
    echo "Please run create-dmg-background.py first"
    exit 1
fi

if [ ! -f "$RETINA_RES" ]; then
    echo "Error: Retina resolution image not found at $RETINA_RES"
    echo "Please run create-dmg-background.py first"
    exit 1
fi

# Create multi-resolution TIFF using tiffutil
echo "Combining standard and Retina images into multi-resolution TIFF..."
tiffutil -cathidpicheck "$STD_RES" "$RETINA_RES" -out "$OUTPUT_TIFF"

# Verify output
if [ ! -f "$OUTPUT_TIFF" ]; then
    echo "Error: Failed to create multi-resolution TIFF"
    exit 1
fi

echo "✓ Multi-resolution TIFF created successfully!"
echo ""
echo "Generated files:"
ls -lh "$ASSETS_DIR"
echo ""
echo "The TIFF file will be used for the DMG background with Retina support."

#!/bin/bash
set -e

VERSION=$1

if [ -z "$VERSION" ]; then
    echo "Usage: $0 <version>"
    exit 1
fi

echo "Creating DMG for TextWave $VERSION..."

# Define background image path with fallbacks
BACKGROUND_IMAGE=".github/assets/dmg-background.tiff"
if [ ! -f "$BACKGROUND_IMAGE" ]; then
    echo "Warning: Multi-resolution TIFF not found, trying PNG..."
    BACKGROUND_IMAGE=".github/assets/dmg-background.png"
fi

# Check if create-dmg is available
if command -v create-dmg &> /dev/null; then
    echo "Using create-dmg..."

    # Build create-dmg command with background if available
    CREATE_DMG_CMD="create-dmg \
      --volname \"TextWave\" \
      --window-pos 200 120 \
      --window-size 600 400 \
      --icon-size 100 \
      --icon \"TextWave.app\" 175 120 \
      --hide-extension \"TextWave.app\" \
      --app-drop-link 425 120"

    # Add background parameter if image exists
    if [ -f "$BACKGROUND_IMAGE" ]; then
        echo "Using custom background: $BACKGROUND_IMAGE"
        CREATE_DMG_CMD="$CREATE_DMG_CMD --background \"$BACKGROUND_IMAGE\""
    else
        echo "No custom background found, using default"
    fi

    # Complete the command
    CREATE_DMG_CMD="$CREATE_DMG_CMD \"TextWave-${VERSION}.dmg\" \"dist/TextWave.app\""

    # Execute
    eval $CREATE_DMG_CMD || true  # create-dmg sometimes exits with error even on success
fi

# If create-dmg isn't available or failed, use hdiutil
if [ ! -f "TextWave-${VERSION}.dmg" ]; then
    echo "Using hdiutil..."
    hdiutil create -volname "TextWave" \
      -srcfolder dist/TextWave.app \
      -ov -format UDZO \
      "TextWave-${VERSION}.dmg"
fi

# Verify DMG was created
if [ ! -f "TextWave-${VERSION}.dmg" ]; then
    echo "Error: DMG creation failed"
    exit 1
fi

echo "DMG created: TextWave-${VERSION}.dmg"
ls -lh "TextWave-${VERSION}.dmg"

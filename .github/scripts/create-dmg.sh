#!/bin/bash
set -e

VERSION=$1

if [ -z "$VERSION" ]; then
    echo "Usage: $0 <version>"
    exit 1
fi

echo "Creating DMG for TextWave $VERSION..."

# Check if create-dmg is available
if command -v create-dmg &> /dev/null; then
    echo "Using create-dmg..."
    create-dmg \
      --volname "TextWave" \
      --window-pos 200 120 \
      --window-size 600 400 \
      --icon-size 100 \
      --icon "TextWave.app" 175 120 \
      --hide-extension "TextWave.app" \
      --app-drop-link 425 120 \
      "TextWave-${VERSION}.dmg" \
      "dist/TextWave.app" \
      || true  # create-dmg sometimes exits with error even on success
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

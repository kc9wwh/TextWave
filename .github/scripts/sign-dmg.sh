#!/bin/bash
set -e

VERSION=$1
DMG_PATH="TextWave-${VERSION}.dmg"

if [ -z "$VERSION" ]; then
    echo "Error: Version not specified"
    exit 1
fi

if [ ! -f "$DMG_PATH" ]; then
    echo "Error: DMG not found at $DMG_PATH"
    exit 1
fi

echo "Signing DMG: $DMG_PATH"

# Find signing identity (keychain already set up by calling workflow)
SIGNING_IDENTITY=$(security find-identity -v -p codesigning | grep "Developer ID Application" | head -1 | grep -o '"[^"]*"' | tr -d '"')

if [ -z "$SIGNING_IDENTITY" ]; then
    echo "Error: No Developer ID Application certificate found"
    exit 1
fi

echo "Using signing identity: $SIGNING_IDENTITY"

# Sign the DMG
codesign --force --sign "$SIGNING_IDENTITY" --timestamp "$DMG_PATH"

# Verify DMG signature
echo "Verifying DMG signature..."
codesign --verify --verbose=2 "$DMG_PATH"

echo "DMG signed successfully!"

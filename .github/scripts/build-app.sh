#!/bin/bash
set -e

echo "Building TextWave macOS app..."

# Clean previous builds
rm -rf build dist

# Build the app
python setup.py py2app

# Verify build
if [ ! -d "dist/TextWave.app" ]; then
    echo "Error: App build failed"
    exit 1
fi

echo "App built successfully at dist/TextWave.app"

# Create zip for direct download
cd dist
zip -r TextWave.app.zip TextWave.app
cd ..

echo "Created TextWave.app.zip"

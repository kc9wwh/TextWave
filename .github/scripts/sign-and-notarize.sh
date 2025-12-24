#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Check required environment variables
if [ -z "$APPLE_CERTIFICATE_P12_BASE64" ]; then
    log_error "APPLE_CERTIFICATE_P12_BASE64 is not set"
    exit 1
fi

if [ -z "$APPLE_CERTIFICATE_PASSWORD" ]; then
    log_error "APPLE_CERTIFICATE_PASSWORD is not set"
    exit 1
fi

if [ -z "$APPLE_ID" ]; then
    log_error "APPLE_ID is not set"
    exit 1
fi

if [ -z "$APPLE_APP_SPECIFIC_PASSWORD" ]; then
    log_error "APPLE_APP_SPECIFIC_PASSWORD is not set"
    exit 1
fi

if [ -z "$APPLE_TEAM_ID" ]; then
    log_error "APPLE_TEAM_ID is not set"
    exit 1
fi

APP_PATH="dist/TextWave.app"
ENTITLEMENTS_PATH=".github/entitlements.plist"

# Verify app exists
if [ ! -d "$APP_PATH" ]; then
    log_error "App not found at $APP_PATH"
    exit 1
fi

log_info "Starting code signing and notarization process..."

# Create temporary keychain
KEYCHAIN_PATH="$RUNNER_TEMP/app-signing.keychain-db"
KEYCHAIN_PASSWORD=$(openssl rand -base64 32)

log_info "Creating temporary keychain..."
security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
security set-keychain-settings -lut 21600 "$KEYCHAIN_PATH"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"

# Decode and import certificate
log_info "Importing certificate..."
CERT_PATH="$RUNNER_TEMP/certificate.p12"
echo "$APPLE_CERTIFICATE_P12_BASE64" | base64 --decode > "$CERT_PATH"
security import "$CERT_PATH" -k "$KEYCHAIN_PATH" -P "$APPLE_CERTIFICATE_PASSWORD" -T /usr/bin/codesign

# Set keychain as default
security list-keychain -d user -s "$KEYCHAIN_PATH"
security set-key-partition-list -S apple-tool:,apple: -s -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"

# Find signing identity
log_info "Finding Developer ID Application certificate..."
SIGNING_IDENTITY=$(security find-identity -v -p codesigning "$KEYCHAIN_PATH" | grep "Developer ID Application" | head -1 | grep -o '"[^"]*"' | tr -d '"')

if [ -z "$SIGNING_IDENTITY" ]; then
    log_error "No Developer ID Application certificate found"
    security delete-keychain "$KEYCHAIN_PATH" || true
    exit 1
fi

log_info "Using signing identity: $SIGNING_IDENTITY"

# Sign all binaries - must be done in correct order: deepest first
log_info "Signing all binaries (this may take a few minutes)..."

# Step 1: Sign all .dylib and .so files
log_info "Step 1/5: Signing .dylib and .so files..."
find "$APP_PATH/Contents/Resources" -type f \( -name "*.dylib" -o -name "*.so" \) -print0 | while IFS= read -r -d '' file; do
    codesign --force --sign "$SIGNING_IDENTITY" --timestamp --options runtime "$file" 2>/dev/null || true
done

# Step 2: Sign all executables in MacOS directory (including Python)
log_info "Step 2/5: Signing executables in MacOS directory..."
find "$APP_PATH/Contents/MacOS" -type f -perm +111 -print0 | while IFS= read -r -d '' file; do
    log_info "  Signing: $(basename "$file")"
    codesign --force --sign "$SIGNING_IDENTITY" --timestamp --options runtime "$file" 2>/dev/null || true
done

# Step 3: Sign Qt/PyQt6 frameworks (must sign nested binaries first, then framework)
log_info "Step 3/5: Signing Qt frameworks..."
if [ -d "$APP_PATH/Contents/Resources/lib/python3.11/PyQt6/Qt6/lib" ]; then
    find "$APP_PATH/Contents/Resources/lib/python3.11/PyQt6/Qt6/lib" -name "*.framework" -print0 | while IFS= read -r -d '' framework; do
        # First sign any binaries inside the framework
        find "$framework" -type f \( -name "*.dylib" -o -perm +111 \) -print0 | while IFS= read -r -d '' binary; do
            codesign --force --sign "$SIGNING_IDENTITY" --timestamp --options runtime "$binary" 2>/dev/null || true
        done
        # Then sign the framework itself
        log_info "  Signing framework: $(basename "$framework")"
        codesign --force --sign "$SIGNING_IDENTITY" --timestamp --options runtime "$framework" 2>/dev/null || true
    done
fi

# Step 4: Sign any frameworks in Contents/Frameworks
log_info "Step 4/5: Signing frameworks in Contents/Frameworks..."
if [ -d "$APP_PATH/Contents/Frameworks" ]; then
    find "$APP_PATH/Contents/Frameworks" -name "*.framework" -print0 | while IFS= read -r -d '' framework; do
        log_info "  Signing framework: $(basename "$framework")"
        codesign --force --sign "$SIGNING_IDENTITY" --timestamp --options runtime "$framework" 2>/dev/null || true
    done
fi

# Step 5: Sign the main executable
log_info "Step 5/5: Signing main executable..."
codesign --force --sign "$SIGNING_IDENTITY" --timestamp --options runtime \
    --entitlements "$ENTITLEMENTS_PATH" \
    "$APP_PATH/Contents/MacOS/TextWave"

# Finally: Sign the app bundle itself
log_info "Signing app bundle..."
codesign --force --sign "$SIGNING_IDENTITY" --timestamp --options runtime \
    --entitlements "$ENTITLEMENTS_PATH" \
    "$APP_PATH"

# Verify signature
log_info "Verifying signature..."
codesign --verify --deep --strict --verbose=2 "$APP_PATH"
spctl --assess --type execute --verbose=4 "$APP_PATH" || log_warning "Gatekeeper assessment may fail before notarization"

# Create zip for notarization (notarization requires zip, not just app bundle)
log_info "Creating archive for notarization..."
NOTARIZATION_ZIP="$RUNNER_TEMP/TextWave-notarization.zip"
ditto -c -k --keepParent "$APP_PATH" "$NOTARIZATION_ZIP"

# Submit for notarization
log_info "Submitting to Apple notary service..."
NOTARIZATION_OUTPUT=$(xcrun notarytool submit "$NOTARIZATION_ZIP" \
    --apple-id "$APPLE_ID" \
    --password "$APPLE_APP_SPECIFIC_PASSWORD" \
    --team-id "$APPLE_TEAM_ID" \
    --wait \
    --timeout 30m 2>&1)

NOTARIZATION_EXIT_CODE=$?
echo "$NOTARIZATION_OUTPUT"

# Extract submission ID from output
SUBMISSION_ID=$(echo "$NOTARIZATION_OUTPUT" | grep -o 'id: [a-f0-9-]*' | head -1 | cut -d' ' -f2)

# Check if notarization was accepted
if echo "$NOTARIZATION_OUTPUT" | grep -q "status: Accepted"; then
    log_info "Notarization accepted!"
elif echo "$NOTARIZATION_OUTPUT" | grep -q "status: Invalid"; then
    log_error "Notarization was rejected by Apple!"
    if [ -n "$SUBMISSION_ID" ]; then
        log_error "Fetching detailed rejection log..."
        xcrun notarytool log "$SUBMISSION_ID" \
            --apple-id "$APPLE_ID" \
            --password "$APPLE_APP_SPECIFIC_PASSWORD" \
            --team-id "$APPLE_TEAM_ID" || true
    fi
    security delete-keychain "$KEYCHAIN_PATH" || true
    exit 1
elif [ $NOTARIZATION_EXIT_CODE -ne 0 ]; then
    log_error "Notarization failed with exit code $NOTARIZATION_EXIT_CODE"
    security delete-keychain "$KEYCHAIN_PATH" || true
    exit 1
else
    log_error "Notarization status unclear - check output above"
    security delete-keychain "$KEYCHAIN_PATH" || true
    exit 1
fi

# Staple the notarization ticket
log_info "Stapling notarization ticket..."
xcrun stapler staple "$APP_PATH"

# Verify stapling
log_info "Verifying stapled ticket..."
xcrun stapler validate "$APP_PATH"

# Final verification
log_info "Final signature verification..."
codesign --verify --deep --strict --verbose=2 "$APP_PATH"
spctl --assess --type execute --verbose=4 "$APP_PATH"

log_info "Code signing and notarization complete!"

# Clean up
log_info "Cleaning up temporary keychain..."
security delete-keychain "$KEYCHAIN_PATH" || true
rm -f "$CERT_PATH"
rm -f "$NOTARIZATION_ZIP"

log_info "All done! The app is signed and notarized."

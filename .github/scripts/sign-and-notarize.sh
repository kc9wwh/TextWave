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

# Sign all executables and frameworks inside the app
log_info "Signing embedded binaries and frameworks..."
find "$APP_PATH/Contents" -type f \( -name "*.dylib" -o -name "*.so" \) -exec codesign --force --sign "$SIGNING_IDENTITY" --timestamp --options runtime {} \;

# Sign frameworks
if [ -d "$APP_PATH/Contents/Frameworks" ]; then
    find "$APP_PATH/Contents/Frameworks" -type d -name "*.framework" | while read framework; do
        log_info "Signing framework: $(basename "$framework")"
        codesign --force --sign "$SIGNING_IDENTITY" --timestamp --options runtime "$framework"
    done
fi

# Sign the main executable
log_info "Signing main executable..."
codesign --force --sign "$SIGNING_IDENTITY" --timestamp --options runtime \
    --entitlements "$ENTITLEMENTS_PATH" \
    "$APP_PATH/Contents/MacOS/TextWave"

# Sign the app bundle
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
xcrun notarytool submit "$NOTARIZATION_ZIP" \
    --apple-id "$APPLE_ID" \
    --password "$APPLE_APP_SPECIFIC_PASSWORD" \
    --team-id "$APPLE_TEAM_ID" \
    --wait \
    --timeout 30m

# Check notarization status
NOTARIZATION_STATUS=$?
if [ $NOTARIZATION_STATUS -ne 0 ]; then
    log_error "Notarization failed"
    security delete-keychain "$KEYCHAIN_PATH" || true
    exit 1
fi

log_info "Notarization successful!"

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

#!/bin/bash
#
# Submit to App Store Connect
# Exports a signed PKG from the archive and uploads it via altool.
#
set -euo pipefail

# Configuration
# Parse Config to find Archive Path
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_PATH="${SCRIPT_DIR}/config.json"

if [ -f "${CONFIG_PATH}" ] && command -v python3 >/dev/null 2>&1; then
    eval "$(python3 - "$CONFIG_PATH" <<'PY'
import json
import shlex
import sys
import os

config_path = sys.argv[1]
try:
    config = json.load(open(config_path, "r", encoding="utf-8"))
except Exception:
    config = {}

def emit(var, key, is_path=False):
    value = config.get(key)
    if value is None or value == "":
        return
    if is_path:
        config_dir = os.path.dirname(os.path.abspath(config_path))
        value = os.path.normpath(os.path.join(config_dir, str(value)))
    print(f"{var}={shlex.quote(str(value))}")

emit("APP_NAME", "app_name")
emit("APPSTORE_ARCHIVE_ROOT", "appstore_archive_root", is_path=True)
PY
)"
fi

# Fallback defaults
APP_NAME="${APP_NAME:-MarcutApp}"
ARCHIVE_ROOT="${APPSTORE_ARCHIVE_ROOT:-Archive}"
ARCHIVE_PATH="${ARCHIVE_ROOT}/${APP_NAME}.xcarchive"
EXPORT_PATH="${ARCHIVE_ROOT}/Exported"
PKG_PATH="${EXPORT_PATH}/${APP_NAME}.pkg"
EXPORT_PLIST="ExportOptions.plist"

# Signing Identity for Installer (Required for App Store)
INSTALLER_IDENTITY="3rd Party Mac Developer Installer: Marc Mandel (QG85EMCQ75)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}ℹ️  $1${NC}"; }
log_success() { echo -e "${GREEN}✅ $1${NC}"; }
log_error() { echo -e "${RED}❌ $1${NC}"; }
log_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }
log_step() { echo -e "${BLUE}▶️  $1${NC}"; }

# Check for Installer Certificate
if ! security find-identity -v | grep -q "${INSTALLER_IDENTITY}"; then
    log_error "Missing Installer Certificate!"
    echo "You need '${INSTALLER_IDENTITY}' to sign the installer package."
    echo "Please create a 'Mac Installer Distribution' certificate in your Apple Developer Account and install it."
    exit 1
fi

# Check for Archive
if [ ! -d "${ARCHIVE_PATH}" ]; then
    log_error "Archive not found at ${ARCHIVE_PATH}"
    echo "Please run the 'Create App Store Archive' step first."
    exit 1
fi

# 1. Export PKG
log_info "Exporting signed installer package..."
rm -rf "${EXPORT_PATH}"
mkdir -p "${EXPORT_PATH}"

# We need a temporary ExportOptions.plist for the pkg export if the main one is different
# But usually standard App Store export produces a pkg if configured right, or we sign manually.
# For Mac App Store, xcodebuild -exportArchive with 'app-store' method should produce a PKG if signed correctly.

# Let's try standard export first.
# Let's try standard export first.
if xcodebuild -exportArchive \
    -archivePath "${ARCHIVE_PATH}" \
    -exportPath "${EXPORT_PATH}" \
    -exportOptionsPlist "${EXPORT_PLIST}"; then
    log_success "Export successful."
else
    log_warning "xcodebuild export failed. Falling back to manual packaging..."
    # Do not exit, proceed to manual packaging
fi

# Find the exported PKG
FOUND_PKG=$(find "${EXPORT_PATH}" -name "*.pkg" | head -1)
if [ -z "${FOUND_PKG}" ]; then
    log_info "No .pkg file found in export output. Checking for .app..."
    
    # Check export path first, then archive path
    FOUND_APP=$(find "${EXPORT_PATH}" -name "*.app" | head -1)
    if [ -z "${FOUND_APP}" ]; then
        FOUND_APP="${ARCHIVE_PATH}/Products/Applications/${APP_NAME}.app"
    fi
    
    if [ -d "${FOUND_APP}" ]; then
        log_info "Found app at: ${FOUND_APP}"
        log_step "Creating installer package manually..."
        
        # Create the package
        # We use --component to package the app bundle.
        # --install-location /Applications is standard.
        productbuild \
            --component "${FOUND_APP}" \
            /Applications \
            --sign "${INSTALLER_IDENTITY}" \
            "${PKG_PATH}"
            
        if [ $? -eq 0 ]; then
            FOUND_PKG="${PKG_PATH}"
            log_success "Created signed installer: ${PKG_PATH}"
        else
            log_error "Failed to create installer package."
            exit 1
        fi
    else
        log_error "Could not find .app bundle to package."
        exit 1
    fi
fi

log_info "Installer ready: ${FOUND_PKG}"

# Parse Arguments
AUTO_MODE=false
for arg in "$@"; do
    if [ "$arg" == "--auto" ]; then
        AUTO_MODE=true
    fi
done

# 2. Upload to App Store using altool
log_info "Ready to upload using altool (standard for App Store)."

# Keychain Configuration
KEYCHAIN_SERVICE="MarcutAppStore"

# Check if credentials exist in Keychain
if security find-generic-password -s "${KEYCHAIN_SERVICE}" &>/dev/null; then
    log_info "Found credentials in Keychain."
    if [ "$AUTO_MODE" = true ]; then
        USE_KEYCHAIN=true
    else
        read -p "Use saved credentials? (Y/n): " USE_SAVED
        if [[ "${USE_SAVED}" =~ ^[Nn]$ ]]; then
            USE_KEYCHAIN=false
        else
            USE_KEYCHAIN=true
        fi
    fi
else
    if [ "$AUTO_MODE" = true ]; then
        log_error "Auto mode: No credentials found in Keychain."
        log_info "Please run without --auto once to save credentials."
        exit 1
    fi
    USE_KEYCHAIN=false
fi

if [ "$USE_KEYCHAIN" = true ]; then
    # Retrieve Apple ID (Account) and Password from Keychain
    SAVED_APPLE_ID=$(security find-generic-password -s "${KEYCHAIN_SERVICE}" | grep "acct" | cut -d "=" -f2 | tr -d '"')
    
    if [ -n "${SAVED_APPLE_ID}" ]; then
        APPLE_ID="${SAVED_APPLE_ID}"
        # altool supports reference to keychain items via @keychain:
        # We need to make sure the service name is what altool expects or just pass the password explicitly
        # Ideally, we pass it explicitly to avoid ambiguity
        APP_PASS=$(security find-generic-password -s "${KEYCHAIN_SERVICE}" -a "${APPLE_ID}" -w)
        
        log_info "Uploading as ${APPLE_ID}..."
        xcrun altool --upload-app --type macos --file "${FOUND_PKG}" \
            --username "${APPLE_ID}" --password "${APP_PASS}"
        exit 0
    else
        log_warning "Could not retrieve Apple ID from Keychain item."
        USE_KEYCHAIN=false
    fi
fi

if [ "$USE_KEYCHAIN" = false ]; then
    echo "You need App Store Connect credentials."
    echo "1. API Key (Issuer ID, Key ID, Private Key)"
    echo "2. App-Specific Password (Email, Password)"
    read -p "Select authentication method (1/2): " AUTH_METHOD

    if [ "$AUTH_METHOD" == "1" ]; then
        read -p "API Key ID: " KEY_ID
        read -p "API Issuer ID: " ISSUER_ID
        read -p "Path to Private Key (.p8) or Key Content: " KEY_PATH
        
        log_info "Uploading with API Key..."
        xcrun altool --upload-app --type macos --file "${FOUND_PKG}" \
            --apiKey "${KEY_ID}" --apiIssuer "${ISSUER_ID}"
            
    elif [ "$AUTH_METHOD" == "2" ]; then
        read -p "Apple ID (Email): " APPLE_ID
        read -s -p "App-Specific Password: " APP_PASS
        echo ""
        
        # Offer to save to Keychain
        read -p "Save directly to Keychain? (y/N): " SAVE_TO_KEYCHAIN
        if [[ "${SAVE_TO_KEYCHAIN}" =~ ^[Yy]$ ]]; then
            # Remove existing if any
            security delete-generic-password -s "${KEYCHAIN_SERVICE}" -a "${APPLE_ID}" &>/dev/null || true
            # Add new
            security add-generic-password -s "${KEYCHAIN_SERVICE}" -a "${APPLE_ID}" -w "${APP_PASS}" -U
            log_success "Saved to Keychain (Service: ${KEYCHAIN_SERVICE}, Account: ${APPLE_ID})"
        fi
        
        log_info "Uploading with App-Specific Password..."
        xcrun altool --upload-app --type macos --file "${FOUND_PKG}" \
            --username "${APPLE_ID}" --password "${APP_PASS}"
    else
        log_error "Invalid selection."
        exit 1
    fi
fi

log_success "Upload command finished."

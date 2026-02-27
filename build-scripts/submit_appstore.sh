#!/bin/bash
#
# Submit to App Store Connect
# Exports a signed PKG from the archive and uploads it via altool.
#
set -euo pipefail

# Configuration
# Parse Config to find Archive Path
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "${SCRIPT_DIR}")"
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
emit("APPSTORE_DEFAULT_ARCHIVE", "appstore_default_archive")
emit("APPSTORE_BUILD_ROOT", "appstore_build_root", is_path=True)
emit("TEAM_ID", "appstore_default_team_id")
emit("INSTALLER_IDENTITY", "appstore_default_installer_identity")
PY
)"
fi

# Fallback defaults
APP_NAME="${APP_NAME:-MarcutApp}"
ARCHIVE_ROOT="${APPSTORE_ARCHIVE_ROOT:-${ROOT_DIR}/.marcut_artifacts/ignored-resources/appstore/Archive}"
ARCHIVE_NAME="${APPSTORE_DEFAULT_ARCHIVE:-${APP_NAME}}"
ARCHIVE_PATH="${ARCHIVE_ROOT}/${ARCHIVE_NAME}.xcarchive"
APPSTORE_BUILD_ROOT="${APPSTORE_BUILD_ROOT:-${ROOT_DIR}/.marcut_artifacts/ignored-resources/appstore/build}"
EXPORT_PATH="${ARCHIVE_ROOT}/Exported"
PKG_PATH="${EXPORT_PATH}/${APP_NAME}.pkg"
EXPORT_PLIST="ExportOptions.plist"

# Signing Identity for Installer (Required for App Store)
INSTALLER_IDENTITY="${INSTALLER_IDENTITY:-}"

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

normalize_permissions() {
    local target="$1"
    if [ -z "$target" ] || [ ! -e "$target" ]; then
        return
    fi
    log_step "Normalizing bundle permissions..."
    chmod -R u+rwX,go+rX "$target" 2>/dev/null || true
}

safe_rm_rf() {
    local target="$1"
    if [[ -z "${target}" || "${target}" == "/" ]]; then
        log_error "Refusing to remove unsafe path: '${target}'"
        exit 1
    fi
    if [[ "${MARCUT_ALLOW_UNSAFE_RM:-}" == "1" ]]; then
        rm -rf "${target}"
        return
    fi
    case "${target}" in
        "${ROOT_DIR}"/*) ;;
        "/tmp/"*|"/var/folders/"*) ;;
        *) log_error "Refusing to remove path outside repo/tmp: ${target} (set MARCUT_ALLOW_UNSAFE_RM=1 to override)"; exit 1 ;;
    esac
    rm -rf "${target}"
}

# Check for Installer Certificate
if [ -z "${INSTALLER_IDENTITY}" ]; then
    log_error "Installer signing identity not configured."
    echo "Set INSTALLER_IDENTITY or appstore_default_installer_identity in build-scripts/config.json."
    exit 1
fi

if ! security find-identity -v | grep -q "${INSTALLER_IDENTITY}"; then
    log_error "Missing Installer Certificate!"
    echo "You need '${INSTALLER_IDENTITY}' to sign the installer package."
    echo "Please create a 'Mac Installer Distribution' certificate in your Apple Developer Account and install it."
    exit 1
fi

# Check for Archive
if [ ! -d "${ARCHIVE_PATH}" ]; then
    log_warning "Archive not found at ${ARCHIVE_PATH}"
    echo "Will attempt to package an existing app bundle instead."
    ARCHIVE_PATH=""
fi

# 1. Export PKG
log_info "Exporting signed installer package..."
safe_rm_rf "${EXPORT_PATH}"
mkdir -p "${EXPORT_PATH}"

# We need a temporary ExportOptions.plist for the pkg export.
EXPORT_PLIST_PATH="${EXPORT_PATH}/${EXPORT_PLIST}"
if [ ! -f "${EXPORT_PLIST_PATH}" ]; then
    log_info "Creating ExportOptions.plist..."
    cat > "${EXPORT_PLIST_PATH}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>method</key>
    <string>app-store</string>
    <key>signingStyle</key>
    <string>automatic</string>
    <key>teamID</key>
    <string>${TEAM_ID}</string>
    <key>uploadSymbols</key>
    <true/>
    <key>uploadBitcode</key>
    <false/>
</dict>
</plist>
EOF
fi

# Try standard export first when an archive is available.
if [ -n "${ARCHIVE_PATH}" ]; then
    if xcodebuild -exportArchive \
        -archivePath "${ARCHIVE_PATH}" \
        -exportPath "${EXPORT_PATH}" \
        -exportOptionsPlist "${EXPORT_PLIST_PATH}"; then
        log_success "Export successful."
    else
        log_warning "xcodebuild export failed. Falling back to manual packaging..."
        # Do not exit, proceed to manual packaging
    fi
else
    log_warning "Skipping xcodebuild export (no archive found)."
fi

# Find the exported PKG
FOUND_PKG=$(find "${EXPORT_PATH}" -name "*.pkg" | head -1)
if [ -z "${FOUND_PKG}" ]; then
    log_info "No .pkg file found in export output. Checking for .app..."
    
    # Check export path first, then archive path
    FOUND_APP=$(find "${EXPORT_PATH}" -name "*.app" | head -1)
    if [ -z "${FOUND_APP}" ] && [ -n "${ARCHIVE_PATH}" ] && [ -d "${ARCHIVE_PATH}/Products/Applications/${APP_NAME}.app" ]; then
        FOUND_APP="${ARCHIVE_PATH}/Products/Applications/${APP_NAME}.app"
    fi
    if [ -z "${FOUND_APP}" ] && [ -d "${APPSTORE_BUILD_ROOT}/${APP_NAME}.app" ]; then
        FOUND_APP="${APPSTORE_BUILD_ROOT}/${APP_NAME}.app"
    fi
    
    if [ -d "${FOUND_APP}" ]; then
        if [ ! -f "${FOUND_APP}/Contents/embedded.provisionprofile" ]; then
            log_error "embedded.provisionprofile missing in app bundle."
            log_info "Rebuild the App Store archive with a valid provisioning profile."
            exit 1
        fi
        log_info "Found app at: ${FOUND_APP}"
        log_step "Creating installer package manually..."

        normalize_permissions "${FOUND_APP}"
        
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
EXPORT_ONLY=false
for arg in "$@"; do
    if [ "$arg" == "--auto" ]; then
        AUTO_MODE=true
    fi
    if [ "$arg" == "--export-only" ]; then
        EXPORT_ONLY=true
    fi
done

if [ "$EXPORT_ONLY" = true ]; then
    log_success "Export-only mode: skipping upload."
    log_info "PKG ready for Transporter: ${FOUND_PKG}"
    exit 0
fi

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

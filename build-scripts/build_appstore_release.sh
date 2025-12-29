#!/bin/bash
#
# MarcutApp - App Store Release Build
# Creates a signed .xcarchive with Embedded Provisioning Profile
#
set -euo pipefail

# --- CONFIGURATION ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "${SCRIPT_DIR}")"
CONFIG_PATH="${SCRIPT_DIR}/config.json"

APP_NAME="MarcutApp"
BUNDLE_ID="com.marclaw.marcutapp"
VERSION="0.3.20"
BUILD_NUMBER="1"
TEAM_ID="QG85EMCQ75"
IDENTITY="3rd Party Mac Developer Application: Marc Mandel (QG85EMCQ75)"

# PROVISIONING PROFILE PATH (Crucial for App Store)
# We point directly to the file you mentioned in your config
PROVISIONING_PROFILE="${ROOT_DIR}/Marcut_App_Store.provisionprofile"

OLLAMA_URL="https://github.com/ollama/ollama/releases/download/v0.12.5/ollama-darwin.tgz"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${BLUE}▶️  $1${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $1${NC}"; }
error() { echo -e "${RED}❌ $1${NC}"; exit 1; }

if [ -f "${CONFIG_PATH}" ] && command -v python3 >/dev/null 2>&1; then
    eval "$(python3 - "$CONFIG_PATH" <<'PY'
import json
import shlex
import sys

config_path = sys.argv[1]
try:
    config = json.load(open(config_path, "r", encoding="utf-8"))
except Exception:
    config = {}

import os

def emit(var, key, is_path=False):
    value = config.get(key)
    if value is None or value == "":
        return
    if is_path:
        # Resolve path relative to config file location
        config_dir = os.path.dirname(os.path.abspath(config_path))
        value = os.path.normpath(os.path.join(config_dir, str(value)))
        
    print(f"{var}={shlex.quote(str(value))}")

emit("APP_NAME", "app_name")
emit("BUNDLE_ID", "bundle_id")
emit("VERSION", "version")
emit("BUILD_NUMBER", "build_number")
emit("TEAM_ID", "appstore_default_team_id")
emit("IDENTITY", "appstore_default_identity")
emit("PROVISIONING_PROFILE", "appstore_default_profile", is_path=True)
emit("SWIFT_PROJECT_DIR", "swift_project_dir", is_path=True)
emit("PYTHON_SITE_SOURCE", "python_site_source", is_path=True)
emit("PYTHON_SITE_REPO_SOURCE", "python_site_repo_source", is_path=True)
emit("PYTHON_FRAMEWORK_SOURCE", "python_framework_source", is_path=True)
emit("PYTHON_FRAMEWORK_SOURCE", "python_framework_source", is_path=True)
emit("OLLAMA_ENTITLEMENTS", "ollama_entitlements", is_path=True)
emit("ASSETS_DIR", "assets_dir", is_path=True)
emit("APPSTORE_BUILD_ROOT", "appstore_build_root", is_path=True)
emit("APPSTORE_ARCHIVE_ROOT", "appstore_archive_root", is_path=True)
PY
)"
fi

if [[ "${PROVISIONING_PROFILE}" != /* ]]; then
    PROVISIONING_PROFILE="${ROOT_DIR}/${PROVISIONING_PROFILE}"
fi

# Ensure we are in the script directory (though absolute paths make this less critical)
cd "${SCRIPT_DIR}"

# Paths (derived after config load)
# Use config values if present, else fallback to historical defaults
BUILD_DIR="${APPSTORE_BUILD_ROOT:-${ROOT_DIR}/build}"
ARCHIVE_DIR="${APPSTORE_ARCHIVE_ROOT:-${ROOT_DIR}/Archive}"

# Ensure these directories exist
mkdir -p "${BUILD_DIR}"
mkdir -p "${ARCHIVE_DIR}"
APP_BUNDLE="${BUILD_DIR}/${APP_NAME}.app"
XCARCHIVE_PATH="${ARCHIVE_DIR}/${APP_NAME}.xcarchive"
ENTITLEMENTS="${SWIFT_PROJECT_DIR}/MarcutApp.entitlements"

# Use config value if present, else default
if [ -z "${OLLAMA_ENTITLEMENTS:-}" ]; then
    OLLAMA_ENTITLEMENTS="MarcutOllama.entitlements"
fi

# --- PRE-FLIGHT ---
log "Checking prerequisites..."
if ! security find-identity -v -p codesigning | grep -q "${TEAM_ID}"; then
    error "Signing identity for team ${TEAM_ID} not found."
fi

if [ ! -f "${PROVISIONING_PROFILE}" ]; then
    error "Provisioning profile not found at: ${PROVISIONING_PROFILE}\nPlease ensure the file exists."
fi

# Create Entitlements
# Note: We use the TeamID prefix for App Groups which is standard
# Create Entitlements - DISABLED, using source entitlements
# if [ ! -f "${ENTITLEMENTS}" ]; then
#     log "Creating entitlements..."
#     cat > "${ENTITLEMENTS}" <<EOF2
# ...
# EOF2
# fi

if [ ! -f "${OLLAMA_ENTITLEMENTS}" ]; then
    cat > "${OLLAMA_ENTITLEMENTS}" <<EOF3
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.app-sandbox</key>
    <true/>
    <key>com.apple.security.inherit</key>
    <true/>
</dict>
</plist>
EOF3
fi

# --- BUILD ---
log "Building Swift Binary..."
rm -rf "${BUILD_DIR}" "${ARCHIVE_DIR}"
mkdir -p "${BUILD_DIR}"
cd "${SWIFT_PROJECT_DIR}"
swift build -c release --arch arm64
cd "${ROOT_DIR}"
[ -f "${SWIFT_PROJECT_DIR}/.build/release/MarcutApp" ] || error "Build failed"

# --- ASSEMBLE ---
log "Assembling App Bundle..."
mkdir -p "${APP_BUNDLE}/Contents/"{MacOS,Resources,Frameworks}

# 1. Install Main Binary
cp "${SWIFT_PROJECT_DIR}/.build/release/MarcutApp" "${APP_BUNDLE}/Contents/MacOS/"

# 2. Install Info.plist
cat > "${APP_BUNDLE}/Contents/Info.plist" <<EOF4
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>${APP_NAME}</string>
    <key>CFBundleIdentifier</key>
    <string>${BUNDLE_ID}</string>
    <key>CFBundleName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleVersion</key>
    <string>${BUILD_NUMBER}</string>
    <key>CFBundleShortVersionString</key>
    <string>${VERSION}</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>14.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSApplicationCategoryType</key>
    <string>public.app-category.productivity</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>ITSAppUsesNonExemptEncryption</key>
    <false/>
</dict>
</plist>
EOF4

# 3. Install Provisioning Profile (CRITICAL FIX)
log "Embedding Provisioning Profile..."
cp "${PROVISIONING_PROFILE}" "${APP_BUNDLE}/Contents/embedded.provisionprofile"

# 4. Install Privacy Manifest (REQUIRED)
log "Installing Privacy Manifest..."
if [ -f "${ASSETS_DIR}/PrivacyInfo.xcprivacy" ]; then
    cp "${ASSETS_DIR}/PrivacyInfo.xcprivacy" "${APP_BUNDLE}/Contents/Resources/"
else
    warn "PrivacyInfo.xcprivacy not found in ${ASSETS_DIR}! App Store submission may fail."
fi

# Copy additional resources
# Ensure we look in the project sources for these files
RESOURCES_SRC="${SWIFT_PROJECT_DIR}/Sources/MarcutApp/Resources"

if [ -f "${RESOURCES_SRC}/excluded-words.txt" ]; then
    log "Copying excluded-words.txt..."
    cp "${RESOURCES_SRC}/excluded-words.txt" "${APP_BUNDLE}/Contents/Resources/"
    
    # Also copy to python_site/marcut location if needed by python code
    mkdir -p "${APP_BUNDLE}/Contents/Resources/python_site/marcut"
    cp "${RESOURCES_SRC}/excluded-words.txt" "${APP_BUNDLE}/Contents/Resources/python_site/marcut/excluded-words.txt"
else
    warn "excluded-words.txt not found at ${RESOURCES_SRC}/excluded-words.txt"
fi

if [ -f "${ROOT_DIR}/pyproject.toml" ]; then
    cp "${ROOT_DIR}/pyproject.toml" "${APP_BUNDLE}/Contents/Resources/"
fi

# Copy help.md from assets
if [ -f "${ROOT_DIR}/assets/help.md" ]; then
    log "Copying help.md..."
    cp "${ROOT_DIR}/assets/help.md" "${APP_BUNDLE}/Contents/Resources/help.md"
else
    warn "help.md not found at ${ROOT_DIR}/assets/help.md"
fi

# 5. Install Python Framework (and sync marcut code first)
# 5. Install Python Site (Base)
if [ -d "${PYTHON_SITE_SOURCE}" ]; then
    log "Installing python_site from ${PYTHON_SITE_SOURCE}..."
    cp -R "${PYTHON_SITE_SOURCE}" "${APP_BUNDLE}/Contents/Resources/"
else
    error "python_site source not found at ${PYTHON_SITE_SOURCE}"
fi

# 6. Overlay Latest Marcut Source
log "Syncing latest marcut source code..."
if [ -d "${PYTHON_SITE_REPO_SOURCE}" ]; then
    mkdir -p "${APP_BUNDLE}/Contents/Resources/python_site/marcut"
    rsync -a --delete "${PYTHON_SITE_REPO_SOURCE}/" "${APP_BUNDLE}/Contents/Resources/python_site/marcut/"
else
    error "Source marcut directory not found at ${PYTHON_SITE_REPO_SOURCE}"
fi

# 7. Install Python Framework
if [ -d "${PYTHON_FRAMEWORK_SOURCE}" ]; then
    log "Installing Python.framework..."
    cp -R "${PYTHON_FRAMEWORK_SOURCE}" "${APP_BUNDLE}/Contents/Frameworks/"
else
    error "Python.framework not found at ${PYTHON_FRAMEWORK_SOURCE}. Run setup_beeware_framework.sh first."
fi

# CLEANUP: Remove Python test suites and __pycache__ to pass App Store validation
log "Cleaning up Python framework (removing tests and caches)..."
find "${APP_BUNDLE}/Contents/Frameworks" -name "test" -type d -exec rm -rf {} + 2>/dev/null || true
find "${APP_BUNDLE}/Contents/Frameworks" -name "tests" -type d -exec rm -rf {} + 2>/dev/null || true
find "${APP_BUNDLE}/Contents/Frameworks" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "${APP_BUNDLE}/Contents/Resources/python_site" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# 6. Install Ollama
if [ ! -f "ollama_binary" ]; then
    log "Downloading Ollama..."
    curl -L -o ollama.tgz "${OLLAMA_URL}"
    tar -xzf ollama.tgz
    mv ollama ollama_binary
    rm ollama.tgz
fi
mkdir -p "${APP_BUNDLE}/Contents/MacOS"
cp ollama_binary "${APP_BUNDLE}/Contents/MacOS/ollama"
chmod 755 "${APP_BUNDLE}/Contents/MacOS/ollama"

# 7. Resources
[ -f "${ASSETS_DIR}/AppIcon.icns" ] && cp "${ASSETS_DIR}/AppIcon.icns" "${APP_BUNDLE}/Contents/Resources/"

# --- CLEANUP ---
log "Fixing permissions..."
chmod -R u+w,go+r,a+rX "${APP_BUNDLE}"
xattr -cr "${APP_BUNDLE}"

# --- SIGNING ---
log "Signing Components..."

# Sign ALL dynamic libraries in Frameworks (dylibs, so files, and Python binary)
log "Signing Frameworks..."
find "${APP_BUNDLE}/Contents/Frameworks" -type f \( -name "*.dylib" -o -name "*.so" -o -name "Python" \) | while read -r lib; do
    log "  Signing: $(basename "$lib")"
    codesign --force --sign "${IDENTITY}" --options runtime --timestamp "$lib" 2>/dev/null || true
done

# Sign ALL dynamic libraries and extensions in python_site (including llama_cpp dylibs)
log "Signing Python site-packages..."
find "${APP_BUNDLE}/Contents/Resources/python_site" -type f \( -name "*.so" -o -name "*.dylib" \) | while read -r lib; do
    log "  Signing: $(basename "$lib")"
    codesign --force --sign "${IDENTITY}" --options runtime --timestamp "$lib" 2>/dev/null || true
done

# Sign Ollama binary with its specific entitlements
log "Signing Ollama..."
codesign --force --sign "${IDENTITY}" --entitlements "${OLLAMA_ENTITLEMENTS}" --options runtime --timestamp "${APP_BUNDLE}/Contents/MacOS/ollama"

# Sign Python.framework bundle (must be signed as a bundle, not individual files)
log "Signing Python.framework..."
if [ -d "${APP_BUNDLE}/Contents/Frameworks/Python.framework" ]; then
    codesign --force --deep --sign "${IDENTITY}" --options runtime --timestamp "${APP_BUNDLE}/Contents/Frameworks/Python.framework"
fi

# Sign Main Bundle LAST (deep sign to catch any missed components)
log "Signing App Bundle..."
codesign --force --sign "${IDENTITY}" --entitlements "${ENTITLEMENTS}" --options runtime --timestamp "${APP_BUNDLE}"

# Verify
log "Verifying Signature..."
if ! codesign --verify --verbose "${APP_BUNDLE}"; then
    error "Signature verification failed"
fi

# --- ARCHIVE ---
log "Creating .xcarchive..."
mkdir -p "${XCARCHIVE_PATH}/Products/Applications"
cp -R "${APP_BUNDLE}" "${XCARCHIVE_PATH}/Products/Applications/"

cat > "${XCARCHIVE_PATH}/Info.plist" <<EOF5
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>ApplicationProperties</key>
    <dict>
        <key>ApplicationPath</key>
        <string>Applications/${APP_NAME}.app</string>
        <key>CFBundleIdentifier</key>
        <string>${BUNDLE_ID}</string>
        <key>CFBundleShortVersionString</key>
        <string>${VERSION}</string>
        <key>CFBundleVersion</key>
        <string>${BUILD_NUMBER}</string>
        <key>SigningIdentity</key>
        <string>${IDENTITY}</string>
        <key>Team</key>
        <string>${TEAM_ID}</string>
    </dict>
    <key>ArchiveVersion</key>
    <integer>2</integer>
    <key>CreationDate</key>
    <date>$(date -u +"%Y-%m-%dT%H:%M:%SZ")</date>
    <key>Name</key>
    <string>${APP_NAME}</string>
    <key>SchemeName</key>
    <string>${APP_NAME}</string>
</dict>
</plist>
EOF5

echo -e "${GREEN}✅ Archive Created: ${XCARCHIVE_PATH}${NC}"

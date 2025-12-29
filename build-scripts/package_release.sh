#!/bin/bash
#
# Package Release (No Upload)
# Builds the App Store Archive and creates a signed PKG, but does NOT upload.
#
set -euo pipefail

# Configuration
APP_NAME="MarcutApp"
ARCHIVE_PATH="Archive/${APP_NAME}.xcarchive"
EXPORT_PATH="Archive/Exported"
PKG_PATH="${EXPORT_PATH}/${APP_NAME}.pkg"
INSTALLER_IDENTITY="3rd Party Mac Developer Installer: Marc Mandel (QG85EMCQ75)"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${BLUE}▶️  $1${NC}"; }
success() { echo -e "${GREEN}✅ $1${NC}"; }
error() { echo -e "${RED}❌ $1${NC}"; }

# 1. Build Archive
log "Building App Store Archive..."
./build_appstore_release.sh

# 2. Create PKG
log "Creating Signed Installer Package..."
rm -rf "${EXPORT_PATH}"
mkdir -p "${EXPORT_PATH}"

# Find App in Archive
FOUND_APP="${ARCHIVE_PATH}/Products/Applications/${APP_NAME}.app"

if [ ! -d "${FOUND_APP}" ]; then
    error "Could not find app at ${FOUND_APP}"
    exit 1
fi

log "Packaging ${FOUND_APP}..."

productbuild \
    --component "${FOUND_APP}" \
    /Applications \
    --sign "${INSTALLER_IDENTITY}" \
    "${PKG_PATH}"

if [ $? -eq 0 ]; then
    success "Package Created: ${PKG_PATH}"
    echo ""
    echo "To test:"
    echo "  open \"${PKG_PATH}\""
    echo ""
    echo "To upload later:"
    echo "  ./submit_appstore.sh"
else
    error "Packaging failed."
    exit 1
fi

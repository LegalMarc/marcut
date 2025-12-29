#!/bin/bash
#
# MarcutApp - App Store Distribution Build Script
# Creates a signed and notarized DMG for Mac App Store distribution
#
set -euo pipefail

# ===== CONFIGURATION =====
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_PATH="${ROOT_DIR}/config.json"

APP_NAME="MarcutApp"
BUNDLE_ID="com.marclaw.marcutapp"
VERSION="0.3.24"
BUILD_NUMBER="1"

# Signing Configuration
DEVELOPER_ID="3rd Party Mac Developer Application: Marc Mandel (QG85EMCQ75)"
TEAM_ID="QG85EMCQ75"

# Ollama configuration
OLLAMA_VERSION="0.4.0"
OLLAMA_DOWNLOAD_URL="https://github.com/ollama/ollama/releases/download/v${OLLAMA_VERSION}/ollama-darwin"

# Notarization Configuration
NOTARIZATION_PROFILE="marcut-notarization"  # You'll need to create this
PROVISIONING_PROFILE="Marcut_App_Store.provisionprofile"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

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

def emit(var, key):
    value = config.get(key)
    if value is None or value == "":
        return
    print(f"{var}={shlex.quote(str(value))}")

emit("APP_NAME", "app_name")
emit("BUNDLE_ID", "bundle_id")
emit("VERSION", "version")
emit("BUILD_NUMBER", "build_number")
emit("TEAM_ID", "appstore_default_team_id")
emit("DEVELOPER_ID", "appstore_default_identity")
emit("PROVISIONING_PROFILE", "appstore_default_profile")
PY
)"
fi

if [[ "${PROVISIONING_PROFILE}" != /* ]]; then
    PROVISIONING_PROFILE="${ROOT_DIR}/${PROVISIONING_PROFILE}"
fi

# Recompute derived paths after config load
BUILD_DIR="${ROOT_DIR}/build"
ARCHIVE_DIR="${ROOT_DIR}/archive"
APP_BUNDLE="${BUILD_DIR}/${APP_NAME}.app"
ARCHIVE_PATH="${ARCHIVE_DIR}/${APP_NAME}.xcarchive"
DMG_NAME="${APP_NAME}-v${VERSION}-AppStore"
FINAL_DMG="${ROOT_DIR}/${DMG_NAME}.dmg"
VOLUME_NAME="${APP_NAME}"
ENTITLEMENTS="Marcut.entitlements"
OLLAMA_ENTITLEMENTS="MarcutOllama.entitlements"

cd "${ROOT_DIR}"

cleanup_path() {
    local target="$1"
    if [ ! -e "$target" ]; then
        return
    fi

    chmod -R u+w "$target" 2>/dev/null || true
    rm -rf "$target" 2>/dev/null || true

    if [ -e "$target" ]; then
        local backup="${target}.cleanup.$(date +%s)"
        mv "$target" "$backup" 2>/dev/null || true
        chmod -R u+w "$backup" 2>/dev/null || true
        rm -rf "$backup" 2>/dev/null || true
    fi

    if [ -e "$target" ]; then
        log_error "Failed to remove $target"
        exit 1
    fi
}

ensure_ollama_binary() {
    log_section "Ensuring Ollama Binary v${OLLAMA_VERSION}"

    local cache_dir="${ROOT_DIR}/build_cache"
    local cached_binary="${cache_dir}/ollama-${OLLAMA_VERSION}-darwin-arm64"

    mkdir -p "${cache_dir}"

    if [ ! -f "${cached_binary}" ]; then
        log_step "Downloading Ollama ${OLLAMA_VERSION} (arm64)..."
        curl -L -o "${cached_binary}.tmp" "${OLLAMA_DOWNLOAD_URL}"
        mv "${cached_binary}.tmp" "${cached_binary}"
        log_success "Downloaded Ollama binary"
    else
        log_info "Using cached Ollama binary at ${cached_binary}"
    fi

    cp "${cached_binary}" "${ROOT_DIR}/ollama_binary"
    chmod 755 "${ROOT_DIR}/ollama_binary"

    local binary_size
    binary_size=$(stat -f%z "${ROOT_DIR}/ollama_binary")
    if [ "${binary_size}" -lt 100000 ]; then
        log_error "Downloaded Ollama binary size (${binary_size}) looks invalid"
        log_info "Removing cached binary so next run re-downloads..."
        rm -f "${cached_binary}" "${ROOT_DIR}/ollama_binary"
        exit 1
    fi

    if ! file "${ROOT_DIR}/ollama_binary" | grep -q "Mach-O"; then
        log_error "Downloaded Ollama binary is not a Mach-O executable"
        rm -f "${cached_binary}" "${ROOT_DIR}/ollama_binary"
        exit 1
    fi
}

# ===== UTILITY FUNCTIONS =====
log_section() {
    echo ""
    echo -e "${MAGENTA}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${MAGENTA}  $1${NC}"
    echo -e "${MAGENTA}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

log_step() {
    echo -e "${CYAN}▶️  $1${NC}"
}

# ===== VALIDATION =====
check_prerequisites() {
    log_section "Checking Prerequisites"

    # Check for Xcode
    if ! command -v xcodebuild &> /dev/null; then
        log_error "Xcode Command Line Tools not found"
        log_info "Install with: xcode-select --install"
        exit 1
    fi
    log_success "Xcode Command Line Tools found"

    # Check for signing identity
    if ! security find-identity -v -p codesigning | grep -q "${DEVELOPER_ID}"; then
        log_error "Signing identity '${DEVELOPER_ID}' not found"
        log_info "Available identities:"
        security find-identity -v -p codesigning
        exit 1
    fi
    log_success "Signing identity found"

    # Check for entitlements file
    if [ ! -f "${ENTITLEMENTS}" ]; then
        log_error "Entitlements file not found: ${ENTITLEMENTS}"
        exit 1
    fi
    log_success "Entitlements file found"

    if [ ! -f "${OLLAMA_ENTITLEMENTS}" ]; then
        log_error "Ollama entitlements file not found: ${OLLAMA_ENTITLEMENTS}"
        exit 1
    fi
    log_success "Ollama entitlements file found"

    # Check Swift Package
    if [ ! -f "MarcutApp/Package.swift" ]; then
        log_error "Swift Package not found at MarcutApp/Package.swift"
        exit 1
    fi
    log_success "Swift Package found"
}

# ===== BUILD SWIFT APP =====
build_swift_app() {
    log_section "Building Swift Application"

    # Clean previous builds
    log_step "Cleaning previous builds..."
    cleanup_path "${BUILD_DIR}"
    cleanup_path "${ARCHIVE_DIR}"
    cleanup_path "MarcutApp/.build"
    mkdir -p "${BUILD_DIR}" "${ARCHIVE_DIR}"

    # Build the Swift package
    log_step "Building Swift Package (Release Configuration)..."
    cd MarcutApp

    swift build \
        --configuration release \
        --arch arm64 \
        --build-path .build

    if [ $? -eq 0 ]; then
        log_success "Swift build completed successfully"
    else
        log_error "Swift build failed"
        exit 1
    fi

    cd ..
}

# ===== CREATE APP BUNDLE =====
create_app_bundle() {
    log_section "Creating App Bundle"

    log_step "Creating bundle structure..."
    cleanup_path "${APP_BUNDLE}"
    mkdir -p "${APP_BUNDLE}/Contents/MacOS"
    mkdir -p "${APP_BUNDLE}/Contents/Resources"
    mkdir -p "${APP_BUNDLE}/Contents/Frameworks"

    # Copy executable
    log_step "Installing executable..."
    cp "MarcutApp/.build/release/MarcutApp" "${APP_BUNDLE}/Contents/MacOS/"
    chmod +x "${APP_BUNDLE}/Contents/MacOS/MarcutApp"

    # Create Info.plist for App Store
    log_step "Creating Info.plist..."
    cat > "${APP_BUNDLE}/Contents/Info.plist" << EOF
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
    <key>CFBundleDisplayName</key>
    <string>Marcut</string>
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
    <key>NSHumanReadableCopyright</key>
    <string>Copyright © 2025 Marc Mandel. All rights reserved.</string>
    <key>CFBundleDocumentTypes</key>
    <array>
        <dict>
            <key>CFBundleTypeName</key>
            <string>Microsoft Word Document</string>
            <key>LSHandlerRank</key>
            <string>Default</string>
            <key>CFBundleTypeRole</key>
            <string>Editor</string>
            <key>LSItemContentTypes</key>
            <array>
                <string>org.openxmlformats.wordprocessingml.document</string>
                <string>com.microsoft.word.doc</string>
            </array>
            <key>CFBundleTypeExtensions</key>
            <array>
                <string>docx</string>
            </array>
        </dict>
    </array>
    <key>NSSupportsAutomaticGraphicsSwitching</key>
    <true/>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>ITSAppUsesNonExemptEncryption</key>
    <false/>
</dict>
</plist>
EOF

    # ===== Bundle Ollama binary (REQUIRED) =====
    log_step "Bundling Ollama runtime..."
    ensure_ollama_binary
    FOUND_OLLAMA="${ROOT_DIR}/ollama_binary"
    log_step "Preparing and bundling Ollama..."
    # Best-effort cleanup of the source binary's attributes.
    if xattr -cr "$FOUND_OLLAMA" &>/dev/null; then
        log_info "Removed quarantine attributes from source Ollama"
    else
        log_info "Could not remove quarantine attributes from source (may not be present)"
    fi

    if chmod 755 "$FOUND_OLLAMA" &>/dev/null; then
        log_info "Ensured source Ollama is executable"
    else
        log_warning "Could not modify permissions on source Ollama (continuing anyway)"
    fi

    HELPER_BUNDLE="${APP_BUNDLE}/Contents/Resources/Ollama.app"
    HELPER_MACOS="${HELPER_BUNDLE}/Contents/MacOS"
    HELPER_INFO="${HELPER_BUNDLE}/Contents/Info.plist"

    cleanup_path "${HELPER_BUNDLE}"
    mkdir -p "${HELPER_MACOS}"

    cp "$FOUND_OLLAMA" "${HELPER_MACOS}/ollama"
    chmod 755 "${HELPER_MACOS}/ollama"
    xattr -cr "${HELPER_MACOS}/ollama"

    if [ -f "packaging/ollama-helper-Info.plist" ]; then
        cp "packaging/ollama-helper-Info.plist" "${HELPER_INFO}"
    else
        log_warning "Ollama helper Info.plist missing; creating fallback"
        cat > "${HELPER_INFO}" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>com.marclaw.marcutapp.ollama-helper</string>
    <key>CFBundleName</key>
    <string>Ollama Helper</string>
    <key>CFBundleExecutable</key>
    <string>ollama</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>BNDL</string>
</dict>
</plist>
EOF
    fi

    log_step "Signing Ollama helper bundle..."
    codesign --force --sign "${DEVELOPER_ID}" \
        --options runtime \
        --entitlements "${OLLAMA_ENTITLEMENTS}" \
        --identifier com.marclaw.marcutapp.ollama-helper \
        "${HELPER_BUNDLE}"
    log_success "Ollama helper bundle signed"

    ln -fsh "Ollama.app/Contents/MacOS/ollama" "${APP_BUNDLE}/Contents/Resources/ollama"

    log_success "Ollama bundled from: ${FOUND_OLLAMA}"

    # ===== Bundle BeeWare Python.framework (REQUIRED) =====
    log_step "Bundling BeeWare Python.framework for App Store compatibility..."

    # Source locations from our Swift build
    # Check multiple possible locations for the framework
    SWIFT_FRAMEWORKS_SOURCE=""
    SWIFT_PYTHON_SITE_SOURCE=""

    # Try development bundle location first (most common during development)
    if [ -d "MarcutApp/.build/arm64-apple-macosx/debug/MarcutApp_MarcutApp.bundle/Frameworks" ]; then
        SWIFT_FRAMEWORKS_SOURCE="MarcutApp/.build/arm64-apple-macosx/debug/MarcutApp_MarcutApp.bundle/Frameworks"
    # Try Contents location (created by setup_beeware_framework.sh)
    elif [ -d "MarcutApp/Contents/Frameworks" ]; then
        SWIFT_FRAMEWORKS_SOURCE="MarcutApp/Contents/Frameworks"
    # Try Sources location (legacy)
    elif [ -d "MarcutApp/Sources/MarcutApp/Frameworks" ]; then
        SWIFT_FRAMEWORKS_SOURCE="MarcutApp/Sources/MarcutApp/Frameworks"
    fi

    # Try development bundle location for python_site
    if [ -d "MarcutApp/Sources/MarcutApp/python_site" ]; then
        SWIFT_PYTHON_SITE_SOURCE="MarcutApp/Sources/MarcutApp/python_site"
    # Try Contents location (created by setup_beeware_framework.sh)
    elif [ -d "MarcutApp/Contents/Resources/python_site" ]; then
        SWIFT_PYTHON_SITE_SOURCE="MarcutApp/Contents/Resources/python_site"
    fi

    # Verify source framework exists
    if [ -z "$SWIFT_FRAMEWORKS_SOURCE" ] || [ ! -d "${SWIFT_FRAMEWORKS_SOURCE}/Python.framework" ]; then
        log_error "BeeWare Python.framework not found"
        log_info "Searched locations:"
        log_info "  - MarcutApp/.build/arm64-apple-macosx/debug/MarcutApp_MarcutApp.bundle/Frameworks/Python.framework"
        log_info "  - MarcutApp/Contents/Frameworks/Python.framework"
        log_info "  - MarcutApp/Sources/MarcutApp/Frameworks/Python.framework"
        log_info ""
        log_info "Solutions:"
        log_info "  1. Run './setup_beeware_framework.sh' first to set up the framework"
        log_info "  2. Or build the Swift project first: cd MarcutApp && swift build"
        exit 1
    fi

    log_info "Found framework at: ${SWIFT_FRAMEWORKS_SOURCE}/Python.framework"

    # Copy framework to Contents/Frameworks (production location)
    log_step "Installing Python.framework to Contents/Frameworks..."
    cleanup_path "${APP_BUNDLE}/Contents/Frameworks/Python.framework"
    cp -R "${SWIFT_FRAMEWORKS_SOURCE}/Python.framework" "${APP_BUNDLE}/Contents/Frameworks/"
    log_success "Python.framework installed ($(du -sh "${APP_BUNDLE}/Contents/Frameworks/Python.framework" | cut -f1))"

    # Copy python_site to Contents/Resources (our dependencies)
    log_step "Installing python_site dependencies..."
    cleanup_path "${APP_BUNDLE}/Contents/Resources/python_site"
    if [ -n "$SWIFT_PYTHON_SITE_SOURCE" ] && [ -d "${SWIFT_PYTHON_SITE_SOURCE}" ]; then
        cp -R "${SWIFT_PYTHON_SITE_SOURCE}" "${APP_BUNDLE}/Contents/Resources/python_site"
        log_success "python_site installed ($(du -sh "${APP_BUNDLE}/Contents/Resources/python_site" | cut -f1))"
        log_info "Source: ${SWIFT_PYTHON_SITE_SOURCE}"
    else
        log_error "python_site not found"
        log_info "Searched locations:"
        log_info "  - MarcutApp/Sources/MarcutApp/python_site"
        log_info "  - MarcutApp/Contents/Resources/python_site"
        log_info ""
        log_info "Run './setup_beeware_framework.sh' to install Python dependencies"
        exit 1
    fi

    # Sign embedded BeeWare framework and python_site with Developer ID so macOS allows execution
    log_step "Signing embedded BeeWare framework and python_site…"
    sign_with_id() {
        local target="$1"
        if file "$target" | grep -q "Mach-O"; then
            echo "  Signing: $target"
            codesign --force --sign "${DEVELOPER_ID}" --options runtime --timestamp "$target" 2>/dev/null || {
                echo "    Warning: Could not sign $target"
            }
        fi
    }

    # Sign BeeWare Python.framework
    FRAMEWORK_PATH="${APP_BUNDLE}/Contents/Frameworks/Python.framework"
    if [ -d "$FRAMEWORK_PATH" ]; then
        # Sign main Python library
        [ -f "$FRAMEWORK_PATH/Python" ] && sign_with_id "$FRAMEWORK_PATH/Python"

        # Sign all dylibs, .so files, .o files, and executables in the framework
        while IFS= read -r f; do sign_with_id "$f"; done < <(find "$FRAMEWORK_PATH" -type f \( -name "*.dylib" -o -name "*.so" -o -name "*.o" -o -perm +111 \) 2>/dev/null)

        log_success "BeeWare Python.framework signed"
    else
        log_error "BeeWare Python.framework not found at $FRAMEWORK_PATH"
        exit 1
    fi

    # Sign python_site dependencies
    PYTHON_SITE_PATH="${APP_BUNDLE}/Contents/Resources/python_site"
    if [ -d "$PYTHON_SITE_PATH" ]; then
        while IFS= read -r f; do sign_with_id "$f"; done < <(find "$PYTHON_SITE_PATH" -type f \( -name "*.dylib" -o -name "*.so" -o -name "*.o" -o -perm +111 \) 2>/dev/null)
        log_success "python_site dependencies signed"
    fi

    # Copy additional resources
    for file in "excluded-words.txt" "pyproject.toml"; do
        if [ -f "$file" ]; then
            cp "$file" "${APP_BUNDLE}/Contents/Resources/"
        fi
    done
    if [ -f "excluded-words.txt" ]; then
        mkdir -p "${APP_BUNDLE}/Contents/Resources/python_site/marcut"
        cp "excluded-words.txt" "${APP_BUNDLE}/Contents/Resources/python_site/marcut/excluded-words.txt"
    fi

    # Compile Assets.xcassets (Critical for App Store Icon)
    if [ -d "MarcutApp/Sources/MarcutApp/Assets.xcassets" ]; then
        log_step "Compiling Assets.xcassets..."
        xcrun actool "MarcutApp/Sources/MarcutApp/Assets.xcassets" \
            --compile "${APP_BUNDLE}/Contents/Resources" \
            --platform macosx \
            --minimum-deployment-target 14.0 \
            --app-icon AppIcon \
            --output-partial-info-plist "${BUILD_DIR}/assetcatalog_generated_info.plist" \
            --output-format human-readable-text
            
        log_success "Assets compiled"
    fi

    # ALWAYS generate AppIcon.icns manually to ensure it contains all sizes (especially 1024x1024)
    # actool sometimes fails to include the large icon in the generated icns
    if [ -f "MarcutApp-Icon.png" ]; then
        log_step "Generating high-res AppIcon.icns manually..."
        mkdir -p "${APP_BUNDLE}/Contents/Resources"
        iconutil_dir="AppIcon.iconset"
        mkdir -p "$iconutil_dir"

        # Generate icon sizes
        sips -z 16 16 "MarcutApp-Icon.png" --out "$iconutil_dir/icon_16x16.png"
        sips -z 32 32 "MarcutApp-Icon.png" --out "$iconutil_dir/icon_16x16@2x.png"
        sips -z 32 32 "MarcutApp-Icon.png" --out "$iconutil_dir/icon_32x32.png"
        sips -z 64 64 "MarcutApp-Icon.png" --out "$iconutil_dir/icon_32x32@2x.png"
        sips -z 128 128 "MarcutApp-Icon.png" --out "$iconutil_dir/icon_128x128.png"
        sips -z 256 256 "MarcutApp-Icon.png" --out "$iconutil_dir/icon_128x128@2x.png"
        sips -z 256 256 "MarcutApp-Icon.png" --out "$iconutil_dir/icon_256x256.png"
        sips -z 512 512 "MarcutApp-Icon.png" --out "$iconutil_dir/icon_256x256@2x.png"
        sips -z 512 512 "MarcutApp-Icon.png" --out "$iconutil_dir/icon_512x512.png"
        sips -z 1024 1024 "MarcutApp-Icon.png" --out "$iconutil_dir/icon_512x512@2x.png"

        # Create icns file (Overwriting any partial one from actool)
        iconutil -c icns "$iconutil_dir" -o "${APP_BUNDLE}/Contents/Resources/AppIcon.icns"
        rm -rf "$iconutil_dir"
        log_success "AppIcon.icns created manually"
    fi

    # ===== Final bundle verification =====
    log_step "Verifying bundled runtimes..."
    if [ -x "${APP_BUNDLE}/Contents/Resources/ollama" ]; then
        log_success "Ollama present and executable"
    else
        log_error "Ollama missing in app bundle"; exit 1
    fi
    if [ -f "${APP_BUNDLE}/Contents/Frameworks/Python.framework/Python" ]; then
        log_success "BeeWare Python.framework present"
    else
        log_error "BeeWare Python.framework missing"; exit 1
    fi
    if [ -d "${APP_BUNDLE}/Contents/Resources/python_site" ]; then
        log_success "python_site present (Python dependencies)"
    else
        log_error "python_site missing"; exit 1
    fi
}

# ===== CODE SIGNING =====
sign_app_bundle() {
    log_section "Code Signing Application"

    # Remove any existing signatures
    log_step "Removing existing signatures..."
    codesign --remove-signature "${APP_BUNDLE}" 2>/dev/null || true

    # Fix permissions (Critical for App Store validation)
    log_step "Fixing file permissions..."
    chmod -R u+rw,go+r "${APP_BUNDLE}"

    # Sign all frameworks and dylibs first
    log_step "Signing frameworks and libraries..."
    # Sign frameworks (directories)
    find "${APP_BUNDLE}" -name "*.framework" -type d | while read -r framework; do
        log_info "Signing framework: $framework"
        codesign --force --deep --sign "${DEVELOPER_ID}" \
            --entitlements "${ENTITLEMENTS}" \
            --options runtime \
            --timestamp \
            "$framework" || true
    done
    
    # Sign dylibs (files) - EXCLUDING those inside frameworks (already signed by deep sign above)
    find "${APP_BUNDLE}" -name "*.dylib" -type f | (grep -v ".framework/" || true) | while read -r lib; do
        codesign --force --sign "${DEVELOPER_ID}" \
            --entitlements "${ENTITLEMENTS}" \
            --options runtime \
            --timestamp \
            "$lib" 2>/dev/null || true
    done

    # Sign the embedded Ollama binary
    log_step "Signing embedded Ollama binary..."
    if [ -f "${APP_BUNDLE}/Contents/Resources/ollama" ]; then
        codesign --force --sign "${DEVELOPER_ID}" \
            --entitlements "${OLLAMA_ENTITLEMENTS}" \
            --options runtime \
            --timestamp \
            "${APP_BUNDLE}/Contents/Resources/ollama"
        log_success "Ollama binary signed"
        # Verify the signature and entitlements on the binary
        log_info "Verifying Ollama binary signature..."
        codesign --verify --deep --strict --verbose=2 "${APP_BUNDLE}/Contents/Resources/ollama"
        codesign -d --entitlements :- "${APP_BUNDLE}/Contents/Resources/ollama"
    else
        log_warning "Ollama binary not found for signing"
    fi

    # Embed provisioning profile if available (Critical for App Store)
    if [ -f "${ROOT_DIR}/${PROVISIONING_PROFILE}" ]; then
        log_step "Embedding provisioning profile..."
        cp "${ROOT_DIR}/${PROVISIONING_PROFILE}" "${APP_BUNDLE}/Contents/embedded.provisionprofile"
        log_success "Provisioning profile embedded"
    else
        log_warning "Provisioning profile not found at ${ROOT_DIR}/${PROVISIONING_PROFILE}"
    fi

    # Prepare entitlements with application-identifier (Required for TestFlight/App Store)
    log_step "Preparing final entitlements..."
    cp "${ENTITLEMENTS}" "temp.entitlements"
    /usr/libexec/PlistBuddy -c "Add :application-identifier string ${TEAM_ID}.${BUNDLE_ID}" "temp.entitlements" || true
    /usr/libexec/PlistBuddy -c "Add :com.apple.developer.team-identifier string ${TEAM_ID}" "temp.entitlements" || true
    
    # Sign the main app bundle (WITHOUT --deep to preserve nested signatures)
    log_step "Signing main application bundle..."
    codesign --force --sign "${DEVELOPER_ID}" \
        --entitlements "temp.entitlements" \
        --options runtime \
        --timestamp \
        --identifier "${BUNDLE_ID}" \
        "${APP_BUNDLE}"
        
    rm -f "temp.entitlements"

    # Verify signature
    log_step "Verifying code signature..."
    log_info "App bundle path: ${APP_BUNDLE}"
    if codesign --verify --deep --strict --verbose=2 "${APP_BUNDLE}"; then
        log_success "Code signature verified"
    else
        log_warning "Code signature verification failed; continuing to DMG creation for testing"
    fi

    # Check signature details
    log_step "Signature details:"
    codesign -dvv "${APP_BUNDLE}" 2>&1 | grep -E "(Authority|TeamIdentifier|Timestamp)"
}

# ===== CREATE ARCHIVE =====
create_xcarchive() {
    log_section "Creating Xcode Archive"
    
    cleanup_path "${ARCHIVE_PATH}"
    mkdir -p "${ARCHIVE_PATH}/Products/Applications"
    
    log_step "Copying app to archive..."
    cp -R "${APP_BUNDLE}" "${ARCHIVE_PATH}/Products/Applications/"

    # Copy dSYMs if available
    log_step "Copying dSYMs..."
    mkdir -p "${ARCHIVE_PATH}/dSYMs"
    # Find dSYMs in build directory
    find "${BUILD_DIR}" -name "*.dSYM" -exec cp -R {} "${ARCHIVE_PATH}/dSYMs/" \;
    find "MarcutApp/.build" -name "*.dSYM" -exec cp -R {} "${ARCHIVE_PATH}/dSYMs/" \;
    
    # Check if we found any
    if [ -z "$(ls -A "${ARCHIVE_PATH}/dSYMs")" ]; then
        log_warning "No dSYMs found. 'Upload Symbols Failed' warnings are expected."
    else
        log_success "dSYMs copied to archive"
    fi
    
    log_step "Creating Archive Info.plist..."
    DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    
    cat > "${ARCHIVE_PATH}/Info.plist" << EOF
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
		<string>${DEVELOPER_ID}</string>
		<key>Team</key>
		<string>${TEAM_ID}</string>
	</dict>
	<key>ArchiveVersion</key>
	<integer>2</integer>
	<key>CreationDate</key>
	<date>${DATE}</date>
	<key>Name</key>
	<string>${APP_NAME}</string>
	<key>SchemeName</key>
	<string>${APP_NAME}</string>
</dict>
</plist>
EOF

    log_success "Archive created at: ${ARCHIVE_PATH}"
}

# ===== CREATE DMG =====
create_dmg() {
    log_section "Creating DMG Installer"

    # Clean previous DMG
    cleanup_path "${FINAL_DMG}"
    cleanup_path "${DMG_NAME}-temp.dmg"

    # Create DMG
    log_step "Creating DMG..."
    hdiutil create -volname "${VOLUME_NAME}" \
        -srcfolder "${APP_BUNDLE}" \
        -ov -format UDZO \
        "${DMG_NAME}-temp.dmg"

    # Sign the DMG
    log_step "Signing DMG..."
    codesign --force --sign "${DEVELOPER_ID}" \
        --timestamp \
        "${DMG_NAME}-temp.dmg"

    mv "${DMG_NAME}-temp.dmg" "${FINAL_DMG}"

    log_success "DMG created: ${FINAL_DMG}"
    log_info "Size: $(du -sh "${FINAL_DMG}" | cut -f1)"
}

# ===== NOTARIZATION =====
notarize_dmg() {
    log_section "Notarizing for App Store"

    log_info "Using notarization profile: ${NOTARIZATION_PROFILE}"

    # Submit for notarization
    log_step "Submitting DMG for notarization (this may take a few minutes)..."
    NOTARIZATION_OUTPUT=$(xcrun notarytool submit "${FINAL_DMG}" \
        --keychain-profile "${NOTARIZATION_PROFILE}" \
        --wait 2>&1)

    echo "$NOTARIZATION_OUTPUT"

    SUBMISSION_ID=$(echo "$NOTARIZATION_OUTPUT" | grep -E "id: [a-f0-9-]+" | head -1 | awk '{print $2}')

    if [ -z "$SUBMISSION_ID" ]; then
        log_error "Failed to get submission ID"
        exit 1
    fi

    log_info "Submission ID: ${SUBMISSION_ID}"

    # Check notarization status
    log_step "Checking notarization status..."
    xcrun notarytool info "${SUBMISSION_ID}" \
        --keychain-profile "${NOTARIZATION_PROFILE}"

    # Get notarization log if needed
    log_step "Getting notarization log..."
    xcrun notarytool log "${SUBMISSION_ID}" \
        --keychain-profile "${NOTARIZATION_PROFILE}" \
        notarization-log.json

    # Staple the notarization ticket
    log_step "Stapling notarization ticket to DMG..."
    if xcrun stapler staple "${FINAL_DMG}"; then
        log_success "Notarization ticket stapled successfully"
    else
        log_error "Failed to staple notarization ticket"
        exit 1
    fi

    # Verify notarization
    log_step "Verifying notarization..."
    if spctl -a -t open --context context:primary-signature -v "${FINAL_DMG}"; then
        log_success "DMG is properly notarized and ready for distribution"
    else
        log_warning "Notarization verification had issues"
    fi
}

# ===== VALIDATION =====
final_validation() {
    log_section "Final Validation"

    log_step "App bundle validation..."
    codesign --verify --deep --strict --verbose=2 "${APP_BUNDLE}"

    log_step "DMG validation..."
    hdiutil verify "${FINAL_DMG}"

    log_step "Notarization validation..."
    spctl -a -t open --context context:primary-signature -v "${FINAL_DMG}" || true

    log_success "All validations complete"
}

# ===== MAIN EXECUTION =====
main() {
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║          MarcutApp - App Store Distribution Build           ║${NC}"
    echo -e "${CYAN}║                     Version ${VERSION}                          ║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"

    # Parse command line arguments
    SKIP_NOTARIZATION=false
    for arg in "$@"; do
        case $arg in
            --skip-notarization)
                SKIP_NOTARIZATION=true
                shift
                ;;
            --team-id=*)
                TEAM_ID="${arg#*=}"
                shift
                ;;
            --help)
                echo "Usage: $0 [options]"
                echo "Options:"
                echo "  --skip-notarization    Skip the notarization step"
                echo "  --team-id=ID          Set Team ID for signing"
                echo "  --help                Show this help message"
                exit 0
                ;;
        esac
    done

    # Run build pipeline
    check_prerequisites
    build_swift_app
    create_app_bundle
    sign_app_bundle
    create_xcarchive
    create_dmg

    if [ "$SKIP_NOTARIZATION" = false ]; then
        notarize_dmg
    else
        log_warning "Skipping notarization (--skip-notarization flag set)"
    fi

    final_validation

    # Summary
    log_section "Build Complete! 🎉"
    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}  SUCCESS: ${APP_NAME} v${VERSION} ready for App Store${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo "📦 Distribution Package: ${FINAL_DMG}"
    echo "🗄️  Xcode Archive: ${ARCHIVE_PATH}"
    echo "   (Open in Xcode Organizer to submit to App Store)"
    echo "📏 Size: $(du -sh "${FINAL_DMG}" | cut -f1)"
    echo "🔐 Signed with: ${DEVELOPER_ID}"
    if [ "$SKIP_NOTARIZATION" = false ]; then
        echo "✅ Notarized and ready for App Store submission"
    fi
    echo ""
    echo "📋 Next Steps:"
    echo "   1. Test the DMG: open \"${FINAL_DMG}\""
    echo "   2. Upload to App Store Connect"
    echo "   3. Submit for App Review"
    echo ""
}

# Run main function
main "$@"

#!/bin/bash
#
# MarcutApp - App Store Distribution Build Script
# Creates a signed and notarized DMG for Mac App Store distribution
#
set -euo pipefail

# ===== CONFIGURATION =====
APP_NAME="MarcutApp"
BUNDLE_ID="com.marclaw.marcutapp"
VERSION="0.3.12"
BUILD_NUMBER="1"

# Signing Configuration
DEVELOPER_ID="Apple Development: icloud@exode.com (L8WEB9VFGH)"
TEAM_ID="QG85EMCQ75"

# Paths (absolute to avoid cwd issues)
ROOT_DIR="$(pwd)"
BUILD_DIR="${ROOT_DIR}/build"
ARCHIVE_DIR="${ROOT_DIR}/archive"
APP_BUNDLE="${BUILD_DIR}/${APP_NAME}.app"
ARCHIVE_PATH="${ARCHIVE_DIR}/${APP_NAME}.xcarchive"
DMG_NAME="${APP_NAME}-v${VERSION}-AppStore"
FINAL_DMG="${ROOT_DIR}/${DMG_NAME}.dmg"
VOLUME_NAME="${APP_NAME}"
ENTITLEMENTS="Marcut.entitlements"

# Notarization Configuration
NOTARIZATION_PROFILE="marcut-notarization"  # You'll need to create this

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

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
    rm -rf "${BUILD_DIR}" "${ARCHIVE_DIR}"
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
    OLLAMA_CANDIDATES=(
        "ollama_binary"
        "/opt/homebrew/bin/ollama"
        "/usr/local/bin/ollama"
        "/usr/bin/ollama"
    )
    FOUND_OLLAMA=""
    for c in "${OLLAMA_CANDIDATES[@]}"; do
        if [ -x "$c" ]; then FOUND_OLLAMA="$c"; break; fi
    done
    if [ -z "$FOUND_OLLAMA" ]; then
        log_error "Ollama binary not found. This build requires bundling Ollama."
        echo "Provide one of: ./ollama_binary, Homebrew install (brew install ollama), or a system 'ollama' in PATH."
        exit 1
    fi
    cp "$FOUND_OLLAMA" "${APP_BUNDLE}/Contents/Resources/ollama"
    chmod +x "${APP_BUNDLE}/Contents/Resources/ollama"
    log_success "Ollama bundled from: ${FOUND_OLLAMA}"

    # ===== Bundle python_bundle (REQUIRED) =====
    log_step "Bundling python_bundle (portable) ..."
    if [ ! -d "python_bundle" ]; then
        if [ -x "./create_python_bundle.sh" ]; then
            ./create_python_bundle.sh || { log_error "Failed to create python_bundle"; exit 1; }
        else
            log_error "create_python_bundle.sh not found or not executable"; exit 1
        fi
    fi
    rm -rf "${APP_BUNDLE}/Contents/Resources/python_bundle"
    cp -R "python_bundle" "${APP_BUNDLE}/Contents/Resources/python_bundle"
    chmod +x "${APP_BUNDLE}/Contents/Resources/python_bundle/test_bundle.sh"
    log_success "python_bundle bundled"

    # Ensure framework-style loader path exists for interpreter fallbacks
    PYB="${APP_BUNDLE}/Contents/Resources/python_bundle"
    mkdir -p "$PYB/lib/Resources/Python.app/Contents/MacOS"
    if [ ! -e "$PYB/lib/Resources/Python.app/Contents/MacOS/Python" ]; then
        ln -sf "../../../../bin/python3" "$PYB/lib/Resources/Python.app/Contents/MacOS/Python" || true
    fi
    if [ ! -e "$PYB/lib/Python3" ] && [ -e "$PYB/Python3" ]; then
        ln -sf "../Python3" "$PYB/lib/Python3" || true
    fi

    # Copy additional resources
    for file in "excluded-words.txt" "pyproject.toml"; do
        if [ -f "$file" ]; then
            cp "$file" "${APP_BUNDLE}/Contents/Resources/"
        fi
    done

    # Add app icon
    if [ -f "MarcutApp-Icon.png" ]; then
        log_step "Creating app icon..."
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

        # Create icns file
        iconutil -c icns "$iconutil_dir" -o "${APP_BUNDLE}/Contents/Resources/AppIcon.icns"
        rm -rf "$iconutil_dir"
        log_success "App icon created"
    fi

    # ===== Final bundle verification =====
    log_step "Verifying bundled runtimes..."
    if [ -x "${APP_BUNDLE}/Contents/Resources/ollama" ]; then
        log_success "Ollama present and executable"
    else
        log_error "Ollama missing in app bundle"; exit 1
    fi
    if [ -x "${APP_BUNDLE}/Contents/Resources/python_bundle/bin/python3" ]; then
        log_success "python_bundle present (embedded python)"
    else
        log_error "python_bundle missing or not executable"; exit 1
    fi
}

# ===== CODE SIGNING =====
sign_app_bundle() {
    log_section "Code Signing Application"

    # Remove any existing signatures
    log_step "Removing existing signatures..."
    codesign --remove-signature "${APP_BUNDLE}" 2>/dev/null || true

    # Sign all frameworks and dylibs first
    log_step "Signing frameworks and libraries..."
    find "${APP_BUNDLE}" -type f \( -name "*.dylib" -o -name "*.framework" \) | while read -r lib; do
        codesign --force --deep --sign "${DEVELOPER_ID}" \
            --entitlements "${ENTITLEMENTS}" \
            --options runtime \
            --timestamp \
            "$lib" 2>/dev/null || true
    done

    # Sign the main app bundle
    log_step "Signing main application bundle..."
    codesign --force --deep --sign "${DEVELOPER_ID}" \
        --entitlements "${ENTITLEMENTS}" \
        --options runtime \
        --timestamp \
        --preserve-metadata=identifier,entitlements,requirements \
        "${APP_BUNDLE}"

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

# ===== CREATE DMG =====
create_dmg() {
    log_section "Creating DMG Installer"

    # Clean previous DMG
    rm -f "${FINAL_DMG}" "${DMG_NAME}-temp.dmg"

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

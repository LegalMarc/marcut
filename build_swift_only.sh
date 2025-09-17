#!/bin/bash
#
# MarcutApp - Swift-Only Build for App Store
# Creates a minimal Swift app without Python dependencies
#
set -euo pipefail

# Configuration
APP_NAME="MarcutApp"
BUNDLE_ID="com.marclaw.marcutapp"
VERSION="0.3.11"
BUILD_NUMBER="1"
DEVELOPER_ID="Apple Development: icloud@exode.com (L8WEB9VFGH)"
TEAM_ID="QG85EMCQ75"

# Paths
BUILD_DIR="build_swift"
APP_BUNDLE="${BUILD_DIR}/${APP_NAME}.app"
DMG_NAME="${APP_NAME}-Swift-v${VERSION}"
FINAL_DMG="${DMG_NAME}.dmg"
ENTITLEMENTS="Marcut.entitlements"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Python Framework Configuration
PY_VERSION="3.11.9"
PY_SHORT="3.11"
PY_PKG_URL="https://www.python.org/ftp/python/${PY_VERSION}/python-${PY_VERSION}-macos11.pkg"

download_and_expand_python() {
  echo -e "${BLUE}Downloading Python.framework ${PY_VERSION}...${NC}"
  mkdir -p build_cache
  local pkg="build_cache/python-${PY_VERSION}.pkg"
  if [ ! -f "$pkg" ]; then
    curl -L "$PY_PKG_URL" -o "$pkg"
  else
    echo -e "${GREEN}✓ Using cached Python pkg${NC}"
  fi

  echo -e "${BLUE}Expanding pkg...${NC}"
  rm -rf build_cache/py_expanded
  pkgutil --expand-full "$pkg" build_cache/py_expanded
  # Framework payload may be an already-expanded directory
  local fw_pkg
  fw_pkg=$(find build_cache/py_expanded -name "Python_Framework.pkg" -maxdepth 1 2>/dev/null | head -1)
  if [ -z "$fw_pkg" ]; then
    echo -e "${RED}❌ Could not locate Python_Framework.pkg inside expanded pkg${NC}"; exit 1
  fi
  if [ -d "$fw_pkg/Payload/Versions" ]; then
    echo -e "${GREEN}✓ Framework payload already expanded${NC}"
  else
    echo -e "${BLUE}Unpacking framework payload (cpio)...${NC}"
    rm -rf build_cache/py_payload
    mkdir -p build_cache/py_payload
    cat "$fw_pkg/Payload" | gunzip -dc | (cd build_cache/py_payload && cpio -id) >/dev/null 2>&1 || true
  fi
}

echo -e "${BLUE}Building Swift-Only MarcutApp${NC}"
echo "================================"

# Clean and create build directory
echo -e "${BLUE}Cleaning build directory...${NC}"
rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"

# Build Swift app with debug symbols for AttributeGraph analysis
echo -e "${BLUE}Building Swift app with debug symbols...${NC}"
cd MarcutApp
swift build --configuration debug --arch arm64 -Xswiftc -g -Xswiftc -enable-testing
cd ..

# Create app bundle
echo -e "${BLUE}Creating app bundle...${NC}"
mkdir -p "${APP_BUNDLE}/Contents/MacOS"
mkdir -p "${APP_BUNDLE}/Contents/Resources"
mkdir -p "${APP_BUNDLE}/Contents/Frameworks"

# Copy executable (debug build)
cp "MarcutApp/.build/arm64-apple-macosx/debug/MarcutApp" "${APP_BUNDLE}/Contents/MacOS/"
chmod +x "${APP_BUNDLE}/Contents/MacOS/MarcutApp"

# Copy resources bundle if it exists (debug build)
if [ -d "MarcutApp/.build/arm64-apple-macosx/debug/MarcutApp_MarcutApp.bundle" ]; then
    cp -R "MarcutApp/.build/arm64-apple-macosx/debug/MarcutApp_MarcutApp.bundle" "${APP_BUNDLE}/Contents/Resources/"
    echo -e "${GREEN}✅ Resources bundle copied${NC}"
fi

# Create Info.plist
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
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>ITSAppUsesNonExemptEncryption</key>
    <false/>
</dict>
</plist>
EOF

# Add icon - always include the scissors icon
echo -e "${BLUE}Creating app icon...${NC}"

# Use the scissors icon from the bundle if available, otherwise use the root file
ICON_SOURCE=""
if [ -f "MarcutApp-Icon.png" ]; then
    ICON_SOURCE="MarcutApp-Icon.png"
elif [ -d "${APP_BUNDLE}/Contents/Resources/MarcutApp_MarcutApp.bundle/Assets.xcassets/AppIcon.appiconset" ]; then
    # Find the largest icon in the bundle
    BUNDLE_ICON=$(find "${APP_BUNDLE}/Contents/Resources/MarcutApp_MarcutApp.bundle/Assets.xcassets/AppIcon.appiconset" -name "*.png" | grep "512x512" | head -1)
    if [ -f "$BUNDLE_ICON" ]; then
        ICON_SOURCE="$BUNDLE_ICON"
    fi
fi

if [ -n "$ICON_SOURCE" ]; then
    mkdir -p "AppIcon.iconset"

    # Create all required icon sizes
    sips -z 16 16 "$ICON_SOURCE" --out "AppIcon.iconset/icon_16x16.png" >/dev/null 2>&1
    sips -z 32 32 "$ICON_SOURCE" --out "AppIcon.iconset/icon_16x16@2x.png" >/dev/null 2>&1
    sips -z 32 32 "$ICON_SOURCE" --out "AppIcon.iconset/icon_32x32.png" >/dev/null 2>&1
    sips -z 64 64 "$ICON_SOURCE" --out "AppIcon.iconset/icon_32x32@2x.png" >/dev/null 2>&1
    sips -z 128 128 "$ICON_SOURCE" --out "AppIcon.iconset/icon_128x128.png" >/dev/null 2>&1
    sips -z 256 256 "$ICON_SOURCE" --out "AppIcon.iconset/icon_128x128@2x.png" >/dev/null 2>&1
    sips -z 256 256 "$ICON_SOURCE" --out "AppIcon.iconset/icon_256x256.png" >/dev/null 2>&1
    sips -z 512 512 "$ICON_SOURCE" --out "AppIcon.iconset/icon_256x256@2x.png" >/dev/null 2>&1
    sips -z 512 512 "$ICON_SOURCE" --out "AppIcon.iconset/icon_512x512.png" >/dev/null 2>&1
    sips -z 1024 1024 "$ICON_SOURCE" --out "AppIcon.iconset/icon_512x512@2x.png" >/dev/null 2>&1

    # Create the icns file
    iconutil -c icns "AppIcon.iconset" -o "${APP_BUNDLE}/Contents/Resources/AppIcon.icns"
    rm -rf "AppIcon.iconset"
    echo -e "${GREEN}✅ Scissors icon included${NC}"
else
    echo -e "${YELLOW}⚠️  No icon found - using default${NC}"
fi

# Bundle Ollama binary (REQUIRED)
echo -e "${BLUE}Bundling Ollama...${NC}"
OLLLAMA_CANDIDATES=(
  "ollama_binary"
  "/opt/homebrew/bin/ollama"
  "/usr/local/bin/ollama"
  "/usr/bin/ollama"
)

FOUND_OLLAMA=""
for c in "${OLLLAMA_CANDIDATES[@]}"; do
  if [ -x "$c" ]; then
    FOUND_OLLAMA="$c"
    break
  fi
done

if [ -z "$FOUND_OLLAMA" ]; then
  echo -e "${RED}❌ Ollama binary not found. This DMG must include Ollama.${NC}"
  echo "   Provide one of:"
  echo "     - A local ./ollama_binary (copied from your system)"
  echo "     - Homebrew install: brew install ollama"
  echo "     - System path containing an executable 'ollama'"
  exit 1
fi

cp "$FOUND_OLLAMA" "${APP_BUNDLE}/Contents/Resources/ollama"
chmod +x "${APP_BUNDLE}/Contents/Resources/ollama"
echo -e "${GREEN}✅ Ollama bundled from: ${FOUND_OLLAMA}${NC}"

# Bundle Marcut executable
echo -e "${BLUE}Skipping marcut_executable (using bundled Python runtime)${NC}"

# Bundle Python runtime (preferred execution path)
echo -e "${BLUE}Bundling Python runtime (portable bundle)...${NC}"
if [ ! -d "python_bundle" ]; then
  if [ -x "./create_python_bundle.sh" ]; then
    ./create_python_bundle.sh || { echo -e "${RED}❌ Failed to create python_bundle${NC}"; exit 1; }
  else
    echo -e "${RED}❌ create_python_bundle.sh not found or not executable${NC}"; exit 1
  fi
fi
rm -rf "${APP_BUNDLE}/Contents/Resources/python_bundle"
cp -R "python_bundle" "${APP_BUNDLE}/Contents/Resources/python_bundle"
chmod +x "${APP_BUNDLE}/Contents/Resources/python_bundle/test_bundle.sh"
echo -e "${GREEN}✅ python_bundle bundled${NC}"

# Ensure framework-style loader path exists for interpreter fallbacks
PYB="${APP_BUNDLE}/Contents/Resources/python_bundle"
mkdir -p "$PYB/lib/Resources/Python.app/Contents/MacOS"
if [ ! -e "$PYB/lib/Resources/Python.app/Contents/MacOS/Python" ]; then
  ln -sf "../../../../bin/python3" "$PYB/lib/Resources/Python.app/Contents/MacOS/Python" || true
fi
# Ensure lib/Python3 symlink exists (compat for @executable_path/../Python3)
if [ ! -e "$PYB/lib/Python3" ] && [ -e "$PYB/Python3" ]; then
  ln -sf "../Python3" "$PYB/lib/Python3" || true
fi

# (Testing) Skip codesign in this debug build to ensure DMG creation
echo -e "${YELLOW}Skipping app codesign for debug DMG${NC}"

# Create DMG
echo -e "${BLUE}Creating DMG...${NC}"
hdiutil create -volname "${APP_NAME}" \
    -srcfolder "${APP_BUNDLE}" \
    -ov -format UDZO \
    "${FINAL_DMG}"

echo -e "${YELLOW}Skipping DMG codesign for debug build${NC}"

echo -e "${GREEN}✅ Build complete!${NC}"
echo "DMG: ${FINAL_DMG}"
echo "Size: $(du -sh "${FINAL_DMG}" | cut -f1)"
echo ""
echo "Verifying bundled resources:"
if [ -x "${APP_BUNDLE}/Contents/Resources/ollama" ]; then
  echo "  ✓ ollama present and executable"
else
  echo "  ⚠️  ollama missing or not executable"
fi
if [ -x "${APP_BUNDLE}/Contents/Resources/python_bundle/bin/python3" ]; then
  echo "  ✓ python_bundle present (embedded python)"
else
  echo "  ⚠️  python_bundle missing"
fi
echo ""
echo "Note: For App Store distribution, you need:"
echo "1. Developer ID Application certificate (not just Development)"
echo "2. Run notarization: xcrun notarytool submit ${FINAL_DMG} --keychain-profile marcut-notarization --wait"
# Python Framework Configuration
PY_VERSION="3.11.9"
PY_SHORT="3.11"
PY_PKG_URL="https://www.python.org/ftp/python/${PY_VERSION}/python-${PY_VERSION}-macos11.pkg"

download_and_expand_python() {
  echo -e "${BLUE}Downloading Python.framework ${PY_VERSION}...${NC}"
  mkdir -p build_cache
  local pkg="build_cache/python-${PY_VERSION}.pkg"
  if [ ! -f "$pkg" ]; then
    curl -L "$PY_PKG_URL" -o "$pkg"
  else
    echo -e "${GREEN}✓ Using cached Python pkg${NC}"
  fi

  echo -e "${BLUE}Expanding pkg...${NC}"
  rm -rf build_cache/py_expanded
  pkgutil --expand-full "$pkg" build_cache/py_expanded
  # Extract Payload for the framework package
  local fw_pkg
  fw_pkg=$(find build_cache/py_expanded -name "PythonFramework-*.pkg" -maxdepth 1 2>/dev/null | head -1)
  if [ -z "$fw_pkg" ]; then
    echo -e "${RED}❌ Could not locate PythonFramework pkg inside expanded pkg${NC}"; exit 1
  fi
  rm -rf build_cache/py_payload
  mkdir -p build_cache/py_payload
  echo -e "${BLUE}Unpacking framework payload...${NC}"
  cat "$fw_pkg/Payload" | gunzip -dc | (cd build_cache/py_payload && cpio -id) >/dev/null 2>&1 || true
  if [ ! -d build_cache/py_payload/Library/Frameworks/Python.framework ]; then
    echo -e "${RED}❌ Python.framework not found after unpack${NC}"; exit 1
  fi
}
echo "3. Staple: xcrun stapler staple ${FINAL_DMG}"

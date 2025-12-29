#!/bin/bash
#
# Marcut Build Configuration
# Centralized configuration for all build scripts
# Updated: November 3, 2025
#

# ===== APP CONFIGURATION =====
export APP_NAME="MarcutApp"
export BUNDLE_ID="com.marclaw.marcutapp"
export VERSION="0.3.12"
export BUILD_NUMBER="1"

# ===== PATHS =====
export PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export BUILD_DIR="build"
export DIST_DIR="dist"
export ARCHIVE_DIR="archive"

CONFIG_PATH="${PROJECT_ROOT}/config.json"
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
PY
)"
    export APP_NAME BUNDLE_ID VERSION BUILD_NUMBER
fi

# Framework and Resources
export FRAMEWORK_DIR="${APP_NAME}/Contents/Frameworks"
export RESOURCES_DIR="${APP_NAME}/Contents/Resources"
export PYTHON_FRAMEWORK_SOURCE="${APP_NAME}/Contents/Frameworks/Python.framework"
export PYTHON_SITE_SOURCE="${APP_NAME}/Contents/Resources/python_site"
export PYTHON_SITE_REPO_SOURCE="${APP_NAME}/Sources/${APP_NAME}/python_site"

# Build Outputs
export APP_BUNDLE="${BUILD_DIR}/${APP_NAME}.app"
export FINAL_DMG="${APP_NAME}-Swift-${VERSION}.dmg"

# ===== OLLAMA CONFIGURATION =====
export OLLAMA_VERSION="0.12.5"
export OLLAMA_DOWNLOAD_URL="https://github.com/ollama/ollama/releases/download/v${OLLAMA_VERSION}/ollama-darwin.tgz"

# ===== PYTHON CONFIGURATION =====
export PYTHON_VERSION="3.11"
export PYTHON_EXECUTABLE="run_python.sh"
export PYTHON_LAUNCHER_PATH="scripts/${PYTHON_EXECUTABLE}"

# ===== SIGNING CONFIGURATION =====
export DEVELOPER_ID="${DEVELOPER_ID:-}"  # Set from environment
export TEAM_ID="${TEAM_ID:-QG85EMCQ75}"
export ENTITLEMENTS="Marcut.entitlements"
export OLLAMA_ENTITLEMENTS="MarcutOllama.entitlements"

# ===== BUILD OPTIONS =====
export ARCH="arm64"
export SKIP_NOTARIZATION="${SKIP_NOTARIZATION:-true}"
export RUN_TESTS="${RUN_TESTS:-false}"
export CLEAN_BUILD="${CLEAN_BUILD:-true}"
export VERBOSE="${VERBOSE:-false}"

# ===== COLORS =====
export RED='\033[0;31m'
export GREEN='\033[0;32m'
export YELLOW='\033[1;33m'
export BLUE='\033[0;34m'
export CYAN='\033[0;36m'
export MAGENTA='\033[0;35m'
export NC='\033[0m'

# ===== VALIDATION FUNCTIONS =====
validate_configuration() {
    echo -e "${BLUE}Validating build configuration...${NC}"

    # Check required tools
    local missing_tools=()
    command -v swift >/dev/null 2>&1 || missing_tools+=("swift")
    command -v hdiutil >/dev/null 2>&1 || missing_tools+=("hdiutil")
    command -v codesign >/dev/null 2>&1 || missing_tools+=("codesign")

    if [ ${#missing_tools[@]} -gt 0 ]; then
        echo -e "${RED}❌ Missing required tools: ${missing_tools[*]}${NC}"
        return 1
    fi

    # Check architecture
    if [ "$(uname -m)" != "$ARCH" ]; then
        echo -e "${YELLOW}⚠️ Architecture mismatch: expected $ARCH, found $(uname -m)${NC}"
        echo "This build is configured for Apple Silicon only."
        return 1
    fi

    echo -e "${GREEN}✅ Configuration validation passed${NC}"
    return 0
}

# ===== UTILITY FUNCTIONS =====
cleanup_build_artifacts() {
    local target="$1"
    if [ ! -e "$target" ]; then
        return
    fi

    echo -e "${YELLOW}Cleaning: $target${NC}"

    if [ -d "$target" ]; then
        chmod -R u+w "$target" 2>/dev/null || true
        rm -rf "$target"
    else
        rm -f "$target"
    fi
}

print_build_summary() {
    echo -e "${CYAN}=== Build Configuration Summary ===${NC}"
    echo -e "App: ${APP_NAME} v${VERSION}"
    echo -e "Architecture: ${ARCH}"
    echo -e "Build Directory: ${BUILD_DIR}"
    echo -e "Python Framework: ${PYTHON_FRAMEWORK_SOURCE}"
    echo -e "Python Launcher: ${PYTHON_LAUNCHER_PATH}"
    echo -e "Ollama Version: ${OLLAMA_VERSION}"
    if [ -n "$DEVELOPER_ID" ]; then
        echo -e "Signing: YES (Developer ID)"
    else
        echo -e "Signing: NO (ad-hoc)"
    fi
    echo -e "${CYAN}================================${NC}"
}

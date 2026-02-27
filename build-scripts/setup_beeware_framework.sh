#!/bin/bash
#
# Downloads and embeds BeeWare Python.framework for MarcutApp
# This replaces the custom python bundle with the official BeeWare framework
# designed for App Store distribution with proper codesigning
#
set -euo pipefail

# Resolve repo paths regardless of invocation directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Parse command line arguments
PURGE_CACHE=false
FORCE_REBUILD=false
for arg in "$@"; do
    case $arg in
        --purge-cache)
            PURGE_CACHE=true
            shift
            ;;
        --force)
            FORCE_REBUILD=true
            shift
            ;;
    esac
done

# Configuration - Using Python 3.11 for better compatibility
PYTHON_VERSION="3.11"
BEEWARE_VERSION="3.11-b7"
# Paths relative to repo root
FRAMEWORK_DIR="${REPO_ROOT}/src/swift/MarcutApp/Sources/MarcutApp/Frameworks"
RESOURCES_DIR="${REPO_ROOT}/src/swift/MarcutApp/Sources/MarcutApp/Resources"
PYTHON_SITE_DIR="${REPO_ROOT}/src/swift/MarcutApp/Sources/MarcutApp/python_site"
TEMP_DIR="${SCRIPT_DIR}/temp_beeware"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

safe_rm_rf() {
    local target="$1"
    if [ -z "${target}" ] || [ "${target}" = "/" ]; then
        echo -e "${RED}❌ Refusing to remove unsafe path: '${target}'${NC}"
        exit 1
    fi
    if [ ! -e "${target}" ]; then
        return 0
    fi

    chmod -R u+rwX "${target}" 2>/dev/null || true
    xattr -cr "${target}" 2>/dev/null || true
    chflags -R nouchg,noschg "${target}" 2>/dev/null || true
    rm -rf "${target}" 2>/dev/null || true

    if [ -e "${target}" ]; then
        local fallback="${target}.stale.$(date +%s)"
        mv "${target}" "${fallback}" 2>/dev/null || true
        rm -rf "${fallback}" 2>/dev/null || true
    fi

    if [ -e "${target}" ]; then
        echo -e "${RED}❌ Unable to fully remove ${target}${NC}"
        exit 1
    fi
}

resolve_framework_version_dir() {
    local framework_root="$1"
    local versions_dir="${framework_root}/Versions"
    local current_link="${versions_dir}/Current"

    if [ -L "${current_link}" ]; then
        echo "${versions_dir}/$(readlink "${current_link}")"
        return 0
    fi

    if [ -d "${current_link}" ]; then
        echo "${current_link}"
        return 0
    fi

    local candidate
    candidate=$(find "${versions_dir}" -mindepth 1 -maxdepth 1 -type d | head -n 1)
    if [ -n "${candidate}" ]; then
        echo "${candidate}"
        return 0
    fi

    return 1
}

strip_tcl_tk() {
    local framework_root="$1"
    local version_dir
    version_dir=$(resolve_framework_version_dir "${framework_root}") || {
        echo -e "${RED}❌ Could not resolve Python.framework version directory${NC}"
        exit 1
    }

    local lib_dir="${version_dir}/lib"
    local python_lib_dir="${lib_dir}/python${PYTHON_VERSION}"

    echo -e "${BLUE}Removing Tcl/Tk from embedded Python.framework...${NC}"
    rm -f "${lib_dir}"/libtk*.dylib "${lib_dir}"/libtcl*.dylib
    rm -rf "${lib_dir}/tk8.6" "${lib_dir}/tcl8.6"
    rm -f "${python_lib_dir}/lib-dynload/"_tkinter*.so "${python_lib_dir}/lib-dynload/"_tkinter*.dylib 2>/dev/null || true
    rm -rf "${python_lib_dir}/tkinter" "${python_lib_dir}/idlelib" "${python_lib_dir}/turtledemo"
}

verify_no_tcl_tk() {
    local framework_root="$1"
    local hits
    hits=$(find "${framework_root}" \
        \( -name "libtk*.dylib" -o -name "libtcl*.dylib" -o -name "_tkinter*.so" -o -name "_tkinter*.dylib" \
           -o -path "*/tk8.6" -o -path "*/tk8.6/*" -o -path "*/tcl8.6" -o -path "*/tcl8.6/*" \
           -o -path "*/tkinter" -o -path "*/tkinter/*" -o -path "*/idlelib" -o -path "*/idlelib/*" \
           -o -path "*/turtledemo" -o -path "*/turtledemo/*" \) \
        -print 2>/dev/null || true)

    if [ -n "${hits}" ]; then
        echo -e "${RED}❌ Tcl/Tk artifacts still present in Python.framework:${NC}"
        echo "${hits}"
        exit 1
    fi

    echo -e "${GREEN}✅ Tcl/Tk removed from Python.framework${NC}"
}

echo -e "${BLUE}Setting up BeeWare Python Framework for MarcutApp${NC}"
echo "=============================================="
echo "Python version: ${PYTHON_VERSION}"
echo "BeeWare version: ${BEEWARE_VERSION}"
echo "Framework dir: ${FRAMEWORK_DIR}"
echo ""

# Clean any existing setup
if [ -d "$FRAMEWORK_DIR" ]; then
    echo -e "${YELLOW}Removing existing framework directory...${NC}"
    safe_rm_rf "$FRAMEWORK_DIR"
fi

if [ "${PURGE_CACHE}" = true ] && [ -d "$TEMP_DIR" ]; then
    echo -e "${YELLOW}Purging cached BeeWare payload...${NC}"
    safe_rm_rf "$TEMP_DIR"
fi

# Create directories
mkdir -p "$FRAMEWORK_DIR"
mkdir -p "$RESOURCES_DIR"
mkdir -p "$PYTHON_SITE_DIR"
mkdir -p "$TEMP_DIR"

echo -e "${BLUE}Downloading BeeWare Python framework...${NC}"

# Download the BeeWare Python framework for macOS (universal2)
FRAMEWORK_URL="https://github.com/beeware/Python-Apple-support/releases/download/3.11-b7/Python-3.11-macOS-support.b7.tar.gz"
TARBALL_PATH="${TEMP_DIR}/python-framework.tar.gz"

if [ -f "${TARBALL_PATH}" ]; then
    echo -e "${YELLOW}Found cached payload; attempting resume...${NC}"
fi

echo "Downloading from: $FRAMEWORK_URL"
curl -L --fail --retry 5 --retry-delay 5 --retry-connrefused --retry-all-errors \
    -C - -o "${TARBALL_PATH}" "$FRAMEWORK_URL"

if [ ! -f "${TARBALL_PATH}" ]; then
    echo -e "${RED}❌ Failed to download BeeWare framework${NC}"
    exit 1
fi

if ! tar -tzf "${TARBALL_PATH}" >/dev/null 2>&1; then
    echo -e "${RED}❌ Downloaded framework archive is invalid or incomplete. Re-run with --purge-cache.${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Framework downloaded ($(du -sh "${TARBALL_PATH}" | cut -f1))${NC}"

# Extract the framework
echo -e "${BLUE}Extracting framework...${NC}"
cd "$TEMP_DIR"
tar -xzf "$(basename "${TARBALL_PATH}")"
cd ..

EXTRACTED_FRAMEWORK_PATH=$(find "$TEMP_DIR" -name "Python.framework" -type d | head -1)

if [ -z "$EXTRACTED_FRAMEWORK_PATH" ] || [ ! -d "$EXTRACTED_FRAMEWORK_PATH" ]; then
    echo -e "${RED}❌ Could not find Python.framework in extracted files${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Found framework at: $EXTRACTED_FRAMEWORK_PATH${NC}"

# Move framework to the correct location
mv "$EXTRACTED_FRAMEWORK_PATH" "$FRAMEWORK_DIR/"

strip_tcl_tk "${FRAMEWORK_DIR}/Python.framework"
verify_no_tcl_tk "${FRAMEWORK_DIR}/Python.framework"

# Create python_site directory for our packages
PYTHON_SITE="$PYTHON_SITE_DIR"
echo -e "${BLUE}Setting up python_site directory...${NC}"
safe_rm_rf "$PYTHON_SITE"
mkdir -p "$PYTHON_SITE"

# Find a compatible system Python (strictly 3.11.x) to act as a build tool for running pip.
echo -e "${BLUE}Finding a build-time Python 3.11 interpreter...${NC}"
SYSTEM_PYTHON=""
for python_candidate in \
    /opt/homebrew/bin/python3.11 \
    /usr/local/bin/python3.11 \
    /usr/bin/python3.11 \
    python3.11 \
    python3 \
    /usr/bin/python3; do

    if [[ "$python_candidate" == /* ]]; then
        if [ -x "$python_candidate" ]; then
            PY_CMD="$python_candidate"
        else
            continue
        fi
    else
        if command -v "$python_candidate" &> /dev/null; then
            PY_CMD=$(command -v "$python_candidate")
        else
            continue
        fi
    fi

    PYTHON_VERSION_CHECK=$("$PY_CMD" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "")
    if [[ "$PYTHON_VERSION_CHECK" == "3.11" ]]; then
        SYSTEM_PYTHON="$PY_CMD"
        echo -e "${GREEN}✅ Found compatible system Python for build tasks: $SYSTEM_PYTHON (version $PYTHON_VERSION_CHECK)${NC}"
        break
    fi
done

if [ -z "$SYSTEM_PYTHON" ]; then
    echo -e "${RED}❌ Could not find Python 3.11 on this machine to run pip for package staging.${NC}"
    echo "Install it with 'brew install python@3.11' and rerun this script."
    exit 1
fi

cat > "$TEMP_DIR/requirements.txt" <<'REQS'
python-docx>=1.1.0
rapidfuzz>=3.6.1
pydantic>=2.6.4
requests>=2.31.0
dateparser>=1.2.0
tqdm>=4.66.0
lxml>=5.0.0
numpy>=1.24.0
regex>=2023.0.0
REQS

# --- Compile Dependencies from Source ---
echo -e "${BLUE}Compiling Python dependencies from source against the BeeWare framework...${NC}"

# Set compiler and linker flags to target the bundled framework
export MACOSX_DEPLOYMENT_TARGET="14.0"
export ARCHFLAGS="-arch arm64"

FRAMEWORK_ROOT_DIR=$(cd "$FRAMEWORK_DIR"; pwd)
FRAMEWORK_PY_DIR="$FRAMEWORK_ROOT_DIR/Python.framework"
FRAMEWORK_HEADERS="$FRAMEWORK_PY_DIR/Versions/Current/include/python3.11"
FRAMEWORK_LIB_DIR="$FRAMEWORK_PY_DIR/Versions/Current/lib"

# Only purge cache if explicitly requested
if [ "$PURGE_CACHE" = true ]; then
    echo -e "${YELLOW}Purging pip cache as requested...${NC}"
    "$SYSTEM_PYTHON" -m pip cache purge
fi

export CC=$(xcrun --find clang)
SDK_PATH=$(xcrun --show-sdk-path)
export CFLAGS="-isysroot $SDK_PATH -I$FRAMEWORK_HEADERS $ARCHFLAGS"
export LDFLAGS="-isysroot $SDK_PATH -L$FRAMEWORK_LIB_DIR -F$FRAMEWORK_ROOT_DIR $ARCHFLAGS"

# Use pip to compile and install packages from source
"$SYSTEM_PYTHON" -m pip install \
    --target "$PYTHON_SITE" \
    --no-binary :all: \
    --compile \
    -r "$TEMP_DIR/requirements.txt"

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Failed to compile Python dependencies.${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Successfully compiled and installed all dependencies.${NC}"

# Ensure lxml (and friends) were built for CPython 3.11 to avoid embedding older wheels.
if ! find "$PYTHON_SITE/lxml" -maxdepth 1 -name "*cpython-311*.so" | grep -q .; then
    echo -e "${RED}❌ lxml was not built for CPython 3.11 (missing *cpython-311*.so).${NC}"
    echo "Make sure /opt/homebrew/bin/python3.11 is first in PATH and rerun this script."
    exit 1
fi

# --- Post-Install Relinking ---
echo -e "${BLUE}Relinking native extensions to use @rpath...${NC}"
FRAMEWORK_PY_RPATH="@rpath/Python.framework/Versions/Current/Python"

find "$PYTHON_SITE" \( -name "*.so" -o -name "*.dylib" \) | while read -r file; do
    # Find the absolute path to the Python library that pip just linked against
    OLD_PATH=$(otool -L "$file" | grep "$FRAMEWORK_PY_DIR" | awk '{print $1}' | head -n 1 || true)

    if [ -n "${OLD_PATH}" ]; then
        echo "Relinking $(basename "$file")"
        echo "  from: $OLD_PATH"
        echo "    to: $FRAMEWORK_PY_RPATH"
        install_name_tool -change "$OLD_PATH" "$FRAMEWORK_PY_RPATH" "$file"
    fi
done
echo -e "${GREEN}✅ Relinking complete.${NC}"

# Install marcut module
echo -e "${BLUE}Installing marcut module...${NC}"
MARCUT_SRC="${REPO_ROOT}/src/python/marcut"
if [ -d "$MARCUT_SRC" ]; then
    cp -R "$MARCUT_SRC" "$PYTHON_SITE/"
    echo -e "${GREEN}✅ Marcut module installed${NC}"
else
    echo -e "${RED}❌ Marcut module directory not found at $MARCUT_SRC${NC}"
    exit 1
fi

# Clean up build artifacts from site-packages
find "$PYTHON_SITE" -name "*.a" -delete
find "$PYTHON_SITE" -name "*.c" -delete
find "$PYTHON_SITE" -name "*.h" -delete

# Clean up temp directory
safe_rm_rf "$TEMP_DIR"

echo -e "${GREEN}✅ BeeWare Python framework setup complete!${NC}"
echo "Framework size: $(du -sh "$FRAMEWORK_DIR" | cut -f1)"
echo "Site packages size: $(du -sh "$PYTHON_SITE" | cut -f1)"

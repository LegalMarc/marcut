#!/bin/bash
# Download and setup ARM64-only BeeWare Python framework for MarcutApp
set -euo pipefail

echo "🚀 Setting up ARM64-only BeeWare Python framework..."

# Configuration
BEFORE_VERSION="3.11-b7"
PYTHON_VERSION="3.11"
FRAMEWORK_NAME="Python.framework"
FRAMEWORK_URL="https://downloads.python.org/beeware/Python-${BEFORE_VERSION}-macos11_arm64.tar.gz"

# Directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRAMEWORK_DEST_DIR="${SCRIPT_DIR}/Sources/MarcutApp/Frameworks"
TEMP_DIR="${SCRIPT_DIR}/temp_framework"

safe_rm_rf() {
    local target="$1"
    if [ -z "${target}" ] || [ "${target}" = "/" ]; then
        echo "❌ Refusing to remove unsafe path: '${target}'"
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
        echo "❌ Unable to fully remove ${target}"
        exit 1
    fi
}

echo "📦 Downloading BeeWare Python ${BEFORE_VERSION} (ARM64 only)..."
echo "URL: ${FRAMEWORK_URL}"

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
        echo "❌ Could not resolve Python.framework version directory"
        exit 1
    }

    local lib_dir="${version_dir}/lib"
    local python_lib_dir="${lib_dir}/python${PYTHON_VERSION}"

    echo "🧹 Removing Tcl/Tk from embedded Python.framework..."
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
        echo "❌ Tcl/Tk artifacts still present in Python.framework:"
        echo "${hits}"
        exit 1
    fi

    echo "✅ Tcl/Tk removed from Python.framework"
}

# Create temporary directory
mkdir -p "${TEMP_DIR}"
cd "${TEMP_DIR}"

# Download the framework
if command -v curl >/dev/null 2>&1; then
    curl -L -o "python_framework.tar.gz" "${FRAMEWORK_URL}"
else
    echo "❌ curl not found. Please install curl."
    exit 1
fi

# Extract the framework
echo "📂 Extracting framework..."
tar -xzf "python_framework.tar.gz"

# Check if framework was extracted
if [ ! -d "${FRAMEWORK_NAME}" ]; then
    echo "❌ Framework extraction failed. Expected directory: ${FRAMEWORK_NAME}"
    echo "Contents of temp directory:"
    ls -la
    exit 1
fi

# Verify ARM64 binary
echo "🔍 Verifying ARM64 binary..."
FRAMEWORK_BIN="${FRAMEWORK_NAME}/Python"
if [ ! -f "${FRAMEWORK_BIN}" ]; then
    echo "❌ Python binary not found in framework"
    exit 1
fi

BINARY_INFO=$(file "${FRAMEWORK_BIN}")
echo "Binary info: ${BINARY_INFO}"

if [[ "${BINARY_INFO}" != *"arm64"* ]]; then
    echo "❌ Binary is not ARM64: ${BINARY_INFO}"
    exit 1
fi

# Test Python functionality
echo "🧪 Testing Python functionality..."
if "${FRAMEWORK_BIN}" --version >/dev/null 2>&1; then
    PYTHON_VERSION_OUTPUT=$("${FRAMEWORK_BIN}" --version)
    echo "✅ Python version: ${PYTHON_VERSION_OUTPUT}"
else
    echo "❌ Python binary test failed"
    exit 1
fi

# Remove old framework
echo "🗑️  Removing old framework..."
safe_rm_rf "${FRAMEWORK_DEST_DIR}/${FRAMEWORK_NAME}"

# Move new framework to destination
echo "📁 Installing framework..."
mv "${FRAMEWORK_NAME}" "${FRAMEWORK_DEST_DIR}/"

# Remove Tcl/Tk to satisfy App Store requirements
strip_tcl_tk "${FRAMEWORK_DEST_DIR}/${FRAMEWORK_NAME}"
verify_no_tcl_tk "${FRAMEWORK_DEST_DIR}/${FRAMEWORK_NAME}"

# Set correct permissions
chmod -R 755 "${FRAMEWORK_DEST_DIR}/${FRAMEWORK_NAME}"

# Clean up temp directory
echo "🧹 Cleaning up..."
cd "${SCRIPT_DIR}"
safe_rm_rf "${TEMP_DIR}"

echo "✅ ARM64 BeeWare Python framework setup complete!"
echo "📍 Framework location: ${FRAMEWORK_DEST_DIR}/${FRAMEWORK_NAME}"

# Verify installation
FINAL_BINARY="${FRAMEWORK_DEST_DIR}/${FRAMEWORK_NAME}/Python"
if [ -f "${FINAL_BINARY}" ]; then
    echo "🔍 Final verification:"
    file "${FINAL_BINARY}"
    echo "✅ Framework ready for use"
else
    echo "❌ Framework installation verification failed"
    exit 1
fi

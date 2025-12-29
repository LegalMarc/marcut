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

echo "📦 Downloading BeeWare Python ${BEFORE_VERSION} (ARM64 only)..."
echo "URL: ${FRAMEWORK_URL}"

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
rm -rf "${FRAMEWORK_DEST_DIR}/${FRAMEWORK_NAME}"

# Move new framework to destination
echo "📁 Installing framework..."
mv "${FRAMEWORK_NAME}" "${FRAMEWORK_DEST_DIR}/"

# Set correct permissions
chmod -R 755 "${FRAMEWORK_DEST_DIR}/${FRAMEWORK_NAME}"

# Clean up temp directory
echo "🧹 Cleaning up..."
cd "${SCRIPT_DIR}"
rm -rf "${TEMP_DIR}"

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
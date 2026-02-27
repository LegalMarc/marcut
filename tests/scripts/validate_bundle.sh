#!/bin/bash
#
# Bundle validation script for MarcutApp
# Validates critical components and runs diagnostic tests
#

set -euo pipefail

SCRIPT_DIR="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CONFIG_FILE="$ROOT_DIR/build-scripts/config.json"
export CONFIG_FILE
BUILD_DIR=""
if [ -f "$CONFIG_FILE" ]; then
    BUILD_DIR=$(python3 - <<'PY'
import json
import os
from pathlib import Path

config = Path(os.environ["CONFIG_FILE"])
try:
    data = json.loads(config.read_text())
    build_dir = data.get("build_dir")
    if build_dir:
        print((config.parent / build_dir).resolve())
except Exception:
    pass
PY
    )
fi
if [ -z "$BUILD_DIR" ]; then
    if [ -d "$ROOT_DIR/.marcut_artifacts/ignored-resources/builds/build_swift" ]; then
        BUILD_DIR="$ROOT_DIR/.marcut_artifacts/ignored-resources/builds/build_swift"
    elif [ -d "$ROOT_DIR/build_swift" ]; then
        BUILD_DIR="$ROOT_DIR/build_swift"
    else
        BUILD_DIR="$ROOT_DIR/build"
    fi
fi

DEFAULT_APP_BUNDLE="$BUILD_DIR/MarcutApp.app"
APP_BUNDLE="${1:-$DEFAULT_APP_BUNDLE}"
RESOURCES_DIR="${APP_BUNDLE}/Contents/Resources"
FRAMEWORKS_DIR="${APP_BUNDLE}/Contents/Frameworks"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test functions
test_file_exists() {
    local file="$1"
    local description="$2"

    if [[ -f "$file" ]]; then
        echo -e "${GREEN}✅${NC} $description: $file"
        return 0
    else
        echo -e "${RED}❌${NC} $description: $file (MISSING)"
        return 1
    fi
}

test_dir_exists() {
    local dir="$1"
    local description="$2"

    if [[ -d "$dir" ]]; then
        echo -e "${GREEN}✅${NC} $description: $dir"
        return 0
    else
        echo -e "${RED}❌${NC} $description: $dir (MISSING)"
        return 1
    fi
}

test_executable() {
    local exec="$1"
    local description="$2"

    if [[ -x "$exec" ]]; then
        echo -e "${GREEN}✅${NC} $description: $exec"
        return 0
    else
        echo -e "${RED}❌${NC} $description: $exec (NOT EXECUTABLE)"
        return 1
    fi
}

test_python_import() {
    local test_script="$1"
    local timeout_duration="${2:-5}"

    echo -e "${YELLOW}🔍${NC} Testing Python import (timeout: ${timeout_duration}s)..."

    if timeout "$timeout_duration" "$test_script" 2>/dev/null; then
        echo -e "${GREEN}✅${NC} Python import test successful"
        return 0
    else
        echo -e "${RED}❌${NC} Python import test failed or timed out"
        return 1
    fi
}

# Main validation
main() {
    echo "=== MarcutApp Bundle Validation ==="
    echo "Bundle: $APP_BUNDLE"
    echo ""

    local failed_tests=0

    # Test critical files
    echo "--- Testing Critical Files ---"
    test_dir_exists "$APP_BUNDLE" "App bundle" || ((failed_tests++))
    test_file_exists "$RESOURCES_DIR/run_python.sh" "run_python.sh script" || ((failed_tests++))
    test_file_exists "$RESOURCES_DIR/excluded-words.txt" "excluded-words.txt" || ((failed_tests++))
    if [[ -x "$APP_BUNDLE/Contents/MacOS/ollama" ]]; then
        echo -e "${GREEN}✅${NC} Ollama binary: $APP_BUNDLE/Contents/MacOS/ollama"
    elif [[ -x "$RESOURCES_DIR/ollama" ]]; then
        echo -e "${GREEN}✅${NC} Ollama binary: $RESOURCES_DIR/ollama"
    elif [[ -x "$RESOURCES_DIR/Ollama.app/Contents/MacOS/ollama" ]]; then
        echo -e "${GREEN}✅${NC} Ollama.app bundle: $RESOURCES_DIR/Ollama.app"
    else
        echo -e "${RED}❌${NC} Ollama binary not found"
        ((failed_tests++))
    fi
    echo ""

    # Test directories
    echo "--- Testing Directories ---"
    test_dir_exists "$RESOURCES_DIR/python_site" "python_site directory" || ((failed_tests++))
    test_dir_exists "$FRAMEWORKS_DIR/Python.framework" "Python.framework" || ((failed_tests++))
    test_dir_exists "$FRAMEWORKS_DIR/Python.framework/Versions/3.11" "Python 3.11 framework" || ((failed_tests++))
    test_dir_exists "$FRAMEWORKS_DIR/Python.framework/Versions/3.11/lib" "Python lib directory" || ((failed_tests++))
    echo ""

    # Test executables
    echo "--- Testing Executables ---"
    test_executable "$RESOURCES_DIR/run_python.sh" "run_python.sh" || ((failed_tests++))
    if [[ -x "$APP_BUNDLE/Contents/MacOS/ollama" ]]; then
        test_executable "$APP_BUNDLE/Contents/MacOS/ollama" "Ollama binary" || ((failed_tests++))
    elif [[ -x "$RESOURCES_DIR/ollama" ]]; then
        test_executable "$RESOURCES_DIR/ollama" "Ollama binary" || ((failed_tests++))
    elif [[ -x "$RESOURCES_DIR/Ollama.app/Contents/MacOS/ollama" ]]; then
        test_executable "$RESOURCES_DIR/Ollama.app/Contents/MacOS/ollama" "Ollama binary" || ((failed_tests++))
    else
        echo -e "${RED}❌${NC} Ollama binary not executable"
        ((failed_tests++))
    fi
    echo ""

    # Test Python functionality
    echo "--- Testing Python Functionality (PythonKit-focused) ---"

    # Test 1: Python framework availability
    echo "Test 1: Python framework availability"
    if [[ -d "$FRAMEWORKS_DIR/Python.framework/Versions/3.11" ]]; then
        echo -e "${GREEN}✅${NC} Python framework available"
    else
        echo -e "${RED}❌${NC} Python framework not available"
        ((failed_tests++))
    fi

    # Test 2: Python modules in python_site
    echo "Test 2: Python modules in python_site"
    if [[ -f "$RESOURCES_DIR/python_site/marcut/cli.py" ]] && [[ -f "$RESOURCES_DIR/python_site/marcut/pipeline.py" ]]; then
        echo -e "${GREEN}✅${NC} Marcut modules available in python_site"
    else
        echo -e "${RED}❌${NC} Marcut modules missing from python_site"
        ((failed_tests++))
    fi

    # Test 3: Essential Python packages
    echo "Test 3: Essential Python packages"
    local missing_packages=()

    PY_LAUNCHER="$RESOURCES_DIR/run_python.sh"
    if [[ ! -x "$PY_LAUNCHER" ]]; then
        PY_LAUNCHER="python3"
    fi

    for package in "lxml" "numpy" "docx" "requests" "pydantic" "tqdm"; do
        if ! [[ -d "$RESOURCES_DIR/python_site/$package" ]] && ! "$PY_LAUNCHER" -c "import $package" 2>/dev/null; then
            missing_packages+=("$package")
        fi
    done

    if [[ ${#missing_packages[@]} -eq 0 ]]; then
        echo -e "${GREEN}✅${NC} Essential Python packages available"
    else
        echo -e "${RED}❌${NC} Missing packages: ${missing_packages[*]}"
        ((failed_tests++))
    fi

    # Test 4: Architecture compatibility (ARM64)
    echo "Test 4: Architecture compatibility (ARM64)"
    local arch=$(uname -m)
    if [[ "$arch" == "arm64" ]]; then
        echo -e "${GREEN}✅${NC} Running on ARM64 architecture"
    else
        echo -e "${YELLOW}⚠️${NC} Running on $arch (ARM64 optimized)"
    fi

    # Note: PythonKit functionality is tested by the app itself during startup
    echo ""

    # Summary
    echo "=== Validation Summary ==="
    if [[ $failed_tests -eq 0 ]]; then
        echo -e "${GREEN}🎉 All tests passed! Bundle is valid.${NC}"
        exit 0
    else
        echo -e "${RED}❌ $failed_tests test(s) failed. Bundle needs attention.${NC}"
        exit 1
    fi
}

# Run validation
main "$@"

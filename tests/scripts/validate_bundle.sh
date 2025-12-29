#!/bin/bash
#
# Bundle validation script for MarcutApp
# Validates critical components and runs diagnostic tests
#

set -euo pipefail

SCRIPT_DIR="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_BUNDLE="${SCRIPT_DIR}/../build/MarcutApp.app"
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
    test_file_exists "$APP_BUNDLE" "App bundle" || ((failed_tests++))
    test_file_exists "$RESOURCES_DIR/run_python.sh" "run_python.sh script" || ((failed_tests++))
    test_file_exists "$RESOURCES_DIR/excluded-words.txt" "excluded-words.txt" || ((failed_tests++))
    test_file_exists "$RESOURCES_DIR/Ollama.app" "Ollama.app bundle" || ((failed_tests++))
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
    test_executable "$RESOURCES_DIR/Ollama.app/Contents/MacOS/ollama" "Ollama binary" || ((failed_tests++))
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

    for package in "lxml" "numpy" "docx" "requests" "pydantic" "tqdm"; do
        if ! [[ -d "$RESOURCES_DIR/python_site/$package" ]] && ! python3 -c "import $package" 2>/dev/null; then
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
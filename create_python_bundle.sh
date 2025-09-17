#!/bin/bash
#
# Creates a minimal Python bundle for embedding in MarcutApp
# This creates a self-contained Python distribution with all marcut dependencies
#
set -euo pipefail

BUNDLE_DIR="python_bundle"
TEMP_VENV="bundle_temp_env"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}Creating Python Bundle for MarcutApp${NC}"
echo "=============================================="

# Clean any existing bundle
if [ -d "$BUNDLE_DIR" ]; then
    echo -e "${YELLOW}Removing existing bundle...${NC}"
    rm -rf "$BUNDLE_DIR"
fi

if [ -d "$TEMP_VENV" ]; then
    rm -rf "$TEMP_VENV"
fi

# Create temporary venv with all dependencies
echo -e "${BLUE}Creating temporary environment with dependencies...${NC}"
python3 -m venv "$TEMP_VENV"
source "$TEMP_VENV/bin/activate"

# Install dependencies
pip install --upgrade pip
pip install python-docx>=1.1.0
pip install rapidfuzz>=3.6.1
pip install pydantic>=2.6.4
pip install requests>=2.31.0
pip install dateparser>=1.2.0
pip install tqdm>=4.66.0

# Install marcut in development mode
pip install -e .

echo -e "${GREEN}✅ Dependencies installed${NC}"

# Create bundle directory structure (will be updated with correct Python version)
echo -e "${BLUE}Creating bundle structure...${NC}"
mkdir -p "$BUNDLE_DIR"/bin "$BUNDLE_DIR"/lib

# Find Python version and paths using the system Python (not venv)
deactivate 2>/dev/null || true
SYSTEM_PYTHON=$(which python3)
PYTHON_VERSION=$($SYSTEM_PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYTHON_LIB_PATH="/opt/homebrew/lib/libpython${PYTHON_VERSION}.dylib"

# Check if Homebrew Python lib exists, fallback to system
if [ ! -f "$PYTHON_LIB_PATH" ]; then
    PYTHON_LIB_PATH="/usr/local/lib/libpython${PYTHON_VERSION}.dylib"
fi

if [ ! -f "$PYTHON_LIB_PATH" ]; then
    # Try to find it via the system Python executable
    PYTHON_LIB_PATH=$($SYSTEM_PYTHON -c "import sys, os; print(os.path.join(sys.exec_prefix, 'lib', f'libpython{sys.version_info.major}.{sys.version_info.minor}.dylib'))")
fi

echo "Python version: $PYTHON_VERSION"
echo "System Python: $SYSTEM_PYTHON"
echo "Python library: $PYTHON_LIB_PATH"

# Re-activate venv for the copying operations
source "$TEMP_VENV/bin/activate"

# Copy Python executable
echo -e "${BLUE}Copying Python executable...${NC}"
cp "$TEMP_VENV/bin/python3" "$BUNDLE_DIR/bin/"
chmod +x "$BUNDLE_DIR/bin/python3"

# Copy Python shared library
echo -e "${BLUE}Copying Python library...${NC}"
if [ -f "$PYTHON_LIB_PATH" ]; then
    cp "$PYTHON_LIB_PATH" "$BUNDLE_DIR/lib/"
    echo -e "${GREEN}✅ Python library copied${NC}"
else
    echo -e "${YELLOW}⚠️  Python shared library not found at $PYTHON_LIB_PATH${NC}"
    echo "Continuing without shared library - may need system Python"
fi

# Create the Python lib directory with correct version
mkdir -p "$BUNDLE_DIR/lib/python${PYTHON_VERSION}"

# Find the system Python installation to copy standard library
deactivate 2>/dev/null || true
SYSTEM_PYTHON_LIB=$($SYSTEM_PYTHON -c "import sys; print(sys.exec_prefix + '/lib/python' + sys.version[:3])")
echo "System Python lib: $SYSTEM_PYTHON_LIB"

# Copy the complete Python standard library
echo -e "${BLUE}Copying Python standard library...${NC}"
if [ -d "$SYSTEM_PYTHON_LIB" ]; then
    # Copy the entire Python standard library
    cp -R "$SYSTEM_PYTHON_LIB"/* "$BUNDLE_DIR/lib/python${PYTHON_VERSION}/"
    echo -e "${GREEN}✅ Standard library copied${NC}"
else
    echo -e "${YELLOW}⚠️  System Python lib not found at $SYSTEM_PYTHON_LIB${NC}"
fi

# Re-activate venv and copy site-packages with dependencies
source "$TEMP_VENV/bin/activate"
echo -e "${BLUE}Copying site-packages...${NC}"
if [ -d "$TEMP_VENV/lib/python${PYTHON_VERSION}/site-packages" ]; then
    cp -R "$TEMP_VENV/lib/python${PYTHON_VERSION}/site-packages"/* "$BUNDLE_DIR/lib/python${PYTHON_VERSION}/site-packages/"
    echo -e "${GREEN}✅ Site-packages copied${NC}"
else
    echo -e "${YELLOW}⚠️  Site-packages not found${NC}"
fi

# Copy marcut module to site-packages instead of separate directory
echo -e "${BLUE}Copying marcut module...${NC}"
cp -R marcut "$BUNDLE_DIR/lib/python${PYTHON_VERSION}/site-packages/"

# Fix library paths using install_name_tool if library was copied
if [ -f "$BUNDLE_DIR/lib/libpython${PYTHON_VERSION}.dylib" ]; then
    echo -e "${BLUE}Fixing library paths...${NC}"
    install_name_tool -change \
        "@rpath/libpython${PYTHON_VERSION}.dylib" \
        "@loader_path/../lib/libpython${PYTHON_VERSION}.dylib" \
        "$BUNDLE_DIR/bin/python3" 2>/dev/null || true
    echo -e "${GREEN}✅ Library paths updated${NC}"

    # Create compatibility symlinks expected by some builds (@executable_path/../Python3)
    ln -sf "libpython${PYTHON_VERSION}.dylib" "$BUNDLE_DIR/lib/Python3" 2>/dev/null || true
    ln -sf "./lib/libpython${PYTHON_VERSION}.dylib" "$BUNDLE_DIR/Python3" 2>/dev/null || true
fi

# If libpython was not available, try to copy the framework-style "Python3" loader
if [ ! -f "$BUNDLE_DIR/lib/libpython${PYTHON_VERSION}.dylib" ]; then
    echo -e "${BLUE}Attempting to vendor framework-style Python3 loader...${NC}"
    FRAME_LIB=$(otool -L "$BUNDLE_DIR/bin/python3" 2>/dev/null | awk '/Python3|Python\.framework\/Versions\//{print $1; exit}')
    if [ -n "$FRAME_LIB" ] && [ -f "$FRAME_LIB" ]; then
        mkdir -p "$BUNDLE_DIR/lib"
        cp "$FRAME_LIB" "$BUNDLE_DIR/Python3" 2>/dev/null || true
        cp "$FRAME_LIB" "$BUNDLE_DIR/lib/Python3" 2>/dev/null || true
        echo -e "${GREEN}✅ Copied Python3 loader from $FRAME_LIB${NC}"
        # Adjust the interpreter's reference from @executable_path/../Python3 to @loader_path/../Python3
        install_name_tool -change \
            "@executable_path/../Python3" \
            "@loader_path/../Python3" \
            "$BUNDLE_DIR/bin/python3" 2>/dev/null || true
        echo -e "${GREEN}✅ Updated interpreter load path to @loader_path${NC}"
    else
        echo -e "${YELLOW}⚠️  Could not locate framework Python3 loader via otool; continuing${NC}"
    fi
fi

# Cleanup temporary environment
echo -e "${BLUE}Cleaning up temporary environment...${NC}"
deactivate 2>/dev/null || true
rm -rf "$TEMP_VENV"

# Create bundle test script with correct Python version
cat > "$BUNDLE_DIR/test_bundle.sh" << EOF
#!/bin/bash
export PYTHONHOME=\$(pwd)
export PYTHONPATH=\$(pwd)/lib/python${PYTHON_VERSION}/site-packages
export DYLD_LIBRARY_PATH=\$(pwd)/lib
exec ./bin/python3 "\$@"
EOF
chmod +x "$BUNDLE_DIR/test_bundle.sh"

echo -e "${GREEN}✅ Python bundle created successfully!${NC}"
echo ""
echo "Bundle structure:"
echo "  $BUNDLE_DIR/"
echo "  ├── bin/python3"
echo "  ├── lib/python${PYTHON_VERSION}/"
echo "  ├── marcut/"
echo "  └── test_bundle.sh"
echo ""
echo "Bundle size: $(du -sh "$BUNDLE_DIR" | cut -f1)"

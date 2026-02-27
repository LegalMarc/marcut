#!/bin/bash
#
# Test PythonKit integration by testing the app's Python functionality
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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

DEFAULT_APP_PATH="$BUILD_DIR/MarcutApp.app/Contents/MacOS/MarcutApp"
APP_PATH="${1:-$DEFAULT_APP_PATH}"

echo "Testing PythonKit integration..."

# Test basic app launch (this will trigger the PythonKit smoke test)
echo "1. Testing app launch with PythonKit smoke test..."

# Use timeout to prevent hanging
if timeout 30 "$APP_PATH" --cli --help >/dev/null 2>&1; then
    echo "✅ App launches successfully"
else
    echo "❌ App launch failed or timed out"
    exit 1
fi

echo "2. Running diagnostics to confirm PythonKit startup..."

DIAG_OUTPUT=""
if command -v timeout >/dev/null 2>&1; then
    DIAG_OUTPUT=$(timeout 60 "$APP_PATH" --diagnose 2>&1) || true
else
    DIAG_OUTPUT=$("$APP_PATH" --diagnose 2>&1) || true
fi

if echo "$DIAG_OUTPUT" | grep -q "Python runtime initialized successfully"; then
    echo "✅ PythonKit diagnostics reported successful initialization"
else
    echo "❌ PythonKit diagnostics did not report successful initialization"
    echo "Diagnostic output (tail):"
    echo "$DIAG_OUTPUT" | tail -20
    exit 1
fi

echo "🎉 PythonKit integration test successful!"

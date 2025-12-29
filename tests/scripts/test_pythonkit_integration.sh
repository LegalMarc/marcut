#!/bin/bash
#
# Test PythonKit integration by testing the app's Python functionality
#

set -euo pipefail

APP_PATH="/Users/mhm/Documents/Hobby/Marcut-2/build/MarcutApp.app/Contents/MacOS/MarcutApp"

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

echo "2. Testing PythonKit smoke test logs..."

# Check logs for PythonKit success
LOG_FILE="/Users/mhm/Library/Application Support/MarcutApp/logs/marcut.log"
if [[ -f "$LOG_FILE" ]]; then
    if tail -20 "$LOG_FILE" | grep -q "PythonKit smoke test succeeded"; then
        echo "✅ PythonKit smoke test passed"
    else
        echo "❌ PythonKit smoke test not found in logs"
        echo "Recent log entries:"
        tail -10 "$LOG_FILE"
        exit 1
    fi
else
    echo "❌ Log file not found: $LOG_FILE"
    exit 1
fi

echo "🎉 PythonKit integration test successful!"
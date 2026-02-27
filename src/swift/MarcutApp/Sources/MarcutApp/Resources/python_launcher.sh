#!/bin/bash
# Launcher script bundled with MarcutApp to execute Python commands from the app bundle.
# Prefers the self-contained python_bundle if present, otherwise falls back to the embedded
# Python.framework + vendored libraries.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEARCH_DIR="$SCRIPT_DIR"
APP_ROOT=""

# Walk up the directory tree until we find the app bundle that contains Contents/MacOS.
while [ "$SEARCH_DIR" != "/" ]; do
  if [ -d "$SEARCH_DIR/Contents/MacOS" ] && [ -d "$SEARCH_DIR/Contents/Resources" ]; then
    APP_ROOT="$SEARCH_DIR"
    break
  fi
  SEARCH_DIR="$(dirname "$SEARCH_DIR")"
done

if [ -z "$APP_ROOT" ]; then
  echo "python_launcher.sh could not determine the app bundle root." >&2
  exit 1
fi

CONTENTS_DIR="$APP_ROOT/Contents"
RESOURCES_DIR="$CONTENTS_DIR/Resources"

SKIP_BUNDLE="${MARCUT_SKIP_PYTHON_BUNDLE:-0}"
BUNDLED_TEST_LAUNCHER="$RESOURCES_DIR/python_bundle/test_bundle.sh"
if [ "$SKIP_BUNDLE" != "1" ] && [ -x "$BUNDLED_TEST_LAUNCHER" ]; then
  exec /bin/bash "$BUNDLED_TEST_LAUNCHER" "$@"
fi

FRAMEWORK_ROOT="$CONTENTS_DIR/Frameworks/Python.framework/Versions/Current"
FRAMEWORK_PYTHON="$FRAMEWORK_ROOT/Python"
FRAMEWORK_APP="$FRAMEWORK_ROOT/Resources/Python.app/Contents/MacOS/Python"
if [ ! -x "$FRAMEWORK_PYTHON" ] && [ -x "$FRAMEWORK_APP" ]; then
  FRAMEWORK_PYTHON="$FRAMEWORK_APP"
fi

if [ -x "$FRAMEWORK_PYTHON" ]; then
  PYTHONPATH_ENTRIES=()
  if [ -d "$RESOURCES_DIR/python_stdlib" ]; then
    PYTHONPATH_ENTRIES+=("$RESOURCES_DIR/python_stdlib")
  fi
  if [ -d "$RESOURCES_DIR/python_site" ]; then
    PYTHONPATH_ENTRIES+=("$RESOURCES_DIR/python_site")
  fi
  if [ ${#PYTHONPATH_ENTRIES[@]} -gt 0 ]; then
    export PYTHONPATH="$(IFS=:; echo "${PYTHONPATH_ENTRIES[*]}")"
  else
    unset PYTHONPATH || true
  fi

  PYTHON_HOME_DIR="$CONTENTS_DIR/Frameworks/Python.framework/Versions/Current"
  if [ ! -d "$PYTHON_HOME_DIR" ]; then
    PYTHON_HOME_DIR="$CONTENTS_DIR/Frameworks/Python.framework/Versions/3.10"
  fi
  export PYTHONHOME="$PYTHON_HOME_DIR"
  export PYTHONNOUSERSITE=1
  export PYTHONDONTWRITEBYTECODE=1
  export DYLD_LIBRARY_PATH="$CONTENTS_DIR/Frameworks:${DYLD_LIBRARY_PATH:-}"

  exec "$FRAMEWORK_PYTHON" "$@"
fi

echo "python_launcher.sh could not find a usable Python runtime inside the app bundle." >&2
exit 1

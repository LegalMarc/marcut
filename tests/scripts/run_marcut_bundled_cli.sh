#!/bin/bash
# Run Marcut CLI using the bundled Python.framework and vendored python_site (no system Python fallback).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

CONFIG_FILE="$ROOT_DIR/build-scripts/config.json"
export CONFIG_FILE
BUILD_DIR=""
if [[ -f "$CONFIG_FILE" ]]; then
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
if [[ -z "$BUILD_DIR" ]]; then
  if [[ -d "$ROOT_DIR/.marcut_artifacts/ignored-resources/builds/build_swift" ]]; then
    BUILD_DIR="$ROOT_DIR/.marcut_artifacts/ignored-resources/builds/build_swift"
  elif [[ -d "$ROOT_DIR/build_swift" ]]; then
    BUILD_DIR="$ROOT_DIR/build_swift"
  else
    BUILD_DIR="$ROOT_DIR/build"
  fi
fi

APP_BUNDLE="$BUILD_DIR/MarcutApp.app"
RUN_PYTHON="$APP_BUNDLE/Contents/Resources/run_python.sh"
if [[ -x "$RUN_PYTHON" ]]; then
  PYTHON_SITE="$APP_BUNDLE/Contents/Resources/python_site"
  export PYTHON_SITE
  exec "$RUN_PYTHON" - <<'PY' "$@"
import os
import runpy
import sys

python_site = os.environ.get("PYTHON_SITE")
if python_site:
    sys.path.insert(0, python_site)
sys.argv = ["marcut"] + sys.argv[1:]
runpy.run_module("marcut.cli", run_name="__main__")
PY
fi

SWIFT_SOURCES="${ROOT_DIR}/src/swift/MarcutApp/Sources/MarcutApp"
PY_VERSION="${PY_VERSION:-3.11}"
PY_VERSION_NODOT="${PY_VERSION/./}"
FRAMEWORK_ROOT="${SWIFT_SOURCES}/Frameworks/Python.framework/Versions/${PY_VERSION}"
PYTHON_BIN=""
EMBED_EXEC="${SCRIPT_DIR}/python3_embed"

if [[ -x "${FRAMEWORK_ROOT}/bin/python${PY_VERSION}" ]]; then
  PYTHON_BIN="${FRAMEWORK_ROOT}/bin/python${PY_VERSION}"
elif [[ -x "${EMBED_EXEC}" ]]; then
  PYTHON_BIN="${EMBED_EXEC}"
elif [[ -x "${FRAMEWORK_ROOT}/Python" ]]; then
  PYTHON_BIN="${FRAMEWORK_ROOT}/Python"
fi

if [[ -z "${PYTHON_BIN}" ]]; then
  echo "Bundled Python runtime not found in framework or scripts directory." >&2
  exit 1
fi

PY_ROOT="${ROOT_DIR}"
PY_SITE="${SWIFT_SOURCES}/python_site"
PY_STDLIB="${SWIFT_SOURCES}/Resources/python_stdlib"
PY_EMBED_STDLIB="${FRAMEWORK_ROOT}/lib/python${PY_VERSION}"
PY_EMBED_ZIP="${FRAMEWORK_ROOT}/lib/python${PY_VERSION_NODOT}.zip"
PY_EMBED_DYNLOAD="${FRAMEWORK_ROOT}/lib/python${PY_VERSION}/lib-dynload"

export PYTHONHOME="${FRAMEWORK_ROOT}"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export DYLD_LIBRARY_PATH="${SWIFT_SOURCES}/Frameworks:${DYLD_LIBRARY_PATH:-}"

PYCODE=$(cat <<'PYCODE'
import sys, runpy
paths = [
    r"{PY_ROOT}",
    r"{PY_SITE}",
    r"{PY_STDLIB}",
    r"{PY_EMBED_STDLIB}",
    r"{PY_EMBED_ZIP}",
    r"{PY_EMBED_DYNLOAD}",
]
sys.path = [p for p in paths if p]
sys.argv = ["marcut"] + sys.argv[1:]
runpy.run_module("marcut.cli", run_name="__main__")
PYCODE
)
PYCODE="${PYCODE//\{PY_ROOT\}/${PY_ROOT}}"
PYCODE="${PYCODE//\{PY_SITE\}/${PY_SITE}}"
PYCODE="${PYCODE//\{PY_STDLIB\}/${PY_STDLIB}}"
PYCODE="${PYCODE//\{PY_EMBED_STDLIB\}/${PY_EMBED_STDLIB}}"
PYCODE="${PYCODE//\{PY_EMBED_ZIP\}/${PY_EMBED_ZIP}}"
PYCODE="${PYCODE//\{PY_EMBED_DYNLOAD\}/${PY_EMBED_DYNLOAD}}"

exec "${PYTHON_BIN}" -c "${PYCODE}" "$@"

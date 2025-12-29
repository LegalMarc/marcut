#!/bin/bash
# Run Marcut CLI using the bundled Python.framework and vendored python_site (no system Python fallback).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

PY_VERSION="3.10"
FRAMEWORK_ROOT="${ROOT_DIR}/MarcutApp/Sources/MarcutApp/Frameworks/Python.framework/Versions/${PY_VERSION}"
PYTHON_BIN="${FRAMEWORK_ROOT}/bin/python${PY_VERSION}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Bundled Python runtime not found at ${PYTHON_BIN}." >&2
  exit 1
fi

PY_ROOT="${ROOT_DIR}"
PY_SITE="${ROOT_DIR}/MarcutApp/Sources/MarcutApp/python_site"
PY_STDLIB="${ROOT_DIR}/MarcutApp/Sources/MarcutApp/Resources/python_stdlib"
PY_EMBED_STDLIB="${FRAMEWORK_ROOT}/lib/python3.10"
PY_EMBED_ZIP="${FRAMEWORK_ROOT}/lib/python310.zip"
PY_EMBED_DYNLOAD="${FRAMEWORK_ROOT}/lib/python3.10/lib-dynload"

export PYTHONHOME="${FRAMEWORK_ROOT}"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export DYLD_LIBRARY_PATH="${ROOT_DIR}/MarcutApp/Sources/MarcutApp/Frameworks:${DYLD_LIBRARY_PATH:-}"

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

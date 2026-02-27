#!/bin/bash
#
# Universal BeeWare Python launcher for MarcutApp.
# Resolves the app bundle paths, sets PYTHONHOME/PYTHONPATH for the embedded
# Python.framework and python_site payload, then forwards all CLI arguments.
#
set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [ -h "${SOURCE}" ]; do
    DIR="$(cd -P "$(dirname "${SOURCE}")" && pwd)"
    SOURCE="$(readlink "${SOURCE}")"
    [[ "${SOURCE}" != /* ]] && SOURCE="${DIR}/${SOURCE}"
done

SCRIPT_DIR="$(cd -P "$(dirname "${SOURCE}")" && pwd)"
APP_CONTENTS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
FRAMEWORK_PATH="${APP_CONTENTS_DIR}/Frameworks/Python.framework"
PYTHON_HOME="${FRAMEWORK_PATH}/Versions/3.11"
PYTHON_SITE_PATH="${SCRIPT_DIR}/python_site"
PYTHON_STDLIB_PATH="${SCRIPT_DIR}/python_stdlib"
EMBED_EXECUTABLE="${SCRIPT_DIR}/python3_embed"

PYTHON_EXECUTABLE=""
if [[ -x "${PYTHON_HOME}/bin/python3" ]]; then
    PYTHON_EXECUTABLE="${PYTHON_HOME}/bin/python3"
elif [[ -x "${EMBED_EXECUTABLE}" ]]; then
    PYTHON_EXECUTABLE="${EMBED_EXECUTABLE}"
elif [[ -x "${PYTHON_HOME}/Python" ]]; then
    PYTHON_EXECUTABLE="${PYTHON_HOME}/Python"
else
    echo "run_python.sh could not locate an embedded Python executable" >&2
    exit 1
fi

export PYTHONHOME="${PYTHON_HOME}"
PYTHONPATH_ENTRIES=()
if [[ -d "${PYTHON_STDLIB_PATH}" ]]; then
    PYTHONPATH_ENTRIES+=("${PYTHON_STDLIB_PATH}")
fi
if [[ -d "${PYTHON_SITE_PATH}" ]]; then
    PYTHONPATH_ENTRIES+=("${PYTHON_SITE_PATH}")
fi
PYTHONPATH_ENTRIES+=("${PYTHON_HOME}/lib/python3.11")
PYTHONPATH_ENTRIES+=("${PYTHON_HOME}/lib/python3.11/site-packages")
PYTHONPATH_FALLBACK="$(IFS=:; echo "${PYTHONPATH_ENTRIES[*]}")"
if [[ -z "${PYTHONPATH:-}" ]]; then
    export PYTHONPATH="${PYTHONPATH_FALLBACK}"
else
    export PYTHONPATH="${PYTHONPATH}:${PYTHONPATH_FALLBACK}"
fi
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export DYLD_LIBRARY_PATH="${APP_CONTENTS_DIR}/Frameworks:${DYLD_LIBRARY_PATH:-}"

exec "${PYTHON_EXECUTABLE}" "$@"

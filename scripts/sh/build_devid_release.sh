#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "Building Developer ID–signed, notarized DMG for direct distribution..."

for arg in "$@"; do
    if [ "$arg" = "--help" ]; then
        cat <<'EOF'
Usage: scripts/sh/build_devid_release.sh [build_appstore_release options]

Builds a Developer ID signed DMG and then notarizes it via scripts/notarize_macos.sh.

Environment:
  CUSTOM_SIGN_IDENTITY   Developer ID Application certificate name
  NOTARIZATION_PROFILE   Optional notarytool profile label (default: marcut-notarization)
EOF
        exit 0
    fi
done

export CUSTOM_SIGN_IDENTITY="${CUSTOM_SIGN_IDENTITY:-}"
export NOTARIZATION_PROFILE="${NOTARIZATION_PROFILE:-marcut-notarization}"
export SKIP_NOTARIZATION="${SKIP_NOTARIZATION:-true}"

CONFIG_PATH="${REPO_ROOT}/build-scripts/config.json"
if [ -z "${CUSTOM_SIGN_IDENTITY}" ] && [ -f "${CONFIG_PATH}" ] && command -v python3 >/dev/null 2>&1; then
    CUSTOM_SIGN_IDENTITY="$(python3 - "${CONFIG_PATH}" <<'PY'
import json
import sys

config_path = sys.argv[1]
try:
    with open(config_path, "r", encoding="utf-8") as handle:
        cfg = json.load(handle)
except Exception:
    cfg = {}

for key in ("custom_sign_identity", "developer_id_identity"):
    value = str(cfg.get(key, "")).strip()
    if value:
        print(value)
        raise SystemExit

candidate = str(cfg.get("appstore_default_identity", "")).strip()
if candidate.startswith("Developer ID Application"):
    print(candidate)
PY
)"
    export CUSTOM_SIGN_IDENTITY
fi

if [ -z "${CUSTOM_SIGN_IDENTITY}" ] && command -v security >/dev/null 2>&1; then
    CUSTOM_SIGN_IDENTITY="$(
        security find-identity -v -p codesigning 2>/dev/null \
            | sed -n 's/.*"\(Developer ID Application:[^"]*\)".*/\1/p' \
            | head -1
    )"
    export CUSTOM_SIGN_IDENTITY
fi

if [ -z "${CUSTOM_SIGN_IDENTITY}" ]; then
    echo "❌ CUSTOM_SIGN_IDENTITY is required for Developer ID builds."
    echo "Set it via env var, or configure custom_sign_identity/developer_id_identity in build-scripts/config.json."
    exit 1
fi

cd "$REPO_ROOT"
BUILD_STARTED_EPOCH="$(date +%s)"

bash "${REPO_ROOT}/scripts/sh/build_appstore_release.sh" --skip-notarization "$@"

DMG_PATH=""
if [ -f "${CONFIG_PATH}" ] && command -v python3 >/dev/null 2>&1; then
    DMG_PATH="$(python3 - "${CONFIG_PATH}" "${REPO_ROOT}" "${BUILD_STARTED_EPOCH}" <<'PY'
import json
import os
import glob
import sys

config_path = sys.argv[1]
repo_root = sys.argv[2]
build_started = int(float(sys.argv[3]))
cfg = {}
try:
    with open(config_path, "r", encoding="utf-8") as handle:
        cfg = json.load(handle)
except Exception:
    cfg = {}

base = os.path.dirname(os.path.abspath(config_path))
app_name = str(cfg.get("app_name", "MarcutApp")).strip() or "MarcutApp"
output_root = os.path.normpath(os.path.join(repo_root, ".marcut_artifacts", "ignored-resources"))

def newest(paths):
    files = [p for p in paths if os.path.isfile(p)]
    if not files:
        return ""
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return files[0]

recent_candidates = []
for pattern in (
    os.path.join(output_root, f"{app_name}-v*-AppStore.dmg"),
    os.path.join(output_root, f"{app_name}-v*.dmg"),
    os.path.join(output_root, f"{app_name}-Swift-*.dmg"),
):
    for path in glob.glob(pattern):
        try:
            if int(os.path.getmtime(path)) >= build_started:
                recent_candidates.append(path)
        except OSError:
            pass

recent_pick = newest(recent_candidates)
if recent_pick:
    print(os.path.normpath(recent_pick))
    raise SystemExit

# Fallback to configured final_dmg when no freshly-created DMG was found.
final = cfg.get("final_dmg")
if final:
    final_path = os.path.normpath(os.path.join(base, final))
    if os.path.isfile(final_path):
        print(final_path)
        raise SystemExit

# Last resort: newest DMG by naming conventions.
fallback_candidates = []
for pattern in (
    os.path.join(output_root, f"{app_name}-v*-AppStore.dmg"),
    os.path.join(output_root, f"{app_name}-v*.dmg"),
    os.path.join(output_root, f"{app_name}-Swift-*.dmg"),
):
    fallback_candidates.extend(glob.glob(pattern))
fallback_pick = newest(fallback_candidates)
if fallback_pick:
    print(os.path.normpath(fallback_pick))
PY
)"
fi

if [ -z "${DMG_PATH}" ] || [ ! -f "${DMG_PATH}" ]; then
    DMG_PATH="$(ls -t "${REPO_ROOT}/.marcut_artifacts/ignored-resources"/MarcutApp-v*.dmg 2>/dev/null | head -1)"
fi

if [ -f "${DMG_PATH}" ]; then
    echo "ℹ️  Notarizing DMG via scripts/notarize_macos.sh (${DMG_PATH})"
    bash "${REPO_ROOT}/scripts/notarize_macos.sh" "${DMG_PATH}"
else
    echo "⚠️  DMG not found; skipping external notarization."
fi

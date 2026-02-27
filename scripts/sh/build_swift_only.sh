#!/bin/bash
#
# Orchestrated build pipeline for MarcutApp.
# This script exposes discrete build stages that can be composed by the TUI or run manually.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
OUTPUT_ROOT="${OUTPUT_ROOT:-$REPO_ROOT/.marcut_artifacts/ignored-resources}"

CONFIG_FILE="${CONFIG_FILE:-$REPO_ROOT/build-scripts/config.json}"
if [ ! -f "$CONFIG_FILE" ] && [ -f "$REPO_ROOT/config.json" ]; then
    CONFIG_FILE="$REPO_ROOT/config.json"
elif [ ! -f "$CONFIG_FILE" ] && [ -f "$SCRIPT_DIR/config.json" ]; then
    CONFIG_FILE="$SCRIPT_DIR/config.json"
fi

if [ ! -f "$CONFIG_FILE" ]; then
    echo "❌ Missing config file at ${CONFIG_FILE}" >&2
    exit 1
fi

cd "$REPO_ROOT"

if ! command -v jq >/dev/null 2>&1; then
    echo "❌ jq is required to parse ${CONFIG_FILE}" >&2
    exit 1
fi

CONFIG_DIR="$(cd "$(dirname "$CONFIG_FILE")" && pwd)"

cfg() {
    jq -r "$1 // empty" "$CONFIG_FILE"
}

resolve_path() {
    local value="$1"
    if [ -z "$value" ]; then
        echo ""
        return
    fi
    # Bare command names (for example "python3.11") are not file paths.
    if [[ "$value" != */* ]]; then
        echo "$value"
        return
    fi
    if [[ "$value" = /* ]]; then
        echo "$value"
    else
        echo "$CONFIG_DIR/$value"
    fi
}

APP_NAME=$(cfg '.app_name')
BUNDLE_ID=$(cfg '.bundle_id')
VERSION=$(cfg '.version')
BUILD_NUMBER=$(cfg '.build_number')
BUILD_DIR=$(resolve_path "$(cfg '.build_dir')")
FINAL_DMG=$(resolve_path "$(cfg '.final_dmg')")
PYTHON_FRAMEWORK_SOURCE=$(resolve_path "$(cfg '.python_framework_source')")
PYTHON_SITE_SOURCE=$(resolve_path "$(cfg '.python_site_source')")
PYTHON_SITE_REPO_SOURCE=$(resolve_path "$(cfg '.python_site_repo_source')")
SETUP_SCRIPT=$(resolve_path "$(cfg '.setup_script')")
HOMEBREW_PYTHON=$(resolve_path "$(cfg '.homebrew_python')")
SWIFT_PROJECT_DIR=$(resolve_path "$(cfg '.swift_project_dir')")
SWIFT_BUILD_DIR=$(resolve_path "$(cfg '.swift_build_dir')")
SWIFT_BINARY_PATH=$(resolve_path "$(cfg '.swift_binary_path')")
SWIFT_RESOURCE_BUNDLE=$(resolve_path "$(cfg '.swift_resource_bundle')")
RUN_PYTHON_LAUNCHER=$(resolve_path "$(cfg '.run_python_launcher')")
PYTHON_STUB_SOURCE=$(resolve_path "$(cfg '.python_stub_source')")
OLLAMA_BINARY=$(resolve_path "$(cfg '.ollama_binary')")
OLLAMA_HELPER_INFO=$(resolve_path "$(cfg '.ollama_helper_info')")
OLLAMA_ENTITLEMENTS=$(resolve_path "$(cfg '.ollama_entitlements')")

if [ -z "${VERSION}" ] && [ -n "${BUILD_NUMBER}" ]; then
    VERSION="${BUILD_NUMBER}"
fi
if [ -z "${BUILD_NUMBER}" ] && [ -n "${VERSION}" ]; then
    BUILD_NUMBER="${VERSION}"
fi
if [ -n "${VERSION}" ] && [ -n "${BUILD_NUMBER}" ] && [ "${VERSION}" != "${BUILD_NUMBER}" ]; then
    echo "⚠️  Version/build mismatch detected (version=${VERSION}, build=${BUILD_NUMBER}); aligning build to version."
    BUILD_NUMBER="${VERSION}"
    if command -v python3 >/dev/null 2>&1; then
        python3 - "$CONFIG_FILE" "$VERSION" <<'PY' >/dev/null 2>&1 || true
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1]).resolve()
version = sys.argv[2]
try:
    data = json.loads(config_path.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(0)

data["version"] = version
data["build_number"] = version
config_path.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
PY
    fi
fi

if [ -z "$BUILD_DIR" ]; then
    BUILD_DIR="${OUTPUT_ROOT}/build_swift"
fi

if [ -z "$PYTHON_SITE_SOURCE" ]; then
    PYTHON_SITE_SOURCE="${SWIFT_PROJECT_DIR}/Sources/MarcutApp/python_site"
fi

if [ -z "$PYTHON_SITE_REPO_SOURCE" ]; then
    PYTHON_SITE_REPO_SOURCE="${REPO_ROOT}/src/python/marcut"
fi

if [ -z "$SWIFT_BUILD_DIR" ]; then
    SWIFT_BUILD_DIR="${OUTPUT_ROOT}/builds/swiftpm"
fi

if [ -z "$SWIFT_BINARY_PATH" ]; then
    SWIFT_BINARY_PATH="${SWIFT_BUILD_DIR}/arm64-apple-macosx/debug/${APP_NAME}"
fi

if [ -z "$SWIFT_RESOURCE_BUNDLE" ]; then
    SWIFT_RESOURCE_BUNDLE="${SWIFT_BUILD_DIR}/arm64-apple-macosx/debug/${APP_NAME}_${APP_NAME}.bundle"
fi

if [ -z "$FINAL_DMG" ]; then
    FINAL_DMG="${OUTPUT_ROOT}/${APP_NAME}-Swift-${VERSION}.dmg"
fi

APP_BUNDLE="${BUILD_DIR}/${APP_NAME}.app"
PYTHON_FRAMEWORK_DEST="${APP_BUNDLE}/Contents/Frameworks/Python.framework"

GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'
SIGN_IDENTITY="${MARCUT_SIGN_IDENTITY:--}"
AUTO_BUMP_NEXT_VERSION="${AUTO_BUMP_NEXT_VERSION:-0}"

log_step() {
    echo -e "${BLUE}==>${NC} $1"
}

run_with_timeout() {
    local seconds="$1"
    shift
    if command -v timeout >/dev/null 2>&1; then
        timeout "$seconds" "$@"
    elif command -v gtimeout >/dev/null 2>&1; then
        gtimeout "$seconds" "$@"
    elif command -v python3 >/dev/null 2>&1; then
        python3 - "$seconds" "$@" <<'PY'
import subprocess
import sys

timeout_s = float(sys.argv[1])
cmd = sys.argv[2:]
proc = subprocess.Popen(cmd)
try:
    proc.wait(timeout=timeout_s)
    sys.exit(proc.returncode)
except subprocess.TimeoutExpired:
    proc.kill()
    sys.exit(124)
PY
    else
        "$@"
    fi
}

prune_tk_artifacts() {
    local target="$1"
    if [ -z "$target" ] || [ ! -e "$target" ]; then
        return
    fi
    local count=0
    while IFS= read -r -d '' path; do
        rm -rf "$path" 2>/dev/null || true
        count=$((count + 1))
    done < <(find "$target" \
        \( -name "libtk*.dylib" -o -name "libtcl*.dylib" -o -name "libtkstub*.a" -o -name "libtclstub*.a" \
           -o -name "_tkinter*.so" -o -name "_tkinter*.dylib" \
           -o -path "*/tk8.6" -o -path "*/tk8.6/*" -o -path "*/tcl8.6" -o -path "*/tcl8.6/*" \
           -o -path "*/tkinter" -o -path "*/tkinter/*" -o -path "*/idlelib" -o -path "*/idlelib/*" \
           -o -path "*/turtledemo" -o -path "*/turtledemo/*" \
           -o -path "*/marcut/gui.py" -o -path "*/marcut/setup_wizard.py" -o -path "*/marcut/bootstrapper.py" \
           -o -path "*/marcut/progress_widgets.py" -o -path "*/marcut/native_setup.py" \
           -o -path "*/tqdm/tk.py" \) -print0 2>/dev/null)
    if [ "$count" -gt 0 ]; then
        echo -e "${BLUE}==>${NC} Pruned ${count} Tk/Tcl artifacts from ${target}"
    fi
}

prune_resource_bundle_runtimes() {
    local resource_root="${APP_BUNDLE}/Contents/Resources"
    if [ ! -d "${resource_root}" ]; then
        return
    fi
    local removed=0
    while IFS= read -r -d '' path; do
        case "${path}" in
            *.bundle/*)
                rm -rf "${path}" 2>/dev/null || true
                removed=$((removed + 1))
                ;;
        esac
    done < <(find "${resource_root}" -type d \( -name "Python.framework" -o -name "python_site" \) -print0 2>/dev/null)
    if [ "${removed}" -gt 0 ]; then
        echo -e "${BLUE}==>${NC} Removed ${removed} nested runtime directories from Swift resource bundles"
    fi
}

validate_resource_bundle_runtimes() {
    local resource_root="${APP_BUNDLE}/Contents/Resources"
    if [ ! -d "${resource_root}" ]; then
        return
    fi
    local leftovers=0
    while IFS= read -r -d '' path; do
        case "${path}" in
            *.bundle/*)
                echo -e "${RED}❌ Nested runtime remains inside resource bundle: ${path}${NC}"
                leftovers=$((leftovers + 1))
                ;;
        esac
    done < <(find "${resource_root}" -type d \( -name "Python.framework" -o -name "python_site" \) -print0 2>/dev/null)
    if [ "${leftovers}" -gt 0 ]; then
        exit 1
    fi
}

verify_python_repo_sync() {
    local repo_root="$1"
    local source_root="$2"
    local repo_pkg="${repo_root}"
    local source_pkg="${source_root}/marcut"

    if [ -d "${repo_root}/marcut" ]; then
        repo_pkg="${repo_root}/marcut"
    fi

    if [ ! -d "${repo_pkg}" ] || [ ! -d "${source_pkg}" ]; then
        echo -e "${RED}❌ python_site source verification failed: missing repo/source package${NC}"
        echo "   repo: ${repo_pkg}"
        echo "   source: ${source_pkg}"
        exit 1
    fi

    local checked_count=0
    local missing_count=0
    local mismatch_count=0

    while IFS= read -r -d '' repo_file; do
        checked_count=$((checked_count + 1))
        local rel_path="${repo_file#${repo_pkg}/}"
        local source_file="${source_pkg}/${rel_path}"
        if [ ! -f "${source_file}" ]; then
            missing_count=$((missing_count + 1))
            if [ "${missing_count}" -le 10 ]; then
                echo -e "${RED}❌ python_site source missing file: marcut/${rel_path}${NC}"
            fi
            continue
        fi
        local repo_hash source_hash
        repo_hash="$(shasum -a 256 "${repo_file}" | awk '{print $1}')"
        source_hash="$(shasum -a 256 "${source_file}" | awk '{print $1}')"
        if [ "${repo_hash}" != "${source_hash}" ]; then
            mismatch_count=$((mismatch_count + 1))
            if [ "${mismatch_count}" -le 10 ]; then
                echo -e "${RED}❌ python_site source stale mismatch: marcut/${rel_path}${NC}"
            fi
        fi
    done < <(find "${repo_pkg}" -type f \( -name "*.py" -o -name "*.txt" \) -print0 2>/dev/null)

    if [ "${checked_count}" -eq 0 ]; then
        echo -e "${RED}❌ python_site source verification failed: no repo files found under ${repo_pkg}${NC}"
        exit 1
    fi

    if [ "${missing_count}" -gt 0 ] || [ "${mismatch_count}" -gt 0 ]; then
        echo -e "${RED}❌ python_site source verification failed (${missing_count} missing, ${mismatch_count} mismatched).${NC}"
        exit 1
    fi

    echo -e "${GREEN}✅ python_site source verified against repo (${checked_count} files matched)${NC}"
}

verify_python_site_source_sync() {
    local src_root="$1"
    local dst_root="$2"
    local src_pkg="${src_root}/marcut"
    local dst_pkg="${dst_root}/marcut"

    if [ ! -d "${src_pkg}" ] || [ ! -d "${dst_pkg}" ]; then
        echo -e "${RED}❌ python_site verification failed: source or destination marcut package missing${NC}"
        echo "   source: ${src_pkg}"
        echo "   destination: ${dst_pkg}"
        exit 1
    fi

    local checked_count=0
    local missing_count=0
    local mismatch_count=0

    while IFS= read -r -d '' src_file; do
        checked_count=$((checked_count + 1))
        local rel_path="${src_file#${src_pkg}/}"
        local dst_file="${dst_pkg}/${rel_path}"
        if [ ! -f "${dst_file}" ]; then
            missing_count=$((missing_count + 1))
            if [ "${missing_count}" -le 10 ]; then
                echo -e "${RED}❌ Missing packaged file: marcut/${rel_path}${NC}"
            fi
            continue
        fi
        local src_hash dst_hash
        src_hash="$(shasum -a 256 "${src_file}" | awk '{print $1}')"
        dst_hash="$(shasum -a 256 "${dst_file}" | awk '{print $1}')"
        if [ "${src_hash}" != "${dst_hash}" ]; then
            mismatch_count=$((mismatch_count + 1))
            if [ "${mismatch_count}" -le 10 ]; then
                echo -e "${RED}❌ Stale packaged file mismatch: marcut/${rel_path}${NC}"
            fi
        fi
    done < <(find "${src_pkg}" -type f \( -name "*.py" -o -name "*.txt" \) -print0 2>/dev/null)

    if [ "${checked_count}" -eq 0 ]; then
        echo -e "${RED}❌ python_site verification failed: no source files found under ${src_pkg}${NC}"
        exit 1
    fi

    if [ "${missing_count}" -gt 0 ] || [ "${mismatch_count}" -gt 0 ]; then
        echo -e "${RED}❌ python_site verification failed (${missing_count} missing, ${mismatch_count} mismatched).${NC}"
        exit 1
    fi

    echo -e "${GREEN}✅ python_site marcut package verified (${checked_count} files matched source)${NC}"
}

step_label() {
    case "$1" in
        cleanup) echo "Step 1: Comprehensive Cleanup" ;;
        refresh_python) echo "Step 2: Refresh Python Payload" ;;
        build_swift) echo "Step 3: Build Swift App" ;;
        verify_build) echo "Step 4: Build Verification" ;;
        assemble_bundle) echo "Step 5: Create App Bundle & Embed Runtimes" ;;
        sign_components) echo "Step 6: Sign App Components" ;;
        testing_cleanup) echo "Step 6.5: Reset App Data (Fresh-Install Simulation)" ;;
        functional_verification) echo "Step 7: Post-Build Functional Verification" ;;
        create_dmg) echo "Step 8: Create Final DMG" ;;
        *) echo "$1" ;;
    esac
}

ensure_homebrew_python() {
    if [ -n "${HOMEBREW_PYTHON}" ] && [ -x "${HOMEBREW_PYTHON}" ]; then
        local py_dir
        py_dir=$(dirname "${HOMEBREW_PYTHON}")
        if [[ ":$PATH:" != *":${py_dir}:"* ]]; then
            export PATH="${py_dir}:$PATH"
        fi
    fi
}

ensure_required_path() {
    local path="$1"
    if [ ! -e "$path" ]; then
        echo -e "${RED}❌ Required path missing: ${path}${NC}"
        exit 1
    fi
}

sync_rule_assets() {
    local root_file=""
    local dest_py="${SWIFT_PROJECT_DIR}/Sources/MarcutApp/python_site/marcut/excluded-words.txt"
    local dest_resources="${SWIFT_PROJECT_DIR}/Sources/MarcutApp/Resources/excluded-words.txt"
    local system_prompt_source=""
    local dest_system_prompt="${SWIFT_PROJECT_DIR}/Sources/MarcutApp/Resources/system-prompt.txt"

    for candidate in "assets/excluded-words.txt" "src/python/marcut/excluded-words.txt" "excluded-words.txt"; do
        if [ -f "$candidate" ]; then
            root_file="$candidate"
            break
        fi
    done

    if [ -z "$root_file" ]; then
        echo -e "${RED}❌ Cannot find excluded-words.txt (checked assets/ and src/python/marcut)${NC}"
        exit 1
    fi

    mkdir -p "$(dirname "$dest_py")" "$(dirname "$dest_resources")"
    rsync -a "$root_file" "$dest_py"
    rsync -a "$root_file" "$dest_resources"

    for candidate in "assets/system-prompt.txt" "system-prompt.txt"; do
        if [ -f "$candidate" ]; then
            system_prompt_source="$candidate"
            break
        fi
    done

    if [ -z "$system_prompt_source" ]; then
        echo -e "${RED}❌ Cannot find system-prompt.txt (checked assets/)${NC}"
        exit 1
    fi

    rsync -a "$system_prompt_source" "$dest_system_prompt"
    echo -e "${BLUE}🔄 Synced excluded-words + system-prompt assets into app resources${NC}"
}

step_cleanup() {
    log_step "Cleaning Python, Swift, and build caches"
    local swiftpm_cache_dir="${SWIFT_PROJECT_DIR}/.build"
    local swift_python_site="${SWIFT_PROJECT_DIR}/Sources/MarcutApp/python_site"
    SWIFTPM_CACHE_DIR="${swiftpm_cache_dir}" SWIFT_PYTHON_SITE="${swift_python_site}" python3 - <<'PY'
import pathlib
import shutil
import subprocess
import os

paths_to_remove = [
    "build_swift",
    "dist",
    "build",
    "build_cache",
    "build_swift_only.dSYM",
    "test_output",
    "test-output"
]

swiftpm_cache_dir = os.environ.get("SWIFTPM_CACHE_DIR", "")
if swiftpm_cache_dir:
    paths_to_remove.append(swiftpm_cache_dir)

for path_str in [p for p in paths_to_remove if p]:
    path = pathlib.Path(path_str)
    shutil.rmtree(path, ignore_errors=True)

try:
    subprocess.run(["swift", "package", "purge"], check=False, capture_output=True)
except Exception:
    pass

def clean_bytecode(root):
    root_path = pathlib.Path(root)
    if not root_path.exists():
        return
    for cache_dir in root_path.rglob("__pycache__"):
        shutil.rmtree(cache_dir, ignore_errors=True)
    for pyc in root_path.rglob("*.pyc"):
        pyc.unlink(missing_ok=True)

clean_bytecode(os.environ.get("SWIFT_PYTHON_SITE", ""))
PY

    echo -e "${BLUE}Removing DerivedData and SwiftPM caches...${NC}"
    rm -rf "${BUILD_DIR}" "${SWIFT_PROJECT_DIR}/.build" dist build *.dmg || true
    if [ -d "$HOME/Library/Developer/Xcode/DerivedData" ]; then
        find "$HOME/Library/Developer/Xcode/DerivedData" -name "*MarcutApp*" -type d -exec rm -rf {} + 2>/dev/null || true
    fi
    rm -rf "$HOME/Library/Caches/org.swift.swiftpm" 2>/dev/null || true
}

step_refresh_python_payload() {
    ensure_homebrew_python

    if [ ! -x "${SETUP_SCRIPT}" ]; then
        echo -e "${RED}❌ setup script not found or not executable: ${SETUP_SCRIPT}${NC}"
        exit 1
    fi

    if [ "${SKIP_PY_RUNTIME_REFRESH:-0}" = "1" ]; then
        echo -e "${YELLOW}⚠️  SKIP_PY_RUNTIME_REFRESH=1 – reusing existing BeeWare runtime${NC}"
        ensure_required_path "${PYTHON_FRAMEWORK_SOURCE}"
        ensure_required_path "${PYTHON_SITE_SOURCE}"
        return
    fi

    log_step "Provisioning BeeWare Python framework"
    "${SETUP_SCRIPT}"

    ensure_required_path "${PYTHON_FRAMEWORK_SOURCE}"
    ensure_required_path "${PYTHON_SITE_SOURCE}"
    log_step "Python runtime refreshed via ${SETUP_SCRIPT}"
}

step_build_swift() {
    log_step "Building Swift targets"
    if [ -f "${REPO_ROOT}/scripts/render_help_html.py" ]; then
        python3 "${REPO_ROOT}/scripts/render_help_html.py"
    fi
    sync_rule_assets
    mkdir -p "${BUILD_DIR}"
    pushd "${SWIFT_PROJECT_DIR}" >/dev/null
    swift build --configuration debug --arch arm64 --build-path "${SWIFT_BUILD_DIR}"
    popd >/dev/null
}

step_verify_build() {
    log_step "Verifying compiled binary"
    if [ ! -f "${SWIFT_BINARY_PATH}" ]; then
        echo -e "${RED}❌ Swift binary not found at ${SWIFT_BINARY_PATH}${NC}"
        exit 1
    fi

    if grep -a -q "PK_SANITIZE_ENV_UNSET" "${SWIFT_BINARY_PATH}"; then
        echo -e "${GREEN}✅ Deadlock fix verified - environment sanitization marker present${NC}"
    else
        echo -e "${YELLOW}⚠️  Deadlock fix marker not found in binary${NC}"
    fi

    if grep -a -q "PK_FRAMEWORK_FOUND" "${SWIFT_BINARY_PATH}"; then
        echo -e "${GREEN}✅ Diagnostic logging verified${NC}"
    else
        echo -e "${YELLOW}⚠️  Diagnostic logging marker not found${NC}"
    fi
}

step_assemble_bundle() {
    log_step "Creating app bundle structure"
    mkdir -p "${APP_BUNDLE}/Contents/MacOS"
    mkdir -p "${APP_BUNDLE}/Contents/Resources"
    mkdir -p "${APP_BUNDLE}/Contents/Frameworks"

    cp "${SWIFT_BINARY_PATH}" "${APP_BUNDLE}/Contents/MacOS/${APP_NAME}"
    chmod +x "${APP_BUNDLE}/Contents/MacOS/${APP_NAME}"

    if command -v otool >/dev/null 2>&1; then
        if ! otool -l "${APP_BUNDLE}/Contents/MacOS/${APP_NAME}" 2>/dev/null | grep -q "@executable_path/../Frameworks"; then
            install_name_tool -add_rpath "@executable_path/../Frameworks" "${APP_BUNDLE}/Contents/MacOS/${APP_NAME}"
        fi
    else
        install_name_tool -add_rpath "@executable_path/../Frameworks" "${APP_BUNDLE}/Contents/MacOS/${APP_NAME}"
    fi

    if [ -d "${SWIFT_RESOURCE_BUNDLE}" ]; then
        rsync -a --delete "${SWIFT_RESOURCE_BUNDLE}" "${APP_BUNDLE}/Contents/Resources/"
        prune_resource_bundle_runtimes
        validate_resource_bundle_runtimes
    fi

    log_step "Embedding Python runtime"
    rsync -a --delete "${PYTHON_FRAMEWORK_SOURCE}" "${APP_BUNDLE}/Contents/Frameworks/"
    mkdir -p "${APP_BUNDLE}/Contents/Resources/python_site"
    verify_python_repo_sync "${PYTHON_SITE_REPO_SOURCE}" "${PYTHON_SITE_SOURCE}"
    rsync -a --delete "${PYTHON_SITE_SOURCE}/" "${APP_BUNDLE}/Contents/Resources/python_site/"
    verify_python_site_source_sync "${PYTHON_SITE_SOURCE}" "${APP_BUNDLE}/Contents/Resources/python_site"

    log_step "Pruning Tk/Tcl artifacts from embedded Python payload"
    prune_tk_artifacts "${APP_BUNDLE}/Contents/Frameworks/Python.framework"
    prune_tk_artifacts "${APP_BUNDLE}/Contents/Resources/python_site"

    if [ -n "${RUN_PYTHON_LAUNCHER}" ] && [ -f "${RUN_PYTHON_LAUNCHER}" ]; then
        cp "${RUN_PYTHON_LAUNCHER}" "${APP_BUNDLE}/Contents/Resources/run_python.sh"
        chmod +x "${APP_BUNDLE}/Contents/Resources/run_python.sh"
    fi

    local cli_launcher="${SWIFT_PROJECT_DIR}/Contents/Resources/marcut_cli_launcher.sh"
    if [ -f "${cli_launcher}" ]; then
        cp "${cli_launcher}" "${APP_BUNDLE}/Contents/Resources/marcut_cli_launcher.sh"
        chmod +x "${APP_BUNDLE}/Contents/Resources/marcut_cli_launcher.sh"
    fi

    if command -v clang >/dev/null 2>&1 && [ -n "${PYTHON_STUB_SOURCE}" ] && [ -f "${PYTHON_STUB_SOURCE}" ]; then
        cat > "${APP_BUNDLE}/Contents/Resources/python_embed_stub_patched.c" <<'EOF'
#include <Python.h>
#include <stdio.h>
#include <dlfcn.h>
#include <libgen.h>
#include <string.h>
#include <mach-o/dyld.h>
#include <wchar.h>

static void handle_status(PyStatus status, PyConfig *config) {
    if (PyStatus_Exception(status)) {
        if (config != NULL) {
            PyConfig_Clear(config);
        }
        Py_ExitStatusException(status);
    }
}

static void append_path(PyConfig *config, const char *path) {
    wchar_t *wpath = Py_DecodeLocale(path, NULL);
    if (!wpath) {
        return;
    }
    PyWideStringList_Append(&config->module_search_paths, wpath);
    PyMem_RawFree(wpath);
}

int main(int argc, char *argv[]) {
    PyConfig config;
    PyStatus status;
    int exit_code;
    char python_path[PATH_MAX];
    char python_home[PATH_MAX];
    char python_site_path[PATH_MAX];
    char python_lib_path[PATH_MAX];
    char python_dynload_path[PATH_MAX];
    char python_sitepackages_path[PATH_MAX];
    char program_name[PATH_MAX];
    char executable_path[PATH_MAX];
    uint32_t exec_size = sizeof(executable_path);

    if (_NSGetExecutablePath(executable_path, &exec_size) != 0) {
        fprintf(stderr, "Failed to get executable path\n");
        return 1;
    }

    char *app_dir = dirname(executable_path);
    char *contents_dir = dirname(app_dir);

    snprintf(python_home, sizeof(python_home), "%s/Frameworks/Python.framework/Versions/3.11", contents_dir);
    snprintf(program_name, sizeof(program_name), "%s/Frameworks/Python.framework/Versions/3.11/bin/python3", contents_dir);
    snprintf(python_path, sizeof(python_path), "%s/Resources/python_site:%s/lib/python3.11:%s/lib/python3.11/lib-dynload",
             contents_dir, python_home, python_home);
    snprintf(python_site_path, sizeof(python_site_path), "%s/Resources/python_site", contents_dir);
    snprintf(python_lib_path, sizeof(python_lib_path), "%s/lib/python3.11", python_home);
    snprintf(python_dynload_path, sizeof(python_dynload_path), "%s/lib/python3.11/lib-dynload", python_home);
    snprintf(python_sitepackages_path, sizeof(python_sitepackages_path), "%s/lib/python3.11/site-packages", python_home);

    PyConfig_InitPythonConfig(&config);
    config.module_search_paths_set = 1;
    append_path(&config, python_site_path);
    append_path(&config, python_lib_path);
    append_path(&config, python_dynload_path);
    append_path(&config, python_sitepackages_path);

    status = PyConfig_SetBytesString(&config, &config.program_name, program_name);
    handle_status(status, &config);

    status = PyConfig_SetBytesString(&config, &config.home, python_home);
    handle_status(status, &config);

    status = PyConfig_SetBytesString(&config, &config.pythonpath_env, python_path);
    handle_status(status, &config);

    config.isolated = 1;
    config.use_environment = 0;
    config.configure_c_stdio = 0;
    config.buffered_stdio = 0;

    status = PyConfig_SetBytesArgv(&config, argc, argv);
    handle_status(status, &config);

    status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    handle_status(status, NULL);

    exit_code = Py_RunMain();
    return exit_code;
}
EOF

        clang -arch arm64 -arch x86_64 \
            -F "${PYTHON_FRAMEWORK_DEST%/Python.framework}" \
            -I "${PYTHON_FRAMEWORK_DEST}/Headers" \
            -I "${PYTHON_FRAMEWORK_DEST}/Versions/3.11/include" \
            -framework Python \
            -Wl,-rpath,@executable_path/../Frameworks \
            -o "${APP_BUNDLE}/Contents/Resources/python3_embed" \
            "${APP_BUNDLE}/Contents/Resources/python_embed_stub_patched.c" || {
                echo -e "${YELLOW}⚠️  Failed to compile python3_embed stub${NC}"
            }
        rm -f "${APP_BUNDLE}/Contents/Resources/python_embed_stub_patched.c"
        chmod +x "${APP_BUNDLE}/Contents/Resources/python3_embed" 2>/dev/null || true
    else
        echo -e "${YELLOW}⚠️  clang or python stub missing; python3_embed stub not built${NC}"
    fi

    cat > "${APP_BUNDLE}/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key><string>${APP_NAME}</string>
    <key>CFBundleIdentifier</key><string>${BUNDLE_ID}</string>
    <key>CFBundleName</key><string>${APP_NAME}</string>
    <key>CFBundleDisplayName</key><string>Marcut</string>
    <key>CFBundleVersion</key><string>${BUILD_NUMBER}</string>
    <key>CFBundleShortVersionString</key><string>${VERSION}</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>LSMinimumSystemVersion</key><string>14.0</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>LSApplicationCategoryType</key><string>public.app-category.productivity</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
</dict>
</plist>
EOF

    local app_icon_source=""
    for candidate in "${REPO_ROOT}/assets/AppIcon.icns" "${REPO_ROOT}/assets/MarcutApp.icns" "${REPO_ROOT}/assets/MarcutApp-Icon.icns"; do
        if [ -f "$candidate" ]; then
            app_icon_source="$candidate"
            break
        fi
    done

    if [ -n "${app_icon_source}" ]; then
        cp "${app_icon_source}" "${APP_BUNDLE}/Contents/Resources/AppIcon.icns"
    elif [ -f "${REPO_ROOT}/assets/MarcutApp-Icon.png" ]; then
        mkdir -p "AppIcon.iconset"
        sips -z 1024 1024 "${REPO_ROOT}/assets/MarcutApp-Icon.png" --out "AppIcon.iconset/icon_512x512@2x.png" >/dev/null 2>&1
        iconutil -c icns "AppIcon.iconset" -o "${APP_BUNDLE}/Contents/Resources/AppIcon.icns"
        rm -rf "AppIcon.iconset"
    fi

    if [ -n "${OLLAMA_BINARY}" ] && [ -x "${OLLAMA_BINARY}" ]; then
        local helper_bundle="${APP_BUNDLE}/Contents/Resources/Ollama.app"
        local helper_macos="${helper_bundle}/Contents/MacOS"
        local helper_info="${helper_bundle}/Contents/Info.plist"

        rm -rf "${helper_bundle}"
        mkdir -p "${helper_macos}"
        cp "${OLLAMA_BINARY}" "${helper_macos}/ollama"
        chmod +x "${helper_macos}/ollama"

        if [ -n "${OLLAMA_HELPER_INFO}" ] && [ -f "${OLLAMA_HELPER_INFO}" ]; then
            cp "${OLLAMA_HELPER_INFO}" "${helper_info}"
        else
            cat > "${helper_info}" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>com.marclaw.marcutapp.ollama-helper</string>
    <key>CFBundleName</key>
    <string>Ollama Helper</string>
    <key>CFBundleExecutable</key>
    <string>ollama</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>BNDL</string>
</dict>
</plist>
EOF
        fi

        ln -fsh "Ollama.app/Contents/MacOS/ollama" "${APP_BUNDLE}/Contents/Resources/ollama"
    fi

    # Ensure Finder shows the bundle as freshly updated
    touch -c "${APP_BUNDLE}" "${APP_BUNDLE}/Contents" "${APP_BUNDLE}/Contents/MacOS" "${APP_BUNDLE}/Contents/Resources"
}

step_sign_components() {
    log_step "Signing app components"

    sign_with_id() {
        local target="$1"
        if [ -z "$target" ] || [ ! -e "$target" ]; then
            return 0
        fi
        if [ "${SIGN_IDENTITY}" = "-" ] || [ -z "${SIGN_IDENTITY}" ]; then
            codesign --force --sign "${SIGN_IDENTITY}" "$target"
        else
            codesign --force --sign "${SIGN_IDENTITY}" --timestamp --options runtime "$target"
        fi
    }

    ENTITLEMENTS_CANDIDATES=(
        "${SWIFT_PROJECT_DIR}/MarcutApp.entitlements"
        "${REPO_ROOT}/src/swift/MarcutApp/MarcutApp.entitlements"
        "MarcutApp.entitlements"
        "Marcut.entitlements"
    )

    ENTITLEMENTS_FILE=""
    for candidate in "${ENTITLEMENTS_CANDIDATES[@]}"; do
        if [ -f "${candidate}" ]; then
            ENTITLEMENTS_FILE="${candidate}"
            break
        fi
    done

    if [ -z "${ENTITLEMENTS_FILE}" ]; then
        echo -e "${RED}❌ Unable to locate main entitlements file${NC}"
        exit 1
    fi

    if [ ! -f "${OLLAMA_ENTITLEMENTS}" ]; then
        echo -e "${RED}❌ Ollama entitlements file missing: ${OLLAMA_ENTITLEMENTS}${NC}"
        exit 1
    fi

    if [ -f "${APP_BUNDLE}/Contents/Resources/Ollama.app/Contents/MacOS/ollama" ]; then
        codesign --force --sign "${SIGN_IDENTITY}" --timestamp --options runtime \
            --entitlements "${OLLAMA_ENTITLEMENTS}" \
            "${APP_BUNDLE}/Contents/Resources/Ollama.app/Contents/MacOS/ollama"
        sign_with_id "${APP_BUNDLE}/Contents/Resources/Ollama.app"
    fi

    if [ -d "${APP_BUNDLE}/Contents/Frameworks" ]; then
        while IFS= read -r f; do sign_with_id "$f" || true; done < <(
            find "${APP_BUNDLE}/Contents/Frameworks" -type f \( -name "*.dylib" -o -name "*.so" -o -name "*.o" -o -perm -111 \) 2>/dev/null
        )
        for fw in "${APP_BUNDLE}/Contents/Frameworks"/*.framework; do
            [ -d "$fw" ] && sign_with_id "$fw" || true
        done
    fi

    if [ -d "${APP_BUNDLE}/Contents/Resources/python_site" ]; then
        while IFS= read -r f; do sign_with_id "$f" || true; done < <(
            find "${APP_BUNDLE}/Contents/Resources/python_site" -type f \( -name "*.dylib" -o -name "*.so" -o -name "*.o" -o -perm -111 \) 2>/dev/null
        )
    fi

    sign_with_id "${APP_BUNDLE}/Contents/MacOS/${APP_NAME}"

    if [ "${SIGN_IDENTITY}" = "-" ] || [ -z "${SIGN_IDENTITY}" ]; then
        codesign --force --sign "${SIGN_IDENTITY}" \
            --entitlements "${ENTITLEMENTS_FILE}" \
            "${APP_BUNDLE}"
    else
        codesign --force --sign "${SIGN_IDENTITY}" --timestamp --options runtime \
            --entitlements "${ENTITLEMENTS_FILE}" \
            "${APP_BUNDLE}"
    fi

    # Refresh top-level bundle timestamp after signing
    touch -c "${APP_BUNDLE}"
}

step_testing_cleanup() {
    log_step "Resetting app data for fresh-install simulation"

    # Kill any existing MarcutApp processes
    if pgrep -f "${APP_NAME}" >/dev/null; then
        echo -e "${YELLOW}🔄 Terminating existing MarcutApp processes${NC}"
        pkill -f "${APP_NAME}" || true
        sleep 2
    fi

    # Clear permission-related UserDefaults for fresh testing
    echo -e "${BLUE}🗑️  Clearing permission-related UserDefaults for testing${NC}"
    defaults delete "${BUNDLE_ID}" 2>/dev/null || true

    # Clear temporary files and caches
    echo -e "${BLUE}🗑️  Clearing temporary files and caches${NC}"
    rm -rf "$HOME/Library/Application Support/${APP_NAME}"/* 2>/dev/null || true
    rm -rf "$HOME/Library/Caches/${BUNDLE_ID}"/* 2>/dev/null || true
    rm -rf "/tmp/marcut-"* 2>/dev/null || true
    rm -rf /var/folders/*/C/com.apple.QuickLook.thumbnailcache*/*marcut* 2>/dev/null || true

    # Clear sandbox container data (App Store build path)
    local container_root="$HOME/Library/Containers/${BUNDLE_ID}/Data"
    if [ -d "${container_root}" ]; then
        echo -e "${BLUE}🗑️  Clearing sandbox container data${NC}"
        rm -rf "${container_root}/Library/Application Support/${APP_NAME}" 2>/dev/null || true
        rm -rf "${container_root}/Library/Caches"/* 2>/dev/null || true
        rm -rf "${container_root}/tmp"/* 2>/dev/null || true
        rm -f "${container_root}/Library/Preferences/${BUNDLE_ID}.plist" 2>/dev/null || true
    fi

    # Reset sandbox quarantine attributes (makes macOS treat it as "fresh" for permissions)
    if [ -d "${APP_BUNDLE}" ]; then
        echo -e "${BLUE}🔄 Resetting quarantine attributes for testing${NC}"
        xattr -d com.apple.quarantine "${APP_BUNDLE}" 2>/dev/null || true
        xattr -d com.apple.quarantine "${APP_BUNDLE}/Contents/MacOS/${APP_NAME}" 2>/dev/null || true
    fi

    echo -e "${GREEN}✅ Testing environment cleaned - ready for fresh permission testing${NC}"
    echo -e "${YELLOW}💡 Note: Launch the app immediately after build for clean permission testing${NC}"
}

step_functional_verification() {
    log_step "Running functional smoke tests"

    if ! run_with_timeout 10 "${APP_BUNDLE}/Contents/MacOS/${APP_NAME}" --help >/dev/null 2>&1; then
        echo -e "${YELLOW}⚠️  App help command failed or timed out${NC}"
    else
        echo -e "${GREEN}✅ App help command ok${NC}"
    fi

    if ! run_with_timeout 15 "${APP_BUNDLE}/Contents/MacOS/${APP_NAME}" --diagnose >/dev/null 2>&1; then
        echo -e "${YELLOW}⚠️  App diagnostic mode failed or timed out${NC}"
    else
        echo -e "${GREEN}✅ App diagnostic mode ok${NC}"
    fi

    if ! run_with_timeout 5 "${APP_BUNDLE}/Contents/MacOS/${APP_NAME}" --cli --help 2>&1 | grep -q "MarcutApp CLI Mode"; then
        echo -e "${YELLOW}⚠️  Python initialization check failed${NC}"
    else
        echo -e "${GREEN}✅ Python initialization check ok${NC}"
    fi
}

step_create_dmg() {
    log_step "Creating distributable DMG"
    local plist="${APP_BUNDLE}/Contents/Info.plist"
    local short_version="${VERSION}"
    local build_version="${BUILD_NUMBER}"
    if [ -f "${plist}" ]; then
        local plist_short
        plist_short="$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "${plist}" 2>/dev/null || true)"
        if [ -n "${plist_short}" ]; then
            short_version="${plist_short}"
        fi
        local plist_build
        plist_build="$(/usr/libexec/PlistBuddy -c "Print :CFBundleVersion" "${plist}" 2>/dev/null || true)"
        if [ -n "${plist_build}" ]; then
            build_version="${plist_build}"
        fi
    fi

    local dmg_version="${short_version}"
    if [ -n "${build_version}" ] && [ "${build_version}" != "${short_version}" ]; then
        echo -e "${YELLOW}⚠️  CFBundleShortVersionString (${short_version}) and CFBundleVersion (${build_version}) differ; using ${short_version} for DMG naming.${NC}"
    fi

    local final_dmg="${FINAL_DMG}"
    if [ -n "${final_dmg}" ]; then
        local replaced="${final_dmg//$VERSION/$dmg_version}"
        if [ "${replaced}" != "${final_dmg}" ]; then
            final_dmg="${replaced}"
        else
            local final_dir
            final_dir="$(dirname "${final_dmg}")"
            final_dmg="${final_dir}/${APP_NAME}-Swift-${dmg_version}.dmg"
        fi
    else
        final_dmg="${OUTPUT_ROOT}/${APP_NAME}-Swift-${dmg_version}.dmg"
    fi

    FINAL_DMG="${final_dmg}"
    rm -f "${FINAL_DMG}"

    local staging_dir
    staging_dir="$(mktemp -d "${OUTPUT_ROOT}/dmg_stage.XXXX")"
    local temp_dmg="${FINAL_DMG%.dmg}-temp.dmg"
    rm -f "${temp_dmg}"

    ditto "${APP_BUNDLE}" "${staging_dir}/${APP_NAME}.app"
    ln -s /Applications "${staging_dir}/Applications"

    if ! hdiutil create -volname "${APP_NAME}" -srcfolder "${staging_dir}" -ov -format UDRW "${temp_dmg}"; then
        echo -e "${RED}❌ Failed to create staging DMG at ${temp_dmg}${NC}"
        rm -rf "${staging_dir}"
        exit 1
    fi

    local volume_mount="/Volumes/${APP_NAME}"
    if [ -d "${volume_mount}" ]; then
        hdiutil detach "${volume_mount}" >/dev/null 2>&1 || true
        sleep 1
    fi

    local attach_output
    attach_output="$(hdiutil attach -readwrite -owners on -noverify -noautoopen "${temp_dmg}")"
    local mount_dir
    mount_dir="$(echo "${attach_output}" | awk 'END {print $3}')"
    if [ -n "${mount_dir}" ] && [ -d "${mount_dir}" ]; then
        if ! touch "${mount_dir}/.write_test" 2>/dev/null; then
            hdiutil detach "${mount_dir}" >/dev/null 2>&1 || true
            local shadow_file="${temp_dmg}.shadow"
            rm -f "${shadow_file}"
            attach_output="$(hdiutil attach -readwrite -owners on -noverify -noautoopen -shadow "${shadow_file}" "${temp_dmg}")"
            mount_dir="$(echo "${attach_output}" | awk 'END {print $3}')"
        else
            rm -f "${mount_dir}/.write_test"
        fi
    fi

    if [ -z "${mount_dir}" ] || [ ! -d "${mount_dir}" ]; then
        echo -e "${RED}❌ Failed to mount DMG for customization${NC}"
        rm -f "${temp_dmg}"
        rm -rf "${staging_dir}"
        exit 1
    fi

    local volume_name
    volume_name="$(basename "${mount_dir}")"

    if [ -n "${mount_dir}" ] && [ -d "${mount_dir}" ]; then
        mkdir -p "${mount_dir}/.background"
        if [ -f "${REPO_ROOT}/assets/dmg-background.png" ]; then
            # Finder renders DMG backgrounds in point space; downscale retina assets
            # so the full composition is visible at the configured window size.
            if command -v sips >/dev/null 2>&1; then
                sips -z 520 800 "${REPO_ROOT}/assets/dmg-background.png" \
                    --out "${mount_dir}/.background/dmg-background.png" >/dev/null 2>&1 \
                    || cp "${REPO_ROOT}/assets/dmg-background.png" "${mount_dir}/.background/"
            else
                cp "${REPO_ROOT}/assets/dmg-background.png" "${mount_dir}/.background/"
            fi
        fi

        if ! /usr/bin/osascript <<EOF
tell application "Finder"
    tell disk "${volume_name}"
        open
        set current view of container window to icon view
        set toolbar visible of container window to false
        set statusbar visible of container window to false
        try
            set pathbar visible of container window to false
        end try
        set the bounds of container window to {100, 100, 900, 620}
        set viewOptions to the icon view options of container window
        set arrangement of viewOptions to not arranged
        set icon size of viewOptions to 120
        set text size of viewOptions to 14
        try
            set background picture of viewOptions to file ".background:dmg-background.png"
        end try
        try
            set position of item "${APP_NAME}.app" of container window to {210, 300}
        end try
        try
            set position of item "Applications" of container window to {590, 300}
        end try
        close
        open
        update without registering applications
        delay 1
    end tell
end tell
EOF
        then
            echo -e "${YELLOW}⚠️  DMG layout customization failed; continuing without Finder layout${NC}"
        fi

        sync
        hdiutil detach "${mount_dir}" >/dev/null 2>&1 || true
    fi

    if ! hdiutil convert "${temp_dmg}" -format UDZO -imagekey zlib-level=9 -o "${FINAL_DMG}"; then
        echo -e "${RED}❌ Failed to convert DMG to ${FINAL_DMG}${NC}"
        rm -f "${temp_dmg}"
        rm -f "${temp_dmg}.shadow"
        rm -rf "${staging_dir}"
        exit 1
    fi
    rm -f "${temp_dmg}"
    rm -f "${temp_dmg}.shadow"
    rm -rf "${staging_dir}"

    echo -e "${GREEN}✅ DMG created at ${FINAL_DMG}${NC}"
    if [ "${AUTO_BUMP_NEXT_VERSION}" = "1" ]; then
        bump_version_metadata
    else
        echo -e "${BLUE}==>${NC} Version/build unchanged (set AUTO_BUMP_NEXT_VERSION=1 to auto-bump after packaging)"
    fi
}

bump_version_metadata() {
    if ! command -v python3 >/dev/null 2>&1; then
        echo -e "${YELLOW}⚠️  python3 not available; skipping automatic version bump${NC}"
        return
    fi

    python3 - "$CONFIG_FILE" <<'PY'
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1]).resolve()
try:
    data = json.loads(config_path.read_text())
except Exception as exc:
    print(f"⚠️  Could not read {config_path}: {exc}")
    raise SystemExit(0)

version = data.get("version")
if not isinstance(version, str):
    print("⚠️  Config version missing or invalid; skipping automatic bump")
    raise SystemExit(0)
build_number = data.get("build_number")
if not isinstance(build_number, str):
    build_number = version

parts = version.split(".")
if not parts or not parts[-1].isdigit():
    print(f"⚠️  Version '{version}' does not end with numeric component; skipping bump")
    raise SystemExit(0)

parts[-1] = str(int(parts[-1]) + 1)
new_version = ".".join(parts)
data["version"] = new_version
data["build_number"] = new_version

final_dmg = data.get("final_dmg")
if isinstance(final_dmg, str):
    updated = final_dmg
    if version and version in updated:
        updated = updated.replace(version, new_version, 1)
    elif build_number and build_number in updated:
        updated = updated.replace(build_number, new_version, 1)
    data["final_dmg"] = updated

config_path.write_text(json.dumps(data, indent=4) + "\n")
print(f"✅ Auto-bumped version/build to {new_version} for next build")
PY
}

run_step_internal() {
    case "$1" in
        cleanup) step_cleanup ;;
        refresh_python) step_refresh_python_payload ;;
        build_swift) step_build_swift ;;
        verify_build) step_verify_build ;;
        assemble_bundle) step_assemble_bundle ;;
        sign_components) step_sign_components ;;
        testing_cleanup) step_testing_cleanup ;;
        functional_verification) step_functional_verification ;;
        create_dmg) step_create_dmg ;;
        *)
            echo -e "${RED}❌ Unknown step: $1${NC}"
            exit 1
            ;;
    esac
}

run_steps() {
    for step in "$@"; do
        local label
        label=$(step_label "$step")
        echo -e "${BLUE}----------------------------------------${NC}"
        echo -e "${BLUE}${label}${NC}"
        run_step_internal "$step"
        echo -e "${GREEN}✅ ${label} completed${NC}"
    done
}

run_preset() {
    case "$1" in
        dev_fast)
            SKIP_PY_RUNTIME_REFRESH="${SKIP_PY_RUNTIME_REFRESH:-1}" run_steps build_swift assemble_bundle sign_components
            ;;
        quick_debug)
            run_steps refresh_python build_swift verify_build assemble_bundle sign_components functional_verification
            ;;
        fast_incremental)
            run_steps build_swift verify_build assemble_bundle sign_components
            ;;
        full_release)
            run_steps cleanup refresh_python build_swift verify_build assemble_bundle sign_components functional_verification create_dmg
            ;;
        diagnostics)
            run_steps verify_build functional_verification
            ;;
        clean)
            run_steps cleanup
            ;;
        *)
            echo "Unknown preset: $1" >&2
            exit 1
            ;;
    esac
}

usage() {
    cat <<'EOF'
Usage: build_swift_only.sh <command> [args]

Env:
  AUTO_BUMP_NEXT_VERSION=1   Auto-increment version/build in config after DMG creation (default: off)

Commands:
  preset <dev_fast|quick_debug|fast_incremental|full_release|diagnostics|clean>
  run_steps <step...>     # run steps in order
  run_step <step>         # run single step

Steps:
  cleanup | refresh_python | build_swift | verify_build |
  assemble_bundle | sign_components | functional_verification | create_dmg
EOF
}

main() {
    local command="${1:-preset}"
    case "$command" in
        preset)
            run_preset "${2:-full_release}"
            ;;
        run_steps)
            shift
            if [ "$#" -eq 0 ]; then
                echo "No steps provided" >&2
                exit 1
            fi
            run_steps "$@"
            ;;
        run_step)
            shift
            if [ "$#" -ne 1 ]; then
                echo "run_step requires exactly one step name" >&2
                exit 1
            fi
            run_steps "$1"
            ;;
        *)
            usage
            exit 1
            ;;
    esac
}

main "$@"

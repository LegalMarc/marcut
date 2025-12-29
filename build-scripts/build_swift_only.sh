#!/bin/bash
#
# Orchestrated build pipeline for MarcutApp.
# This script exposes discrete build stages that can be composed by the TUI or run manually.
#
set -euo pipefail

# Ensure we're running from the script's directory (build-scripts/)
# This makes the script self-contained and independent of caller's CWD
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

CONFIG_FILE="${CONFIG_FILE:-./config.json}"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "❌ Missing config file at ${CONFIG_FILE}" >&2
    exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "❌ jq is required to parse ${CONFIG_FILE}" >&2
    exit 1
fi

cfg() {
    jq -r "$1 // empty" "$CONFIG_FILE"
}

APP_NAME=$(cfg '.app_name')
BUNDLE_ID=$(cfg '.bundle_id')
VERSION=$(cfg '.version')
BUILD_NUMBER=$(cfg '.build_number')
BUILD_DIR=$(cfg '.build_dir')
FINAL_DMG=$(cfg '.final_dmg')
PYTHON_FRAMEWORK_SOURCE=$(cfg '.python_framework_source')
PYTHON_SITE_SOURCE=$(cfg '.python_site_source')
PYTHON_SITE_REPO_SOURCE=$(cfg '.python_site_repo_source')
SETUP_SCRIPT=$(cfg '.setup_script')
HOMEBREW_PYTHON=$(cfg '.homebrew_python')
SWIFT_PROJECT_DIR=$(cfg '.swift_project_dir')
SWIFT_BINARY_PATH=$(cfg '.swift_binary_path')
SWIFT_RESOURCE_BUNDLE=$(cfg '.swift_resource_bundle')
RUN_PYTHON_LAUNCHER=$(cfg '.run_python_launcher')
PYTHON_STUB_SOURCE=$(cfg '.python_stub_source')
OLLAMA_BINARY=$(cfg '.ollama_binary')
OLLAMA_HELPER_INFO=$(cfg '.ollama_helper_info')
OLLAMA_ENTITLEMENTS=$(cfg '.ollama_entitlements')
DEVELOPER_ID_IDENTITY=$(cfg '.developer_id_identity')
NOTARIZE_SCRIPT=$(cfg '.notarize_script')
HELPER_ENTITLEMENTS="${SWIFT_PROJECT_DIR}/OllamaHelperService.entitlements"
LAST_DMG_PATH_FILE="${BUILD_DIR}/.last_dmg_path"

APP_BUNDLE="${BUILD_DIR}/${APP_NAME}.app"
PYTHON_FRAMEWORK_DEST="${APP_BUNDLE}/Contents/Frameworks/Python.framework"

GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_step() {
    echo -e "${BLUE}==>${NC} $1"
}

step_label() {
    case "$1" in
        bump_version) echo "Step 0: Bump Patch Version" ;;
        cleanup) echo "Step 1: Comprehensive Cleanup" ;;
        refresh_python) echo "Step 2: Refresh Python Payload" ;;
        build_swift) echo "Step 3: Build Swift App" ;;
        verify_build) echo "Step 4: Build Verification" ;;
        assemble_bundle) echo "Step 5: Create App Bundle & Embed Runtimes" ;;
        bundle_cleanup) echo "Step 5.5: Bundle Bytecode Cleanup" ;;
        sign_components) echo "Step 6: Sign App Components" ;;
        testing_cleanup) echo "Step 6.5: Testing Environment Cleanup" ;;
        bundle_audit) echo "Step 7: Bundle Audit (Gatekeeper + File Checks)" ;;
        functional_verification) echo "Step 8: Post-Build Functional Verification" ;;
        create_dmg) echo "Step 9: Create Final DMG" ;;
        notarize_dmg) echo "Step 10: Notarize & Staple DMG" ;;
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
    # Assets are now in assets/ folder, sources in src/
    local script_dir="$(dirname "$0")"
    local project_root="$(cd "$script_dir/.." && pwd)"
    
    local excluded_file="${project_root}/assets/excluded-words.txt"
    local prompt_file="${project_root}/assets/system-prompt.txt"
    local dest_py="${project_root}/src/swift/MarcutApp/Sources/MarcutApp/python_site/marcut/excluded-words.txt"
    local dest_resources="${project_root}/src/swift/MarcutApp/Sources/MarcutApp/Resources/excluded-words.txt"
    local dest_prompt="${project_root}/src/swift/MarcutApp/Sources/MarcutApp/Resources/system-prompt.txt"
    local dest_pkg="${project_root}/src/swift/MarcutApp/Sources/MarcutApp/python_site/marcut"
    local marcut_src="${project_root}/src/python/marcut"

    if [ ! -f "$excluded_file" ]; then
        echo -e "${RED}❌ Cannot find ${excluded_file}; ensure assets folder exists${NC}"
        exit 1
    fi
    if [ ! -d "$marcut_src" ]; then
        echo -e "${RED}❌ Cannot find marcut package at ${marcut_src}${NC}"
        exit 1
    fi

    mkdir -p "$(dirname "$dest_py")" "$(dirname "$dest_resources")" "$dest_pkg"
    rsync -a "$excluded_file" "$dest_py"
    rsync -a "$excluded_file" "$dest_resources"
    
    # Sync system prompt if it exists
    if [ -f "$prompt_file" ]; then
        rsync -a "$prompt_file" "$dest_prompt"
        echo -e "${BLUE}🔄 Synced system-prompt.txt into app resources${NC}"
    fi
    
    rsync -a --exclude "__pycache__/" --exclude "*.pyc" --exclude "excluded-words.txt" \
        "$marcut_src/" "$dest_pkg/"
    echo -e "${BLUE}🔄 Synced excluded-words payload into app resources${NC}"
    echo -e "${BLUE}🔄 Synced marcut package into app python_site${NC}"
}

sync_help_assets() {
    local script_dir="$(dirname "$0")"
    local project_root="$(cd "$script_dir/.." && pwd)"
    
    local root_help="${project_root}/assets/help.md"
    local dest_help="${project_root}/src/swift/MarcutApp/Sources/MarcutApp/Resources/help.md"

    if [ ! -f "$root_help" ]; then
        echo -e "${YELLOW}WARN: Missing ${root_help}; skipping help sync${NC}"
        return 0
    fi

    mkdir -p "$(dirname "$dest_help")"
    rsync -a "$root_help" "$dest_help"
    echo -e "${BLUE}Synced help content into app resources${NC}"
}

resolve_signing_identity() {
    local identity="${DEVELOPER_ID_IDENTITY:-${SIGN_IDENTITY:-}}"
    if [ -n "${identity}" ]; then
        echo "${identity}"
        return 0
    fi

    local matches=()
    if command -v security >/dev/null 2>&1; then
        while IFS= read -r line; do
            [ -n "${line}" ] && matches+=("${line}")
        done < <(security find-identity -v -p codesigning 2>/dev/null | awk -F'"' '/Developer ID Application/ {print $2}')
    fi

    if [ "${#matches[@]}" -eq 1 ]; then
        echo "${matches[0]}"
        return 0
    fi

    if [ "${#matches[@]}" -gt 1 ]; then
        if [ -t 0 ]; then
            echo -e "${YELLOW}⚠️  Multiple Developer ID Application identities found:${NC}"
            local idx=1
            for candidate in "${matches[@]}"; do
                echo "  ${idx}) ${candidate}"
                idx=$((idx + 1))
            done
            local choice
            read -r -p "Select signing identity (1-${#matches[@]}), or press Enter to abort: " choice
            if [ -z "${choice}" ]; then
                return 1
            fi
            if [[ "${choice}" =~ ^[0-9]+$ ]] && [ "${choice}" -ge 1 ] && [ "${choice}" -le "${#matches[@]}" ]; then
                echo "${matches[$((choice - 1))]}"
                return 0
            fi
            echo -e "${RED}❌ Invalid selection${NC}"
            return 1
        fi

        echo -e "${RED}❌ Multiple Developer ID Application identities found. Set DEVELOPER_ID_IDENTITY or SIGN_IDENTITY to choose.${NC}" >&2
        for candidate in "${matches[@]}"; do
            echo "  ${candidate}" >&2
        done
        return 1
    fi

    if [ -t 0 ]; then
        echo -e "${YELLOW}⚠️  No Developer ID Application identity found in keychain.${NC}"
        read -r -p "Enter Developer ID Application identity to use (or press Enter to abort): " identity
        if [ -n "${identity}" ]; then
            echo "${identity}"
            return 0
        fi
        return 1
    fi

    echo -e "${RED}❌ No Developer ID Application identity found. Install a Developer ID certificate or set DEVELOPER_ID_IDENTITY/SIGN_IDENTITY.${NC}" >&2
    return 1
}

fix_python_site_symlinks() {
    local target="${APP_BUNDLE}/Contents/Resources/python_site"
    if [ ! -d "${target}" ]; then
        echo -e "${YELLOW}⚠️  python_site not found at ${target}; skipping site-packages relink${NC}"
        return 0
    fi

    if ! command -v python3 >/dev/null 2>&1; then
        echo -e "${YELLOW}⚠️  python3 not available; skipping site-packages relink${NC}"
        return 0
    fi

    local relinked=0
    while IFS= read -r -d '' link_path; do
        if [ -L "${link_path}" ]; then
            local link_dir
            link_dir="$(dirname "${link_path}")"
            local rel_target
            rel_target="$(python3 - "${target}" "${link_dir}" <<'PY'
import os
import sys
print(os.path.relpath(sys.argv[1], sys.argv[2]))
PY
)"
            rm -f "${link_path}"
            ln -s "${rel_target}" "${link_path}"
            relinked=1
        fi
    done < <(find "${APP_BUNDLE}" -path "*/Python.framework/Versions/*/lib/python*/site-packages" -print0 2>/dev/null || true)

    if [ "${relinked}" -eq 1 ]; then
        echo -e "${GREEN}✅ Relinked Python.framework site-packages to bundled python_site${NC}"
    fi
}

clean_bundle_python_bytecode() {
    if [ ! -d "${APP_BUNDLE}" ]; then
        echo -e "${YELLOW}⚠️  App bundle not found; skipping bytecode cleanup${NC}"
        return 0
    fi

    local targets=(
        "${APP_BUNDLE}/Contents/Frameworks/Python.framework"
        "${APP_BUNDLE}/Contents/Resources/python_site"
        "${APP_BUNDLE}/Contents/Resources/python_stdlib"
        "${APP_BUNDLE}/Contents/Resources/MarcutApp_MarcutApp.bundle"
    )

    local cleaned=0
    for target in "${targets[@]}"; do
        if [ -d "${target}" ]; then
            find "${target}" -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
            find "${target}" -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete 2>/dev/null || true
            cleaned=1
        fi
    done

    if [ "${cleaned}" -eq 1 ]; then
        echo -e "${GREEN}✅ Removed Python bytecode artifacts from bundle${NC}"
    fi
}

step_bump_version() {
    log_step "Bumping patch version for DMG build"

    if ! command -v python3 >/dev/null 2>&1; then
        echo -e "${YELLOW}⚠️  python3 not available; skipping version bump${NC}"
        return 0
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
    print("⚠️  Config version missing or invalid; skipping version bump")
    raise SystemExit(0)

parts = version.split(".")
if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
    print(f"⚠️  Version '{version}' does not look like MAJOR.MINOR[.PATCH]; skipping bump")
    raise SystemExit(0)

if len(parts) >= 3 and parts[-1].isdigit():
    parts[-1] = str(int(parts[-1]) + 1)
    new_version = ".".join(parts)
else:
    new_version = f"{parts[0]}.{parts[1]}.1"

data["version"] = new_version
data["build_number"] = new_version

final_dmg = data.get("final_dmg")
if isinstance(final_dmg, str):
    data["final_dmg"] = final_dmg.replace(version, new_version, 1)

config_path.write_text(json.dumps(data, indent=4) + "\n")
print(f"✅ Auto-bumped version: {version} → {new_version}")
PY
}

step_cleanup() {
    log_step "Cleaning Python, Swift, and build caches"
    
    # Path calculation relative to script
    local script_dir="$(dirname "$0")"
    local project_root="$(cd "$script_dir/.." && pwd)"
    # Resolve swift project dir relative to root (SWIFT_PROJECT_DIR is ../src/...)
    local swift_dir="${project_root}/src/swift/MarcutApp"

    python3 - <<PY
import pathlib
import shutil
import subprocess

# Paths relative to build-scripts/
paths_to_remove = [
    "../ignored-resources/builds/build_swift",
    "../src/swift/MarcutApp/.build",
    "../dist",
    "../build",
    "../ignored-resources/build_cache",
    "../ignored-resources/test_output"
]

for path_str in paths_to_remove:
    path = pathlib.Path(path_str).resolve()
    if path.exists():
        print(f"Removing {path}")
        shutil.rmtree(path, ignore_errors=True)

# Also clean legacy paths if they exist
legacy_paths = [
    "MarcutApp/.build",
    "build_swift"
]
for path_str in legacy_paths:
    path = pathlib.Path(path_str)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)

def clean_bytecode(root):
    root_path = pathlib.Path(root)
    if not root_path.exists():
        return
    for cache_dir in root_path.rglob("__pycache__"):
        shutil.rmtree(cache_dir, ignore_errors=True)
    for pyc in root_path.rglob("*.pyc"):
        pyc.unlink(missing_ok=True)

clean_bytecode("../src/swift/MarcutApp/Sources/MarcutApp/python_site")
PY

    echo -e "${BLUE}Removing DerivedData and SwiftPM caches...${NC}"
    # Use SWIFT_PROJECT_DIR from config if available, else derive
    if [ -d "${swift_dir}/.build" ]; then
         rm -rf "${swift_dir}/.build"
    fi
    
    # Clean DerivedData
    if [ -d "$HOME/Library/Developer/Xcode/DerivedData" ]; then
        find "$HOME/Library/Developer/Xcode/DerivedData" -name "*MarcutApp*" -type d -exec rm -rf {} + 2>/dev/null || true
    fi
    rm -rf "$HOME/Library/Caches/org.swift.swiftpm" 2>/dev/null || true
}

step_refresh_python_payload() {
    ensure_homebrew_python

    if [ ! -x "${SETUP_SCRIPT}" ]; then
        echo -e "${RED}❌ setup script not found or not executable: ${SETUP_SCRIPT}${NC}"
        echo "Current Directory: $(pwd)"
        echo "Listing:"
        ls -la
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
    sync_rule_assets
    sync_help_assets
    mkdir -p "${BUILD_DIR}"
    pushd "${SWIFT_PROJECT_DIR}" >/dev/null
    local build_log
    build_log=$(mktemp)

    run_swift_build() {
        swift build --configuration debug --arch arm64 2>&1 | tee "$build_log"
        return "${PIPESTATUS[0]}"
    }

    local build_success=0
    local build_attempt=1
    local cleaned_build=0

    while [ "${build_attempt}" -le 3 ]; do
        if run_swift_build; then
            build_success=1
            break
        fi

        if grep -qi "build.db" "$build_log"; then
            if [ "${cleaned_build}" -eq 0 ]; then
                echo -e "${YELLOW}⚠️  Detected Swift build.db corruption. Clearing .build cache and retrying...${NC}"
                rm -rf .build
                cleaned_build=1
            else
                echo -e "${YELLOW}⚠️  build.db error persisted. Resetting SwiftPM caches and retrying...${NC}"
                rm -rf .build
                swift package reset --skip-update >/dev/null 2>&1 || true
                rm -rf "$HOME/Library/Caches/org.swift.swiftpm" 2>/dev/null || true
            fi
        else
            echo -e "${RED}❌ Swift build failed. See ${build_log}${NC}"
            popd >/dev/null
            exit 1
        fi

        build_attempt=$((build_attempt + 1))
    done

    if [ "${build_success}" -ne 1 ]; then
        echo -e "${RED}❌ Swift build failed after recovery attempts. See ${build_log}${NC}"
        popd >/dev/null
        exit 1
    fi

    rm -f "$build_log"
    popd >/dev/null
}

step_verify_build() {
    log_step "Verifying compiled binary"
    if [ ! -f "${SWIFT_BINARY_PATH}" ]; then
        echo -e "${RED}❌ Swift binary not found at ${SWIFT_BINARY_PATH}${NC}"
        exit 1
    fi

    if strings "${SWIFT_BINARY_PATH}" | grep -q "TEMPORARILY COMMENT OUT THESE LINES"; then
        echo -e "${GREEN}✅ Deadlock fix verified - environment variables commented out${NC}"
    else
        echo -e "${YELLOW}⚠️  Deadlock fix marker not found in binary${NC}"
    fi

    if strings "${SWIFT_BINARY_PATH}" | grep -q "PK_FRAMEWORK_SEARCH"; then
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

    # Generate Info.plist
    log_step "Generating Info.plist"
    cat > "${APP_BUNDLE}/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key>
    <string>en</string>
    <key>CFBundleExecutable</key>
    <string>${APP_NAME}</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundleIdentifier</key>
    <string>${BUNDLE_ID}</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleName</key>
    <string>${APP_NAME}</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>${VERSION}</string>
    <key>CFBundleVersion</key>
    <string>${BUILD_NUMBER}</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSPrincipalClass</key>
    <string>NSApplication</string>
</dict>
</plist>
EOF

    # Copy AppIcon
    local script_dir="$(dirname "$0")"
    local project_root="$(cd "$script_dir/.." && pwd)"
    if [ -f "${project_root}/assets/AppIcon.icns" ]; then
         log_step "Copying AppIcon.icns"
         cp "${project_root}/assets/AppIcon.icns" "${APP_BUNDLE}/Contents/Resources/AppIcon.icns"
    else
         echo -e "${YELLOW}⚠️  AppIcon.icns not found in assets/ directory${NC}"
    fi

    cp "${SWIFT_BINARY_PATH}" "${APP_BUNDLE}/Contents/MacOS/${APP_NAME}"
    chmod +x "${APP_BUNDLE}/Contents/MacOS/${APP_NAME}"

    install_name_tool -add_rpath "@executable_path/../Frameworks" "${APP_BUNDLE}/Contents/MacOS/${APP_NAME}"

    if [ -d "${SWIFT_RESOURCE_BUNDLE}" ]; then
        rsync -a --delete "${SWIFT_RESOURCE_BUNDLE}" "${APP_BUNDLE}/Contents/Resources/"

        # Strip duplicate runtimes from the Swift resource bundle to avoid notarization bloat
        local bundle_res="${APP_BUNDLE}/Contents/Resources/MarcutApp_MarcutApp.bundle"
        if [ -d "${bundle_res}" ]; then
            rm -rf "${bundle_res}/Frameworks" \
                   "${bundle_res}/python_site" \
                   "${bundle_res}/python_stdlib" \
                   "${bundle_res}/Resources/python_stdlib" \
                   "${bundle_res}/Resources/ollama_runners" \
                   "${bundle_res}/Resources/python_site"
        fi
    fi

    log_step "Embedding Python runtime"
    local python_current
    if [ -d "${PYTHON_FRAMEWORK_SOURCE}/Versions/3.11" ]; then
        python_current="3.11"
    else
        python_current=$(basename "$(readlink "${PYTHON_FRAMEWORK_SOURCE}/Versions/Current" || true)")
        if [ -z "${python_current}" ]; then
            python_current="3.10"
        fi
    fi

    local python_stage
    python_stage=$(mktemp -d)
    rsync -a --delete "${PYTHON_FRAMEWORK_SOURCE}/" "${python_stage}/Python.framework/"
    if [ -d "${python_stage}/Python.framework/Versions" ]; then
        find "${python_stage}/Python.framework/Versions" -mindepth 1 -maxdepth 1 -type d ! -name "${python_current}" -exec rm -rf {} +
        ln -sfn "${python_current}" "${python_stage}/Python.framework/Versions/Current"
        # Drop development config artifacts that are not needed at runtime and can trigger notarization errors
        rm -rf "${python_stage}/Python.framework/Versions/${python_current}/lib/python${python_current}/config-"*"-darwin" || true
    fi
    # Remove top-level symlinks that point to missing dev tools to avoid broken link warnings
    rm -f "${python_stage}/Python.framework/bin" "${python_stage}/Python.framework/Headers" "${python_stage}/Python.framework/share"
    chmod -R u+rwX "${python_stage}/Python.framework" || true
    rsync -a --delete "${python_stage}/Python.framework" "${APP_BUNDLE}/Contents/Frameworks/"
    rm -rf "${python_stage}"

    mkdir -p "${APP_BUNDLE}/Contents/Resources/python_site"
    rsync -a --delete "${PYTHON_SITE_SOURCE}/" "${APP_BUNDLE}/Contents/Resources/python_site/"

    # Ensure excluded-words.txt is always present in the app bundle resources + python_site
    # Ensure excluded-words.txt is always present in the app bundle resources + python_site
    local script_dir="$(dirname "$0")"
    local project_root="$(cd "$script_dir/.." && pwd)"
    local assets_file="${project_root}/assets/excluded-words.txt"
    
    if [ -f "${assets_file}" ]; then
        cp "${assets_file}" "${APP_BUNDLE}/Contents/Resources/excluded-words.txt"
        cp "${assets_file}" "${APP_BUNDLE}/Contents/Resources/python_site/marcut/excluded-words.txt"
    elif [ -f "excluded-words.txt" ]; then
        cp "excluded-words.txt" "${APP_BUNDLE}/Contents/Resources/excluded-words.txt"
        cp "excluded-words.txt" "${APP_BUNDLE}/Contents/Resources/python_site/marcut/excluded-words.txt"
    else
        echo -e "${YELLOW}⚠️  excluded-words.txt not found in ${assets_file}; bundle will miss default exclusions${NC}"
    fi

    # Copy help.md from assets directly to app bundle
    local help_file="${project_root}/assets/help.md"
    if [ -f "${help_file}" ]; then
        cp "${help_file}" "${APP_BUNDLE}/Contents/Resources/help.md"
        echo -e "${GREEN}✅ Copied help.md to app bundle${NC}"
    else
        echo -e "${YELLOW}⚠️  HELP.md not found at ${help_file}${NC}"
    fi

    if [ -n "${RUN_PYTHON_LAUNCHER}" ] && [ -f "${RUN_PYTHON_LAUNCHER}" ]; then
        cp "${RUN_PYTHON_LAUNCHER}" "${APP_BUNDLE}/Contents/Resources/run_python.sh"
        chmod +x "${APP_BUNDLE}/Contents/Resources/run_python.sh"
    fi

    local cli_launcher="MarcutApp/Contents/Resources/marcut_cli_launcher.sh"
    if [ -f "${cli_launcher}" ]; then
        cp "${cli_launcher}" "${APP_BUNDLE}/Contents/Resources/marcut_cli_launcher.sh"
        chmod +x "${APP_BUNDLE}/Contents/Resources/marcut_cli_launcher.sh"
    fi

    local embed_stub_path="${APP_BUNDLE}/Contents/Resources/python_embed_stub_patched.c"
    if command -v clang >/dev/null 2>&1 && [ -n "${PYTHON_STUB_SOURCE}" ] && [ -f "${PYTHON_STUB_SOURCE}" ]; then
        cp "${PYTHON_STUB_SOURCE}" "${embed_stub_path}"
    elif command -v clang >/dev/null 2>&1; then
        cat > "${embed_stub_path}" <<'EOF'
#include <Python.h>
#include <dlfcn.h>
#include <libgen.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void handle_status(PyStatus status, PyConfig *config) {
    if (PyStatus_Exception(status)) {
        if (config != NULL) {
            PyConfig_Clear(config);
        }
        Py_ExitStatusException(status);
    }
}

int main(int argc, char *argv[]) {
    PyConfig config;
    PyStatus status;
    int exit_code;
    char python_path[PATH_MAX];
    char python_home[PATH_MAX];
    char python_home_resolved[PATH_MAX];
    char program_name[PATH_MAX];
    char executable_path[PATH_MAX];
    uint32_t exec_size = sizeof(executable_path);

    if (_NSGetExecutablePath(executable_path, &exec_size) != 0) {
        fprintf(stderr, "python3_embed: Failed to get executable path\n");
        return 1;
    }

    char *app_dir = dirname(executable_path);
    char *contents_dir = dirname(app_dir);
    if (!app_dir || !contents_dir) {
        fprintf(stderr, "python3_embed: Failed to resolve app directory structure\n");
        return 1;
    }

    snprintf(python_home, sizeof(python_home), "%s/Frameworks/Python.framework/Versions/Current", contents_dir);
    if (!realpath(python_home, python_home_resolved)) {
        fprintf(stderr, "python3_embed: Unable to resolve Python home at %s\n", python_home);
        return 1;
    }

    const char *version_component = strrchr(python_home_resolved, '/');
    const char *python_version = (version_component && *(version_component + 1) != '\0') ? version_component + 1 : "3.10";

    snprintf(program_name, sizeof(program_name), "%s/bin/python3", python_home_resolved);
    snprintf(python_path, sizeof(python_path), "%s/Resources/python_site:%s/lib/python%s:%s/lib/python%s/lib-dynload",
             contents_dir, python_home_resolved, python_version, python_home_resolved, python_version);

    PyConfig_InitPythonConfig(&config);

    status = PyConfig_SetBytesString(&config, &config.program_name, program_name);
    handle_status(status, &config);

    status = PyConfig_SetBytesString(&config, &config.home, python_home_resolved);
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
    fi

    if command -v clang >/dev/null 2>&1 && [ -f "${embed_stub_path}" ]; then
        # Compile against SOURCE framework because DEST has headers stripped
        clang -arch arm64 \
            -F "$(dirname "${PYTHON_FRAMEWORK_SOURCE}")" \
            -I "${PYTHON_FRAMEWORK_SOURCE}/Headers" \
            -I "${PYTHON_FRAMEWORK_SOURCE}/Versions/Current/include" \
            -framework Python \
            -Wl,-rpath,@executable_path/../Frameworks \
            -o "${APP_BUNDLE}/Contents/Resources/python3_embed" \
            "${embed_stub_path}" || {
                echo -e "${YELLOW}⚠️  Failed to compile python3_embed stub${NC}"
            }
        rm -f "${embed_stub_path}"
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

    if [ -f "MarcutApp-Icon.png" ]; then
        mkdir -p "AppIcon.iconset"
        sips -z 1024 1024 "MarcutApp-Icon.png" --out "AppIcon.iconset/icon_512x512@2x.png" >/dev/null 2>&1
        iconutil -c icns "AppIcon.iconset" -o "${APP_BUNDLE}/Contents/Resources/AppIcon.icns"
        rm -rf "AppIcon.iconset"
    fi

    if [ -n "${OLLAMA_BINARY}" ] && [ -x "${OLLAMA_BINARY}" ]; then
        local target_dir="${APP_BUNDLE}/Contents/MacOS"
        mkdir -p "${target_dir}"
        cp "${OLLAMA_BINARY}" "${target_dir}/ollama"
        chmod +x "${target_dir}/ollama"
        echo -e "${GREEN}✅ Ollama binary installed to Contents/MacOS/ollama${NC}"

        # Removed legacy Ollama.app helper bundle creation
        
        # Extract and pre-sign Ollama runner to avoid runtime quarantine issues
        log_step "Extracting and pre-signing Ollama runner"
        local ollama_bin="${target_dir}/ollama"
        local runners_dir="$(pwd)/${APP_BUNDLE}/Contents/Resources/ollama_runners"

        if [ ! -x "$ollama_bin" ]; then
            echo -e "${RED}❌ Ollama binary not found or not executable at: $ollama_bin${NC}"
            # Skip runner extraction but continue build
        elif [ -x "${runners_dir}/metal/ollama_llama_server" ]; then
            echo -e "${GREEN}✅ Ollama runner already present; skipping extraction${NC}"
        else
            local temp_dir=$(mktemp -d)

            # Set environment and start Ollama to trigger runner extraction
            export OLLAMA_MODELS="$temp_dir/models"
            export OLLAMA_TMPDIR="$temp_dir"
            mkdir -p "$OLLAMA_MODELS"
            if command -v python3 >/dev/null 2>&1; then
                local free_port
                free_port=$(python3 - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
)
                if [ -n "$free_port" ]; then
                    export OLLAMA_HOST="127.0.0.1:${free_port}"
                fi
            fi

            # Resolve absolute path before changing directory
            local ollama_bin_abs
            ollama_bin_abs="$(cd "$(dirname "$ollama_bin")" && pwd)/$(basename "$ollama_bin")"

            cd "$temp_dir"
            "$ollama_bin_abs" serve > "$temp_dir/ollama.log" 2>&1 &
            local ollama_pid=$!
            
            # Wait for runner extraction (can take 5-10 seconds)
            echo -e "${BLUE}   Waiting for Ollama to extract runner...${NC}"
            local runner_path=""
            local extraction_success=0
            
            for i in {1..15}; do
                sleep 1
                # Search local temp dir since we set OLLAMA_TMPDIR
                runner_path=$(find "$temp_dir" -name "ollama_llama_server" -type f 2>/dev/null | head -1)
                if [ -n "$runner_path" ] && [ -f "$runner_path" ]; then
                    echo -e "${GREEN}   Found runner after ${i}s at: $runner_path${NC}"
                    
                    # Copy IMMEDIATELY before killing Ollama (which cleans up tmp)
                    mkdir -p "$runners_dir/metal"
                    # Get the directory containing the runner
                    local runner_src_dir=$(dirname "$runner_path")
                    # echo -e "${BLUE}   Runner source dir: $runner_src_dir${NC}"
                    # ls -la "$runner_src_dir"
                    
                    # Copy all files (including .metal shaders)
                    cp -R "$runner_src_dir/"* "$runners_dir/metal/"
                    chmod +x "$runners_dir/metal/ollama_llama_server"
                    extraction_success=1
                    break
                fi
            done
            
            # Kill Ollama
            kill $ollama_pid 2>/dev/null || true
            sleep 1
            pkill -P $ollama_pid 2>/dev/null || true
            
            if [ "$extraction_success" -eq 1 ]; then
                # Sign the runner
                codesign --force --deep --sign - "$runners_dir/metal/ollama_llama_server" 2>/dev/null || {
                    echo -e "${YELLOW}⚠️  Failed to sign runner, but continuing${NC}"
                }
                
                # Verify no quarantine
                if xattr -l "$runners_dir/metal/ollama_llama_server" 2>/dev/null | grep -q "com.apple.quarantine"; then
                    xattr -d com.apple.quarantine "$runners_dir/metal/ollama_llama_server" 2>/dev/null || true
                fi
                
                echo -e "${GREEN}✅ Ollama runner extracted and pre-signed at: $runners_dir/metal/ollama_llama_server${NC}"
            else
                echo -e "${RED}❌ Could not extract Ollama runner after 15s - check $temp_dir/ollama.log${NC}"
                echo -e "${YELLOW}   Last 10 lines of ollama.log:${NC}"
                tail -10 "$temp_dir/ollama.log" 2>/dev/null || echo "   (log not available)"
            fi
            
            # Cleanup
            cd -
            rm -rf "$temp_dir"
        fi
        
        if [ -f "${APP_BUNDLE}/Contents/Resources/ollama" ]; then
             rm "${APP_BUNDLE}/Contents/Resources/ollama"
        fi
    fi

    # XPC helper removed - CLI subprocess only approach
    log_step "Skipping XPC helper build (CLI-only architecture)"
    pushd "${SWIFT_PROJECT_DIR}" >/dev/null
    # XPC removed - CLI subprocess only approach
    log_step "Skipping XPC helper build (CLI-only architecture)"
    local helper_bin
    helper_bin=$(find .build -type f -name "OllamaHelperService" | head -1)
    popd >/dev/null

    if [ -n "${helper_bin}" ] && [ -x "${helper_bin}" ]; then
        local helper_xpc="${APP_BUNDLE}/Contents/XPCServices/OllamaHelperService.xpc"
        rm -rf "${helper_xpc}"
        mkdir -p "${helper_xpc}/Contents/MacOS"
        mkdir -p "${helper_xpc}/Contents/Resources"
        cp "${helper_bin}" "${helper_xpc}/Contents/MacOS/OllamaHelperService"
        chmod +x "${helper_xpc}/Contents/MacOS/OllamaHelperService"
        if [ -f "${SWIFT_PROJECT_DIR}/Sources/OllamaHelperService/Info.plist" ]; then
            cp "${SWIFT_PROJECT_DIR}/Sources/OllamaHelperService/Info.plist" "${helper_xpc}/Contents/Info.plist"
        fi
        if [ -d "${APP_BUNDLE}/Contents/Resources/Ollama.app" ]; then
            cp -R "${APP_BUNDLE}/Contents/Resources/Ollama.app" "${helper_xpc}/Contents/Resources/"
        fi
    else
        echo -e "${YELLOW}⚠️  Could not locate built OllamaHelperService; XPC helper not embedded${NC}"
    fi

    # Ensure Finder shows the bundle as freshly updated
    touch -c "${APP_BUNDLE}" "${APP_BUNDLE}/Contents" "${APP_BUNDLE}/Contents/MacOS" "${APP_BUNDLE}/Contents/Resources"

    # Repair Python.framework site-packages symlinks after all resources are in place
    fix_python_site_symlinks
}

step_bundle_cleanup() {
    log_step "Cleaning bundled Python bytecode artifacts"
    clean_bundle_python_bytecode
}

step_sign_components() {
    log_step "Signing app components"

    local sign_identity
    if ! sign_identity="$(resolve_signing_identity)"; then
        echo -e "${RED}❌ Signing identity unavailable; aborting signing step.${NC}"
        exit 1
    fi
    echo -e "${BLUE}🔐 Using signing identity: ${sign_identity}${NC}"

    local script_dir="$(dirname "$0")"
    local project_root="$(cd "$script_dir/.." && pwd)"

    ENTITLEMENTS_CANDIDATES=(
        "${project_root}/assets/Marcut.entitlements"
        "MarcutApp/MarcutApp.entitlements"
        "MarcutApp/MarcutApp/MarcutApp.entitlements"
        "MarcutApp.entitlements"
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

    # Sign nested dynamic libraries and Python extensions first
    if [ -d "${PYTHON_FRAMEWORK_DEST}" ]; then
        find "${PYTHON_FRAMEWORK_DEST}" -type f \( -name "*.dylib" -o -name "*.so" -o -name "Python" \) -print0 | while IFS= read -r -d '' lib; do
            codesign --force --sign "${sign_identity}" --timestamp --options runtime "$lib"
        done
    fi

    if [ -d "${APP_BUNDLE}/Contents/Resources/python_site" ]; then
        find "${APP_BUNDLE}/Contents/Resources/python_site" -type f \( -name "*.so" -o -name "*.dylib" \) -print0 | while IFS= read -r -d '' lib; do
            codesign --force --sign "${sign_identity}" --timestamp --options runtime "$lib"
        done
    fi

    if [ -f "${APP_BUNDLE}/Contents/MacOS/ollama" ]; then
        codesign --force --sign "${sign_identity}" --timestamp --options runtime \
            --entitlements "${OLLAMA_ENTITLEMENTS}" \
            "${APP_BUNDLE}/Contents/MacOS/ollama"
    fi

    if [ -f "${APP_BUNDLE}/Contents/Resources/ollama_runners/metal/ollama_llama_server" ]; then
        if ! codesign --force --sign "${sign_identity}" --timestamp --options runtime \
            "${APP_BUNDLE}/Contents/Resources/ollama_runners/metal/ollama_llama_server"; then
            echo -e "${YELLOW}⚠️  Failed to sign ollama runner; removing to avoid notarization failure${NC}"
            rm -f "${APP_BUNDLE}/Contents/Resources/ollama_runners/metal/ollama_llama_server" 2>/dev/null || true
        fi
    fi

    if [ -d "${APP_BUNDLE}/Contents/XPCServices/OllamaHelperService.xpc" ]; then
        local helper_ent="${HELPER_ENTITLEMENTS}"
        [ -f "${helper_ent}" ] || helper_ent="${ENTITLEMENTS_FILE}"

        if [ -f "${APP_BUNDLE}/Contents/XPCServices/OllamaHelperService.xpc/Contents/Resources/Ollama.app/Contents/MacOS/ollama" ]; then
            codesign --force --sign "${sign_identity}" --timestamp --options runtime \
                --entitlements "${OLLAMA_ENTITLEMENTS}" \
                "${APP_BUNDLE}/Contents/XPCServices/OllamaHelperService.xpc/Contents/Resources/Ollama.app/Contents/MacOS/ollama"
            codesign --force --sign "${sign_identity}" --timestamp --options runtime \
                "${APP_BUNDLE}/Contents/XPCServices/OllamaHelperService.xpc/Contents/Resources/Ollama.app"
        fi

        if [ -f "${APP_BUNDLE}/Contents/XPCServices/OllamaHelperService.xpc/Contents/MacOS/OllamaHelperService" ]; then
            codesign --force --sign "${sign_identity}" --timestamp --options runtime \
                --entitlements "${helper_ent}" \
                "${APP_BUNDLE}/Contents/XPCServices/OllamaHelperService.xpc/Contents/MacOS/OllamaHelperService"
        fi
        codesign --force --sign "${sign_identity}" --timestamp --options runtime \
            --entitlements "${helper_ent}" \
            "${APP_BUNDLE}/Contents/XPCServices/OllamaHelperService.xpc"
    fi

    if [ -d "${PYTHON_FRAMEWORK_DEST}" ]; then
        codesign --force --sign "${sign_identity}" --timestamp --options runtime --deep \
            "${PYTHON_FRAMEWORK_DEST}"
    fi

    if [ -f "${APP_BUNDLE}/Contents/Resources/python3_embed" ]; then
        codesign --force --sign "${sign_identity}" --timestamp --options runtime \
            "${APP_BUNDLE}/Contents/Resources/python3_embed"
    fi

    codesign --force --sign "${sign_identity}" --timestamp --options runtime \
        "${APP_BUNDLE}/Contents/MacOS/${APP_NAME}"

    codesign --force --sign "${sign_identity}" --timestamp --options runtime \
        --entitlements "${ENTITLEMENTS_FILE}" \
        "${APP_BUNDLE}"

    # Refresh top-level bundle timestamp after signing
    touch -c "${APP_BUNDLE}"
}

step_testing_cleanup() {
    log_step "Cleaning testing environment for fresh permission testing"

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
    rm -rf "/var/folders/*/C/com.apple.QuickLook.thumbnailcache*"/*marcut* 2>/dev/null || true

    # Reset sandbox quarantine attributes (makes macOS treat it as "fresh" for permissions)
    if [ -d "${APP_BUNDLE}" ]; then
        echo -e "${BLUE}🔄 Resetting quarantine attributes for testing${NC}"
        xattr -d com.apple.quarantine "${APP_BUNDLE}" 2>/dev/null || true
        xattr -d com.apple.quarantine "${APP_BUNDLE}/Contents/MacOS/${APP_NAME}" 2>/dev/null || true
    fi

    echo -e "${GREEN}✅ Testing environment cleaned - ready for fresh permission testing${NC}"
    echo -e "${YELLOW}💡 Note: Launch the app immediately after build for clean permission testing${NC}"
}

step_bundle_audit() {
    log_step "Running bundle audit (Gatekeeper + missing files + clean-env smoke test)"

    if [ ! -d "${APP_BUNDLE}" ]; then
        echo -e "${RED}❌ App bundle not found at ${APP_BUNDLE}${NC}"
        exit 1
    fi

    local failures=0

    local required_items=(
        "Contents/Info.plist"
        "Contents/MacOS/${APP_NAME}"
        "Contents/Frameworks/Python.framework/Versions/Current/Python"
        "Contents/Resources/python_site/marcut/__init__.py"
        "Contents/Resources/excluded-words.txt"
    )

        optional_items+=("Contents/MacOS/ollama")
        optional_items+=("Contents/Resources/ollama_runners/metal/ollama_llama_server")

    for rel_path in "${required_items[@]}"; do
        if [ ! -e "${APP_BUNDLE}/${rel_path}" ]; then
            echo -e "${RED}❌ Missing required bundle item: ${rel_path}${NC}"
            failures=$((failures + 1))
        fi
    done

    for rel_path in "${optional_items[@]}"; do
        if [ ! -e "${APP_BUNDLE}/${rel_path}" ]; then
            echo -e "${YELLOW}⚠️  Optional bundle item missing: ${rel_path}${NC}"
        fi
    done

    if command -v plutil >/dev/null 2>&1; then
        if ! plutil -lint "${APP_BUNDLE}/Contents/Info.plist" >/dev/null 2>&1; then
            echo -e "${RED}❌ Info.plist failed validation${NC}"
            failures=$((failures + 1))
        fi
    else
        echo -e "${YELLOW}⚠️  plutil not available; skipping Info.plist validation${NC}"
    fi

    local broken_links=""
    while IFS= read -r -d '' link; do
        if [ ! -e "${link}" ]; then
            broken_links+="${link}\n"
        fi
    done < <(find "${APP_BUNDLE}" -type l -print0 2>/dev/null || true)
    if [ -n "${broken_links}" ]; then
        echo -e "${RED}❌ Broken symlinks detected:${NC}"
        printf "%b" "${broken_links}"
        failures=$((failures + 1))
    fi

    if codesign --verify --deep --strict --verbose=2 "${APP_BUNDLE}" >/dev/null 2>&1; then
        echo -e "${GREEN}✅ codesign verification ok${NC}"
    else
        echo -e "${RED}❌ codesign verification failed${NC}"
        failures=$((failures + 1))
    fi

    if command -v spctl >/dev/null 2>&1; then
        local dmg_path=""
        if [ -f "${LAST_DMG_PATH_FILE}" ]; then
            dmg_path="$(cat "${LAST_DMG_PATH_FILE}")"
        fi
        if [ -z "${dmg_path}" ] || [ ! -f "${dmg_path}" ]; then
            dmg_path="${FINAL_DMG}"
            if [[ "${dmg_path}" != /* ]]; then
                dmg_path="$(pwd)/${dmg_path}"
            fi
        fi

        if [ -f "${dmg_path}" ]; then
            if command -v xcrun >/dev/null 2>&1 && xcrun stapler validate "${dmg_path}" >/dev/null 2>&1; then
                if spctl -a -t open --context context:primary-signature -v "${dmg_path}" >/dev/null 2>&1; then
                    echo -e "${GREEN}✅ Gatekeeper assessment ok (notarized DMG)${NC}"
                else
                    echo -e "${RED}❌ Gatekeeper assessment failed on notarized DMG${NC}"
                    spctl -a -t open --context context:primary-signature -v "${dmg_path}" || true
                    failures=$((failures + 1))
                fi
            else
                echo -e "${YELLOW}⚠️  DMG is not notarized; skipping Gatekeeper check in dev builds${NC}"
                echo -e "${YELLOW}💡 Run the Full Release build (with notarization) to validate Gatekeeper.${NC}"
            fi
        else
            echo -e "${YELLOW}⚠️  No DMG found; skipping Gatekeeper check in dev builds${NC}"
            echo -e "${YELLOW}💡 Run the Full Release build (with notarization) to validate Gatekeeper.${NC}"
        fi
    else
        echo -e "${YELLOW}⚠️  spctl not available; skipping Gatekeeper assessment${NC}"
    fi

    local smoke_home
    smoke_home=$(mktemp -d)
    local smoke_log
    smoke_log=$(mktemp)
    local pycache_prefix
    pycache_prefix=$(mktemp -d)
    local smoke_cmd=("${APP_BUNDLE}/Contents/MacOS/${APP_NAME}" "--diagnose")

    if command -v timeout >/dev/null 2>&1; then
        if timeout 25 env -i HOME="${smoke_home}" TMPDIR="/tmp" PATH="/usr/bin:/bin" \
            PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX="${pycache_prefix}" \
            "${smoke_cmd[@]}" >"${smoke_log}" 2>&1; then
            echo -e "${GREEN}✅ Clean-env --diagnose ok${NC}"
        else
            echo -e "${RED}❌ Clean-env --diagnose failed${NC}"
            tail -20 "${smoke_log}" || true
            failures=$((failures + 1))
        fi
    else
        if env -i HOME="${smoke_home}" TMPDIR="/tmp" PATH="/usr/bin:/bin" \
            PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX="${pycache_prefix}" \
            "${smoke_cmd[@]}" >"${smoke_log}" 2>&1; then
            echo -e "${GREEN}✅ Clean-env --diagnose ok${NC}"
        else
            echo -e "${RED}❌ Clean-env --diagnose failed${NC}"
            tail -20 "${smoke_log}" || true
            failures=$((failures + 1))
        fi
    fi

    rm -rf "${smoke_home}"
    rm -rf "${pycache_prefix}"
    rm -f "${smoke_log}"

    if [ "${failures}" -ne 0 ]; then
        echo -e "${RED}❌ Bundle audit failed with ${failures} issue(s)${NC}"
        exit 1
    fi

    echo -e "${GREEN}✅ Bundle audit passed${NC}"
}

step_functional_verification() {
    log_step "Running functional smoke tests"

    local pycache_prefix
    pycache_prefix=$(mktemp -d)
    local env_prefix=(env PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX="${pycache_prefix}")

    if ! timeout 10 "${env_prefix[@]}" "${APP_BUNDLE}/Contents/MacOS/${APP_NAME}" --help >/dev/null 2>&1; then
        echo -e "${YELLOW}⚠️  App help command failed or timed out${NC}"
    else
        echo -e "${GREEN}✅ App help command ok${NC}"
    fi

    if ! timeout 15 "${env_prefix[@]}" "${APP_BUNDLE}/Contents/MacOS/${APP_NAME}" --diagnose >/dev/null 2>&1; then
        echo -e "${YELLOW}⚠️  App diagnostic mode failed or timed out${NC}"
    else
        echo -e "${GREEN}✅ App diagnostic mode ok${NC}"
    fi

    if ! timeout 5 "${env_prefix[@]}" "${APP_BUNDLE}/Contents/MacOS/${APP_NAME}" --cli --help 2>&1 | grep -q "MarcutApp CLI Mode"; then
        echo -e "${YELLOW}⚠️  Python initialization check failed${NC}"
    else
        echo -e "${GREEN}✅ Python initialization check ok${NC}"
    fi

    rm -rf "${pycache_prefix}"
}

step_create_dmg() {
    log_step "Creating distributable DMG"
    rm -f "${FINAL_DMG}"
    if ! hdiutil create -volname "${APP_NAME}" -srcfolder "${APP_BUNDLE}" -ov -format UDZO "${FINAL_DMG}"; then
        echo -e "${RED}❌ Failed to create DMG at ${FINAL_DMG}${NC}"
        exit 1
    fi
    echo -e "${GREEN}✅ DMG created at ${FINAL_DMG}${NC}"

    local dmg_sign_identity
    if ! dmg_sign_identity="$(resolve_signing_identity)"; then
        echo -e "${YELLOW}⚠️  Unable to resolve signing identity; DMG will remain unsigned${NC}"
    else
        if codesign --force --sign "${dmg_sign_identity}" --timestamp "${FINAL_DMG}"; then
            echo -e "${GREEN}✅ DMG signed with Developer ID${NC}"
        else
            echo -e "${YELLOW}⚠️  Failed to sign DMG; continuing unsigned${NC}"
        fi
    fi

    mkdir -p "${BUILD_DIR}"
    local dmg_path="${FINAL_DMG}"
    if [[ "${dmg_path}" != /* ]]; then
        dmg_path="$(pwd)/${dmg_path}"
    fi
    echo "${dmg_path}" > "${LAST_DMG_PATH_FILE}"
    echo -e "${BLUE}🧾 Recorded DMG path: ${dmg_path}${NC}"
}

step_notarize_dmg() {
    log_step "Notarizing DMG"

    if [ "${SKIP_NOTARIZE:-0}" = "1" ]; then
        echo -e "${YELLOW}⚠️  SKIP_NOTARIZE=1 – skipping notarization${NC}"
        return
    fi

    if [ -z "${NOTARIZE_SCRIPT}" ]; then
        echo -e "${YELLOW}⚠️  Notarize script not configured (config.json: notarize_script); skipping${NC}"
        return
    fi

    local script_path="${NOTARIZE_SCRIPT}"
    if [[ "${script_path}" != /* ]]; then
        script_path="$(cd "$(dirname "$0")" && pwd)/${script_path}"
    fi

    if [ ! -f "${script_path}" ]; then
        echo -e "${RED}❌ Notarize script not found: ${script_path}${NC}"
        exit 1
    fi

    local dmg_path=""
    if [ -f "${LAST_DMG_PATH_FILE}" ]; then
        dmg_path="$(cat "${LAST_DMG_PATH_FILE}")"
    fi
    if [ -z "${dmg_path}" ] || [ ! -f "${dmg_path}" ]; then
        dmg_path="${FINAL_DMG}"
        if [[ "${dmg_path}" != /* ]]; then
            dmg_path="$(pwd)/${dmg_path}"
        fi
    fi

    if [ ! -f "${dmg_path}" ]; then
        echo -e "${RED}❌ DMG not found; create the DMG before notarizing${NC}"
        echo -e "${YELLOW}💡 Expected at: ${dmg_path}${NC}"
        exit 1
    fi

    bash "${script_path}" "${dmg_path}"
}

step_appstore_sign() {
    log_step "Signing app for App Store distribution"

    # App Store requires specific certificate
    local app_identity="3rd Party Mac Developer Application: Marc Mandel (QG85EMCQ75)"
    local installer_identity="3rd Party Mac Developer Installer: Marc Mandel (QG85EMCQ75)"
    
    echo -e "${BLUE}🔐 Using App Store identity: ${app_identity}${NC}"

    local script_dir="$(dirname "$0")"
    local project_root="$(cd "$script_dir/.." && pwd)"

    # Locate entitlements
    local main_entitlements="${project_root}/src/swift/MarcutApp/MarcutApp.entitlements"
    if [ ! -f "${main_entitlements}" ]; then
        main_entitlements="${project_root}/assets/Marcut.entitlements"
    fi
    if [ ! -f "${main_entitlements}" ]; then
        echo -e "${RED}❌ Main entitlements file not found${NC}"
        exit 1
    fi

    # Create sandbox inherit entitlements for embedded executables
    local inherit_entitlements=$(mktemp)
    cat > "${inherit_entitlements}" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.app-sandbox</key>
    <true/>
    <key>com.apple.security.inherit</key>
    <true/>
</dict>
</plist>
EOF

    # Fix file permissions - all files must be readable by non-root users
    log_step "Fixing file permissions for App Store"
    chmod -R a+rX "${APP_BUNDLE}"
    find "${APP_BUNDLE}" -type f -exec chmod a+r {} \;
    find "${APP_BUNDLE}" -type d -exec chmod a+rx {} \;
    
    # Sign Python framework dylibs and .so files with App Store certificate
    log_step "Signing Python framework for App Store"
    if [ -d "${PYTHON_FRAMEWORK_DEST}" ]; then
        find "${PYTHON_FRAMEWORK_DEST}" -type f \( -name "*.dylib" -o -name "*.so" -o -name "Python" \) -print0 | while IFS= read -r -d '' lib; do
            codesign --force --sign "${app_identity}" --timestamp --options runtime "$lib" 2>/dev/null || true
        done
    fi

    # Sign python_site .so and .dylib files
    log_step "Signing Python site packages for App Store"
    if [ -d "${APP_BUNDLE}/Contents/Resources/python_site" ]; then
        find "${APP_BUNDLE}/Contents/Resources/python_site" -type f \( -name "*.so" -o -name "*.dylib" \) -print0 | while IFS= read -r -d '' lib; do
            codesign --force --sign "${app_identity}" --timestamp --options runtime "$lib" 2>/dev/null || true
        done
    fi

    # Sign python3_embed with sandbox inherit entitlements
    if [ -f "${APP_BUNDLE}/Contents/Resources/python3_embed" ]; then
        log_step "Signing python3_embed with sandbox entitlements"
        codesign --force --sign "${app_identity}" --timestamp --options runtime \
            --entitlements "${inherit_entitlements}" \
            "${APP_BUNDLE}/Contents/Resources/python3_embed"
    fi

    # Sign Ollama with inherit entitlements
    if [ -f "${APP_BUNDLE}/Contents/MacOS/ollama" ]; then
        log_step "Signing Ollama for App Store"
        codesign --force --sign "${app_identity}" --timestamp --options runtime \
            --entitlements "${inherit_entitlements}" \
            "${APP_BUNDLE}/Contents/MacOS/ollama"
    fi

    # Sign Ollama runner if present
    if [ -f "${APP_BUNDLE}/Contents/Resources/ollama_runners/metal/ollama_llama_server" ]; then
        codesign --force --sign "${app_identity}" --timestamp --options runtime \
            --entitlements "${inherit_entitlements}" \
            "${APP_BUNDLE}/Contents/Resources/ollama_runners/metal/ollama_llama_server" 2>/dev/null || {
            echo -e "${YELLOW}⚠️  Could not sign ollama runner; removing${NC}"
            rm -f "${APP_BUNDLE}/Contents/Resources/ollama_runners/metal/ollama_llama_server"
        }
    fi

    # Sign the Python framework bundle
    if [ -d "${PYTHON_FRAMEWORK_DEST}" ]; then
        codesign --force --sign "${app_identity}" --timestamp --options runtime --deep \
            "${PYTHON_FRAMEWORK_DEST}"
    fi

    # Sign the main executable with entitlements
    codesign --force --sign "${app_identity}" --timestamp --options runtime \
        --entitlements "${main_entitlements}" \
        "${APP_BUNDLE}/Contents/MacOS/${APP_NAME}"

    # Sign the app bundle with main entitlements
    codesign --force --sign "${app_identity}" --timestamp --options runtime \
        --entitlements "${main_entitlements}" \
        "${APP_BUNDLE}"

    # Cleanup
    rm -f "${inherit_entitlements}"

    # Verify signature
    if codesign --verify --deep --strict "${APP_BUNDLE}"; then
        echo -e "${GREEN}✅ App Store signature verified${NC}"
    else
        echo -e "${RED}❌ App Store signature verification failed${NC}"
        exit 1
    fi
}

step_appstore_package() {
    log_step "Creating App Store archive and PKG"

    local script_dir="$(dirname "$0")"
    local archive_dir="${script_dir}/Archive"
    local archive_path="${archive_dir}/${APP_NAME}.xcarchive"
    local export_dir="${archive_dir}/Exported"
    local pkg_path="${export_dir}/${APP_NAME}.pkg"
    local installer_identity="3rd Party Mac Developer Installer: Marc Mandel (QG85EMCQ75)"
    local app_identity="3rd Party Mac Developer Application: Marc Mandel (QG85EMCQ75)"
    local provisioning_profile="${script_dir}/../ignored-resources/certificates/Marcut_App_Store.provisionprofile"

    # Clean up old archives
    rm -rf "${archive_path}" "${export_dir}"
    mkdir -p "${archive_path}/Products/Applications"
    mkdir -p "${export_dir}"

    # Copy app to archive
    log_step "Creating xcarchive structure"
    cp -R "${APP_BUNDLE}" "${archive_path}/Products/Applications/"

    # Embed provisioning profile if not present
    if [ -f "${provisioning_profile}" ] && [ ! -f "${archive_path}/Products/Applications/${APP_NAME}.app/Contents/embedded.provisionprofile" ]; then
        log_step "Embedding provisioning profile"
        cp "${provisioning_profile}" "${archive_path}/Products/Applications/${APP_NAME}.app/Contents/embedded.provisionprofile"
    fi

    # Create archive Info.plist
    cat > "${archive_path}/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>ApplicationProperties</key>
    <dict>
        <key>ApplicationPath</key>
        <string>Applications/${APP_NAME}.app</string>
        <key>CFBundleIdentifier</key>
        <string>${BUNDLE_ID}</string>
        <key>CFBundleShortVersionString</key>
        <string>${VERSION}</string>
        <key>CFBundleVersion</key>
        <string>${BUILD_NUMBER}</string>
        <key>SigningIdentity</key>
        <string>${app_identity}</string>
        <key>Team</key>
        <string>QG85EMCQ75</string>
    </dict>
    <key>ArchiveVersion</key>
    <integer>2</integer>
    <key>CreationDate</key>
    <date>$(date -u +"%Y-%m-%dT%H:%M:%SZ")</date>
    <key>Name</key>
    <string>${APP_NAME}</string>
    <key>SchemeName</key>
    <string>${APP_NAME}</string>
</dict>
</plist>
EOF

    # Create signed PKG
    log_step "Creating signed installer package"
    if productbuild \
        --component "${archive_path}/Products/Applications/${APP_NAME}.app" \
        /Applications \
        --sign "${installer_identity}" \
        "${pkg_path}"; then
        echo -e "${GREEN}✅ PKG created: ${pkg_path}${NC}"
    else
        echo -e "${RED}❌ Failed to create PKG${NC}"
        exit 1
    fi

    echo -e "${GREEN}✅ App Store archive created: ${archive_path}${NC}"
    echo -e "${GREEN}✅ App Store PKG created: ${pkg_path}${NC}"
}

step_appstore_upload() {
    log_step "Uploading to App Store Connect"

    local script_dir="$(dirname "$0")"
    local export_dir="${script_dir}/Archive/Exported"
    local pkg_path="${export_dir}/${APP_NAME}.pkg"

    if [ ! -f "${pkg_path}" ]; then
        echo -e "${RED}❌ PKG not found at ${pkg_path}. Run appstore_package first.${NC}"
        exit 1
    fi

    # Use keychain credentials
    local apple_id="icloud@exode.com"
    local keychain_item="MarcutAppStore"

    echo -e "${BLUE}Uploading ${pkg_path} to App Store Connect...${NC}"
    # Using manual altool
    echo -e "${YELLOW}Please start the submission script via ./build-scripts/submit_appstore.sh or TUI for better handling.${NC}"
    echo -e "${BLUE}Command preview: xcrun altool --upload-app --type macos --file \"${pkg_path}\" --username \"${apple_id}\" -p ...${NC}"
}

run_step_internal() {
    case "$1" in
        bump_version) step_bump_version ;;
        cleanup) step_cleanup ;;
        refresh_python) step_refresh_python_payload ;;
        build_swift) step_build_swift ;;
        verify_build) step_verify_build ;;
        assemble_bundle) step_assemble_bundle ;;
        bundle_cleanup) step_bundle_cleanup ;;
        sign_components) step_sign_components ;;
        testing_cleanup) step_testing_cleanup ;;
        bundle_audit) step_bundle_audit ;;
        functional_verification) step_functional_verification ;;
        create_dmg) step_create_dmg ;;
        notarize_dmg) step_notarize_dmg ;;
        appstore_sign) step_appstore_sign ;;
        appstore_package) step_appstore_package ;;
        appstore_upload) step_appstore_upload ;;
        *)
            echo -e "${RED}❌ Unknown step: $1${NC}"
            exit 1
            ;;
    esac
}

run_steps() {
    local steps=("$@")
    local has_dmg=0
    local has_bump=0
    for step in "${steps[@]}"; do
        [ "$step" = "create_dmg" ] && has_dmg=1
        [ "$step" = "bump_version" ] && has_bump=1
    done
    if [ "$has_dmg" -eq 1 ] && [ "$has_bump" -eq 0 ]; then
        echo -e "${YELLOW}⚠️  DMG build detected; bumping patch version first.${NC}"
        steps=("bump_version" "${steps[@]}")
    fi

    for step in "${steps[@]}"; do
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
            SKIP_PY_RUNTIME_REFRESH="${SKIP_PY_RUNTIME_REFRESH:-1}" run_steps build_swift assemble_bundle bundle_cleanup sign_components
            ;;
        quick_debug)
            run_steps refresh_python build_swift verify_build assemble_bundle bundle_cleanup sign_components bundle_audit functional_verification
            ;;
        fast_incremental)
            run_steps build_swift verify_build assemble_bundle bundle_cleanup sign_components testing_cleanup bundle_audit
            ;;
        full_release)
            run_steps bump_version cleanup refresh_python build_swift verify_build assemble_bundle bundle_cleanup sign_components testing_cleanup functional_verification create_dmg notarize_dmg bundle_audit
            ;;
        appstore)
            run_steps bump_version cleanup refresh_python build_swift verify_build assemble_bundle bundle_cleanup appstore_sign appstore_package appstore_upload
            ;;
        appstore_only)
            # Re-sign and package existing build for App Store (no rebuild)
            run_steps appstore_sign appstore_package appstore_upload
            ;;
        diagnostics)
            run_steps verify_build bundle_audit functional_verification
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

Commands:
  preset <dev_fast|quick_debug|fast_incremental|full_release|appstore|appstore_only|diagnostics|clean>
  run_steps <step...>     # run steps in order
  run_step <step>         # run single step

Steps:
  bump_version | cleanup | refresh_python | build_swift | verify_build |
  assemble_bundle | bundle_cleanup | sign_components | testing_cleanup |
  bundle_audit | functional_verification | create_dmg | notarize_dmg
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

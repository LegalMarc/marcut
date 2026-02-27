#!/bin/bash
#
# MarcutApp - App Store Distribution Build Script
# Creates an App Store archive + signed DMG.
# Notarization is only valid with a Developer ID Application cert (direct distribution).
#
set -euo pipefail

# Paths (absolute to avoid cwd issues)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
CONFIG_PATH="${ROOT_DIR}/build-scripts/config.json"
if [ ! -f "${CONFIG_PATH}" ] && [ -f "${ROOT_DIR}/config.json" ]; then
    CONFIG_PATH="${ROOT_DIR}/config.json"
fi

# ===== CONFIGURATION =====
if [ -f "${CONFIG_PATH}" ] && command -v python3 >/dev/null 2>&1; then
    eval "$(python3 - "$CONFIG_PATH" <<'PY'
import json
import os
import shlex
import sys

config_path = sys.argv[1]
try:
    config = json.load(open(config_path, "r", encoding="utf-8"))
except Exception:
    config = {}

def emit(var, key, is_path=False):
    value = config.get(key)
    if value in (None, ""):
        return
    if is_path:
        config_dir = os.path.dirname(os.path.abspath(config_path))
        value = os.path.normpath(os.path.join(config_dir, str(value)))
    print(f"{var}={shlex.quote(str(value))}")

emit("APP_NAME", "app_name")
emit("BUNDLE_ID", "bundle_id")
emit("VERSION", "version")
emit("BUILD_NUMBER", "build_number")
emit("PYTHON_SITE_SOURCE", "python_site_source", is_path=True)
emit("PYTHON_SITE_REPO_SOURCE", "python_site_repo_source", is_path=True)
emit("TEAM_ID", "appstore_default_team_id")
emit("DEVELOPER_ID", "appstore_default_identity")
emit("CUSTOM_SIGN_IDENTITY", "custom_sign_identity")
emit("SWIFT_PROJECT_DIR", "swift_project_dir", is_path=True)
emit("APPSTORE_ARCHIVE_ROOT", "appstore_archive_root", is_path=True)
emit("APPSTORE_BUILD_ROOT", "appstore_build_root", is_path=True)
emit("SWIFT_BUILD_DIR", "swift_build_dir", is_path=True)
emit("FINAL_DMG", "final_dmg", is_path=True)
emit("OLLAMA_ENTITLEMENTS", "ollama_entitlements", is_path=True)
emit("ASSETS_DIR", "assets_dir", is_path=True)
emit("APPSTORE_DEFAULT_ARCHIVE", "appstore_default_archive")
emit("APPSTORE_PROFILE", "appstore_default_profile", is_path=True)
PY
)"
fi

APP_NAME="${APP_NAME:-MarcutApp}"
BUNDLE_ID="${BUNDLE_ID:-com.marclaw.marcutapp}"
VERSION="${VERSION:-0.0.0}"
BUILD_NUMBER="${BUILD_NUMBER:-1}"

# Signing Configuration
# Developer ID / App Store signing identity
DEVELOPER_ID="${DEVELOPER_ID:-${CUSTOM_SIGN_IDENTITY:-}}"
if [ -n "${CUSTOM_SIGN_IDENTITY:-}" ]; then
    DEVELOPER_ID="${CUSTOM_SIGN_IDENTITY}"
    echo "ℹ️  Custom signing identity applied: ${DEVELOPER_ID}"
fi
TEAM_ID="${TEAM_ID:-}"
AUTO_BUMP_BUILD_NUMBER="${AUTO_BUMP_BUILD_NUMBER:-false}"

# Ollama configuration
OLLAMA_VERSION="0.12.5"
OLLAMA_DOWNLOAD_URL="https://github.com/ollama/ollama/releases/download/v${OLLAMA_VERSION}/ollama-darwin.tgz"

cd "$ROOT_DIR"
OUTPUT_ROOT="${OUTPUT_ROOT:-${ROOT_DIR}/.marcut_artifacts/ignored-resources}"
BUILD_DIR="${APPSTORE_BUILD_ROOT:-${OUTPUT_ROOT}/build}"
ARCHIVE_DIR="${APPSTORE_ARCHIVE_ROOT:-${OUTPUT_ROOT}/archive}"
SWIFT_BUILD_DIR="${SWIFT_BUILD_DIR:-${OUTPUT_ROOT}/builds/swiftpm}"
SWIFT_PROJECT_DIR="${SWIFT_PROJECT_DIR:-${ROOT_DIR}/src/swift/MarcutApp}"
PYTHON_SITE_SOURCE="${PYTHON_SITE_SOURCE:-${SWIFT_PROJECT_DIR}/Sources/MarcutApp/python_site}"
PYTHON_SITE_REPO_SOURCE="${PYTHON_SITE_REPO_SOURCE:-${ROOT_DIR}/src/python/marcut}"
APP_BUNDLE="${BUILD_DIR}/${APP_NAME}.app"
ARCHIVE_NAME="${APPSTORE_DEFAULT_ARCHIVE:-${APP_NAME}}"
ARCHIVE_PATH="${ARCHIVE_DIR}/${ARCHIVE_NAME}.xcarchive"
DMG_NAME="${APP_NAME}-v${VERSION}-AppStore"
FINAL_DMG="${FINAL_DMG:-${OUTPUT_ROOT}/${DMG_NAME}.dmg}"
VOLUME_NAME="${APP_NAME}"
ENTITLEMENTS="${ROOT_DIR}/Marcut.entitlements"
if [ -z "${OLLAMA_ENTITLEMENTS:-}" ]; then
    if [ -n "${ASSETS_DIR:-}" ]; then
        OLLAMA_ENTITLEMENTS="${ASSETS_DIR}/MarcutOllama.entitlements"
    else
        OLLAMA_ENTITLEMENTS="${ROOT_DIR}/assets/MarcutOllama.entitlements"
    fi
fi
APPSTORE_PROFILE="${APPSTORE_PROFILE:-}"
SIGN_ENTITLEMENTS="${ENTITLEMENTS}"

auto_bump_build_number() {
    if [ "${AUTO_BUMP_BUILD_NUMBER}" != "true" ]; then
        return
    fi
    if [[ "${DEVELOPER_ID}" != "3rd Party Mac Developer Application"* && "${DEVELOPER_ID}" != "Apple Distribution"* ]]; then
        return
    fi
    if [ -z "${CONFIG_PATH}" ] || [ ! -f "${CONFIG_PATH}" ]; then
        return
    fi
    if ! command -v python3 >/dev/null 2>&1; then
        log_warning "python3 not available; skipping build number bump."
        return
    fi

    local new_build
    new_build="$(python3 - "${CONFIG_PATH}" "${BUILD_NUMBER}" <<'PY'
import json
import os
import re
import sys

config_path = sys.argv[1]
current = sys.argv[2] if len(sys.argv) > 2 else ""

def parse_numeric_parts(value: str):
    s = (value or "").strip()
    if not re.fullmatch(r"\d+(?:\.\d+)*", s):
        return None
    return [int(p) for p in s.split(".")]

def format_parts(parts):
    return ".".join(str(p) for p in parts)

def bump_parts(parts):
    if not parts:
        return None
    if len(parts) > 3:
        parts = parts[:3]
    parts = list(parts)
    parts[-1] += 1
    return parts

def bump_with_version(version: str, build: str) -> str:
    build_parts = parse_numeric_parts(build)
    if build_parts:
        bumped = bump_parts(build_parts)
        return format_parts(bumped)

    version_parts = parse_numeric_parts(version)
    if version_parts:
        if len(version_parts) > 3:
            version_parts = version_parts[:3]
        return format_parts(version_parts)

    m = re.search(r"(\d+)$", (build or "").strip())
    if m:
        return str(int(m.group(1)) + 1)
    return "1"

try:
    with open(config_path, "r", encoding="utf-8") as handle:
        cfg = json.load(handle)
except Exception:
    cfg = {}

current_cfg = str(cfg.get("build_number", current or ""))
current_version = str(cfg.get("version", ""))
new_build = bump_with_version(current_version, current_cfg)
# Keep display version and build in lockstep so About/Info/DMG naming stay aligned.
cfg["build_number"] = new_build
cfg["version"] = new_build

with open(config_path, "w", encoding="utf-8") as handle:
    json.dump(cfg, handle, indent=4, sort_keys=True)
    handle.write("\n")

print(new_build)
PY
)"
    if [ -n "${new_build}" ]; then
        BUILD_NUMBER="${new_build}"
        VERSION="${new_build}"
        log_info "Auto-bumped version/build to ${VERSION}"
    fi
}

synchronize_version_build_metadata() {
    if [ -z "${VERSION}" ] && [ -n "${BUILD_NUMBER}" ]; then
        VERSION="${BUILD_NUMBER}"
    fi
    if [ -z "${BUILD_NUMBER}" ] && [ -n "${VERSION}" ]; then
        BUILD_NUMBER="${VERSION}"
    fi
    if [ "${VERSION}" = "${BUILD_NUMBER}" ]; then
        return
    fi

    log_warning "Version/build mismatch detected (version=${VERSION}, build=${BUILD_NUMBER}); aligning build to version."
    BUILD_NUMBER="${VERSION}"

    if [ -n "${CONFIG_PATH}" ] && [ -f "${CONFIG_PATH}" ] && command -v python3 >/dev/null 2>&1; then
        python3 - "${CONFIG_PATH}" "${VERSION}" <<'PY' >/dev/null 2>&1 || true
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
version = sys.argv[2]
try:
    data = json.loads(config_path.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(0)

data["version"] = version
data["build_number"] = version
config_path.write_text(json.dumps(data, indent=4, sort_keys=True) + "\n", encoding="utf-8")
PY
    fi
}

# Notarization Configuration
NOTARIZATION_PROFILE="marcut-notarization"  # You'll need to create this

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

cleanup_path() {
    local target="$1"
    if [ ! -e "$target" ]; then
        return
    fi

    chmod -R u+w "$target" 2>/dev/null || true
    rm -rf "$target" 2>/dev/null || true

    if [ -e "$target" ]; then
        local backup="${target}.cleanup.$(date +%s)"
        mv "$target" "$backup" 2>/dev/null || true
        chmod -R u+w "$backup" 2>/dev/null || true
        rm -rf "$backup" 2>/dev/null || true
    fi

    if [ -e "$target" ]; then
        log_error "Failed to remove $target"
        exit 1
    fi
}

clear_quarantine() {
    local target="$1"
    if [ -z "$target" ] || [ ! -e "$target" ]; then
        return
    fi
    xattr -dr com.apple.quarantine "$target" 2>/dev/null || true
    xattr -cr "$target" 2>/dev/null || true
}

prune_static_artifacts() {
    local target="$1"
    if [ -z "$target" ] || [ ! -d "$target" ]; then
        return
    fi

    local count=0
    while IFS= read -r -d '' file; do
        rm -f "$file" 2>/dev/null || true
        count=$((count + 1))
    done < <(find "$target" -type f \( -name "*.a" -o -name "*.o" -o -name "*.bc" -o -name "*.ll" -o -name "*.llvm" \) -print0 2>/dev/null)

    if [ "$count" -gt 0 ]; then
        log_info "Pruned ${count} static/bitcode artifacts from ${target}"
    else
        log_info "No static/bitcode artifacts found under ${target}"
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
        log_info "Pruned ${count} Tk/Tcl artifacts from ${target}"
    else
        log_info "No Tk/Tcl artifacts found under ${target}"
    fi
}

normalize_permissions() {
    local target="$1"
    if [ -z "$target" ] || [ ! -e "$target" ]; then
        return
    fi
    log_step "Normalizing bundle permissions..."
    chmod -R u+rwX,go+rX "$target" 2>/dev/null || true
    log_step "Clearing quarantine attributes..."
    clear_quarantine "$target"
}

prune_resource_bundle_runtimes() {
    local resource_root="${APP_BUNDLE}/Contents/Resources"
    if [ ! -d "${resource_root}" ]; then
        return
    fi

    local removed=false
    while IFS= read -r -d '' path; do
        case "${path}" in
            *.bundle/*)
                log_step "Removing nested runtime: ${path}"
                cleanup_path "${path}"
                removed=true
                ;;
        esac
    done < <(find "${resource_root}" -type d \( -name "Python.framework" -o -name "python_site" \) -print0 2>/dev/null)

    if [ "${removed}" = true ]; then
        log_success "Removed nested runtimes from resource bundles"
    fi
}

validate_resource_bundle_runtimes() {
    local resource_root="${APP_BUNDLE}/Contents/Resources"
    if [ ! -d "${resource_root}" ]; then
        return
    fi
    local leftovers=""
    while IFS= read -r -d '' path; do
        case "${path}" in
            *.bundle/*)
                leftovers+="${path}"$'\n'
                ;;
        esac
    done < <(find "${resource_root}" -type d \( -name "Python.framework" -o -name "python_site" \) -print0 2>/dev/null)
    if [ -n "${leftovers}" ]; then
        log_error "Nested Python runtimes remain in resource bundles:"
        printf "%s" "${leftovers}"
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
        log_error "python_site source verification failed: repo or source package missing."
        log_info "  repo: ${repo_pkg}"
        log_info "  source: ${source_pkg}"
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
                log_error "python_site source missing file: marcut/${rel_path}"
            fi
            continue
        fi
        local repo_hash source_hash
        repo_hash="$(shasum -a 256 "${repo_file}" | awk '{print $1}')"
        source_hash="$(shasum -a 256 "${source_file}" | awk '{print $1}')"
        if [ "${repo_hash}" != "${source_hash}" ]; then
            mismatch_count=$((mismatch_count + 1))
            if [ "${mismatch_count}" -le 10 ]; then
                log_error "python_site source stale mismatch: marcut/${rel_path}"
            fi
        fi
    done < <(find "${repo_pkg}" -type f \( -name "*.py" -o -name "*.txt" \) -print0 2>/dev/null)

    if [ "${checked_count}" -eq 0 ]; then
        log_error "python_site source verification failed: no repo files found under ${repo_pkg}"
        exit 1
    fi

    if [ "${missing_count}" -gt 0 ] || [ "${mismatch_count}" -gt 0 ]; then
        log_error "python_site source verification failed (${missing_count} missing, ${mismatch_count} mismatched)."
        exit 1
    fi

    log_success "python_site source verified against repo (${checked_count} files matched)."
}

verify_python_site_source_sync() {
    local src_root="$1"
    local dst_root="$2"
    local src_pkg="${src_root}/marcut"
    local dst_pkg="${dst_root}/marcut"

    if [ ! -d "${src_pkg}" ] || [ ! -d "${dst_pkg}" ]; then
        log_error "python_site verification failed: source or destination marcut package missing."
        log_info "  source: ${src_pkg}"
        log_info "  destination: ${dst_pkg}"
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
                log_error "Missing packaged file: marcut/${rel_path}"
            fi
            continue
        fi
        local src_hash dst_hash
        src_hash="$(shasum -a 256 "${src_file}" | awk '{print $1}')"
        dst_hash="$(shasum -a 256 "${dst_file}" | awk '{print $1}')"
        if [ "${src_hash}" != "${dst_hash}" ]; then
            mismatch_count=$((mismatch_count + 1))
            if [ "${mismatch_count}" -le 10 ]; then
                log_error "Stale packaged file mismatch: marcut/${rel_path}"
            fi
        fi
    done < <(find "${src_pkg}" -type f \( -name "*.py" -o -name "*.txt" \) -print0 2>/dev/null)

    if [ "${checked_count}" -eq 0 ]; then
        log_error "python_site verification failed: no source files found under ${src_pkg}"
        exit 1
    fi

    if [ "${missing_count}" -gt 0 ] || [ "${mismatch_count}" -gt 0 ]; then
        log_error "python_site verification failed (${missing_count} missing, ${mismatch_count} mismatched)."
        exit 1
    fi

    log_success "python_site marcut package verified (${checked_count} files matched source)."
}

prepare_signing_entitlements() {
    SIGN_ENTITLEMENTS="${ENTITLEMENTS}"
    if [[ "${DEVELOPER_ID}" != "3rd Party Mac Developer Application"* && "${DEVELOPER_ID}" != "Apple Distribution"* ]]; then
        return
    fi
    if [ -z "${APPSTORE_PROFILE}" ] || [ ! -f "${APPSTORE_PROFILE}" ]; then
        log_warning "App Store provisioning profile missing; using base entitlements."
        return
    fi
    if ! command -v python3 >/dev/null 2>&1; then
        log_warning "python3 not available; using base entitlements."
        return
    fi
    local ent_path="${OUTPUT_ROOT}/appstore/entitlements.appstore.plist"
    mkdir -p "$(dirname "${ent_path}")"
    if python3 - "${ENTITLEMENTS}" "${APPSTORE_PROFILE}" "${ent_path}" <<'PY'
import plistlib
import subprocess
import sys

base_path, profile_path, out_path = sys.argv[1:4]
with open(base_path, "rb") as f:
    entitlements = plistlib.load(f)

profile_xml = subprocess.check_output(["security", "cms", "-D", "-i", profile_path])
profile = plistlib.loads(profile_xml)
profile_entitlements = profile.get("Entitlements", {})

for key in ("com.apple.application-identifier", "com.apple.developer.team-identifier"):
    if key in profile_entitlements:
        entitlements[key] = profile_entitlements[key]

with open(out_path, "wb") as f:
    plistlib.dump(entitlements, f)
PY
    then
        SIGN_ENTITLEMENTS="${ent_path}"
        log_info "Using App Store entitlements: ${SIGN_ENTITLEMENTS}"
    else
        log_warning "Failed to derive App Store entitlements; using base entitlements."
    fi
}

ensure_ollama_binary() {
    log_section "Ensuring Ollama Binary v${OLLAMA_VERSION}"

    local cache_dir="${OUTPUT_ROOT}/build_cache"
    local cached_archive="${cache_dir}/ollama-${OLLAMA_VERSION}-darwin.tgz"
    local extracted_binary="${cache_dir}/ollama-${OLLAMA_VERSION}-darwin-arm64"
    local output_binary="${OUTPUT_ROOT}/binaries/ollama_binary"

    mkdir -p "${cache_dir}"
    mkdir -p "$(dirname "${output_binary}")"

    if [ ! -f "${extracted_binary}" ]; then
        if [ ! -f "${cached_archive}" ]; then
            log_step "Downloading Ollama ${OLLAMA_VERSION} (arm64)..."
            curl -L -o "${cached_archive}.tmp" "${OLLAMA_DOWNLOAD_URL}"
            mv "${cached_archive}.tmp" "${cached_archive}"
            log_success "Downloaded Ollama archive"
        else
            log_info "Using cached Ollama archive at ${cached_archive}"
        fi

        log_step "Extracting Ollama binary..."
        tar -xzf "${cached_archive}" -C "${cache_dir}"
        mv "${cache_dir}/ollama" "${extracted_binary}"
        log_success "Extracted Ollama binary"
    else
        log_info "Using cached Ollama binary at ${extracted_binary}"
    fi

    cp "${extracted_binary}" "${output_binary}"
    chmod 755 "${output_binary}"

    local binary_size
    binary_size=$(stat -f%z "${output_binary}")
    if [ "${binary_size}" -lt 100000 ]; then
        log_error "Downloaded Ollama binary size (${binary_size}) looks invalid"
        log_info "Removing cached binary so next run re-downloads..."
        rm -f "${cached_binary}" "${output_binary}"
        exit 1
    fi

    if ! file "${output_binary}" | grep -q "Mach-O"; then
        log_error "Downloaded Ollama binary is not a Mach-O executable"
        rm -f "${cached_binary}" "${output_binary}"
        exit 1
    fi
}

# ===== UTILITY FUNCTIONS =====
log_section() {
    echo ""
    echo -e "${MAGENTA}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${MAGENTA}  $1${NC}"
    echo -e "${MAGENTA}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

log_step() {
    echo -e "${CYAN}▶️  $1${NC}"
}

# ===== VALIDATION =====
check_prerequisites() {
    log_section "Checking Prerequisites"

    if [ -z "${DEVELOPER_ID}" ]; then
        log_error "No signing identity configured."
        log_info "Set appstore_default_identity in build-scripts/config.json or export DEVELOPER_ID/CUSTOM_SIGN_IDENTITY."
        exit 1
    fi

    if [ -z "${TEAM_ID}" ]; then
        log_error "No Team ID configured."
        log_info "Set appstore_default_team_id in build-scripts/config.json or export TEAM_ID."
        exit 1
    fi

    # Check for Xcode
    if ! command -v xcodebuild &> /dev/null; then
        log_error "Xcode Command Line Tools not found"
        log_info "Install with: xcode-select --install"
        exit 1
    fi
    log_success "Xcode Command Line Tools found"

    # Check for signing identity
    if ! security find-identity -v -p codesigning | grep -q "${DEVELOPER_ID}"; then
        log_error "Signing identity '${DEVELOPER_ID}' not found"
        log_info "Available identities:"
        security find-identity -v -p codesigning
        exit 1
    fi
    log_success "Signing identity found"

    # Check for entitlements file
    if [ ! -f "${ENTITLEMENTS}" ]; then
        log_error "Entitlements file not found: ${ENTITLEMENTS}"
        exit 1
    fi
    log_success "Entitlements file found"

    if [ ! -f "${OLLAMA_ENTITLEMENTS}" ]; then
        log_error "Ollama entitlements file not found: ${OLLAMA_ENTITLEMENTS}"
        exit 1
    fi
    log_success "Ollama entitlements file found"

    # Check Swift Package
    if [ ! -f "${SWIFT_PROJECT_DIR}/Package.swift" ]; then
        log_error "Swift Package not found at ${SWIFT_PROJECT_DIR}/Package.swift"
        exit 1
    fi
    log_success "Swift Package found"

    # App Store provisioning profile validation (required for App Store uploads).
    if [[ "${DEVELOPER_ID}" == "3rd Party Mac Developer Application"* || "${DEVELOPER_ID}" == "Apple Distribution"* ]]; then
        if [ -z "${APPSTORE_PROFILE}" ] || [ ! -f "${APPSTORE_PROFILE}" ]; then
            log_error "App Store provisioning profile not found."
            log_info "Set appstore_default_profile in build-scripts/config.json."
            exit 1
        fi
        if ! command -v python3 >/dev/null 2>&1; then
            log_error "python3 is required to validate the provisioning profile."
            exit 1
        fi
        local expected_app_id="${TEAM_ID}.${BUNDLE_ID}"
        local profile_app_id profile_team_id
        IFS=$'\n' read -r profile_app_id profile_team_id < <(python3 - "${APPSTORE_PROFILE}" <<'PY'
import plistlib
import subprocess
import sys

profile_path = sys.argv[1]
try:
    xml = subprocess.check_output(["security", "cms", "-D", "-i", profile_path])
    profile = plistlib.loads(xml)
    entitlements = profile.get("Entitlements", {})
    app_id = entitlements.get("com.apple.application-identifier", "")
    team_id = entitlements.get("com.apple.developer.team-identifier", "")
    print(app_id)
    print(team_id)
except Exception:
    print("")
    print("")
PY
)
        if [ -z "${profile_app_id}" ]; then
            log_error "Unable to read application identifier from provisioning profile."
            exit 1
        fi
        if [ -n "${profile_team_id}" ] && [ "${profile_team_id}" != "${TEAM_ID}" ]; then
            log_error "Provisioning profile Team ID (${profile_team_id}) does not match ${TEAM_ID}."
            exit 1
        fi
        if [ "${profile_app_id}" != "${expected_app_id}" ]; then
            log_error "Provisioning profile app identifier (${profile_app_id}) does not match ${expected_app_id}."
            exit 1
        fi
        log_success "App Store provisioning profile validated"
    fi
}

# ===== BUILD SWIFT APP =====
build_swift_app() {
    log_section "Building Swift Application"

    # Clean previous builds
    log_step "Cleaning previous builds..."
    cleanup_path "${BUILD_DIR}"
    cleanup_path "${ARCHIVE_DIR}"
    cleanup_path "${SWIFT_BUILD_DIR}"
    mkdir -p "${BUILD_DIR}" "${ARCHIVE_DIR}"

    if [ -f "${ROOT_DIR}/scripts/render_help_html.py" ]; then
        python3 "${ROOT_DIR}/scripts/render_help_html.py"
    fi

    # Build the Swift package
    log_step "Building Swift Package (Release Configuration)..."
    cd "${SWIFT_PROJECT_DIR}"

    swift build \
        --configuration release \
        --arch arm64 \
        --build-path "${SWIFT_BUILD_DIR}"

    if [ $? -eq 0 ]; then
        log_success "Swift build completed successfully"
    else
        log_error "Swift build failed"
        exit 1
    fi

    cd "${ROOT_DIR}"
}

# ===== CREATE APP BUNDLE =====
create_app_bundle() {
    log_section "Creating App Bundle"

    log_step "Creating bundle structure..."
    cleanup_path "${APP_BUNDLE}"
    mkdir -p "${APP_BUNDLE}/Contents/MacOS"
    mkdir -p "${APP_BUNDLE}/Contents/Resources"
    mkdir -p "${APP_BUNDLE}/Contents/Frameworks"

    # Copy executable
    log_step "Installing executable..."
    local swift_binary=""
    for candidate in \
        "${SWIFT_BUILD_DIR}/release/${APP_NAME}" \
        "${SWIFT_BUILD_DIR}/arm64-apple-macosx/release/${APP_NAME}" \
        "${SWIFT_BUILD_DIR}/x86_64-apple-macosx/release/${APP_NAME}" \
        "${SWIFT_PROJECT_DIR}/.build/arm64-apple-macosx/release/${APP_NAME}" \
        "${SWIFT_PROJECT_DIR}/.build/release/${APP_NAME}"; do
        if [ -f "$candidate" ]; then
            swift_binary="$candidate"
            break
        fi
    done
    if [ -z "$swift_binary" ]; then
        log_error "Swift executable not found"
        log_info "Searched locations:"
        log_info "  - ${SWIFT_BUILD_DIR}/release/${APP_NAME}"
        log_info "  - ${SWIFT_BUILD_DIR}/arm64-apple-macosx/release/${APP_NAME}"
        log_info "  - ${SWIFT_BUILD_DIR}/x86_64-apple-macosx/release/${APP_NAME}"
        log_info "  - ${SWIFT_PROJECT_DIR}/.build/arm64-apple-macosx/release/${APP_NAME}"
        log_info "  - ${SWIFT_PROJECT_DIR}/.build/release/${APP_NAME}"
        exit 1
    fi
    cp "${swift_binary}" "${APP_BUNDLE}/Contents/MacOS/${APP_NAME}"
    chmod +x "${APP_BUNDLE}/Contents/MacOS/${APP_NAME}"

    # Copy SwiftPM resource bundle (contains Help/Forensics HTML/MD and other assets)
    local resource_bundle_name="${APP_NAME}_${APP_NAME}.bundle"
    local swift_bundle=""
    for candidate in \
        "${SWIFT_BUILD_DIR}/release/${resource_bundle_name}" \
        "${SWIFT_BUILD_DIR}/arm64-apple-macosx/release/${resource_bundle_name}" \
        "${SWIFT_BUILD_DIR}/x86_64-apple-macosx/release/${resource_bundle_name}" \
        "${SWIFT_PROJECT_DIR}/.build/arm64-apple-macosx/release/${resource_bundle_name}" \
        "${SWIFT_PROJECT_DIR}/.build/release/${resource_bundle_name}"; do
        if [ -d "$candidate" ]; then
            swift_bundle="$candidate"
            break
        fi
    done
    if [ -n "$swift_bundle" ]; then
        log_step "Copying Swift resource bundle..."
        cp -R "$swift_bundle" "${APP_BUNDLE}/Contents/Resources/"
        local bundle_target="${APP_BUNDLE}/Contents/Resources/${resource_bundle_name}"
        if [ -d "${bundle_target}/Frameworks/Python.framework" ] || [ -d "${bundle_target}/Resources/python_site" ] || [ -d "${bundle_target}/Resources/Resources/python_site" ] || [ -d "${bundle_target}/python_site" ]; then
            log_step "Removing duplicate Python runtimes from Swift resource bundle..."
            cleanup_path "${bundle_target}/Frameworks/Python.framework"
            cleanup_path "${bundle_target}/Resources/python_site"
            cleanup_path "${bundle_target}/Resources/Resources/python_site"
            cleanup_path "${bundle_target}/python_site"
        fi
        prune_resource_bundle_runtimes
    else
        log_warning "Swift resource bundle not found; help/forensics content may be missing."
    fi

    # Create Info.plist for App Store
    log_step "Creating Info.plist..."
    cat > "${APP_BUNDLE}/Contents/Info.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>${APP_NAME}</string>
    <key>CFBundleIdentifier</key>
    <string>${BUNDLE_ID}</string>
    <key>CFBundleName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleDisplayName</key>
    <string>Marcut</string>
    <key>CFBundleVersion</key>
    <string>${BUILD_NUMBER}</string>
    <key>CFBundleShortVersionString</key>
    <string>${VERSION}</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>14.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSApplicationCategoryType</key>
    <string>public.app-category.productivity</string>
    <key>NSHumanReadableCopyright</key>
    <string>Copyright © 2025 Marc Mandel. All rights reserved.</string>
    <key>CFBundleDocumentTypes</key>
    <array>
        <dict>
            <key>CFBundleTypeName</key>
            <string>Microsoft Word Document</string>
            <key>LSHandlerRank</key>
            <string>Default</string>
            <key>CFBundleTypeRole</key>
            <string>Editor</string>
            <key>LSItemContentTypes</key>
            <array>
                <string>org.openxmlformats.wordprocessingml.document</string>
                <string>com.microsoft.word.doc</string>
            </array>
            <key>CFBundleTypeExtensions</key>
            <array>
                <string>docx</string>
            </array>
        </dict>
    </array>
    <key>NSSupportsAutomaticGraphicsSwitching</key>
    <true/>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>ITSAppUsesNonExemptEncryption</key>
    <false/>
</dict>
</plist>
EOF

    # Embed provisioning profile for App Store submissions.
    if [[ "${DEVELOPER_ID}" == "3rd Party Mac Developer Application"* || "${DEVELOPER_ID}" == "Apple Distribution"* ]]; then
        if [ -n "${APPSTORE_PROFILE}" ] && [ -f "${APPSTORE_PROFILE}" ]; then
            log_step "Embedding App Store provisioning profile..."
            clear_quarantine "${APPSTORE_PROFILE}"
            cp "${APPSTORE_PROFILE}" "${APP_BUNDLE}/Contents/embedded.provisionprofile"
            clear_quarantine "${APP_BUNDLE}/Contents/embedded.provisionprofile"
        else
            log_warning "App Store provisioning profile not found; upload may be rejected."
        fi
    else
        cleanup_path "${APP_BUNDLE}/Contents/embedded.provisionprofile"
    fi

    # ===== Bundle Ollama binary (REQUIRED) =====
    log_step "Bundling Ollama runtime..."
    ensure_ollama_binary
    FOUND_OLLAMA="${OUTPUT_ROOT}/binaries/ollama_binary"
    log_step "Preparing and bundling Ollama..."
    # Best-effort cleanup of the source binary's attributes.
    if xattr -cr "$FOUND_OLLAMA" &>/dev/null; then
        log_info "Removed quarantine attributes from source Ollama"
    else
        log_info "Could not remove quarantine attributes from source (may not be present)"
    fi

    if chmod 755 "$FOUND_OLLAMA" &>/dev/null; then
        log_info "Ensured source Ollama is executable"
    else
        log_warning "Could not modify permissions on source Ollama (continuing anyway)"
    fi

    HELPER_BUNDLE="${APP_BUNDLE}/Contents/Resources/Ollama.app"
    HELPER_MACOS="${HELPER_BUNDLE}/Contents/MacOS"
    HELPER_INFO="${HELPER_BUNDLE}/Contents/Info.plist"

    cleanup_path "${HELPER_BUNDLE}"
    mkdir -p "${HELPER_MACOS}"

    cp "$FOUND_OLLAMA" "${HELPER_MACOS}/ollama"
    chmod 755 "${HELPER_MACOS}/ollama"
    xattr -cr "${HELPER_MACOS}/ollama"

    if [ -f "packaging/ollama-helper-Info.plist" ]; then
        cp "packaging/ollama-helper-Info.plist" "${HELPER_INFO}"
    else
        log_warning "Ollama helper Info.plist missing; creating fallback"
        cat > "${HELPER_INFO}" <<'EOF'
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

    log_step "Signing Ollama helper bundle..."
    codesign --force --sign "${DEVELOPER_ID}" \
        --options runtime \
        --entitlements "${OLLAMA_ENTITLEMENTS}" \
        --identifier com.marclaw.marcutapp.ollama-helper \
        "${HELPER_BUNDLE}"
    log_success "Ollama helper bundle signed"

    ln -fsh "Ollama.app/Contents/MacOS/ollama" "${APP_BUNDLE}/Contents/Resources/ollama"

    log_success "Ollama bundled from: ${FOUND_OLLAMA}"

    # ===== Bundle BeeWare Python.framework (REQUIRED) =====
    log_step "Bundling BeeWare Python.framework for App Store compatibility..."

    # Source locations from our Swift build
    # Check multiple possible locations for the framework
    SWIFT_FRAMEWORKS_SOURCE=""
    SWIFT_PYTHON_SITE_SOURCE=""
    local resource_bundle_name="${APP_NAME}_${APP_NAME}.bundle"

    # Try SwiftPM bundle locations (release first)
    if [ -d "${SWIFT_BUILD_DIR}/arm64-apple-macosx/release/${resource_bundle_name}/Frameworks" ]; then
        SWIFT_FRAMEWORKS_SOURCE="${SWIFT_BUILD_DIR}/arm64-apple-macosx/release/${resource_bundle_name}/Frameworks"
    elif [ -d "${SWIFT_BUILD_DIR}/arm64-apple-macosx/debug/${resource_bundle_name}/Frameworks" ]; then
        SWIFT_FRAMEWORKS_SOURCE="${SWIFT_BUILD_DIR}/arm64-apple-macosx/debug/${resource_bundle_name}/Frameworks"
    elif [ -d "${SWIFT_PROJECT_DIR}/.build/arm64-apple-macosx/release/${resource_bundle_name}/Frameworks" ]; then
        SWIFT_FRAMEWORKS_SOURCE="${SWIFT_PROJECT_DIR}/.build/arm64-apple-macosx/release/${resource_bundle_name}/Frameworks"
    elif [ -d "${SWIFT_PROJECT_DIR}/.build/arm64-apple-macosx/debug/${resource_bundle_name}/Frameworks" ]; then
        SWIFT_FRAMEWORKS_SOURCE="${SWIFT_PROJECT_DIR}/.build/arm64-apple-macosx/debug/${resource_bundle_name}/Frameworks"
    # Try Contents location (created by setup_beeware_framework.sh)
    elif [ -d "${SWIFT_PROJECT_DIR}/Contents/Frameworks" ]; then
        SWIFT_FRAMEWORKS_SOURCE="${SWIFT_PROJECT_DIR}/Contents/Frameworks"
    # Try Sources location (legacy)
    elif [ -d "${SWIFT_PROJECT_DIR}/Sources/MarcutApp/Frameworks" ]; then
        SWIFT_FRAMEWORKS_SOURCE="${SWIFT_PROJECT_DIR}/Sources/MarcutApp/Frameworks"
    fi

    # Only source from the tracked tree; avoid stale build-cache python_site copies.
    SWIFT_PYTHON_SITE_SOURCE="${PYTHON_SITE_SOURCE}"

    # Verify source framework exists
    if [ -z "$SWIFT_FRAMEWORKS_SOURCE" ] || [ ! -d "${SWIFT_FRAMEWORKS_SOURCE}/Python.framework" ]; then
        log_error "BeeWare Python.framework not found"
        log_info "Searched locations:"
        log_info "  - ${SWIFT_BUILD_DIR}/arm64-apple-macosx/release/${resource_bundle_name}/Frameworks/Python.framework"
        log_info "  - ${SWIFT_BUILD_DIR}/arm64-apple-macosx/debug/${resource_bundle_name}/Frameworks/Python.framework"
        log_info "  - ${SWIFT_PROJECT_DIR}/.build/arm64-apple-macosx/release/${resource_bundle_name}/Frameworks/Python.framework"
        log_info "  - ${SWIFT_PROJECT_DIR}/.build/arm64-apple-macosx/debug/${resource_bundle_name}/Frameworks/Python.framework"
        log_info "  - ${SWIFT_PROJECT_DIR}/Contents/Frameworks/Python.framework"
        log_info "  - ${SWIFT_PROJECT_DIR}/Sources/MarcutApp/Frameworks/Python.framework"
        log_info ""
        log_info "Solutions:"
        log_info "  1. Run './setup_beeware_framework.sh' first to set up the framework"
        log_info "  2. Or build the Swift project first: cd ${SWIFT_PROJECT_DIR} && swift build"
        exit 1
    fi

    log_info "Found framework at: ${SWIFT_FRAMEWORKS_SOURCE}/Python.framework"

    # Copy framework to Contents/Frameworks (production location)
    log_step "Installing Python.framework to Contents/Frameworks..."
    cleanup_path "${APP_BUNDLE}/Contents/Frameworks/Python.framework"
    cp -R "${SWIFT_FRAMEWORKS_SOURCE}/Python.framework" "${APP_BUNDLE}/Contents/Frameworks/"
    log_success "Python.framework installed ($(du -sh "${APP_BUNDLE}/Contents/Frameworks/Python.framework" | cut -f1))"

    # Copy python_site to Contents/Resources (our dependencies)
    log_step "Installing python_site dependencies..."
    cleanup_path "${APP_BUNDLE}/Contents/Resources/python_site"
    if [ -n "$SWIFT_PYTHON_SITE_SOURCE" ] && [ -d "${SWIFT_PYTHON_SITE_SOURCE}" ]; then
        verify_python_repo_sync "${PYTHON_SITE_REPO_SOURCE}" "${SWIFT_PYTHON_SITE_SOURCE}"
        cp -R "${SWIFT_PYTHON_SITE_SOURCE}" "${APP_BUNDLE}/Contents/Resources/python_site"
        log_success "python_site installed ($(du -sh "${APP_BUNDLE}/Contents/Resources/python_site" | cut -f1))"
        log_info "Source: ${SWIFT_PYTHON_SITE_SOURCE}"
        verify_python_site_source_sync "${SWIFT_PYTHON_SITE_SOURCE}" "${APP_BUNDLE}/Contents/Resources/python_site"
    else
        log_error "python_site not found"
        log_info "Searched locations:"
        log_info "  - ${PYTHON_SITE_SOURCE}"
        log_info ""
        log_info "Run './setup_beeware_framework.sh' to install Python dependencies"
        exit 1
    fi

    log_step "Pruning Tk/Tcl artifacts from embedded Python payload..."
    prune_tk_artifacts "${APP_BUNDLE}/Contents/Frameworks/Python.framework"
    prune_tk_artifacts "${APP_BUNDLE}/Contents/Resources/python_site"

    log_step "Pruning static/bitcode artifacts from embedded Python.framework..."
    prune_static_artifacts "${APP_BUNDLE}/Contents/Frameworks/Python.framework"

    # Sign embedded BeeWare framework and python_site with Developer ID so macOS allows execution
    log_step "Signing embedded BeeWare framework and python_site…"
    sign_with_id() {
        local target="$1"
        if file "$target" | grep -q "Mach-O"; then
            echo "  Signing: $target"
            codesign --force --sign "${DEVELOPER_ID}" --options runtime --timestamp "$target" 2>/dev/null || {
                echo "    Warning: Could not sign $target"
            }
        fi
    }

    # Sign BeeWare Python.framework
    FRAMEWORK_PATH="${APP_BUNDLE}/Contents/Frameworks/Python.framework"
    if [ -d "$FRAMEWORK_PATH" ]; then
        # Sign main Python library
        [ -f "$FRAMEWORK_PATH/Python" ] && sign_with_id "$FRAMEWORK_PATH/Python"

        # Sign all dylibs, .so files, .o files, and executables in the framework
        while IFS= read -r f; do sign_with_id "$f"; done < <(find "$FRAMEWORK_PATH" -type f \( -name "*.dylib" -o -name "*.so" -o -name "*.o" -o -perm +111 \) 2>/dev/null)

        log_success "BeeWare Python.framework signed"
    else
        log_error "BeeWare Python.framework not found at $FRAMEWORK_PATH"
        exit 1
    fi

    # Sign python_site dependencies
    PYTHON_SITE_PATH="${APP_BUNDLE}/Contents/Resources/python_site"
    if [ -d "$PYTHON_SITE_PATH" ]; then
        while IFS= read -r f; do sign_with_id "$f"; done < <(find "$PYTHON_SITE_PATH" -type f \( -name "*.dylib" -o -name "*.so" -o -name "*.o" -o -perm +111 \) 2>/dev/null)
        log_success "python_site dependencies signed"
    fi

    # Copy additional resources
    local excluded_words_source=""
    for candidate in "assets/excluded-words.txt" "src/python/marcut/excluded-words.txt" "excluded-words.txt"; do
        if [ -f "$candidate" ]; then
            excluded_words_source="$candidate"
            break
        fi
    done
    if [ -n "$excluded_words_source" ]; then
        cp "$excluded_words_source" "${APP_BUNDLE}/Contents/Resources/excluded-words.txt"
    fi
    local system_prompt_source=""
    for candidate in "assets/system-prompt.txt" "system-prompt.txt"; do
        if [ -f "$candidate" ]; then
            system_prompt_source="$candidate"
            break
        fi
    done
    if [ -n "$system_prompt_source" ]; then
        cp "$system_prompt_source" "${APP_BUNDLE}/Contents/Resources/system-prompt.txt"
    fi
    local assets_dir="${ASSETS_DIR:-${ROOT_DIR}/assets}"
    local swift_resources_dir="${SWIFT_PROJECT_DIR}/Sources/MarcutApp/Resources"
    local help_md_source=""
    for candidate in "${assets_dir}/help.md" "${ROOT_DIR}/assets/help.md"; do
        if [ -f "$candidate" ]; then
            help_md_source="$candidate"
            break
        fi
    done
    if [ -n "$help_md_source" ]; then
        cp "$help_md_source" "${APP_BUNDLE}/Contents/Resources/help.md"
    fi
    local forensics_md_source=""
    for candidate in "${assets_dir}/forensics-guide.md" "${ROOT_DIR}/assets/forensics-guide.md"; do
        if [ -f "$candidate" ]; then
            forensics_md_source="$candidate"
            break
        fi
    done
    if [ -n "$forensics_md_source" ]; then
        cp "$forensics_md_source" "${APP_BUNDLE}/Contents/Resources/forensics-guide.md"
    fi
    local privacy_manifest_source=""
    for candidate in "${swift_resources_dir}/PrivacyInfo.xcprivacy" "${assets_dir}/PrivacyInfo.xcprivacy" "${ROOT_DIR}/assets/PrivacyInfo.xcprivacy"; do
        if [ -f "$candidate" ]; then
            privacy_manifest_source="$candidate"
            break
        fi
    done
    if [ -n "$privacy_manifest_source" ]; then
        cp "$privacy_manifest_source" "${APP_BUNDLE}/Contents/Resources/PrivacyInfo.xcprivacy"
    else
        log_warning "PrivacyInfo.xcprivacy not found; App Store validation may fail."
    fi
    if [ -d "$swift_resources_dir" ]; then
        [ -f "${swift_resources_dir}/help.html" ] && cp "${swift_resources_dir}/help.html" "${APP_BUNDLE}/Contents/Resources/help.html"
        [ -f "${swift_resources_dir}/forensics-guide.html" ] && cp "${swift_resources_dir}/forensics-guide.html" "${APP_BUNDLE}/Contents/Resources/forensics-guide.html"
    fi
    if [ -f "pyproject.toml" ]; then
        cp "pyproject.toml" "${APP_BUNDLE}/Contents/Resources/"
    fi

    # Add app icon
    local icns_source=""
    for candidate in "${ASSETS_DIR:-}/AppIcon.icns" "${ROOT_DIR}/assets/AppIcon.icns" "${ROOT_DIR}/assets/MarcutApp.icns" "${ROOT_DIR}/assets/MarcutApp-Icon.icns"; do
        if [ -n "$candidate" ] && [ -f "$candidate" ]; then
            icns_source="$candidate"
            break
        fi
    done

    if [ -n "$icns_source" ]; then
        log_step "Installing app icon..."
        mkdir -p "${APP_BUNDLE}/Contents/Resources"
        cp "$icns_source" "${APP_BUNDLE}/Contents/Resources/AppIcon.icns"
        log_success "App icon installed"
    else
        local icon_source=""
        for candidate in "${ASSETS_DIR:-}/MarcutApp-Icon.png" "${ROOT_DIR}/assets/MarcutApp-Icon.png" "${ROOT_DIR}/MarcutApp-Icon.png"; do
            if [ -n "$candidate" ] && [ -f "$candidate" ]; then
                icon_source="$candidate"
                break
            fi
        done
        if [ -n "$icon_source" ]; then
            log_step "Creating app icon..."
            mkdir -p "${APP_BUNDLE}/Contents/Resources"
            iconutil_dir="AppIcon.iconset"
            mkdir -p "$iconutil_dir"

            # Generate icon sizes
            sips -z 16 16 "$icon_source" --out "$iconutil_dir/icon_16x16.png"
            sips -z 32 32 "$icon_source" --out "$iconutil_dir/icon_16x16@2x.png"
            sips -z 32 32 "$icon_source" --out "$iconutil_dir/icon_32x32.png"
            sips -z 64 64 "$icon_source" --out "$iconutil_dir/icon_32x32@2x.png"
            sips -z 128 128 "$icon_source" --out "$iconutil_dir/icon_128x128.png"
            sips -z 256 256 "$icon_source" --out "$iconutil_dir/icon_128x128@2x.png"
            sips -z 256 256 "$icon_source" --out "$iconutil_dir/icon_256x256.png"
            sips -z 512 512 "$icon_source" --out "$iconutil_dir/icon_256x256@2x.png"
            sips -z 512 512 "$icon_source" --out "$iconutil_dir/icon_512x512.png"
            sips -z 1024 1024 "$icon_source" --out "$iconutil_dir/icon_512x512@2x.png"

            # Create icns file
            iconutil -c icns "$iconutil_dir" -o "${APP_BUNDLE}/Contents/Resources/AppIcon.icns"
            rm -rf "$iconutil_dir"
            log_success "App icon created"
        else
            log_warning "App icon source not found; expected assets/AppIcon.icns or assets/MarcutApp-Icon.png"
        fi
    fi

    # ===== Final bundle verification =====
    normalize_permissions "${APP_BUNDLE}"
    log_step "Verifying bundled runtimes..."
    if [ -x "${APP_BUNDLE}/Contents/Resources/ollama" ]; then
        log_success "Ollama present and executable"
    else
        log_error "Ollama missing in app bundle"; exit 1
    fi
    if [ -f "${APP_BUNDLE}/Contents/Frameworks/Python.framework/Python" ]; then
        log_success "BeeWare Python.framework present"
    else
        log_error "BeeWare Python.framework missing"; exit 1
    fi
    if [ -d "${APP_BUNDLE}/Contents/Resources/python_site" ]; then
        log_success "python_site present (Python dependencies)"
    else
        log_error "python_site missing"; exit 1
    fi
    if [ -f "${APP_BUNDLE}/Contents/Resources/PrivacyInfo.xcprivacy" ]; then
        log_success "PrivacyInfo.xcprivacy present"
    else
        log_error "PrivacyInfo.xcprivacy missing"; exit 1
    fi
}

# ===== CODE SIGNING =====
sign_app_bundle() {
    log_section "Code Signing Application"

    # Remove any existing signatures
    log_step "Removing existing signatures..."
    codesign --remove-signature "${APP_BUNDLE}" 2>/dev/null || true

    # Sign all framework bundles and executable objects first
    log_step "Signing frameworks and libraries..."
    while IFS= read -r framework; do
        codesign --force --deep --sign "${DEVELOPER_ID}" \
            --entitlements "${SIGN_ENTITLEMENTS}" \
            --options runtime \
            --timestamp \
            "$framework"
    done < <(find "${APP_BUNDLE}/Contents/Frameworks" -type d -name "*.framework" 2>/dev/null)

    while IFS= read -r lib; do
        codesign --force --deep --sign "${DEVELOPER_ID}" \
            --entitlements "${SIGN_ENTITLEMENTS}" \
            --options runtime \
            --timestamp \
            "$lib"
    done < <(find "${APP_BUNDLE}/Contents/Frameworks" -type f \( -name "*.dylib" -o -name "*.so" -o -perm -111 \) 2>/dev/null)

    # Sign the embedded Ollama binary
    log_step "Signing embedded Ollama binary..."
    if [ -f "${APP_BUNDLE}/Contents/Resources/ollama" ]; then
        codesign --force --sign "${DEVELOPER_ID}" \
            --entitlements "${OLLAMA_ENTITLEMENTS}" \
            --options runtime \
            --timestamp \
            "${APP_BUNDLE}/Contents/Resources/ollama"
        log_success "Ollama binary signed"
        # Verify the signature and entitlements on the binary
        log_info "Verifying Ollama binary signature..."
        codesign --verify --deep --strict --verbose=2 "${APP_BUNDLE}/Contents/Resources/ollama"
        codesign -d --entitlements :- "${APP_BUNDLE}/Contents/Resources/ollama"
    else
        log_warning "Ollama binary not found for signing"
    fi

    # Sign the main app bundle
    log_step "Signing main application bundle..."
    codesign --force --deep --sign "${DEVELOPER_ID}" \
        --entitlements "${SIGN_ENTITLEMENTS}" \
        --options runtime \
        --timestamp \
        --preserve-metadata=identifier,entitlements,requirements \
        "${APP_BUNDLE}"

    # Verify signature
    log_step "Verifying code signature..."
    log_info "App bundle path: ${APP_BUNDLE}"
    if codesign --verify --deep --strict --verbose=2 "${APP_BUNDLE}"; then
        log_success "Code signature verified"
    else
        log_warning "Code signature verification failed; continuing to DMG creation for testing"
    fi

    # Check signature details
    log_step "Signature details:"
    codesign -dvv "${APP_BUNDLE}" 2>&1 | grep -E "(Authority|TeamIdentifier|Timestamp)"
}

create_xcarchive() {
    log_section "Creating App Store Archive"

    cleanup_path "${ARCHIVE_PATH}"
    mkdir -p "${ARCHIVE_PATH}/Products/Applications"

    log_step "Copying app bundle into archive..."
    cp -R "${APP_BUNDLE}" "${ARCHIVE_PATH}/Products/Applications/${APP_NAME}.app"
    normalize_permissions "${ARCHIVE_PATH}"

    log_step "Writing archive metadata..."
    cat > "${ARCHIVE_PATH}/Info.plist" <<EOF
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
        <string>${DEVELOPER_ID}</string>
        <key>Team</key>
        <string>${TEAM_ID}</string>
    </dict>
    <key>ArchiveVersion</key>
    <integer>2</integer>
    <key>Name</key>
    <string>${APP_NAME}</string>
    <key>SchemeName</key>
    <string>${APP_NAME}</string>
</dict>
</plist>
EOF

    log_success "Archive created at ${ARCHIVE_PATH}"
}

# ===== CREATE DMG =====
create_dmg() {
    log_section "Creating DMG Installer"

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
        log_warning "CFBundleShortVersionString (${short_version}) and CFBundleVersion (${build_version}) differ; using ${short_version} for DMG naming."
    fi

    local computed_name="${APP_NAME}-v${dmg_version}-AppStore"
    local final_dmg="${FINAL_DMG}"
    if [ -n "${final_dmg}" ]; then
        local replaced="${final_dmg//$VERSION/$dmg_version}"
        if [ "${replaced}" != "${final_dmg}" ]; then
            final_dmg="${replaced}"
        else
            local final_dir
            final_dir="$(dirname "${final_dmg}")"
            final_dmg="${final_dir}/${computed_name}.dmg"
        fi
    else
        final_dmg="${OUTPUT_ROOT}/${computed_name}.dmg"
    fi

    DMG_NAME="${computed_name}"
    FINAL_DMG="${final_dmg}"

    # Clean previous DMG
    cleanup_path "${FINAL_DMG}"
    cleanup_path "${DMG_NAME}-temp.dmg"

    # Create staged DMG with background + Applications alias
    log_step "Creating DMG..."
    local staging_dir
    staging_dir="$(mktemp -d "${OUTPUT_ROOT}/dmg_stage.XXXX")"
    local temp_dmg="${DMG_NAME}-temp.dmg"

    ditto "${APP_BUNDLE}" "${staging_dir}/${APP_NAME}.app"
    ln -s /Applications "${staging_dir}/Applications"

    hdiutil create -volname "${VOLUME_NAME}" \
        -srcfolder "${staging_dir}" \
        -ov -format UDRW \
        "${temp_dmg}"

    local volume_mount="/Volumes/${VOLUME_NAME}"
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
        if [ -f "${ROOT_DIR}/assets/dmg-background.png" ]; then
            # Finder renders DMG backgrounds in point space; downscale retina assets
            # so the full composition is visible at the configured window size.
            if command -v sips >/dev/null 2>&1; then
                sips -z 520 800 "${ROOT_DIR}/assets/dmg-background.png" \
                    --out "${mount_dir}/.background/dmg-background.png" >/dev/null 2>&1 \
                    || cp "${ROOT_DIR}/assets/dmg-background.png" "${mount_dir}/.background/"
            else
                cp "${ROOT_DIR}/assets/dmg-background.png" "${mount_dir}/.background/"
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

    hdiutil convert "${temp_dmg}" -format UDZO -imagekey zlib-level=9 -o "${FINAL_DMG}"
    rm -f "${temp_dmg}"
    rm -f "${temp_dmg}.shadow"
    rm -rf "${staging_dir}"

    # Sign the DMG
    log_step "Signing DMG..."
    codesign --force --sign "${DEVELOPER_ID}" \
        --timestamp \
        "${FINAL_DMG}"

    log_success "DMG created: ${FINAL_DMG}"
    log_info "Size: $(du -sh "${FINAL_DMG}" | cut -f1)"
}

# ===== NOTARIZATION =====
notarize_dmg() {
    log_section "Notarizing for App Store"

    if [ "${SKIP_NOTARIZATION:-false}" = "true" ]; then
        log_warning "Skipping notarization (SKIP_NOTARIZATION=true)"
        return 0
    fi

    log_info "Using notarization profile: ${NOTARIZATION_PROFILE}"

    # Submit for notarization
    log_step "Submitting DMG for notarization (this may take a few minutes)..."
    set +e
    NOTARIZATION_OUTPUT=$(xcrun notarytool submit "${FINAL_DMG}" \
        --keychain-profile "${NOTARIZATION_PROFILE}" \
        --wait 2>&1)
    NOTARIZATION_STATUS=$?
    set -e

    if [ "${NOTARIZATION_STATUS}" -ne 0 ]; then
        if echo "${NOTARIZATION_OUTPUT}" | grep -q "No Keychain password item found"; then
            log_warning "Notarization skipped: keychain profile '${NOTARIZATION_PROFILE}' not found."
            return 0
        fi
        log_error "Notarization failed"
        echo "${NOTARIZATION_OUTPUT}"
        exit 1
    fi

    echo "$NOTARIZATION_OUTPUT"

    SUBMISSION_ID=$(echo "$NOTARIZATION_OUTPUT" | grep -E "id: [a-f0-9-]+" | head -1 | awk '{print $2}')

    if [ -z "$SUBMISSION_ID" ]; then
        log_error "Failed to get submission ID"
        exit 1
    fi

    log_info "Submission ID: ${SUBMISSION_ID}"

    # Check notarization status
    log_step "Checking notarization status..."
    xcrun notarytool info "${SUBMISSION_ID}" \
        --keychain-profile "${NOTARIZATION_PROFILE}"

    # Get notarization log if needed
    log_step "Getting notarization log..."
    local notarization_log_dir="${OUTPUT_ROOT}/notarization"
    mkdir -p "${notarization_log_dir}"
    local notarization_log="${notarization_log_dir}/notarization-log.json"
    xcrun notarytool log "${SUBMISSION_ID}" \
        --keychain-profile "${NOTARIZATION_PROFILE}" \
        "${notarization_log}"
    log_info "Notarization log saved: ${notarization_log}"

    # Staple the notarization ticket
    log_step "Stapling notarization ticket to DMG..."
    if xcrun stapler staple "${FINAL_DMG}"; then
        log_success "Notarization ticket stapled successfully"
    else
        log_error "Failed to staple notarization ticket"
        exit 1
    fi

    # Verify notarization
    log_step "Verifying notarization..."
    if spctl -a -t open --context context:primary-signature -v "${FINAL_DMG}"; then
        log_success "DMG is properly notarized and ready for distribution"
    else
        log_warning "Notarization verification had issues"
    fi
}

# ===== VALIDATION =====
final_validation() {
    log_section "Final Validation"

    log_step "App bundle validation..."
    codesign --verify --deep --strict --verbose=2 "${APP_BUNDLE}"

    log_step "DMG validation..."
    hdiutil verify "${FINAL_DMG}"

    if [ "${SKIP_NOTARIZATION:-false}" = "true" ]; then
        log_warning "Notarization validation skipped (SKIP_NOTARIZATION=true)"
    else
        log_step "Notarization validation..."
        spctl -a -t open --context context:primary-signature -v "${FINAL_DMG}" || true
    fi

    log_success "All validations complete"
}

clean_app_logs() {
    log_section "Cleaning Application Logs"

    # Clean non-sandboxed app logs
    local nonsandboxed_logs="$HOME/Library/Application Support/MarcutApp/logs/marcut.log"
    if [ -f "$nonsandboxed_logs" ]; then
        log_step "Removing non-sandboxed app logs..."
        rm -f "$nonsandboxed_logs"
        log_success "Non-sandboxed logs removed"
    fi

    # Clean sandboxed app logs (from installed app)
    local sandboxed_logs="$HOME/Library/Containers/com.marclaw.marcutapp/Data/Library/Application Support/MarcutApp/logs/marcut.log"
    if [ -f "$sandboxed_logs" ]; then
        log_step "Removing sandboxed app logs..."
        rm -f "$sandboxed_logs"
        log_success "Sandboxed logs removed"
    fi

    log_success "Application logs cleaned - fresh start for production build"
}

# ===== MAIN EXECUTION =====
main() {
    # Parse command line arguments
    SKIP_NOTARIZATION=false
    for arg in "$@"; do
        case $arg in
            --skip-notarization)
                SKIP_NOTARIZATION=true
                shift
                ;;
            --team-id=*)
                TEAM_ID="${arg#*=}"
                shift
                ;;
            --no-bump)
                AUTO_BUMP_BUILD_NUMBER=false
                shift
                ;;
            --auto-bump)
                AUTO_BUMP_BUILD_NUMBER=true
                shift
                ;;
            --help)
                echo "Usage: $0 [options]"
                echo "Options:"
                echo "  --skip-notarization    Skip the notarization step"
                echo "  --team-id=ID          Set Team ID for signing"
                echo "  --auto-bump           Enable version/build auto-bump"
                echo "  --no-bump             Disable version/build auto-bump (default)"
                echo "  --help                Show this help message"
                exit 0
                ;;
        esac
    done

    auto_bump_build_number
    synchronize_version_build_metadata

    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║          MarcutApp - App Store Distribution Build           ║${NC}"
    echo -e "${CYAN}║                     Version ${VERSION}                          ║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"

    if [ "$SKIP_NOTARIZATION" = false ]; then
        if [[ "${DEVELOPER_ID}" != "Developer ID Application"* ]]; then
            log_warning "Notarization requires a Developer ID Application certificate."
            log_warning "Current signing identity: ${DEVELOPER_ID}"
            log_warning "Skipping notarization for App Store identity."
            log_warning "Use scripts/sh/build_devid_release.sh for direct distribution."
            SKIP_NOTARIZATION=true
        fi
    fi

    # Run build pipeline
    check_prerequisites
    clean_app_logs
    build_swift_app
    create_app_bundle
    prune_resource_bundle_runtimes
    validate_resource_bundle_runtimes
    prepare_signing_entitlements
    sign_app_bundle
    create_xcarchive
    create_dmg

    if [ "$SKIP_NOTARIZATION" = false ]; then
        notarize_dmg
    else
        log_warning "Skipping notarization (SKIP_NOTARIZATION=true)"
    fi

    final_validation

    # Summary
    log_section "Build Complete! 🎉"
    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}  SUCCESS: ${APP_NAME} v${VERSION} ready for App Store${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo "📦 Distribution Package: ${FINAL_DMG}"
    echo "📏 Size: $(du -sh "${FINAL_DMG}" | cut -f1)"
    echo "🔐 Signed with: ${DEVELOPER_ID}"
    if [ "$SKIP_NOTARIZATION" = false ]; then
        echo "✅ Notarized and ready for direct distribution"
    else
        echo "ℹ️  Notarization skipped for App Store identity"
    fi
    echo ""
    echo "📋 Next Steps:"
    echo "   1. Test the DMG: open \"${FINAL_DMG}\""
    echo "   2. Upload to App Store Connect"
    echo "   3. Submit for App Review"
    echo ""
}

# Run main function
main "$@"

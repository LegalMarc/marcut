#!/usr/bin/env bash
# Release preflight gate.
#
# Wraps the automatable subset of docs/RELEASE_CHECKLIST.md section 1
# ("Pre-Release Checks") into a single command that fails fast on the first
# broken step and prints a clear PASS/FAIL summary line per step:
#   1. Python test suite (pytest)
#   2. Swift test suite (swift test)
#   3. SBOM generate + check
#   4. Dependency vulnerability audit
#   5. Markdown link check
#   6. Version-sync check (build-scripts/config.json vs last tagged release)
#   7. Secrets check (build-scripts/config.json must not be tracked by git)
#
# A release must not proceed if any step is silently skipped, so this script
# does not continue past the first failing step. It does not modify any
# tracked files (SBOM regeneration writes docs/release/python-sbom.json,
# which is expected to change and is already tracked).
#
# Usage:
#   bash scripts/release_preflight.sh
#
# Optional env:
#   RELEASE_PREFLIGHT_BUNDLE_ROOT - path to a built MarcutApp.app to derive
#     the SBOM from (passed as --bundle-root to generate_python_sbom.py),
#     matching RELEASE_CHECKLIST.md's guidance to point at the real bundle
#     for release validation. Defaults to the staged repo checkout.

set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

log() { printf "\033[0;34m[preflight]\033[0m %s\n" "$*"; }
ok()  { printf "\033[0;32m✓ PASS\033[0m %s\n" "$*"; }
err() { printf "\033[0;31m✗ FAIL\033[0m %s\n" "$*"; }

STEP_NAMES=()
STEP_RESULTS=()

run_step() {
  local name="$1"; shift
  log "Running: $name"
  if "$@"; then
    ok "$name"
    STEP_NAMES+=("$name")
    STEP_RESULTS+=("PASS")
    return 0
  else
    err "$name"
    STEP_NAMES+=("$name")
    STEP_RESULTS+=("FAIL")
    print_summary
    exit 1
  fi
}

print_summary() {
  echo ""
  log "Summary:"
  local i
  for i in "${!STEP_NAMES[@]}"; do
    if [ "${STEP_RESULTS[$i]}" = "PASS" ]; then
      printf "  \033[0;32mPASS\033[0m  %s\n" "${STEP_NAMES[$i]}"
    else
      printf "  \033[0;31mFAIL\033[0m  %s\n" "${STEP_NAMES[$i]}"
    fi
  done
}

step_python_tests() {
  PYTHONPATH=src/python python3 -m pytest -q
}

step_swift_tests() {
  swift test --package-path src/swift/MarcutApp
}

step_sbom() {
  if [ -n "${RELEASE_PREFLIGHT_BUNDLE_ROOT:-}" ]; then
    python3 scripts/generate_python_sbom.py --output docs/release/python-sbom.json --bundle-root "$RELEASE_PREFLIGHT_BUNDLE_ROOT" \
      && python3 scripts/generate_python_sbom.py --check --bundle-root "$RELEASE_PREFLIGHT_BUNDLE_ROOT"
  else
    python3 scripts/generate_python_sbom.py --output docs/release/python-sbom.json \
      && python3 scripts/generate_python_sbom.py --check
  fi
}

step_dependency_audit() {
  python3 scripts/check_dependency_vulnerabilities.py --sbom docs/release/python-sbom.json
}

step_markdown_links() {
  python3 scripts/check_markdown_links.py
}

step_version_sync() {
  local config_path="build-scripts/config.json"
  if [ ! -f "$config_path" ]; then
    err "Missing $config_path"
    return 1
  fi

  local version build_number
  version=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('version') or '')" "$config_path")
  build_number=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('build_number') or '')" "$config_path")

  if [ -z "$version" ] || [ -z "$build_number" ]; then
    err "$config_path is missing a non-empty 'version' and/or 'build_number' field"
    return 1
  fi

  local last_tag
  if last_tag=$(git describe --tags --abbrev=0 2>/dev/null); then
    local last_tag_version="${last_tag#v}"
    if [ "$version" = "$last_tag_version" ]; then
      err "build-scripts/config.json version ($version) matches the last tagged release ($last_tag); bump version/build_number for a new release"
      return 1
    fi
    log "Version $version differs from last tagged release $last_tag"
  else
    log "No git tags found; only checking that version/build_number are present"
  fi

  return 0
}

step_secrets_check() {
  local config_path="build-scripts/config.json"
  if git ls-files --error-unmatch "$config_path" >/dev/null 2>&1; then
    err "$config_path is tracked by git; it must stay untracked (use build-scripts/config.example.json instead)"
    return 1
  fi
  return 0
}

main() {
  run_step "Python test suite" step_python_tests
  run_step "Swift test suite" step_swift_tests
  run_step "SBOM generate + check" step_sbom
  run_step "Dependency vulnerability audit" step_dependency_audit
  run_step "Markdown link check" step_markdown_links
  run_step "Version-sync check" step_version_sync
  run_step "Secrets check (config.json untracked)" step_secrets_check

  print_summary
  echo ""
  log "All release preflight checks passed."
}

main "$@"

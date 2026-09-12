#!/usr/bin/env bash
set -euo pipefail

APP_BUNDLE=${1:?"Usage: scripts/verify_entitlements.sh /path/to/MarcutApp.app [helper.app]"}
HELPER_BUNDLE=${2:-"${APP_BUNDLE}/Contents/Resources/Ollama.app"}

check_entitlements() {
  local label="$1"
  local bundle="$2"
  if [ ! -e "$bundle" ]; then
    echo "ENTITLEMENTS: SKIP ${label} (${bundle} not found)"
    return 0
  fi
  echo "ENTITLEMENTS: ${label} ${bundle}"
  local output
  output="$(codesign -d --entitlements :- "$bundle" 2>/dev/null || true)"
  if [ -z "$output" ]; then
    echo "ENTITLEMENTS: FAILED (${label} has no readable entitlements)" >&2
    return 1
  fi
  printf '%s\n' "$output"
  for forbidden in \
    "com.apple.security.cs.disable-library-validation" \
    "com.apple.security.cs.allow-jit" \
    "com.apple.security.get-task-allow"; do
    if printf '%s\n' "$output" | grep -q "$forbidden"; then
      echo "ENTITLEMENTS: FAILED (${label} contains forbidden entitlement ${forbidden})" >&2
      return 1
    fi
  done
}

check_entitlements "app" "$APP_BUNDLE"
check_entitlements "ollama-helper" "$HELPER_BUNDLE"
echo "ENTITLEMENTS: OK"

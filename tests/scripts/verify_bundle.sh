#!/usr/bin/env bash
# Artifact verification for Marcut app bundles and DMGs
# Usage:
#   scripts/verify_bundle.sh /path/to/MarcutApp.app
#   scripts/verify_bundle.sh /path/to/MarcutApp-*.dmg

set -euo pipefail

print_ok()  { printf "\033[0;32m✓ %s\033[0m\n" "$1"; }
print_warn(){ printf "\033[1;33m⚠ %s\033[0m\n" "$1"; }
print_err() { printf "\033[0;31m✗ %s\033[0m\n" "$1"; }

pass_count=0
fail_count=0

req_exec() {
  if [ -x "$1" ]; then print_ok "$2"; pass_count=$((pass_count+1)); else print_err "$3"; fail_count=$((fail_count+1)); fi
}

req_exists() {
  if [ -e "$1" ]; then print_ok "$2"; pass_count=$((pass_count+1)); else print_err "$3"; fail_count=$((fail_count+1)); fi
}

check_app() {
  local APP="$1"
  echo "Verifying app: $APP"
  local MACOS="$APP/Contents/MacOS/MarcutApp"
  local RES="$APP/Contents/Resources"
  local OLLAMA="$APP/Contents/MacOS/ollama"
  local PYLIB="$APP/Contents/Frameworks/Python.framework/Python"
  local PY_SITE="$RES/python_site"
  local LAUNCHER=""

  req_exec "$MACOS"   "MarcutApp executable present" "Missing or not executable: $MACOS"
  if [ -x "$OLLAMA" ]; then
    req_exec "$OLLAMA"  "Ollama present and executable" "Missing or not executable: $OLLAMA"
  else
    OLLAMA="$RES/ollama"
    req_exec "$OLLAMA"  "Ollama present and executable" "Missing or not executable: $OLLAMA"
  fi
  req_exists "$PYLIB" "BeeWare Python.framework library present" "Missing: $PYLIB"
  req_exists "$PY_SITE" "python_site payload present" "Missing: $PY_SITE"

  local CANDIDATES=(
    "$RES/run_python.sh"
    "$RES/python_launcher.sh"
    "$RES/MarcutApp_MarcutApp.bundle/Resources/run_python.sh"
    "$RES/MarcutApp_MarcutApp.bundle/Resources/python_launcher.sh"
  )
  for candidate in "${CANDIDATES[@]}"; do
    if [ -x "$candidate" ]; then
      LAUNCHER="$candidate"
      break
    fi
  done
  if [ -n "$LAUNCHER" ]; then
    req_exec "$LAUNCHER" "Python launcher present" "Missing or not executable: $LAUNCHER"
  else
    print_err "No usable python launcher found in $APP"
    fail_count=$((fail_count+1))
    return
  fi

  # Execute embedded interpreter via launcher to catch spawn errors (DMG/read-only safe)
  if /bin/bash "$LAUNCHER" -c 'import sys, numpy, lxml.etree; print("ok")' >/dev/null 2>&1; then
    print_ok "BeeWare Python executes successfully via launcher"
    pass_count=$((pass_count+1))
  else
    print_err "Launcher failed to execute BeeWare Python"
    fail_count=$((fail_count+1))
  fi

  # Perform a tiny redaction using mock backend to validate CLI path
  local TMP
  TMP=$(mktemp -d 2>/dev/null || mktemp -d -t marcut)
  local INP="$TMP/test.docx"; local OUTDOC="$TMP/out.docx"; local OUTJSON="$TMP/out.json"
  if /bin/bash "$LAUNCHER" - "$INP" << 'PY'
from docx import Document
from pathlib import Path
import sys
inp = Path(sys.argv[1])
doc = Document()
doc.add_paragraph('Contact: sample123@example.com and https://example.com')
doc.save(inp)
print('ok')
PY
  then
    print_ok "DOCX fixture created"
    pass_count=$((pass_count+1))
  else
    print_err "Failed to create DOCX fixture via embedded python"
    fail_count=$((fail_count+1))
  fi

  if /bin/bash "$LAUNCHER" -m marcut.cli redact --in "$INP" --out "$OUTDOC" --report "$OUTJSON" --backend mock --model none --mode rules >/dev/null 2>&1; then
    print_ok "Mock redaction executed"
    pass_count=$((pass_count+1))
  else
    print_err "Mock redaction failed (CLI did not run)"
    fail_count=$((fail_count+1))
  fi

  if [ -f "$OUTDOC" ] && [ -f "$OUTJSON" ]; then
    print_ok "Outputs present (DOCX, JSON)"
    pass_count=$((pass_count+1))
    # Validate JSON parses using embedded python
    if /bin/bash "$LAUNCHER" - "$OUTJSON" << 'PY'
import json,sys; json.load(open(sys.argv[1])); print('ok')
PY
    then
      print_ok "JSON report valid"
      pass_count=$((pass_count+1))
    else
      print_err "JSON report invalid"
      fail_count=$((fail_count+1))
    fi
  else
    print_err "Redaction outputs missing"
    fail_count=$((fail_count+1))
  fi

  # Info.plist version sync check
  local PLIST="$APP/Contents/Info.plist"
  if [ -f "$PLIST" ]; then
    local ver
    ver=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$PLIST" 2>/dev/null || true)
    if [ -n "$ver" ]; then print_ok "CFBundleShortVersionString: $ver"; pass_count=$((pass_count+1)); else print_warn "CFBundleShortVersionString not found"; fi
  else
    print_warn "Info.plist not found at $PLIST"
  fi
}

mount_and_check_dmg() {
  local DMG="$1"
  echo "Mounting DMG: $DMG"
  local MNT
  MNT=$(hdiutil attach -nobrowse "$DMG" | awk '{print $3}' | tail -1)
  if [ -z "$MNT" ]; then print_err "Failed to mount DMG"; exit 1; fi
  print_ok "Mounted at $MNT"
  local APP
  APP=$(find "$MNT" -maxdepth 2 -name "MarcutApp.app" -print -quit)
  if [ -z "$APP" ]; then print_err "No MarcutApp.app in DMG"; hdiutil detach -quiet "$MNT" || true; exit 1; fi
  check_app "$APP"
  hdiutil detach -quiet "$MNT" || true
}

main() {
  if [ $# -ne 1 ]; then echo "Usage: $0 </path/to/MarcutApp.app|.dmg>"; exit 2; fi
  local TARGET="$1"
  if [ -d "$TARGET/Contents/MacOS" ]; then
    check_app "$TARGET"
    # Also validate installed-copy behavior at ~/Applications
    local DST="$HOME/Applications/MarcutApp.app"
    mkdir -p "$HOME/Applications" || true
    rm -rf "$DST" 2>/dev/null || true
    cp -R "$TARGET" "$DST"
    print_ok "Copied app to $DST"
    check_app "$DST"
    rm -rf "$DST" 2>/dev/null || true
  elif [ -f "$TARGET" ] && [[ "$TARGET" == *.dmg ]]; then
    mount_and_check_dmg "$TARGET"
  else
    echo "Unknown target: $TARGET"; exit 2
  fi

  echo ""; echo "Summary: $pass_count checks passed, $fail_count failed"
  if [ $fail_count -eq 0 ]; then exit 0; else exit 1; fi
}

main "$@"

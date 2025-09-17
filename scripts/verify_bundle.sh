#!/usr/bin/env bash
set -euo pipefail

print_ok()  { printf "\033[0;32m✓ %s\033[0m\n" "$1"; }
print_warn(){ printf "\033[1;33m⚠ %s\033[0m\n" "$1"; }
print_err() { printf "\033[0;31m✗ %s\033[0m\n" "$1"; }

pass_count=0; fail_count=0

req_exec()   { if [ -x "$1" ]; then print_ok "$2"; pass_count=$((pass_count+1)); else print_err "$3"; fail_count=$((fail_count+1)); fi }
req_exists() { if [ -e "$1" ]; then print_ok "$2"; pass_count=$((pass_count+1)); else print_err "$3"; fail_count=$((fail_count+1)); fi }

check_app() {
  local APP="$1"
  echo "Verifying app: $APP"
  local MACOS="$APP/Contents/MacOS/MarcutApp"
  local RES="$APP/Contents/Resources"
  local OLLAMA="$RES/ollama"
  local PYB="$RES/python_bundle"

  req_exec   "$MACOS" "MarcutApp executable present" "Missing or not executable: $MACOS"
  req_exec   "$OLLAMA" "Ollama present and executable" "Missing or not executable: $OLLAMA"
  req_exec   "$PYB/bin/python3" "Embedded python present" "Missing or not executable: $PYB/bin/python3"
  req_exec   "$PYB/test_bundle.sh" "Launcher present and executable" "Missing or not executable: $PYB/test_bundle.sh"
  req_exists "$PYB/Python3" "Python3 loader present (root)" "Missing: $PYB/Python3"
  req_exists "$PYB/lib/Python3" "Python3 loader present (lib/)" "Missing: $PYB/lib/Python3"

  if otool -L "$PYB/bin/python3" | grep -q "@executable_path/../Python3\|@loader_path/../Python3"; then
    print_ok "python3 links to Python3 via relative path"
    pass_count=$((pass_count+1))
  else
    print_err "python3 does not link to Python3 loader as expected"
    fail_count=$((fail_count+1))
  fi

  local FW_LOADER="$PYB/lib/Resources/Python.app/Contents/MacOS/Python"
  if otool -L "$PYB/bin/python3" | grep -q "Python\.app/Contents/MacOS/Python"; then
    if [ -f "$FW_LOADER" ]; then print_ok "Framework-style loader present: $FW_LOADER"; pass_count=$((pass_count+1)); else print_err "Framework-style loader missing: $FW_LOADER"; fail_count=$((fail_count+1)); fi
  fi

  if /bin/bash "$PYB/test_bundle.sh" -c 'import sys; print("ok")' >/dev/null 2>&1; then
    print_ok "Embedded python launcher executes successfully"
    pass_count=$((pass_count+1))
  else
    print_err "Embedded python launcher failed to execute (check loader/paths)"
    fail_count=$((fail_count+1))
  fi

  # Minimal mock redaction to prove CLI path (fast)
  local TMP; TMP=$(mktemp -d 2>/dev/null || mktemp -d -t marcut)
  local INP="$TMP/test.docx"; local OUTDOC="$TMP/out.docx"; local OUTJSON="$TMP/out.json"
  if /bin/bash "$PYB/test_bundle.sh" - "$INP" <<'PY'
from docx import Document
from pathlib import Path
import sys
p=Path(sys.argv[1]); d=Document(); d.add_paragraph('Email: test@example.com URL: https://example.com'); d.save(p); print('ok')
PY
  then print_ok "DOCX fixture created"; pass_count=$((pass_count+1)); else print_err "Failed to create DOCX via embedded python"; fail_count=$((fail_count+1)); fi

  if /bin/bash "$PYB/test_bundle.sh" -m marcut.cli redact --in "$INP" --out "$OUTDOC" --report "$OUTJSON" --backend mock --model none >/dev/null 2>&1; then
    print_ok "Mock redaction executed"
    pass_count=$((pass_count+1))
  else
    print_err "Mock redaction failed"
    fail_count=$((fail_count+1))
  fi

  if [ -f "$OUTDOC" ] && [ -f "$OUTJSON" ]; then
    print_ok "Outputs present (DOCX, JSON)"
    pass_count=$((pass_count+1))
    if /bin/bash "$PYB/test_bundle.sh" - "$OUTJSON" <<'PY'
import json,sys; json.load(open(sys.argv[1])); print('ok')
PY
    then print_ok "JSON report valid"; pass_count=$((pass_count+1)); else print_err "JSON report invalid"; fail_count=$((fail_count+1)); fi
  else
    print_err "Redaction outputs missing"
    fail_count=$((fail_count+1))
  fi

  # Version sync
  local PLIST="$APP/Contents/Info.plist"
  if [ -f "$PLIST" ]; then
    local ver; ver=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$PLIST" 2>/dev/null || true)
    if [ -n "$ver" ]; then print_ok "CFBundleShortVersionString: $ver"; pass_count=$((pass_count+1)); else print_warn "CFBundleShortVersionString not found"; fi
  fi
}

mount_and_check_dmg() {
  local DMG="$1"
  echo "Mounting DMG: $DMG"
  local MNT; MNT=$(hdiutil attach -nobrowse "$DMG" | awk '{print $3}' | tail -1)
  if [ -z "$MNT" ]; then print_err "Failed to mount DMG"; exit 1; fi
  print_ok "Mounted at $MNT"
  local APP; APP=$(find "$MNT" -maxdepth 2 -name "MarcutApp.app" -print -quit)
  if [ -z "$APP" ]; then print_err "No MarcutApp.app in DMG"; hdiutil detach "$MNT" || true; exit 1; fi
  check_app "$APP"
  hdiutil detach "$MNT" || true
}

main() {
  if [ $# -ne 1 ]; then echo "Usage: $0 </path/to/MarcutApp.app|.dmg>"; exit 2; fi
  local TARGET="$1"
  if [ -d "$TARGET/Contents/MacOS" ]; then
    check_app "$TARGET"
    # Install copy to ~/Applications and verify
    local DST="$HOME/Applications/MarcutApp.app"; mkdir -p "$HOME/Applications" || true
    rm -rf "$DST" 2>/dev/null || true; cp -R "$TARGET" "$DST"; print_ok "Copied app to $DST"; check_app "$DST"; rm -rf "$DST" 2>/dev/null || true
  elif [ -f "$TARGET" ] && [[ "$TARGET" == *.dmg ]]; then
    mount_and_check_dmg "$TARGET"
  else
    echo "Unknown target: $TARGET"; exit 2
  fi
  echo; echo "Summary: $pass_count checks passed, $fail_count failed"; if [ $fail_count -eq 0 ]; then exit 0; else exit 1; fi
}

main "$@"


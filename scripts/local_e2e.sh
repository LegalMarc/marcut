#!/usr/bin/env bash
# Local end-to-end test runner for Marcut on macOS.
# Builds embedded python, builds DMG, validates embedded interpreter spawn from
# bundle / DMG / installed copy, and performs a small mock redaction. If a live
# Ollama service is detected, it will also run a real redaction with a small
# model (llama3.2:1b) if available.

set -euo pipefail

FAST_MODE=${E2E_FAST_MODE:-0}
remaining_args=()
for arg in "$@"; do
  if [ "$arg" = "--fast" ]; then
    FAST_MODE=1
    continue
  fi
  remaining_args+=("$arg")
done
if [ "${#remaining_args[@]}" -gt 0 ]; then
  set -- "${remaining_args[@]}"
else
  set --
fi

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

log() { printf "\033[0;34m[local-e2e]\033[0m %s\n" "$*"; }
ok()  { printf "\033[0;32m✓\033[0m %s\n" "$*"; }
err() { printf "\033[0;31m✗\033[0m %s\n" "$*"; }

timed_step() {
  local desc="$1"; shift
  local start end
  start=$(date +%s)
  log "$desc..."
  if "$@"; then
    end=$(date +%s)
    ok "$desc (took $((end - start))s)"
  else
    end=$(date +%s)
    err "$desc FAILED (took $((end - start))s)"
    exit 1
  fi
}

require() { command -v "$1" >/dev/null 2>&1 || { err "Missing dependency: $1"; exit 1; }; }

require hdiutil
require unzip

clean() {
  rm -rf test-output /tmp/marcut.log || true
  if [ "$FAST_MODE" -ne 1 ]; then
    rm -rf build_swift
  fi
}

resolve_launcher() {
  local APP="$1"
  clear_quarantine "$APP"
  local CANDIDATES=(
    "$APP/Contents/Resources/run_python.sh"
    "$APP/Contents/Resources/python_launcher.sh"
    "$APP/Contents/Resources/MarcutApp_MarcutApp.bundle/Resources/run_python.sh"
    "$APP/Contents/Resources/MarcutApp_MarcutApp.bundle/Resources/python_launcher.sh"
  )
  local candidate
  for candidate in "${CANDIDATES[@]}"; do
    if [ -x "$candidate" ]; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

clear_quarantine() {
  local TARGET="$1"
  if command -v xattr >/dev/null 2>&1; then
    xattr -dr com.apple.quarantine "$TARGET" 2>/dev/null || true
    xattr -dr com.apple.provenance "$TARGET" 2>/dev/null || true
  fi
}

spawn_test() {
  local APP="$1"
  local LAUNCHER
  if ! LAUNCHER=$(resolve_launcher "$APP"); then
    err "Spawn FAILED at $APP (no usable Python launcher)."
    return 1
  fi
  if MARCUT_SKIP_PYTHON_BUNDLE=1 /bin/bash "$LAUNCHER" -c 'import sys, numpy, lxml.etree; print("ok")' >/dev/null 2>&1; then
    ok "Spawn OK (launcher): $APP"
    return 0
  fi
  err "Spawn FAILED at $APP via $LAUNCHER"
  return 1
}

mock_redaction() {
  local APP="$1"; local OUTDIR="$2"; mkdir -p "$OUTDIR"
  local LAUNCHER
  if ! LAUNCHER=$(resolve_launcher "$APP"); then
    log "Mock redaction skipped for $APP; python launcher unavailable."
    return 0
  fi
  local RUNNER=(env /bin/bash "$LAUNCHER")
  local INP="$OUTDIR/mock_input.docx"; local OUTDOC="$OUTDIR/mock_out.docx"; local OUTJSON="$OUTDIR/mock_report.json"

  if ! cat <<'PY' | "${RUNNER[@]}" - "$INP"
from docx import Document
from pathlib import Path
import sys
p=Path(sys.argv[1]); d=Document(); d.add_paragraph('Email: test@example.com URL: https://example.com'); d.save(p)
print('ok')
PY
  then
    err "Unable to generate mock input for mock redaction"
    return 1
  fi
  "${RUNNER[@]}" -m marcut.cli redact --in "$INP" --out "$OUTDOC" --report "$OUTJSON" --mode rules --backend mock --model none
  test -f "$OUTDOC" && test -f "$OUTJSON" || { err "Mock redaction outputs missing"; return 1; }
  ok "Mock redaction produced $OUTDOC and $OUTJSON"
}

word_tag_check() {
  local DOCX="$1"
  if unzip -p "$DOCX" word/document.xml | grep -E -q 'w:del|w:ins|\[EMAIL|\[URL'; then
    ok "DOCX contains track-changes/tags"
  else
    log "DOCX tag scan inconclusive; open in Word to confirm."
  fi
}

real_redaction_if_ollama() {
  if [ "$FAST_MODE" -eq 1 ]; then
    log "FAST MODE: Skipping real Ollama E2E test."
    return 0
  fi
  local APP="$1"; local OUTDIR="$2"; mkdir -p "$OUTDIR"
  local HOST=${OLLAMA_HOST:-http://127.0.0.1:11434}
  local DEFAULT_MODEL="llama3.2:1b"
  local LAUNCHER
  if ! LAUNCHER=$(resolve_launcher "$APP"); then
    log "Real E2E skipped for $APP; python launcher unavailable."
    return 0
  fi
  local RUNNER=(/bin/bash "$LAUNCHER")

  if ! curl -sSf "$HOST/api/tags" >/dev/null 2>&1; then
    log "Ollama not reachable at $HOST; attempting embedded startup."
    if ! OLLAMA_HOST="$HOST" "${RUNNER[@]}" - <<PY
from marcut.preflight import ensure_ollama_ready
ensure_ollama_ready(model_name="${DEFAULT_MODEL}")
PY
    then
      log "Failed to bootstrap Ollama service via embedded runtime."
    fi
  fi

  if curl -sSf "$HOST/api/tags" >/dev/null 2>&1; then
    ok "Ollama reachable at $HOST"
  else
    log "Ollama not reachable after bootstrap; skipping real E2E."
    return 0
  fi
  local tags_json
  tags_json=$(curl -sSf "$HOST/api/tags" 2>/dev/null || true)
  local E2E_MODEL=""
  if [ -n "$tags_json" ]; then
    E2E_MODEL=$(printf '%s' "$tags_json" | perl -ne 'if (/"name":\s*"([^"]*(phi|gemma|1b|3b|qwen)[^"]*)"/i) { print "$1\n"; exit 0 }')
  fi
  if [ -z "$E2E_MODEL" ]; then
    log "No small test model discovered via Ollama tags; falling back to ${DEFAULT_MODEL}"
    E2E_MODEL="$DEFAULT_MODEL"
  else
    log "Using discovered Ollama model '${E2E_MODEL}' for real E2E test"
  fi

  local INP="$OUTDIR/e2e_input.docx"; local OUTDOC="$OUTDIR/e2e_out.docx"; local OUTJSON="$OUTDIR/e2e_report.json"
  "${RUNNER[@]}" - "$INP" <<'PY'
from docx import Document
from pathlib import Path
import sys
p=Path(sys.argv[1]); d=Document(); d.add_paragraph('Email: alice@example.com URL: https://legal.example'); d.save(p)
print('ok')
PY
  OLLAMA_HOST="$HOST" "${RUNNER[@]}" -m marcut.cli redact \
    --in "$INP" --out "$OUTDOC" --report "$OUTJSON" \
    --backend ollama --model "$E2E_MODEL" --mode enhanced --debug
  test -f "$OUTDOC" && test -f "$OUTJSON" || { err "Real E2E outputs missing"; return 1; }
  ok "Real E2E produced $OUTDOC and $OUTJSON"
  word_tag_check "$OUTDOC"
}

cli_redaction_mock() {
  local APP="$1"
  local GROUP_DIR="$HOME/Library/Group Containers/QG85EMCQ75.group.com.marclaw.marcutapp/MarcutOllama"
  local INPUT_DOC="$GROUP_DIR/cli-input.docx"
  local OUT_DIR="$GROUP_DIR"
  local REPORT="$GROUP_DIR/cli-input_report.json"
  local OUT_DOC="$GROUP_DIR/cli-input_redacted.docx"
  local WORK_SUBDIR="$GROUP_DIR/Work"
  mkdir -p "$GROUP_DIR"
  for attr in com.apple.quarantine com.apple.provenance; do
    xattr -d "$attr" "$GROUP_DIR" 2>/dev/null || true
  done
  mkdir -p "$WORK_SUBDIR"
  chmod 0777 "$WORK_SUBDIR" 2>/dev/null || true
  for attr in com.apple.quarantine com.apple.provenance; do
    xattr -d "$attr" "$WORK_SUBDIR" 2>/dev/null || true
  done
  rm -f "$INPUT_DOC" "$OUT_DOC" "$REPORT" \
    "$WORK_SUBDIR/cli-input_input.docx" "$WORK_SUBDIR/cli-input_redacted.docx" \
    "$WORK_SUBDIR/cli-input_report.json"

  local LAUNCHER
  if ! LAUNCHER=$(resolve_launcher "$APP"); then
    err "Python launcher missing for $APP"
    return 1
  fi

  /bin/bash "$LAUNCHER" - "$INPUT_DOC" <<'PY'
from docx import Document
from pathlib import Path
import sys
path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
doc = Document()
doc.add_paragraph("CLI sandbox test email cli@example.com")
doc.save(path)
print("ok")
PY
  for attr in com.apple.quarantine com.apple.provenance; do
    xattr -d "$attr" "$WORK_SUBDIR" 2>/dev/null || true
  done
  for attr in com.apple.quarantine com.apple.provenance; do
    xattr -d "$attr" "$INPUT_DOC" 2>/dev/null || true
  done

  local CLI_BIN="$APP/Contents/MacOS/MarcutApp"
  if [ ! -x "$CLI_BIN" ]; then
    err "CLI binary missing at $CLI_BIN"
    return 1
  fi

  if ! NSUnbufferedIO=YES "$CLI_BIN" --cli --redact \
      --in "$INPUT_DOC" \
      --outdir "$OUT_DIR" \
      --backend mock \
      --mode rules \
      --model none; then
    err "Sandboxed CLI redaction failed"
    return 1
  fi

  test -f "$OUT_DOC" && test -f "$REPORT" || { err "CLI outputs missing (expected $OUT_DOC / $REPORT)"; return 1; }
  ok "Sandboxed CLI redaction produced $OUT_DOC and $REPORT"
}

main() {
  if [ "$FAST_MODE" -eq 1 ]; then
    log "🚀 Running E2E in FAST MODE (skips build if app exists, DMG mounting, and install tests) 🚀"
  fi

  timed_step "Cleaning previous run" clean

  local BAPP="build_swift/MarcutApp.app"
  if [ "$FAST_MODE" -eq 1 ] && [ -d "$BAPP" ]; then
    log "FAST MODE: Skipping build, app bundle already exists."
  else
    timed_step "Building Swift app and DMG" bash -c "chmod +x scripts/sh/build_swift_only.sh && ./scripts/sh/build_swift_only.sh"
  fi

  if [ ! -d "$BAPP" ]; then
    err "Expected app bundle at $BAPP"
    exit 1
  fi

  log "\n--- Testing build output bundle ---"
  timed_step "Spawn test (from bundle)" spawn_test "$BAPP"
  timed_step "Mock redaction (from bundle)" mock_redaction "$BAPP" "test-output/bundle"

  if [ "$FAST_MODE" -eq 1 ]; then
    log "\nFAST MODE: Skipping DMG and install validation."
    ok "Local E2E (Fast Mode) complete."
    return 0
  fi

  local DMG; DMG=$(ls -1 MarcutApp-Swift-*.dmg | tail -1)
  [ -n "$DMG" ] || { err "No DMG found"; exit 1; }
  ok "Using DMG: $DMG"

  log "\n--- Testing DMG mount ---"
  local attach_start attach_end MNT_OUTPUT MNT
  attach_start=$(date +%s)
  if ! MNT_OUTPUT=$(hdiutil attach -nobrowse "$DMG"); then
    attach_end=$(date +%s)
    err "Mounting DMG FAILED (took $((attach_end - attach_start))s)"
    exit 1
  fi
  attach_end=$(date +%s)
  MNT=$(printf "%s\n" "$MNT_OUTPUT" | perl -ne 'if (m{(/Volumes/.*)}) { print "$1\n"; exit 0 }' )
  [ -n "$MNT" ] || { err "Failed to parse mount point from DMG output"; echo "$MNT_OUTPUT"; exit 1; }
  ok "Mounted DMG at $MNT (took $((attach_end - attach_start))s)"
  local DAPP="$MNT/MarcutApp.app"
  timed_step "Spawn test (from DMG)" spawn_test "$DAPP"
  timed_step "Mock redaction (from DMG)" mock_redaction "$DAPP" "test-output/dmg"

  log "\n--- Testing installed copy ---"
  local IAPP="$HOME/Applications/MarcutApp.app"
  timed_step "Installing app copy" bash -c "rm -rf '$IAPP'; mkdir -p '$HOME/Applications'; cp -R '$DAPP' '$IAPP'"
  timed_step "Spawn test (from installed copy)" spawn_test "$IAPP"
  timed_step "Mock redaction (from installed copy)" mock_redaction "$IAPP" "test-output/installed"
  timed_step "Sandboxed CLI mock redaction" cli_redaction_mock "$IAPP"
  timed_step "Real Ollama E2E (if available)" real_redaction_if_ollama "$IAPP" "test-output/real"

  hdiutil detach "$MNT" >/dev/null 2>&1 || true
  ok "Local E2E (Full) complete. Outputs in test-output/"
}

main "$@"

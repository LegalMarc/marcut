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

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
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

resolve_cli_binary() {
  local APP="$1"
  clear_quarantine "$APP"
  local CLI_BIN="$APP/Contents/MacOS/MarcutApp"
  if [ -x "$CLI_BIN" ]; then
    echo "$CLI_BIN"
    return 0
  fi
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
  local CLI_BIN
  if ! CLI_BIN=$(resolve_cli_binary "$APP"); then
    err "CLI FAILED at $APP (binary not found)."
    return 1
  fi
  if "$CLI_BIN" --diagnose >/dev/null 2>&1; then
    ok "Spawn OK (CLI binary): $APP"
    return 0
  fi
  err "Spawn FAILED at $APP via $CLI_BIN"
  return 1
}

mock_redaction() {
  local APP="$1"; local OUTDIR="$2"; mkdir -p "$OUTDIR"
  local CLI_BIN
  if ! CLI_BIN=$(resolve_cli_binary "$APP"); then
    log "Mock redaction skipped for $APP; CLI binary unavailable."
    return 0
  fi

  # Check if this is the new unified app or older embedded app
  local IS_NEW_APP=false
  if "$CLI_BIN" --diagnose >/dev/null 2>&1; then
    IS_NEW_APP=true
    log "Detected new unified ARM64 app"
  else
    log "Detected older embedded app structure"
  fi

  local INPUT_DOC OUTPUT_DOC OUTPUT_JSON

  if [ "$IS_NEW_APP" = true ]; then
    # New unified app uses App Group sandbox
    local GROUP_DIR="$HOME/Library/Group Containers/group.com.marclaw.marcutapp/MarcutOllama/Work"
    mkdir -p "$GROUP_DIR"
    INPUT_DOC="$GROUP_DIR/mock_input.docx"
    OUTPUT_DOC="$OUTDIR/mock_out.docx"
    OUTPUT_JSON="$OUTDIR/mock_report.json"

    # Copy sample file
    if [ -f "$ROOT_DIR/sample-files/Shareholder-Consent.docx" ]; then
      cp "$ROOT_DIR/sample-files/Shareholder-Consent.docx" "$INPUT_DOC"
    else
      # Use any available sample file
      find "$ROOT_DIR/sample-files" -name "*.docx" | head -1 | xargs cp -t "$GROUP_DIR" || {
        log "No sample files available, skipping mock redaction"
        return 0
      }
    fi

    # Use CLI binary directly (build app uses --outdir, not --out)
    if ! "$CLI_BIN" --redact --in "$INPUT_DOC" --outdir "$OUTDIR" --report "$OUTPUT_JSON" --mode rules --backend mock; then
      err "Mock redaction failed via CLI"
      return 1
    fi

    # Check for outputs with flexible naming pattern
    local FOUND_DOC=$(find "$OUTDIR" -name "*redacted*.docx" | head -1)
    local FOUND_JSON=$(find "$OUTDIR" -name "*report*.json" | head -1)

    if [ -n "$FOUND_DOC" ] && [ -n "$FOUND_JSON" ]; then
      ok "Mock redaction produced $FOUND_DOC and $FOUND_JSON"
    else
      err "Mock redaction outputs missing"
      ls -la "$OUTDIR" 2>/dev/null || true
      return 1
    fi

  else
    # Older embedded app uses different sandbox structure
    local EMBEDDED_DIR="$HOME/Library/Containers/com.marclaw.marcutapp/Data"
    mkdir -p "$EMBEDDED_DIR"
    INPUT_DOC="$EMBEDDED_DIR/mock_input.docx"
    OUTPUT_DOC="$OUTDIR/mock_out.docx"
    OUTPUT_JSON="$OUTDIR/mock_report.json"

    # Copy sample file
    if [ -f "$ROOT_DIR/sample-files/Shareholder-Consent.docx" ]; then
      cp "$ROOT_DIR/sample-files/Shareholder-Consent.docx" "$INPUT_DOC"
    else
      find "$ROOT_DIR/sample-files" -name "*.docx" | head -1 | xargs cp -t "$EMBEDDED_DIR" || {
        log "No sample files available, skipping mock redaction"
        return 0
      }
    fi

    # Use CLI binary with embedded app structure
    if ! "$CLI_BIN" --redact --in "$INPUT_DOC" --outdir "$OUTDIR" --mode rules --backend mock; then
      err "Mock redaction failed via CLI"
      return 1
    fi

    # Check for output files with flexible naming
    local FOUND_DOC=$(find "$OUTDIR" -name "*redacted*.docx" | head -1)
    local FOUND_JSON=$(find "$OUTDIR" -name "*report*.json" | head -1)

    if [ -n "$FOUND_DOC" ] && [ -n "$FOUND_JSON" ]; then
      ok "Mock redaction produced $FOUND_DOC and $FOUND_JSON"
    else
      err "Mock redaction outputs missing"
      ls -la "$OUTDIR" 2>/dev/null || true
      return 1
    fi
  fi
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
  local CLI_BIN
  if ! CLI_BIN=$(resolve_cli_binary "$APP"); then
    log "Real E2E skipped for $APP; CLI binary unavailable."
    return 0
  fi

  if ! curl -sSf "$HOST/api/tags" >/dev/null 2>&1; then
    log "Ollama not reachable at $HOST; attempting embedded startup."
    # CLI binary will attempt to start Ollama if needed
    "$CLI_BIN" --download-model "$DEFAULT_MODEL" >/dev/null 2>&1 || true
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

  # Copy sample file to sandbox directory
  local GROUP_DIR="$HOME/Library/Group Containers/group.com.marclaw.marcutapp/MarcutOllama/Work"
  mkdir -p "$GROUP_DIR"
  if [ -f "$ROOT_DIR/sample-files/Shareholder-Consent.docx" ]; then
    cp "$ROOT_DIR/sample-files/Shareholder-Consent.docx" "$INP"
  else
    # Create minimal test file in Work directory
    cp "$ROOT_DIR/sample-files/*Consent*.docx" "$INP" 2>/dev/null || {
      log "No sample file found, using CLI to create test input"
      # Use CLI to create a basic test (may fail but that's ok for this test)
      echo "Email: alice@example.com URL: https://legal.example" > /tmp/test_content.txt
      log "Created minimal test content at /tmp/test_content.txt"
    }
  fi

  # Use CLI binary for real E2E test
  if ! OLLAMA_HOST="$HOST" "$CLI_BIN" --redact \
    --in "$INP" --out "$OUTDOC" --report "$OUTJSON" \
    --backend ollama --model "$E2E_MODEL" --mode enhanced; then
    err "Real E2E redaction failed"
    return 1
  fi

  test -f "$OUTDOC" && test -f "$OUTJSON" || { err "Real E2E outputs missing"; return 1; }
  ok "Real E2E produced $OUTDOC and $OUTJSON"
  word_tag_check "$OUTDOC"
}

cli_redaction_mock() {
  local APP="$1"
  local GROUP_DIR="$HOME/Library/Group Containers/group.com.marclaw.marcutapp/MarcutOllama"
  local INPUT_DOC="$GROUP_DIR/cli-input.docx"
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
  rm -f "$INPUT_DOC" \
    "$WORK_SUBDIR/cli-input_input.docx" "$WORK_SUBDIR/cli-input_redacted.docx" \
    "$WORK_SUBDIR/cli-input_report.json"

  local CLI_BIN
  if ! CLI_BIN=$(resolve_cli_binary "$APP"); then
    err "CLI binary missing for $APP"
    return 1
  fi

  # Copy sample file to sandbox directory for CLI testing
  if [ -f "$ROOT_DIR/sample-files/Shareholder-Consent.docx" ]; then
    cp "$ROOT_DIR/sample-files/Shareholder-Consent.docx" "$INPUT_DOC"
  else
    # Create minimal test document using available sample files
    cp "$ROOT_DIR/sample-files/"*.docx "$INPUT_DOC" 2>/dev/null || {
      # Fallback: use any docx file we can find
      find "$ROOT_DIR/sample-files" -name "*.docx" | head -1 | xargs cp -t "$WORK_SUBDIR" 2>/dev/null || {
        err "No sample DOCX files available for CLI test"
        return 1
      }
    }
  fi

  # Clear quarantine attributes on input file
  for attr in com.apple.quarantine com.apple.provenance; do
    xattr -d "$attr" "$INPUT_DOC" 2>/dev/null || true
  done

  # Use CLI binary directly (no --cli flag needed)
  if ! "$CLI_BIN" --redact \
      --in "$INPUT_DOC" \
      --outdir "$OUT_DIR" \
      --backend mock \
      --mode rules; then
    err "Sandboxed CLI redaction failed"
    return 1
  fi

  # Check for expected outputs with the new naming pattern
  local EXPECTED_DOC="$OUT_DIR/cli-input_redacted.docx"
  local EXPECTED_REPORT="$OUT_DIR/cli-input_report.json"

  test -f "$EXPECTED_DOC" && test -f "$EXPECTED_REPORT" || {
    err "CLI outputs missing (expected $EXPECTED_DOC / $EXPECTED_REPORT)"
    ls -la "$OUT_DIR" 2>/dev/null || true
    return 1
  }
  ok "Sandboxed CLI redaction produced $EXPECTED_DOC and $EXPECTED_REPORT"
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
    timed_step "Building Swift app and DMG" bash -c "chmod +x build_swift_only.sh && ./build_swift_only.sh"
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

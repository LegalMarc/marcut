#!/usr/bin/env bash
set -euo pipefail

# Notarize and staple a DMG using App Store Connect API key or Apple ID
# API key env: ASC_API_KEY_ID, ASC_API_KEY_ISSUER, ASC_API_KEY_BASE64
# Apple ID env: NOTARYTOOL_APPLE_ID, NOTARYTOOL_APP_PASSWORD, NOTARYTOOL_TEAM_ID (optional)
# Optional: MARCUT_NOTARIZE_ENV to load/store credentials (default: ~/.config/marcut/notarize.env)

DMG=${1:?"Usage: scripts/notarize_macos.sh /path/to/App.dmg"}

ENV_FILE="${MARCUT_NOTARIZE_ENV:-$HOME/.config/marcut/notarize.env}"

decode_base64() {
  if base64 --decode </dev/null >/dev/null 2>&1; then
    base64 --decode
  else
    base64 -D
  fi
}

load_env_file() {
  if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
    echo "Loaded notarization credentials from $ENV_FILE"
  fi
}

write_env_file() {
  local dir
  dir="$(dirname "$ENV_FILE")"
  mkdir -p "$dir"
  {
    echo "ASC_API_KEY_ID=\"${ASC_API_KEY_ID}\""
    echo "ASC_API_KEY_ISSUER=\"${ASC_API_KEY_ISSUER}\""
    echo "ASC_API_KEY_BASE64=\"${ASC_API_KEY_BASE64}\""
    echo "NOTARYTOOL_APPLE_ID=\"${NOTARYTOOL_APPLE_ID}\""
    echo "NOTARYTOOL_APP_PASSWORD=\"${NOTARYTOOL_APP_PASSWORD}\""
    echo "NOTARYTOOL_TEAM_ID=\"${NOTARYTOOL_TEAM_ID}\""
  } > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "Saved notarization credentials to $ENV_FILE"
}

validate_key_file() {
  local file="$1"
  if ! grep -q "BEGIN PRIVATE KEY" "$file" 2>/dev/null; then
    return 1
  fi
  return 0
}

prompt_for_credentials() {
  if [ -t 0 ]; then
    if [ -z "${ASC_API_KEY_ID:-}" ]; then
      read -r -p "ASC_API_KEY_ID: " ASC_API_KEY_ID
    fi
    if [ -z "${ASC_API_KEY_ISSUER:-}" ]; then
      read -r -p "ASC_API_KEY_ISSUER: " ASC_API_KEY_ISSUER
    fi
    if [ -z "${ASC_API_KEY_BASE64:-}" ]; then
      read -r -p "Path to .p8 key file (preferred) or paste base64 (leave blank to use Apple ID): " key_input
      if [ -n "$key_input" ] && [ -f "$key_input" ]; then
        ASC_API_KEY_BASE64="$(base64 < "$key_input" | tr -d '\n')"
      elif [ -n "$key_input" ]; then
        ASC_API_KEY_BASE64="$key_input"
      fi
    fi

    if [ -z "${ASC_API_KEY_ID:-}" ] || [ -z "${ASC_API_KEY_ISSUER:-}" ] || [ -z "${ASC_API_KEY_BASE64:-}" ]; then
      if [ -z "${NOTARYTOOL_APPLE_ID:-}" ]; then
        read -r -p "Apple ID (email) for notarization: " NOTARYTOOL_APPLE_ID
      fi
      if [ -z "${NOTARYTOOL_TEAM_ID:-}" ]; then
        read -r -p "Apple Team ID (optional): " NOTARYTOOL_TEAM_ID
      fi
      if [ -z "${NOTARYTOOL_APP_PASSWORD:-}" ]; then
        read -r -s -p "App-specific password: " NOTARYTOOL_APP_PASSWORD
        echo ""
      fi
    fi
  fi
}

load_env_file
prompt_for_credentials

if [ -t 0 ]; then
  if read -r -p "Save notarization credentials to ${ENV_FILE}? [Y/n] " save_choice; then
    if [ -z "$save_choice" ] || [ "$save_choice" = "y" ] || [ "$save_choice" = "Y" ]; then
      write_env_file
    fi
  fi
fi

ASC_API_KEY_BASE64="$(printf "%s" "$ASC_API_KEY_BASE64" | tr -d '\n\r ')"
NOTARYTOOL_APPLE_ID="$(printf "%s" "$NOTARYTOOL_APPLE_ID" | tr -d '\n\r ')"
NOTARYTOOL_APP_PASSWORD="$(printf "%s" "$NOTARYTOOL_APP_PASSWORD" | tr -d '\n\r ')"
NOTARYTOOL_TEAM_ID="$(printf "%s" "$NOTARYTOOL_TEAM_ID" | tr -d '\n\r ')"

use_api_key=false
use_apple_id=false

if [ -n "${ASC_API_KEY_ID:-}" ] && [ -n "${ASC_API_KEY_ISSUER:-}" ] && [ -n "${ASC_API_KEY_BASE64:-}" ]; then
  use_api_key=true
elif [ -n "${NOTARYTOOL_APPLE_ID:-}" ] && [ -n "${NOTARYTOOL_APP_PASSWORD:-}" ]; then
  use_apple_id=true
fi

if [ "${use_api_key}" = false ] && [ "${use_apple_id}" = false ]; then
  echo "NOTARIZATION: SKIPPED (missing API key or Apple ID credentials)" >&2
  echo "Set ASC_API_KEY_ID/ASC_API_KEY_ISSUER/ASC_API_KEY_BASE64 or NOTARYTOOL_APPLE_ID/NOTARYTOOL_APP_PASSWORD (optional NOTARYTOOL_TEAM_ID)" >&2
  exit 0
fi

echo "NOTARIZATION: START"
echo "Submitting $DMG for notarization..."
if [ "${use_api_key}" = true ]; then
  tmp_key="$(mktemp)"
  trap 'rm -f "$tmp_key"' EXIT
  if ! printf "%s" "$ASC_API_KEY_BASE64" | decode_base64 > "$tmp_key" 2>/dev/null; then
    echo "NOTARIZATION: SKIPPED (invalid ASC_API_KEY_BASE64)" >&2
    exit 0
  fi
  if ! validate_key_file "$tmp_key"; then
    echo "NOTARIZATION: SKIPPED (decoded key is not a valid .p8 file)" >&2
    exit 0
  fi
  SUBMIT_OUT=$(xcrun notarytool submit "$DMG" \
    --key "$tmp_key" \
    --key-id "$ASC_API_KEY_ID" \
    --issuer "$ASC_API_KEY_ISSUER" \
    --wait 2>&1 | tee /dev/stderr)
else
  submit_args=(--apple-id "$NOTARYTOOL_APPLE_ID" --password "$NOTARYTOOL_APP_PASSWORD")
  if [ -n "${NOTARYTOOL_TEAM_ID}" ]; then
    submit_args+=(--team-id "$NOTARYTOOL_TEAM_ID")
  fi
  SUBMIT_OUT=$(xcrun notarytool submit "$DMG" \
    "${submit_args[@]}" \
    --wait 2>&1 | tee /dev/stderr)
fi

echo "$SUBMIT_OUT" | sed 's/^/SUBMIT: /'
STATUS=$(echo "$SUBMIT_OUT" | awk '/status:/ {print $2}' | tail -1)
SUBMISSION_ID=$(echo "$SUBMIT_OUT" | awk '/id:/ {print $2}' | head -1)

if [ "${STATUS}" = "Accepted" ]; then
  echo "Stapling notarization ticket..."
  xcrun stapler staple "$DMG"
  echo "Staple complete. Verifying..."
  spctl -a -t open --context context:primary-signature -v "$DMG" || true
  echo "NOTARIZATION: OK"
elif [ -n "$SUBMISSION_ID" ]; then
  echo "NOTARIZATION: IN PROGRESS (submission id: $SUBMISSION_ID)"
  echo "You can poll with:"
  if [ "${use_api_key}" = true ]; then
    echo "  xcrun notarytool info $SUBMISSION_ID --key <your .p8> --key-id $ASC_API_KEY_ID --issuer $ASC_API_KEY_ISSUER"
  else
    echo "  xcrun notarytool info $SUBMISSION_ID --apple-id $NOTARYTOOL_APPLE_ID --password '***'${NOTARYTOOL_TEAM_ID:+ --team-id $NOTARYTOOL_TEAM_ID}"
  fi
  echo "NOTARIZATION: PENDING"
  exit 0
else
  echo "NOTARIZATION: FAILED" >&2
  echo "Notarization failed or not accepted. Output:" >&2
  echo "$SUBMIT_OUT" >&2
  exit 1
fi

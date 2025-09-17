#!/usr/bin/env bash
set -euo pipefail

# Notarize and staple a DMG using App Store Connect API key
# Requires env: ASC_API_KEY_ID, ASC_API_KEY_ISSUER, ASC_API_KEY_BASE64

DMG=${1:?"Usage: scripts/notarize_macos.sh /path/to/App.dmg"}

if [ -z "${ASC_API_KEY_ID:-}" ] || [ -z "${ASC_API_KEY_ISSUER:-}" ] || [ -z "${ASC_API_KEY_BASE64:-}" ]; then
  echo "ASC API secrets not present; skipping notarization" >&2
  exit 0
fi

echo "$ASC_API_KEY_BASE64" | base64 --decode > asc_api_key.p8

echo "Submitting $DMG for notarization..."
SUBMIT_OUT=$(xcrun notarytool submit "$DMG" \
  --key asc_api_key.p8 \
  --key-id "$ASC_API_KEY_ID" \
  --issuer "$ASC_API_KEY_ISSUER" \
  --wait 2>&1 | tee /dev/stderr)

if echo "$SUBMIT_OUT" | grep -q "status: Accepted"; then
  echo "Stapling notarization ticket..."
  xcrun stapler staple "$DMG"
  echo "Staple complete. Verifying..."
  spctl -a -t open --context context:primary-signature -v "$DMG" || true
else
  echo "Notarization failed or not accepted. Output:" >&2
  echo "$SUBMIT_OUT" >&2
  exit 1
fi


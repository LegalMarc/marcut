#!/usr/bin/env bash
set -euo pipefail

DMG=${1:?"Usage: scripts/verify_macos.sh /path/to/App.dmg"}
SCRIPTS_DIR=$(cd "$(dirname "$0")" && pwd)
bash "$SCRIPTS_DIR/verify_bundle.sh" "$DMG"


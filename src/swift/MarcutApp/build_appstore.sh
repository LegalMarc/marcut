#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
CANONICAL_SCRIPT="${REPO_ROOT}/scripts/sh/build_appstore_release.sh"

echo "⚠️  Deprecated entrypoint: src/swift/MarcutApp/build_appstore.sh"
echo "➡️  Delegating to canonical build pipeline: scripts/sh/build_appstore_release.sh"

if [ ! -x "${CANONICAL_SCRIPT}" ]; then
    chmod +x "${CANONICAL_SCRIPT}" 2>/dev/null || true
fi

if [ ! -f "${CANONICAL_SCRIPT}" ]; then
    echo "❌ Canonical App Store build script not found at ${CANONICAL_SCRIPT}" >&2
    exit 1
fi

exec bash "${CANONICAL_SCRIPT}" "$@"

#!/usr/bin/env bash
# Wrapper so legacy tooling can reuse the root-level verify_bundle script.
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
exec "$REPO_ROOT/tests/scripts/verify_bundle.sh" "$@"

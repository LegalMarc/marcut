#!/usr/bin/env bash
set -euo pipefail

# Thin wrapper to build DMGs. Uses existing project scripts.
# For debug (PRs): builds Swift-only DMG after creating python_bundle and stubbing Ollama.
# For release (tags): builds App Store DMG (skip notarization here; handled in separate step).

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

# Ensure a stub Ollama is present so bundling never fails on CI
if [ ! -x "ollama_binary" ]; then
  cat > ollama_binary <<'SH'
#!/usr/bin/env bash
echo "ollama stub: $@" >&2
exit 0
SH
  chmod +x ollama_binary
fi

echo "Creating embedded python bundle..."
chmod +x create_python_bundle.sh
./create_python_bundle.sh

MODE=${1:-debug}
if [ "$MODE" = "release" ]; then
  echo "Building App Store DMG (skip notarization)..."
  chmod +x build_appstore_release.sh
  ./build_appstore_release.sh --skip-notarization
else
  echo "Building Swift-only DMG (debug)..."
  chmod +x build_swift_only.sh
  ./build_swift_only.sh
fi


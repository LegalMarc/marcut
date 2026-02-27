#!/bin/bash
set -euo pipefail

# Build and embed OllamaHelperService.xpc into the existing built app in build_swift/MarcutApp.app

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_BUNDLE="${ROOT}/build_swift/MarcutApp.app"
HELPER_BUILD_DIR="${ROOT}/build_swift"
HELPER_XPC="${HELPER_BUILD_DIR}/OllamaHelperService.xpc"

if [[ ! -d "${APP_BUNDLE}" ]]; then
  echo "App bundle not found at ${APP_BUNDLE}. Build the main app first."
  exit 1
fi

echo "Building OllamaHelperService..."
cd "${ROOT}/MarcutApp"
swift build -c release --arch arm64 --product OllamaHelperService

# Find the built helper
BUILT_HELPER=$(find ./.build -name "OllamaHelperService" -type f | head -1)
if [[ -z "${BUILT_HELPER}" ]]; then
  echo "Failed to locate built OllamaHelperService"
  exit 1
fi

echo "Assembling XPC bundle..."
rm -rf "${HELPER_XPC}"
mkdir -p "${HELPER_XPC}/Contents/MacOS"
mkdir -p "${HELPER_XPC}/Contents/Resources"

cp "${BUILT_HELPER}" "${HELPER_XPC}/Contents/MacOS/OllamaHelperService"
cp Sources/OllamaHelperService/Info.plist "${HELPER_XPC}/Contents/Info.plist"

# Copy entitlements (informational; actual signing handled externally)
if [[ -f "${ROOT}/MarcutApp/OllamaHelperService.entitlements" ]]; then
  cp "${ROOT}/MarcutApp/OllamaHelperService.entitlements" "${HELPER_XPC}/Contents/Resources/entitlements.plist"
fi

echo "Embedding XPC into app..."
mkdir -p "${APP_BUNDLE}/Contents/XPCServices"
cp -R "${HELPER_XPC}" "${APP_BUNDLE}/Contents/XPCServices/"

# Copy Ollama.app into helper Resources if present in main app
if [[ -d "${APP_BUNDLE}/Contents/Resources/Ollama.app" ]]; then
  cp -R "${APP_BUNDLE}/Contents/Resources/Ollama.app" "${APP_BUNDLE}/Contents/XPCServices/OllamaHelperService.xpc/Contents/Resources/"
  echo "Copied Ollama.app into helper Resources"
fi

echo "Done. XPC service embedded at ${APP_BUNDLE}/Contents/XPCServices/OllamaHelperService.xpc"

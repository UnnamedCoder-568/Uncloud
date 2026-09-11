#!/usr/bin/env bash
set -euo pipefail

BUNDLE="${1:?usage: verify_macos_bundle.sh DMG OUTPUT}"
OUTPUT="${2:?usage: verify_macos_bundle.sh DMG OUTPUT}"
TEMP="$(mktemp -d)"
MOUNT="$TEMP/mount"
mkdir -p "$MOUNT"
trap 'hdiutil detach "$MOUNT" -quiet 2>/dev/null || true; rm -rf "$TEMP"' EXIT

BUNDLE="$(realpath "$BUNDLE")"
hdiutil attach -nobrowse -readonly -mountpoint "$MOUNT" "$BUNDLE" >/dev/null
APP="$(find "$MOUNT" -maxdepth 2 -type d -name 'Uncloud.app' -print -quit)"
[[ -n "$APP" ]] || { echo "DMG does not contain Uncloud.app" >&2; exit 1; }
[[ -x "$APP/Contents/Resources/uv" ]] || {
  echo "DMG does not contain executable bundled uv" >&2
  exit 1
}
[[ -f "$APP/Contents/Resources/engine/pyproject.toml" ]] || {
  echo "DMG does not contain engine/pyproject.toml" >&2
  exit 1
}
hdiutil detach "$MOUNT" -quiet

mkdir -p "$(dirname "$OUTPUT")"
cp "$BUNDLE" "$OUTPUT"
echo "Verified macOS DMG contents and wrote $OUTPUT"

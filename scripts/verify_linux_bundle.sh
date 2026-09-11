#!/usr/bin/env bash
set -euo pipefail

BUNDLE="${1:?usage: verify_linux_bundle.sh APPIMAGE OUTPUT}"
OUTPUT="${2:?usage: verify_linux_bundle.sh APPIMAGE OUTPUT}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
TEMP="$(mktemp -d)"
trap 'rm -rf "$TEMP"' EXIT

BUNDLE="$(realpath "$BUNDLE")"
chmod +x "$BUNDLE"
mkdir -p "$TEMP/extracted" "$TEMP/state"
(
  cd "$TEMP/extracted"
  "$BUNDLE" --appimage-extract >/dev/null
)

APPDIR="$TEMP/extracted/squashfs-root"
UV="$(find "$APPDIR" -type f -name uv -perm -u+x -print -quit)"
ENGINE_MANIFEST="$(find "$APPDIR" -type f -path '*/engine/pyproject.toml' -print -quit)"
[[ -n "$UV" ]] || { echo "AppImage does not include executable uv" >&2; exit 1; }
[[ -n "$ENGINE_MANIFEST" ]] || {
  echo "AppImage does not include engine/pyproject.toml" >&2
  exit 1
}
[[ "$("$UV" --version)" == "uv 0.12.13"* ]] || {
  echo "AppImage contains an unexpected uv version" >&2
  exit 1
}

HOME="$TEMP/state" USERPROFILE="$TEMP/state" xvfb-run -a "$APPDIR/AppRun" \
  >"$TEMP/app.log" 2>&1 &
APP_PID=$!
sleep 10
if ! kill -0 "$APP_PID" 2>/dev/null; then
  echo "Extracted AppImage exited during startup" >&2
  tail -100 "$TEMP/app.log" >&2
  exit 1
fi
kill "$APP_PID" 2>/dev/null || true
wait "$APP_PID" 2>/dev/null || true

python3 "$REPO/scripts/smoke_engine.py" \
  --uv "$UV" \
  --engine "$(dirname "$ENGINE_MANIFEST")" \
  --work-dir "$TEMP/engine-smoke"

mkdir -p "$(dirname "$OUTPUT")"
cp "$BUNDLE" "$OUTPUT"
chmod +x "$OUTPUT"
echo "Verified Linux AppImage and wrote $OUTPUT"

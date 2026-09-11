#!/usr/bin/env bash
# Download, verify, and stage the uv binary for a Tauri target.
set -euo pipefail

cd "$(dirname "$0")/.."

UV_VERSION="${UV_VERSION:-0.12.13}"
TARGET="${1:-}"

if [[ -z "$TARGET" ]]; then
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) TARGET="aarch64-apple-darwin" ;;
    Darwin-x86_64) TARGET="x86_64-apple-darwin" ;;
    Linux-x86_64) TARGET="x86_64-unknown-linux-gnu" ;;
    MINGW*-x86_64|MSYS*-x86_64) TARGET="x86_64-pc-windows-msvc" ;;
    *) echo "Pass a supported Rust target triple to stage_uv.sh." >&2; exit 1 ;;
  esac
fi

case "$TARGET" in
  x86_64-pc-windows-msvc)
    ARCHIVE="uv-$TARGET.zip"
    MEMBER="uv.exe"
    DEST="src-tauri/binaries/uv.exe"
    ;;
  x86_64-unknown-linux-gnu|aarch64-apple-darwin|x86_64-apple-darwin)
    ARCHIVE="uv-$TARGET.tar.gz"
    MEMBER="uv-$TARGET/uv"
    DEST="src-tauri/binaries/uv"
    ;;
  *) echo "Unsupported uv target: $TARGET" >&2; exit 1 ;;
esac

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
BASE="https://github.com/astral-sh/uv/releases/download/$UV_VERSION"

curl --fail --silent --show-error --location \
  --output "$TMP/$ARCHIVE" "$BASE/$ARCHIVE"
curl --fail --silent --show-error --location \
  --output "$TMP/$ARCHIVE.sha256" "$BASE/$ARCHIVE.sha256"

(
  cd "$TMP"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum --check "$ARCHIVE.sha256"
  else
    shasum -a 256 --check "$ARCHIVE.sha256"
  fi
)

mkdir -p src-tauri/binaries
rm -f src-tauri/binaries/uv src-tauri/binaries/uv.exe
if [[ "$ARCHIVE" == *.zip ]]; then
  unzip -j -q "$TMP/$ARCHIVE" "$MEMBER" -d src-tauri/binaries
else
  tar -xzf "$TMP/$ARCHIVE" -C "$TMP"
  cp "$TMP/$MEMBER" "$DEST"
fi
chmod +x "$DEST"

FOUND="$("$DEST" --version)"
[[ "$FOUND" == "uv $UV_VERSION"* ]] || {
  echo "Staged uv reported '$FOUND', expected $UV_VERSION." >&2
  exit 1
}
echo "Staged $FOUND for $TARGET."

#!/bin/bash
# Stage the `uv` matching this machine, and verify it.
#
# Shipping the wrong architecture produces a bundle that installs cleanly and
# then cannot start its engine. The build must not be able to succeed quietly
# with the wrong one in place.
set -euo pipefail
cd "$(dirname "$0")/.."

case "$(uname -m)" in
  arm64)  SRC="src-tauri/binaries/uv-aarch64"; WANT="arm64"  ;;
  x86_64) SRC="src-tauri/binaries/uv-x86_64";  WANT="x86_64" ;;
  *) echo "unknown architecture $(uname -m)" >&2; exit 1 ;;
esac

[ -f "$SRC" ] || { echo "$SRC is missing" >&2; exit 1; }
cp "$SRC" src-tauri/binaries/uv
chmod +x src-tauri/binaries/uv
file -b src-tauri/binaries/uv | grep -q "$WANT" \
  || { echo "staged uv is not $WANT: $(file -b src-tauri/binaries/uv)" >&2; exit 1; }
echo "staged $WANT uv"

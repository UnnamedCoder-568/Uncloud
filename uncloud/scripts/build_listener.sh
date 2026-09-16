#!/usr/bin/env bash
# Build the native listener, and put it where the bundle will pick it up.
#
# Swift, because the recogniser is Apple's and has no other interface. macOS
# only: every other platform transcribes with Whisper through the engine, which
# is what the interface falls back to when this file is not there.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
listener="$here/src-tauri/listener"
out="$here/src-tauri/binaries/uncloud-listen"

if [ "$(uname -s)" != "Darwin" ]; then
  echo "Not macOS — skipping the native listener." >&2
  exit 0
fi

mkdir -p "$(dirname "$out")"
# The usage descriptions are linked INTO the binary: macOS reads them from the
# process that asks for the microphone, and a command-line tool has no bundle
# to read them from. Without this it is killed on the first request, which
# looks like a crash and explains nothing.
swiftc -O -parse-as-library "$listener/main.swift" -o "$out" \
  -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker "$listener/Info.plist"
codesign -s - -f "$out" >/dev/null 2>&1 || true
echo "built $out"

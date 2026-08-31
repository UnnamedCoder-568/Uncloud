#!/bin/zsh
# Puts an Uncloud alias on the Desktop pointing at the built app.
set -e

APP="/Volumes/AI Folder/AstroForge/uncloud/src-tauri/target/release/bundle/macos/Uncloud.app"
DESKTOP="$HOME/Desktop"

if [ ! -d "$APP" ]; then
  echo "Uncloud.app not found. Build it first:"
  echo "  cd '/Volumes/AI Folder/AstroForge/uncloud' && npm run tauri build"
  exit 1
fi

rm -f "$DESKTOP/Uncloud" "$DESKTOP/Uncloud.app" 2>/dev/null || true

# A Finder alias rather than a symlink, so it survives the app moving and shows
# the real icon in the Dock.
osascript >/dev/null <<EOF
tell application "Finder"
  make new alias file at POSIX file "$DESKTOP" to POSIX file "$APP"
  set name of result to "Uncloud"
end tell
EOF

echo "Added Uncloud to your Desktop."

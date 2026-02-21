#!/usr/bin/env zsh

# Apply a custom PNG/SVG icon to the macOS app bundle
# X3P Marketing Team.app by generating a proper .icns file.
#
# Usage:
#   1) Save your icon image (PNG recommended, ~1024x1024) to a path, e.g.,
#      ~/Downloads/x3p_marketing_icon.png
#   2) Double‑click this file (or run from Terminal):
#      ./apply_app_icon.command ~/Downloads/x3p_marketing_icon.png
#
# This script converts the source into a .icns and replaces the app's icon.
# If Pillow (PIL) is installed, a round mask will be applied to the image first.

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 /path/to/icon.png" >&2
  exit 1
fi

SRC_ICON="$1"
if [[ ! -f "$SRC_ICON" ]]; then
  echo "Icon file not found: $SRC_ICON" >&2
  exit 1
fi

APP_PATH="$HOME/Applications/X3P Marketing Team.app"
if [[ ! -d "$APP_PATH" ]]; then
  echo "App bundle not found at $APP_PATH" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ICONSET_DIR="$(mktemp -d -t x3p_iconset)"
ICNS_OUT="$SCRIPT_DIR/RunX3P.icns"
ROUNDED_PNG="$(mktemp -t x3p_rounded).png"

# Attempt to round the icon using Python + Pillow if available
PY_ROUNDER="$SCRIPT_DIR/round_iconify.py"
SRC_FOR_ICON="$SRC_ICON"
if command -v python3 >/dev/null 2>&1 && [ -f "$PY_ROUNDER" ]; then
  if python3 "$PY_ROUNDER" "$SRC_ICON" "$ROUNDED_PNG" >/dev/null 2>&1; then
    SRC_FOR_ICON="$ROUNDED_PNG"
    echo "• Applied round mask to source icon"
  else
    echo "• Pillow not available or failed; using original image"
  fi
fi

echo "• Building iconset from: $SRC_FOR_ICON"
mkdir -p "$ICONSET_DIR"

# Sizes required by macOS iconutil
function make_icon() {
  local size=$1; local name=$2
  sips -z $size $size "$SRC_FOR_ICON" --out "$ICONSET_DIR/$name" >/dev/null
}

make_icon 16  icon_16x16.png
make_icon 32  icon_16x16@2x.png
make_icon 32  icon_32x32.png
make_icon 64  icon_32x32@2x.png
make_icon 128 icon_128x128.png
make_icon 256 icon_128x128@2x.png
make_icon 256 icon_256x256.png
make_icon 512 icon_256x256@2x.png
make_icon 512 icon_512x512.png
make_icon 1024 icon_512x512@2x.png

echo "• Converting to ICNS: $ICNS_OUT"
iconutil -c icns "$ICONSET_DIR" -o "$ICNS_OUT"
rm -rf "$ICONSET_DIR"
rm -f "$ROUNDED_PNG" 2>/dev/null || true

RES_DIR="$APP_PATH/Contents/Resources"
PLIST="$APP_PATH/Contents/Info.plist"

echo "• Installing icon into app bundle"
cp "$ICNS_OUT" "$RES_DIR/RunX3P.icns"

# Ensure Info.plist references the correct file name
/usr/bin/sed -i '' 's#<key>CFBundleIconFile</key>\n\s*<string>.*</string>#<key>CFBundleIconFile</key>\n    <string>RunX3P.icns</string>#' "$PLIST"

echo "• Refreshing Dock (icon cache)"
touch "$APP_PATH"
killall Dock >/dev/null 2>&1 || true

echo "✔ Icon applied. If Finder/Dock hasn’t updated, relaunch Finder or log out/in."

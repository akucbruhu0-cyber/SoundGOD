#!/bin/zsh
# Build "סטודיו סאונד.app": a double-click launcher (Dock, Spotlight, Launchpad) for the local UI.
# usage: scripts/make-app.sh [destination folder]    default: ~/Applications
# The app stores the path of this project; if you move the project, run this script again.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-$HOME/Applications}"
NAME="סטודיו סאונד"
APP="$DEST/$NAME.app"
UV="$(command -v uv || echo /opt/homebrew/bin/uv)"

mkdir -p "$DEST"
[ "${APP:?}" != "/" ] && rm -rf "${APP:?}"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
print -rn -- "$ROOT" > "$APP/Contents/Resources/root"

ICONSET="$(mktemp -d)/AppIcon.iconset"
"$UV" run --script "$ROOT/scripts/make-icon.py" "$ICONSET"
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>$NAME</string>
  <key>CFBundleDisplayName</key><string>$NAME</string>
  <key>CFBundleIdentifier</key><string>local.audio-enhance.studio</string>
  <key>CFBundleExecutable</key><string>launch</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>$(cat "$ROOT/VERSION")</string>
  <key>CFBundleShortVersionString</key><string>$(cat "$ROOT/VERSION")</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

cat > "$APP/Contents/MacOS/launch" <<'LAUNCH'
#!/bin/zsh
# Starts the local server if it is not already running, then opens the page.
APP="$(cd "$(dirname "$0")/../.." && pwd)"
ROOT="$(cat "$APP/Contents/Resources/root" 2>/dev/null)"
[ -f "$ROOT/ui/server.py" ] || ROOT="$(cd "$APP/.." && pwd)"   # fallback: app sits inside the project folder
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
LOG="${TMPDIR:-/tmp}/audio-enhance-app.log"

alert() { osascript -e 'on run argv' -e 'display dialog (item 1 of argv) with title "סטודיו סאונד" buttons {"אישור"} default button 1 with icon caution' -e 'end run' "$1" >/dev/null 2>&1; }

[ -f "$ROOT/ui/server.py" ] || { alert "לא מצאתי את תיקיית הפרויקט. הרץ שוב את scripts/make-app.sh מתוכה."; exit 1; }
for t in ffmpeg uv; do
  command -v $t >/dev/null || { alert "חסר $t. בטרמינל: brew install ffmpeg uv"; exit 1; }
done
xattr -dr com.apple.quarantine "$ROOT" 2>/dev/null

is_ours() { curl -sf -m 2 "http://127.0.0.1:$1/" 2>/dev/null | grep -q "audio-enhance-ui" ; }

for p in {8787..8806}; do                      # already running? just open it
  if is_ours $p; then open "http://127.0.0.1:$p/"; exit 0; fi
done
for p in {8787..8806}; do
  nc -z 127.0.0.1 $p 2>/dev/null && continue   # taken by something else
  nohup "$ROOT/ui/server.py" --port $p --no-open --idle-exit 15 >"$LOG" 2>&1 &
  disown
  for i in {1..240}; do                        # the first run may build the uv environment
    is_ours $p && { open "http://127.0.0.1:$p/"; exit 0; }
    sleep 0.5
  done
  alert "השרת לא עלה. הפרטים ב: $LOG"
  exit 1
done
alert "לא נמצאה יציאה פנויה (8787 עד 8806)."
LAUNCH
chmod +x "$APP/Contents/MacOS/launch"
codesign --force --sign - "$APP" >/dev/null 2>&1 || true
touch "$APP"
echo "built $APP"

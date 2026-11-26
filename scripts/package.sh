#!/bin/zsh
# Build dist/SoundGOD-<version>-macos-arm64.zip: everything needed to run, models included.
# Upload that file as a GitHub Release asset.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAME="SoundGOD-$(cat "$ROOT/VERSION")-macos-arm64"
[ -x "$ROOT/bin/noise-reduction" ] || { echo "bin/noise-reduction is missing: run scripts/build-cli.sh" >&2; exit 1; }
[ -f "$ROOT/models/nemotron-re-use/model.safetensors" ] || { echo "model weights are missing" >&2; exit 1; }
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/$NAME" "$ROOT/dist"
rsync -a --exclude dist/ --exclude samples/ --exclude .test/ --exclude .git/ --exclude docs/ --exclude models/sidon/ \
  --exclude __pycache__/ --exclude '*.profraw' --exclude .DS_Store "$ROOT/" "$STAGE/$NAME/"
rm -f "$ROOT/dist/$NAME.zip"
( cd "$STAGE" && ditto -c -k --keepParent --norsrc --noextattr --noacl "$NAME" "$ROOT/dist/$NAME.zip" )   # ditto keeps exec bits and .bundle dirs intact
echo "built dist/$NAME.zip ($(du -h "$ROOT/dist/$NAME.zip" | cut -f1))"
shasum -a 256 "$ROOT/dist/$NAME.zip"

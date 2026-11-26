#!/bin/zsh
# Build the release zips into dist/ and upload them as GitHub Release assets:
#   SoundGOD-<version>-macos-arm64.zip           Apple silicon: the MLX tool in bin/ (fast, GPU)
#   SoundGOD-<version>-windows-macos-intel.zip   Windows and Intel Macs: no bin/, the clean engine runs on PyTorch (CPU)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VER="$(cat "$ROOT/VERSION")"
[ -x "$ROOT/bin/noise-reduction" ] || { echo "bin/noise-reduction is missing: run scripts/build-cli.sh" >&2; exit 1; }
[ -f "$ROOT/models/nemotron-re-use/model.safetensors" ] || { echo "model weights are missing" >&2; exit 1; }
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$ROOT/dist"

build() {  # build NAME [extra rsync excludes...]
  local NAME="$1"; shift
  mkdir -p "$STAGE/$NAME"
  rsync -a --exclude dist/ --exclude samples/ --exclude .test/ --exclude .git/ --exclude .github/ --exclude docs/ --exclude models/sidon/ \
    --exclude __pycache__/ --exclude '*.profraw' --exclude .DS_Store "$@" "$ROOT/" "$STAGE/$NAME/"
  rm -f "$ROOT/dist/$NAME.zip"
  ( cd "$STAGE" && ditto -c -k --keepParent --norsrc --noextattr --noacl "$NAME" "$ROOT/dist/$NAME.zip" )   # ditto keeps exec bits and .bundle dirs intact
  echo "built dist/$NAME.zip ($(du -h "$ROOT/dist/$NAME.zip" | cut -f1))"
  shasum -a 256 "$ROOT/dist/$NAME.zip"
}

build "SoundGOD-$VER-macos-arm64" --exclude start.bat
build "SoundGOD-$VER-windows-macos-intel" --exclude bin/ --exclude scripts/build-cli.sh

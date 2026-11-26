#!/bin/zsh
# Build the MLX command-line tool from source into bin/. Needs Apple silicon, macOS 14+, Xcode.
# Pinned to the commit this project was developed and tested against.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO=https://github.com/JacobLinCool/apple-efficient-noise-reduction
COMMIT=31a2e64d08d03109cf4b33f33c5d17a7e64c871c
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
git clone -q "$REPO" "$WORK/src"
git -C "$WORK/src" checkout -q "$COMMIT"
# MLX compiles Metal shaders; Xcode needs the Metal Toolchain component (~840 MB, one time)
xcodebuild -downloadComponent MetalToolchain || true
( cd "$WORK/src" && make build )
R="$WORK/src/.build/xcode/Build/Products/Release"
rm -rf "$ROOT/bin"; mkdir -p "$ROOT/bin"
cp -R "$R/noise-reduction" "$R"/*.bundle "$ROOT/bin/"
echo "built $ROOT/bin/noise-reduction"

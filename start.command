#!/bin/zsh
# Double-click to open the local UI in your browser.
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
xattr -dr com.apple.quarantine . 2>/dev/null      # a downloaded zip is quarantined; the bundled tool must be allowed to run
for t in ffmpeg uv; do
  command -v $t >/dev/null || { echo "$t is missing. Install it with:  brew install $t"; read -k 1 "?press any key"; exit 1; }
done
if [ "$(sysctl -n hw.optional.arm64 2>/dev/null)" != 1 ]; then   # Intel Mac: the AI engine runs on PyTorch, set it up once
  echo "Preparing the AI engine. The first time this downloads about 1 GB and takes a few minutes."
  uv run -q --script engine/nemotron.py --help >/dev/null || { read -k 1 "?press any key"; exit 1; }
fi
exec ./ui/server.py

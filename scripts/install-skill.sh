#!/bin/zsh
# Install the studio-audio skill for Claude Code, pointing at THIS copy of the project.
# CLAUDE_SKILLS_DIR overrides the target (default ~/.claude/skills).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}/studio-audio"
[ -L "$DEST" ] && rm "$DEST"          # an older install may be a symlink
mkdir -p "$DEST"
ESC="${ROOT//&/\\&}"
sed "s#{{ROOT}}#${ESC}#g" "$ROOT/skill/SKILL.md.tmpl" > "$DEST/SKILL.md"
echo "installed: $DEST/SKILL.md  (engine: $ROOT/engine/enhance.py)"

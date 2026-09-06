#!/usr/bin/env bash
# 選用：把五個技能 symlink 到已安裝工具的全域技能目錄，讓 /inventory 在任何專案目錄都能用。
# 只處理實際存在的工具目錄；不覆蓋既有同名技能。
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$REPO/.agents/skills"

link_into() {  # $1 = 目標技能目錄
  local dest="$1"
  mkdir -p "$dest"
  for skill in "$SRC"/*/; do
    local name; name="$(basename "$skill")"
    if [ -e "$dest/$name" ] && [ ! -L "$dest/$name" ]; then
      echo "  略過 $dest/$name（已有非 symlink 的同名技能）"
    else
      ln -sfn "$skill" "$dest/$name"
      echo "  連結 $dest/$name"
    fi
  done
}

[ -d "$HOME/.claude" ]   && { echo "Claude Code";  link_into "$HOME/.claude/skills"; }
[ -d "$HOME/.codex" ]    && { echo "Codex / Cursor / OpenClaw（共用 ~/.agents/skills）"; link_into "$HOME/.agents/skills"; }
[ -d "$HOME/.gemini/antigravity" ] && { echo "Google Antigravity"; link_into "$HOME/.gemini/antigravity/skills"; }
[ -d "$HOME/.hermes" ]   && { echo "Hermes Agent";  link_into "$HOME/.hermes/skills"; }
[ -d "$HOME/.cursor" ] && [ ! -d "$HOME/.codex" ] && { echo "Cursor"; link_into "$HOME/.agents/skills"; }
echo "完成。重新開啟你的 agent 工作階段後即可使用 /inventory。"

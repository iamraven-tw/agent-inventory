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
# 把這份 clone 的絕對路徑寫進設定檔的 repoRoot；技能被連結到全域目錄後，agent 從任何目錄都找得到 bin/ 與 data/。
CFG="${AGENT_INVENTORY_CONFIG:-$HOME/.config/agent-inventory/config.json}"
mkdir -p "$(dirname "$CFG")"
python3 - "$CFG" "$REPO" <<'EOS'
import json, os, sys
cfg_path, repo = sys.argv[1], sys.argv[2]
cfg = json.load(open(cfg_path, encoding="utf-8")) if os.path.isfile(cfg_path) else {}
cfg["repoRoot"] = repo
with open(cfg_path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2); f.write("\n")
print(f"  repoRoot = {repo} → {cfg_path}")
EOS
echo "完成。重新開啟你的 agent 工作階段後即可使用 /inventory。"

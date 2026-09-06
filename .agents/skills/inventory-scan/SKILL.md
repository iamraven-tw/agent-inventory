---
name: inventory-scan
description: agent-inventory 的第二步：依設定檔掃描六個 AI agent 工具的全域規則、全域技能、專案規則、專案技能，去重並標記跨工具共用，產出 data/inventory.json 與待補摘要清單。使用者說「重新掃描規則與技能」「更新 inventory」時使用。
---

# inventory-scan — 掃描

## 執行

```bash
python3 bin/scan.py
```

沒有設定檔時可以臨時指定：

```bash
python3 bin/scan.py --roots "~/Developer,~/Projects" --tools claude-code,codex --depth 4
```

## 它做了什麼

- 依 `adapters/` 底下每個工具的規格（哪些路徑是全域規則、全域技能、專案裡要找哪些檔）逐一掃描。六個工具的路徑對照表見 repo 的 `README.md`。
- 用 realpath 去重：同一個技能透過 symlink 或共用目錄（例如 `~/.agents/skills` 同時餵 Codex、Cursor、OpenClaw）被多個工具讀到時，只算一個項目，記錄在 `tools[]` 裡，網站上顯示「共用於 ×N」。
- 摘要分兩層：技能 frontmatter 有 `description` 就直接用；規則檔通常沒有，會列進 `data/pending-summaries.json`，由下一步的 agent 撰寫。之前寫過的摘要存在 `data/summary-cache.json`（以內容 hash 為 key），檔案沒改就直接沿用。
- 只寫 `@AGENTS.md` 之類引用的 CLAUDE.md 會自動判定為「引用檔」，不需要另寫摘要。

## 輸出

- `data/inventory.json`：網站的唯一資料來源。
- `data/pending-summaries.json`：待補摘要清單，每筆含 `id`、`name`、`path`、`excerpt`（最多 2500 字的內文節錄）。

## 回報格式

把腳本印出的表格轉述給使用者：每個工具的全域規則、全域技能、專案數、專案規則、專案技能數量，以及「跨工具共用」與「待補摘要」兩個總數。若某工具顯示「未偵測到」，說明那一列是它「如果安裝了會讀到」的共用目錄內容。

待補摘要大於 0 時，接著執行 `inventory-summarize`；等於 0 就直接執行 `inventory-serve`。

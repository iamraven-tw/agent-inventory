---
name: inventory-setup
description: agent-inventory 的第一步：偵測這台電腦裝了哪些 AI agent 工具、找出候選的專案根目錄，用選項框問使用者要掃哪些，然後寫入 ~/.config/agent-inventory/config.json。使用者說「設定 inventory」「重新設定掃描範圍」或 /inventory 發現沒有設定檔時使用。
---

# inventory-setup — 問清楚要掃什麼

## 步驟

### 0. 取得 $REPO

先取得 `$REPO`（agent-inventory 的 clone 目錄）。所有指令與 `data/` 路徑都用它當前綴，從任何目錄執行都可以，不需要 cd：

```bash
REPO="$(python3 -c 'import json,os;p=os.path.expanduser(os.environ.get("AGENT_INVENTORY_CONFIG","~/.config/agent-inventory/config.json"));print(json.load(open(p)).get("repoRoot","") if os.path.isfile(p) else "")')"; [ -z "$REPO" ] && [ -f bin/scan.py ] && REPO="$PWD"; echo "REPO=$REPO"
```

印出空白代表兩邊都找不到：問使用者 clone 放在哪，第 3 小節就會把它寫進設定檔的 `repoRoot`。

### 1. 跑偵測腳本

```bash
python3 "$REPO/bin/detect.py" --json
```

輸出包含：
- `repoRoot`：這份 clone 的絕對路徑，原樣寫進設定檔。
- `tools[]`：六個支援的工具，各有 `installed`（是否偵測到）與 `evidence`（憑什麼判斷）。
- `candidateRoots[]`：候選專案根目錄，附底下含規則或技能的專案數，已排除工具自己的家目錄、Library、node_modules、Go 套件快取。
- `projects[]`：實際找到的專案資料夾清單。

### 2. 問使用者（用你所在工具的選項框功能）

Claude Code 用 AskUserQuestion；Codex、Antigravity、Cursor 等用各自的提問方式；沒有選項框就在對話裡列出編號讓使用者選。**兩個問題一次問完**：

**問題 A：要盤點哪些 AI agent？**（可多選）
- 把偵測到的工具預設勾起來，沒偵測到的也列出來但標「未偵測到」。
- 使用者可以保留未偵測到的工具（例如剛好想看 Cursor 會讀到哪些共用目錄）。

**問題 B：要掃描哪些專案根目錄？**（可多選）
- 選項就是 `candidateRoots`，每個標上專案數，例如「~/Developer（15 個專案）」。
- 一定要留一個「我自己輸入路徑」的出口，使用者可能有外接磁碟或不在常見位置的資料夾。
- 若 `candidateRoots` 為空，直接請使用者輸入路徑。

可選的第三個問題：摘要語言（預設繁體中文；使用者用英文對話時預設英文）。

### 3. 寫入設定檔

```bash
mkdir -p ~/.config/agent-inventory
```

寫入 `~/.config/agent-inventory/config.json`，格式：

```json
{
  "repoRoot": "/絕對路徑/agent-inventory",
  "tools": ["claude-code", "codex", "antigravity", "cursor", "openclaw", "hermes"],
  "projectRoots": ["~/Developer", "~/Projects"],
  "scanDepth": 4,
  "language": "zh-TW"
}
```

- `repoRoot` 直接用 `detect.py` 印出的值（絕對路徑，不用 `~`）；設定檔已存在時保留其他欄位，只更新要改的鍵。
- `tools` 只放使用者選的 id（合法值：`claude-code`、`codex`、`antigravity`、`cursor`、`openclaw`、`hermes`）。
- `projectRoots` 用 `~` 開頭的相對家目錄寫法，方便日後換機器。
- `scanDepth` 預設 4；使用者的專案巢狀很深時可以調到 5 或 6，但會變慢。

### 4. 回報

一句話說明寫了什麼設定，然後接著執行 `inventory-scan`。

## 注意

- 這一步是整個流程唯一需要使用者回答的地方，問完就不要再問。
- 若設定檔已存在而使用者只是想重跑掃描，不需要重新問，直接用舊設定。
- 不要把使用者的家目錄整個當根目錄（會掃到 Library 與各種快取，很慢又沒意義）；候選清單裡不會有它，使用者堅持要時提醒一次再照做。

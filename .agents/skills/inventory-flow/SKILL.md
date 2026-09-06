---
name: inventory-flow
description: agent-inventory 的第四步：為每個技能畫一張 Mermaid 流程圖，並標出哪些節點需要人類介入、哪些由 AI agent 執行，寫成 JSON 後用 bin/merge.py 合併。掃描後「待補流程圖」大於 0 時使用；使用者說「補流程圖」「畫技能流程」時也用。
---

# inventory-flow — 為每個技能畫流程圖

網站上點開任何技能，摘要下方會顯示這張流程圖。圖的重點不是把 SKILL.md 抄一遍，而是讓人一眼看出**這個技能怎麼跑、哪裡會停下來等人**。

## 步驟

### 0. 取得 $REPO

先取得 `$REPO`（agent-inventory 的 clone 目錄）。所有指令與 `data/` 路徑都用它當前綴，從任何目錄執行都可以，不需要 cd：

```bash
REPO="$(python3 -c 'import json,os;p=os.path.expanduser(os.environ.get("AGENT_INVENTORY_CONFIG","~/.config/agent-inventory/config.json"));print(json.load(open(p)).get("repoRoot","") if os.path.isfile(p) else "")')"; [ -z "$REPO" ] && [ -f bin/scan.py ] && REPO="$PWD"; echo "REPO=$REPO"
```

印出空白代表兩邊都找不到：問使用者 clone 放在哪，之後由 `inventory-setup` 寫進設定檔的 `repoRoot`。

### 1. 讀待補清單

```bash
python3 -c "import json,sys; p=json.load(open(sys.argv[1])); print(len(p)); [print(x['id'], x['name'], x['path']) for x in p[:40]]" "$REPO/data/pending-flows.json"
```

每筆有 `id`、`name`、`path`、`description`（作者寫的說明）、`steps`。`steps` 是掃描器抽出來的骨架，三種前綴：

| 前綴 | 意思 |
| :-- | :-- |
| `#` | 標題（通常就是流程的階段） |
| `-` | 編號步驟、清單項目或表格列 |
| `!` | 這一行提到確認、授權、審核、人類、拍板之類的字眼，**極可能是人類介入點** |

數量很多時分批做，每批 30 到 40 筆。讀 `steps` 就夠了；只有骨架看不出流程時，才用 Read 開原始檔前 150 行。

### 2. 為每個技能寫一張流程圖

規格：

- **Mermaid `flowchart TD`**（由上而下）。抽屜只有 620 像素寬，`LR` 會擠成一團。
- **4 到 8 個節點**。太細會看不懂，太粗沒有資訊。抓「輸入 → 主要階段 → 產出」這條主線，分支只保留真正會影響走向的判斷。
- **每個節點都要標身分**：節點後面加 `:::agent` 或 `:::human`。
  - `:::human` — 這一步必須由人做或由人拍板：確認、選擇、授權發布、實際錄影、登入。
  - `:::agent` — AI agent 自己完成：查資料、寫檔、呼叫 API、驗證。
  - 顏色與圖例由網站自動加上，**不要自己寫 `classDef`**。
- **節點文字用繁體中文**，8 到 14 個字，動詞開頭。含有 `()` `[]` `:` 等符號時整段用雙引號包起來：`A["確認規格（含尺寸）"]:::agent`。
- 需要換行用 `<br/>`。
- 判斷節點用 `{ }`，例如 `D{通過驗證？}:::agent`。

同時填 `humanGates`：**依流程順序**列出每個人類介入點在做什麼決定，一項一句話。全程自動就給空陣列 `[]`。這份清單會顯示在圖下方，所以要寫得像給人看的檢查表，不是節點文字的複製。

### 3. 寫成 JSON 批次檔

檔名 `$REPO/data/flows/batch-<三位數>.json`：

```json
{
  "aad1190da7fa": {
    "mermaid": "flowchart TD\n    A[任務需要 1Password 的密碼]:::agent --> B[關閉 Bash 沙箱]:::agent\n    B --> C[執行 op read 讀取]:::agent\n    C --> D{Touch ID 授權}:::human\n    D --> E[取得密碼並繼續任務]:::agent",
    "humanGates": ["在 1Password 桌面 App 按 Touch ID 授權這次讀取"]
  },
  "e8d8f807f164": {
    "mermaid": "flowchart TD\n    A[使用者提供網址]:::human --> B[defuddle parse --md 抽取內文]:::agent\n    B --> C[回傳乾淨 Markdown]:::agent",
    "humanGates": ["提供要讀的網址"]
  },
  "f357bf13dbb2": null
}
```

`null` 代表**我看過了，這個技能沒有多步驟流程**（純參考資料、語法對照、風格指南這類）。一定要寫 `null` 而不是跳過，否則它會一直留在待補清單。

判斷標準：技能內容是「照著做的步驟」就畫圖；是「查得到的知識」就給 `null`。例如 n8n 表達式語法、Obsidian Markdown 語法、配色資料庫屬於後者。

### 4. 合併

```bash
python3 "$REPO/bin/merge.py"
```

它會把流程圖寫進 `$REPO/data/inventory.json` 與 `$REPO/data/flow-cache.json`（以檔案內容 hash 為 key，技能沒改就不用重畫），更新待補清單，並把批次檔搬到 `$REPO/data/flows/done/`。

### 5. 回報

說明畫了幾張、幾個標為無流程、還剩幾筆。

## 注意

- `$REPO/data/user-flows.json` 裡的是使用者在網頁上手改的流程圖，merge.py 會跳過，你不要覆蓋。
- 不要把每個小標題都變成節點。一個技能只有一條主線，讀者要的是「我什麼時候得出手」。
- 沒有把握哪一步需要人時，看 `steps` 裡 `!` 開頭的行；那是掃描器找出來的候選。
- 流程圖語法錯誤時 merge.py 會擋下來（必須以 `flowchart` 或 `graph` 開頭），網站算不出圖時會退回顯示原始碼，不會整頁壞掉。

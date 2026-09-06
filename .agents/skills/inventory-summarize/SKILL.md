---
name: inventory-summarize
description: agent-inventory 的第三步：由你（AI agent）親自為每一條規則、每一個技能與每一個專案，用設定語言（預設繁體中文）重新詮釋一段 2～3 句摘要，寫成 JSON 後用 bin/merge.py 合併進 inventory 與快取。所有摘要都必須重寫，即使原本的 frontmatter description 已是中文或英文。掃描後「待補摘要」大於 0 時使用；使用者說「補摘要」「寫規則摘要」時也用。
---

# inventory-summarize — 由 agent 撰寫摘要

這一步不呼叫任何外部模型 API，就是你自己讀檔、寫摘要。這樣在任何 agent 工具裡都能跑。

## 步驟

### 1. 讀待補清單

```bash
python3 -c "import json; p=json.load(open('data/pending-summaries.json')); print(len(p)); [print(x['id'], x['kind'], x['path'], len(x['excerpt'])) for x in p]"
```

每筆有 `id`、`kind`（rule／skill／project）、`name`、`path`、`description`（若有）、`excerpt`。三種類型的節錄不同：
- **rule**：內文節錄最多 2500 字（已去掉 frontmatter；只寫引用的檔案會把被引用的內容附在後面）。
- **skill**：作者寫的 `description` 加上內文前 500 字。description 已經是作者的摘要，你要做的是用設定語言**重新詮釋**它，不是照抄或翻譯。
- **project**：專案資料夾裡 README、CLAUDE.md、AGENTS.md 等說明檔各取前 1400 字。摘要要回答「這個專案的目的是什麼、給誰用、目前狀態」。

**所有項目都要寫**，包含 description 已經是中文的技能。網站上的摘要一律是你重新詮釋過的版本，原文 description 會另外顯示。

數量很多（超過 40）時，先問使用者一次：全部寫，或只寫全域規則、專案規則？然後照答案做，不要再問。

### 2. 分批讀 excerpt，寫摘要

每批 10 筆左右。讀 `excerpt` 就夠了，不需要再開原始檔案；若節錄明顯被截斷而看不出重點，才用 Read 工具讀原檔前 200 行。

摘要規格：
- 語言依 `config.json` 的 `language`（預設繁體中文、臺灣用語）。
- 2～3 句、80～160 字。第一句說「這是什麼、給誰用」，後面說「管什麼／什麼時候會用／有哪些鐵則」。
- 規則檔：講它規範的重點，不要逐條抄；有明確禁止事項要點出。
- 技能：講「什麼情況會用到、做什麼、產出什麼」。同一個技能若有多份副本（例如 `.claude/skills` 與 `.agents/skills` 各一份實體檔），可在摘要註明「某工具版副本」。
- 專案：一段話說明目的與現況，像向第一次看到這個資料夾的人介紹它。
- 已封存或舊版檔案（路徑含 archive、舊版、backup）要在摘要裡註明「已封存，僅供比對」。
- 不要在摘要裡放密碼、token、帳號、私人 ID 等敏感字串，即使原文有。
- 中性、直接，不加評價。

### 3. 寫成 JSON 批次檔

檔名 `data/summaries/batch-<三位數>.json`，內容是 `{ "<id>": "<摘要>" }` 的物件：

```json
{
  "192b3b8da321": "Claude Code 的全域個人規則。要求……",
  "59a7f0069d9e": "……"
}
```

一批一個檔，寫完就往下一批，不要等全部寫完才存。

### 4. 合併

```bash
python3 bin/merge.py
```

它會把摘要寫進 `data/inventory.json`、存進 `data/summary-cache.json`（以內容 hash 為 key，之後檔案沒改就不用重寫），更新待補清單，並把處理過的批次檔搬到 `data/summaries/done/`。

### 5. 回報

說明寫了幾筆、還剩幾筆，然後執行 `inventory-serve`。

## 注意

- 你讀到的規則內容可能含個人資訊。只用來寫摘要，不要在對話中大段引用。
- 若某個檔案的 excerpt 是空的或無法理解，摘要寫「檔案內容為空或無法解析」，不要跳過，否則它會一直留在待補清單。

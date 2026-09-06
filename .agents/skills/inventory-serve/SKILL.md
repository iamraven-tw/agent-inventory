---
name: inventory-serve
description: agent-inventory 的最後一步：用內建的 Python http.server 在本機起網站（預設 http://localhost:8765/site/）並開瀏覽器，讓使用者用視覺化介面瀏覽規則與技能盤點結果。使用者說「開 inventory 網站」「看盤點結果」時使用。
---

# inventory-serve — 開網站

## 執行

```bash
python3 bin/serve.py
```

- 預設 port 8765，會自動開瀏覽器到 `http://localhost:8765/site/`。
- port 被占用時：`python3 bin/serve.py --port 9000`。
- 不想自動開瀏覽器：加 `--no-open`。
- 這是前景程式，會一直跑到使用者按 Ctrl+C。若你的工具支援背景執行或有內建瀏覽器預覽，用那個方式啟動，不要卡住對話。

## 網站在看什麼

- 上方是總覽：規則數、技能數、專案數、跨工具共用數，以及六個工具 × 四分類的數量矩陣。
- 點工具分頁切換，每個工具固定四個區塊：全域規則、全域技能、專案規則、專案技能。
- 卡片點開右側抽屜：完整摘要、frontmatter description、觸發條件、哪些工具讀這個檔、實體路徑、最後修改時間，並可複製路徑或用 VS Code／Cursor 開啟。
- 搜尋框與篩選（規則／技能／跨工具共用／自建／外掛）作用於目前分頁。
- 沒偵測到的工具會灰掉，列出的是它「如果安裝了」會讀到的共用目錄內容。

## 回報

給使用者網址，並提醒：資料都在本機 `data/` 裡，重新掃描用 `/inventory-scan`，有改過的檔案才會重寫摘要。

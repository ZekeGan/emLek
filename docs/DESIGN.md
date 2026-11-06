# emLek 產品與規格索引

## 定位

本機、單一使用者、Windows 優先的個人長期文字記憶庫。AI 經 MCP／CLI 保存、查找與追溯，核心只寫一份。規格描述現行核定行為；實作差距與驗收狀態只見 [PROGRESS](PROGRESS.md)。

## 核心原則

原文不可變，修改新增版本；未知作者／日期／來源留未知，original／ai_summary／inference 分開。一般問題不讀不存；個人敘述須主動 start 首次同意，最高風險永不新增保存。一般刪除可恢復，徹底清除保留真人終端機與 PIN；備份匯出可攜。

## 規格分工

| 領域 | 唯一規格來源 |
|---|---|
| 儲存、資料模型、時間精度與限制 | [STORAGE](spec/STORAGE.md) |
| 筆記、版本、隱藏／清除、工具與自動記錄 | [MEMORY](spec/MEMORY.md) |
| 搜尋、日期過濾、排序、摘要與分頁 | [SEARCH](spec/SEARCH.md) |
| 同意、敏感掃描、PIN、權限與威脅模型 | [SECURITY](spec/SECURITY.md) |
| 標籤、別名、近似名稱與階層 | [DESIGN_TAGS](DESIGN_TAGS.md) |
| 匯入、備份加密、還原與匯出 | [TRANSFER](spec/TRANSFER.md) |
| AI 操作與回答 | [AGENT_RULES](AGENT_RULES.md)；簡報見 [範本](DAILY_BRIEFING.md) |

程式／測試路由以 [areas.json](areas.json) 為準，`workflow.py context <領域>` 定位、`--read` 取章節。開發見 [WORKFLOW](WORKFLOW.md)，版本／發布見 [RELEASING](RELEASING.md)，重要取捨查 [DECISIONS](DECISIONS.md)。

## 刻意不做

不做多使用者、身分隔離／授權 grant、常駐服務、向量／語意搜尋、完整知識圖譜、查詢歷史、獨立搜尋庫／outbox、長期自動分析、獨立簡繁對照表。語意搜尋重新評估及其他未核定方向只列 [ROADMAP](ROADMAP.md)，不能因文件整理自行開發。

## 已知限制

資料庫本體、匯出與遷移前副本為明文，只有備份可選加密。同帳號且能執行命令的 AI 可直接接觸檔案，MCP 唯讀／終端機檢查不是絕對隔離。搜尋受用詞及標籤覆蓋限制，不能保證完整；只找得到確實保存的內容。完整威脅模型見 SECURITY。

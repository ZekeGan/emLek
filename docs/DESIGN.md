# emLek 設計

狀態：規劃中，尚未實作。取代 [archive](archive/) 的完整版藍圖（非現行規格）。決策原因見 [DECISIONS](DECISIONS.md)。

## 定位

單一使用者、單一 Windows 電腦、本機優先、不上雲；只管理文字；信任使用者自己的 AI。目標：AI 能存、能找、能追溯來源，換設備能簡單備份搬家。只做本檔列出的功能，其餘等實際遇到痛點再加。

## 核心原則

1. 原文不可變：修改＝新增版本。
2. 來源與時間必標；未知記為未知，不補造。
3. 內容分三類：`original`（使用者原文）、`ai_summary`（AI 整理）、`inference`（AI 推論）。
4. 預設不讀不存；只有明確指令才存（[AGENT_RULES](AGENT_RULES.md)）。
5. 可離開：隨時匯出 JSON／Markdown。

## 技術選型

| 項目 | 選擇 |
|---|---|
| 語言 | Python 3.14（uv 管理） |
| 資料庫 | 單一 SQLite 檔 |
| 搜尋 | 同檔 FTS5 trigram；1–2 字元短詞改逐筆掃描（LIKE），資料量小時可接受，不足再評估 |
| AI 入口 | MCP（stdio）＋命令列 CLI；核心只寫一份，兩者都是薄外殼 |
| 加密 | 日常靠 Windows 裝置加密；備份可選密碼加密，用現成函式庫，不自寫 |

## 資料模型

| 表 | 欄位 |
|---|---|
| `records` | `id`、`created_at`、`hidden`、`hidden_at` |
| `revisions` | `id`、`record_id`、`version_no`、`body`（UTF-8）、`kind`、`created_at`、`event_time`（可空）、`event_time_precision`（可空）、`source`（可空＝未知） |
| `links` | `revision_id`、`derived_from_revision_id` |
| `phrases` | `id`、`kind`（save／purge／exclude）、`text`、`enabled`、`created_at`、`updated_at` |
| `meta` | schema 版本 |

另有 FTS5 虛擬表索引 `revisions.body`。

規則：
- `revisions` 寫入後不可更新或刪除（徹底清除除外）；修改＝同一 `record_id` 新增下一個 `version_no`。
- `ai_summary`、`inference` 以 `links` 指向依據版本。
- 資料庫不存絕對路徑；搜尋預設排除 `hidden`。

## 自訂語句

使用者以 CLI 增刪改查，存在資料庫隨備份搬家。預設：`save`＝記住、幫我記一下、存起來、記憶；`purge`＝完全刪除；`exclude`＝上週記住了文法（不算指令的範例）。

| 命令 | 作用 |
|---|---|
| `emlek phrase list [kind]` | 查 |
| `emlek phrase add <kind> "<語句>"` | 增 |
| `emlek phrase set <id> "<新語句>"` | 改、啟用或停用 |
| `emlek phrase remove <id>` | 刪 |

- AI 只能用 MCP 唯讀工具 `phrases_list`。
- 動到 `purge` 類語句必須在真人互動終端機重新輸入確認；非互動環境（腳本、AI 代跑）拒絕。沒有啟用的 `purge` 語句時，徹底清除關閉。
- 限制：能執行命令的 AI 理論上仍可嘗試呼叫 CLI；互動確認是主要防線，不是絕對隔離。
- 語句只是 AI 的判斷依據，不是機械比對。

## 刪除

| 層級 | 行為 |
|---|---|
| 隱藏（預設的「刪除」） | `hidden=1`，搜尋與一般讀取看不到，可 `unhide` 恢復 |
| 徹底清除 | 真正移除該記錄所有版本與索引，無法恢復；對話流程見 [AGENT_RULES](AGENT_RULES.md) §3 |

徹底清除的實作：`purge_preview` 回傳摘要與一次性確認碼，`purge_confirm` 帶確認碼才執行；完成後 `VACUUM`。**不改動既有備份**，回覆須提醒使用者自行處理舊備份，並說明已傳給第三方 AI 的內容無法收回。第一版先做隱藏，徹底清除在步驟 5。

## 工具（MCP／CLI 共用）

| 動作 | 說明 |
|---|---|
| `save` | 新增；參數：內容、kind、來源、事件時間（可空）、依據版本（可空） |
| `amend` | 為既有記錄新增版本 |
| `search` | 全文搜尋，回傳記錄、版本、來源、片段 |
| `get` | 讀取指定記錄／版本 |
| `hide`／`unhide` | 隱藏與恢復 |
| `purge_preview`／`purge_confirm` | 徹底清除兩步 |
| `phrases_list` | 唯讀取得啟用語句 |

僅 CLI（不開放 MCP）：`backup`、`restore`、`export`、`phrase add·set·remove`。查詢預設 20 筆、上限 100；過長內容標明已截斷並提供取得剩餘部分的方式。

## 備份與搬家

1. 資料在一個 Vault 資料夾，主體是一個 `.db`（含搜尋索引）。
2. `emlek backup`：用 SQLite 一致性備份（backup API 或 `VACUUM INTO`）產生帶日期的單一檔，不直接複製使用中的檔案。可選 `--encrypt` 密碼加密，須提醒密碼遺失無法還原。
3. `emlek export`：完整 JSON（含所有版本與關係）＋供閱讀的 Markdown。
4. `emlek restore <備份檔>`：還原後驗證完整性與筆數。
5. 換設備：舊機 backup → 新機安裝 → restore → 重新指向 MCP 設定。

## 開發順序

| 步驟 | 內容 | 完成標準 |
|---|---|---|
| 1 | 資料庫＋`save`／`get`／`search`（CLI） | 合成資料存取、中日英搜尋正確；版本不覆蓋 |
| 2 | MCP 外殼 | 至少一個 AI 實際呼叫並找回 |
| 3 | 版本與來源連結、`hide`／`unhide`、`phrase`、`phrases_list` | 修改產生新版本；隱藏後搜不到可恢復；語句增刪改查可用，AI 端唯讀 |
| 4 | `backup`／`restore`／`export` | 乾淨資料夾還原後筆數與內容一致 |
| 5 | 徹底清除 | 預覽、確認碼、清除後搜不到且資料庫無殘留 |
| 6 | 依實際痛點決定 | — |

## 刻意不做

身分／SID／named pipe 隔離、授權 grant、提案→確認→提交流程、獨立安全帳本與防備份復活、restic、獨立搜尋庫與 outbox、長期分析掃描、向量搜尋、知識圖譜。需要時從 archive 取用。

## 已知限制

- AI 是否正確判斷「要不要存」靠使用指示，軟體無法強制。
- 徹底清除不影響既有備份與第三方副本。
- 軟體層不加密資料庫本體。
- 只能找回使用者主動保存的內容。

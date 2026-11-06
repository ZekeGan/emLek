# 儲存與核心契約

現行規格；工作狀態只見 [PROGRESS](../PROGRESS.md)，測試見 [TEST_PLAN](../TEST_PLAN.md)。

## 技術選型

| 項目 | 選擇 |
|---|---|
| 語言 | Python 3.14（uv 管理） |
| 資料庫 | 單一 SQLite 檔 |
| 搜尋 | 同檔 FTS5 trigram，建在正規化副本 `revisions.body_norm` 上。查詢拆成詞：3 字元以上走 FTS5，1–2 字元走 LIKE 逐筆掃描，各詞結果取交集；FTS5 對某詞無結果時補跑 LIKE 再下結論。有 3 字元以上的詞時，先用 FTS5 取候選再對候選做 LIKE 驗證；只有短詞時先用標籤或日期縮小範圍。實測（合成 3.6 萬筆、平均約 1.7K 字元）：2 字元 LIKE 全掃約 0.5 秒、3 字元以上 FTS5 低於 1 毫秒，資料庫約為原文位元組的 2.5 倍 |
| AI 入口 | MCP（stdio）＋命令列 CLI；核心只寫一份，兩者都是薄外殼 |
| 加密 | 資料庫本體不加密，doctor 如實提示；最高風險永不新增保存，建議使用密碼管理器。備份可選密碼加密，資料庫本體加密的未核定方向見 ROADMAP |

實作層的技術決定（目錄、套件、遷移、CLI 與 MCP 函式庫）見 [WORKFLOW](../WORKFLOW.md)。

## 資料模型

| 表 | 欄位 |
|---|---|
| `records` | `id`、`created_at`、`hidden`、`hidden_at`、`sensitivity`（none／medium／high） |
| `revisions` | `id`、`record_id`、`version_no`、`body`（UTF-8 原文）、`body_norm`（NFKC＋casefold 的衍生副本，供搜尋）、`kind`、`created_at`、`event_time`（可空）、`event_time_precision`（可空）、`source`（可空＝未知）、`event_date_start`／`event_date_end`（由 event_time 與精度推出的日曆日期區間，虛擬欄位，供日期範圍查詢） |
| `links` | `revision_id`、`derived_from_revision_id`、`relation`（選填） |
| `phrases` | `id`、`kind`（save／purge／exclude）、`text`、`enabled`、`created_at`、`updated_at` |
| `notice_settings` | `level`（保留相容鍵 medium，代表全體個人資訊同意）、`enabled`、`acknowledged_at` |
| `import_batches`、`import_log` | 批次與每檔紀錄：`file_name`、`content_hash`、`record_id`（清除後為空）、`purged`、`batch_id`、`imported_at`（M8 精簡版，`chunk_index` 延後） |
| 標籤相關 | `tags`、`record_tags`、`tag_links`、`tag_aliases`、`tag_events`，見 [DESIGN_TAGS](../DESIGN_TAGS.md) |
| `meta` | schema 版本、上次備份時間 |

規則：
- `revisions` 寫入後不可更新或刪除（徹底清除除外，見「刪除」）；修改＝同一 `record_id` 新增下一個 `version_no`。`body_norm` 是可重建的衍生資料。
- `ai_summary`、`inference` 以 `links` 指向依據版本。
- `links.relation` 選填：`supersedes`（推翻）、`supports`（支持）、`supplements`（補充）、`derived`（衍生）、`summarizes`（摘要涵蓋該來源）；空＝未指定。
- 改錯字、補充＝同一記錄新增版本；改變看法或推翻結論＝新記錄，並以 `links` 連回被推翻的版本，才能呈現「某時間點改變了想法」的完整時間線。
- `event_time` 一律存實際日期（「昨天」須由 AI 換算），可以是未來日期，用來記期限、約定、預約；未知則空，查詢時另行標示，不排除也不假裝完整。
- 資料庫不存絕對路徑。

## 輸入輸出與儲存限制

- **位置**：預設 `%LOCALAPPDATA%/emlek/`（不在 OneDrive 等同步位置）；`--data-dir` 或 `EMLEK_DATA_DIR` 覆寫。資料夾內有資料庫與 `config.toml`（`timezone`，預設 `local`＝系統時區；`backup_dir`；由 `init` 建立）。`emlek init` 建立並限制只有目前使用者可存取（已實測 `icacls` 不需管理員權限）；`emlek doctor` 檢查 Python 與 SQLite 版本、FTS5 trigram、WAL 修補版本、資料夾是否在同步位置、權限、最近備份。
- **編號**：整數主鍵；對外顯示為 `r<id>`、`r<id>.v<n>`。
- **時間**：`created_at` 存 UTC（ISO 8601，毫秒）。`event_time_precision` 為 year、month、day、hour、minute、second。year、month、day 存日曆日期字串（`2026`、`2026-11`、`2026-01-15`，不換算時區）；hour、minute、second 存含偏移的 ISO 8601（如 `2026-01-15T09:30+09:00`）。範圍查詢以該值涵蓋的時間區間與查詢區間有重疊即命中；「今天」的日界線依 `timezone`。
- **SQLite**：WAL、`synchronous=FULL`、`foreign_keys=ON`、`busy_timeout=5000`，啟動時讀回 PRAGMA 驗證。SQLite 須 ≥ 3.51.3（或修補線 3.50.7、3.44.6）才用 WAL，否則退回 `journal_mode=DELETE` 並警告。每個 `save` 為單一交易，記錄、版本、連結、標籤、全文索引全成功或全失敗。同一時間只有一個寫入交易，多行程（CLI 與 MCP）以 busy_timeout 序列化。
- **大小限制**：單版原文 ≤ 1 MiB（UTF-8 位元組），不得含 NUL（U+0000）或孤立代理字元；來源 ≤ 500 字元；每筆標籤 ≤ 20 個、名稱 ≤ 64 字元、說明 ≤ 200 字元；查詢 ≤ 512 字元；單頁 ≤ 100 筆。
- **搜尋正規化**：`body_norm` 與查詢都先做 NFKC 與 casefold，原文不動；簡繁不統一，用別名。
- **全文索引與一致性**：`revisions_fts` 是以 `body_norm` 為外部內容的 FTS5 trigram 表，由觸發器在同一交易內維護。查詢的 3 字元以上詞走索引、1–2 字元詞走 LIKE；索引沒有任何結果時補跑一次 LIKE 完整掃描，若掃描有結果就回 `warnings=["index_stale"]`，`doctor` 的 `search_index` 與 `emlek reindex` 用來檢查與重建。日期過濾對 `event_time` 用 `event_date_*`（照原文寫法的日曆日期，不換算時區），對 `created_at` 用使用者時區的日界線；M2 的 `timezone` 只支援 `local`（系統時區）與 `+09:00` 這類固定偏移，IANA 名稱（如 Asia/Tokyo）尚未支援，會回 `INVALID_INPUT`。
- **錯誤**：回傳 `{ok, error:{code, message, retryable, data?}}`。代碼：`INVALID_INPUT`、`NOT_FOUND`、`CONFLICT`、`NEEDS_CONFIRMATION`（待確認狀態也用此代碼，`error.data.state` 區分）、`TOKEN_INVALID`（確認碼錯誤、過期或已用過）、`NOT_PERMITTED`、`BUSY`、`INTERNAL`。CLI 結束碼：0 成功、1 內部錯誤、2 輸入錯誤、3 不允許或需確認、4 找不到或衝突、5 忙碌或暫時失敗。
- **匯出 v1**：資料夾內 `export.jsonl`（第一行 `{"type":"header","format_version":1,"schema_version":N,...}`，其後每行一個物件，`type` 為 record、revision、link、tag、record_tag、tag_link、tag_alias、tag_event、phrase、notice_setting、import_log、meta；隱藏的記錄照匯出並帶 `hidden` 旗標；不含 `body_norm`，匯入時重建）與 `markdown/`（每筆記錄一檔，含版本、標籤、來源，供閱讀）。
- **備份加密**：`cryptography` 的 AES-256-GCM，金鑰由 `hashlib.scrypt` 從密碼導出，參數與格式版本寫入檔頭，不儲存密碼。
- **語言與日誌**：CLI 與訊息預設繁體中文，欄位與代碼用英文；程式輸入輸出一律明確用 UTF-8。日誌不記內容。

## 核心與入口邊界

目前一律本機使用。以下準則讓日後加手機或遠端存取時不必重寫核心：
- 核心不依賴任何傳輸方式；MCP（stdio）與 CLI 只是外殼，日後可再加 HTTP 入口。
- 權限（唯讀、可寫、需真人終端機）由**核心**的權限表判斷，不只靠外殼，新入口自動繼承；遠端入口將不開放清除。
- 位置與設定可由參數或環境變數指定（`--data-dir`）；資料庫不存絕對路徑；資料庫不得放在同步資料夾。
- 工具輸入輸出用有版本號的格式（`api_version`），未知欄位拒絕，讓不同客戶端可共存。
- 資料庫結構從第一版就有版本與遷移機制。
- 日誌不記內容；提供健康檢查。
- 匯入與匯出用與工具無關的純文字格式。

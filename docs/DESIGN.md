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
| `links` | `revision_id`、`derived_from_revision_id`、`relation`（選填） |
| `phrases` | `id`、`kind`（save／purge／exclude）、`text`、`enabled`、`created_at`、`updated_at` |
| `tags` | `id`、`name`（唯一，正規化）、`type`、`description`（含近義詞，進索引）、`created_by`、`created_at` |
| `record_tags` | `record_id`、`tag_id`、`added_by`（user／ai）、`added_at` |
| `tag_links` | `parent_tag_id`、`child_tag_id`（只有「包含」關係） |
| `tag_aliases` | `alias`、`tag_id` |
| `tag_events` | `id`、`at`、`actor`、`action`、`detail`（標籤系統所有變動的紀錄） |
| `meta` | schema 版本、上次備份時間 |

另有 FTS5 虛擬表索引 `revisions.body`；標籤名、別名、說明另建小型索引。

規則：
- `revisions` 寫入後不可更新或刪除（徹底清除除外）；修改＝同一 `record_id` 新增下一個 `version_no`。
- `ai_summary`、`inference` 以 `links` 指向依據版本。
- `links.relation` 選填：`supersedes`（推翻）、`supports`（支持）、`supplements`（補充）、`derived`（衍生）；空＝未指定。
- 改錯字、補充＝同一記錄新增版本；改變看法或推翻結論＝新記錄，並以 `links` 連回被推翻的版本。這樣才能呈現「某時間點改變了想法」的完整時間線。
- 標籤是輔助索引，不是原文，可事後增減，不影響原文不可變；細節見「標籤系統」。
- `event_time` 一律存實際日期（「昨天」須由 AI 換算），保留精度；未知則空，查詢時另行標示，不排除也不假裝完整。
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

## 標籤系統

目的：讓問句容易對到標籤，並讓精細標籤能往上收攏（住在日本就不標「日本」，搜「日本」仍能展開到東京、吉原）。

存入：
- `record_tags.added_by` 區分來源：使用者手打的 `#標籤` 由系統解析並記為 user（原文不變）；AI 補的記為 ai。情緒類一律是 AI 推測，不當事實。
- 標籤名正規化（NFKC、不分大小寫）；簡繁、中日英同義靠別名。同詞多義用不同標籤名（「醬油拉麵」vs「醬油」），並以說明區分。`type`：place、person、topic、activity、emotion。
- 建立標籤時 AI 寫一句說明並含近義詞（如「日式麵食；豚骨、醬油、味噌」），說明也被索引：在寫入時做一次語意擴展，查詢時省 token。
- `save`、`set_tags` 在名稱接近既有標籤時回傳 `similar_tags`，AI 應重用。

查詢：
- `search` 可指定 `tags`（任一／全部）與類型；預設 `expand=true`：沿 `tag_links` **只往下**展開（最多 3 層）並含別名，回應列出實際展開的標籤。
- 回應附 facets（結果中最常見的標籤與次數）；結果為 0 或過少時附相近標籤建議。
- `tags_find(text)`：模糊查標籤名、別名、說明（容忍簡繁、全半形、錯字），依使用頻率與近期排序。`tags_list`、`tags_tree`、`tag_related`（常一起出現的標籤，純統計）。
- MCP 說明內附最常用約 200 個標籤（名稱、類型、次數，約 2K token 內），讓 AI 一開始就看得到。

維護：
- AI 可新增標籤、包含關係與別名（記為 ai，並在回答中告知）；使用者的說法（「那間店＝一蘭」）記為別名。合併、移除只限 CLI（`emlek tag merge·remove`），合併時舊名稱自動變別名。變動都寫入 `tag_events`。
- `emlek tags audit`（CLI）：列出疑似重複、只用過一次、使用次數過高（失去區辨力）的標籤。
- 不預先灌入世界知識（AI 本來就懂），圖只記使用者個人的分類與別名。
- 已規劃、暫不開發：新標籤建立後回頭替舊紀錄補標籤（AI 搜尋、列預覽、使用者確認後批次補）。

## 刪除

| 層級 | 行為 |
|---|---|
| 隱藏（預設的「刪除」） | `hidden=1`，搜尋與一般讀取看不到，可 `unhide` 恢復 |
| 徹底清除 | 真正移除該記錄所有版本與索引，無法恢復；對話流程見 [AGENT_RULES](AGENT_RULES.md) §3 |

徹底清除的實作：`purge_preview` 回傳摘要與一次性確認碼，`purge_confirm` 帶確認碼才執行；完成後 `VACUUM`。**不改動既有備份**，回覆須提醒使用者自行處理舊備份，並說明已傳給第三方 AI 的內容無法收回。第一版先做隱藏，徹底清除在步驟 6。

## 工具（MCP／CLI 共用）

| 動作 | 說明 |
|---|---|
| `save` | 新增；參數：內容、kind、來源、事件時間（可空）、標籤（可空）、依據或關聯版本與 relation（可空）；回傳 `similar_tags` |
| `amend` | 為既有記錄新增版本 |
| `set_tags` | 增減某記錄的標籤（不動原文） |
| `search` | 全文搜尋＋日期範圍＋標籤篩選與展開；回傳記錄、版本、來源、片段、總筆數、facets |
| `tags_find`／`tags_list`／`tags_tree`／`tag_related` | 唯讀：模糊查標籤、列表與次數、階層目錄、共現標籤 |
| `tag_link`／`tag_alias` | 新增包含關係與別名（AI 與使用者皆可，記錄來源） |
| `get` | 讀取指定記錄／版本 |
| `hide`／`unhide` | 隱藏與恢復 |
| `purge_preview`／`purge_confirm` | 徹底清除兩步 |
| `phrases_list` | 唯讀取得啟用語句 |
| `stats` | 唯讀：記錄數、最早與最晚日期、上次備份時間 |

僅 CLI（不開放 MCP）：`backup`、`restore`、`export`、`phrase add·set·remove`、`tag merge·remove`、`tags audit`。

搜尋規則：
- 日期範圍可指定依 `event_time` 或 `created_at`；事件時間未知的記錄另計並標示，不默默排除。
- 一律回傳總筆數並分頁（預設 20 筆、上限 100，附下一頁游標）；過長內容標明已截斷並提供取得剩餘部分的方式。
- 同一天或同一時段的日期範圍即可瀏覽當天或當期所有紀錄。

## 寬泛問題與分層摘要（已規劃，未開發）

資料量大時（例如五年每日記錄，約一至三萬則），技術上搜尋沒有問題，困難在問題太寬、無法逐筆讀完。做法：AI 先回報規模並請使用者縮小範圍；需要整體回顧時，經使用者同意，依月份分批讀取寫成 `ai_summary`（以 `links` 連回依據，標明範圍，不覆蓋原文），再彙整成年度；已存摘要供日後直接使用。這只用現有資料模型，不需新架構；專用統整功能等實際使用後再依痛點決定。

## 備份與搬家

1. 資料在一個 Vault 資料夾，主體是一個 `.db`（含搜尋索引）。
2. `emlek backup`：用 SQLite 一致性備份（backup API 或 `VACUUM INTO`）產生帶日期的單一檔，不直接複製使用中的檔案。可選 `--encrypt` 密碼加密，須提醒密碼遺失無法還原。
3. `emlek export`：完整 JSON（含所有版本與關係）＋供閱讀的 Markdown。
4. `emlek restore <備份檔>`：還原後驗證完整性與筆數。
5. 換設備：舊機 backup → 新機安裝 → restore → 重新指向 MCP 設定。

## 開發順序

| 步驟 | 內容 | 完成標準 |
|---|---|---|
| 1 | 資料庫＋`save`／`get`／`search`（CLI），含日期範圍、總筆數與分頁、事件時間 | 合成資料存取、中日英搜尋正確；日期篩選與分頁正確；版本不覆蓋 |
| 2 | MCP 外殼 | 至少一個 AI 實際呼叫並找回 |
| 3 | 版本與來源連結（含 relation）、`hide`／`unhide`、`phrase`、`phrases_list` | 修改產生新版本；推翻產生新記錄並連回；隱藏後搜不到可恢復；語句增刪改查可用，AI 端唯讀 |
| 4 | 標籤系統（資料表、`#標籤` 解析、階層與別名、展開查詢與 facets、查詢與維護工具、合併與健檢） | 搜上層標籤會展開子標籤且回應列出展開結果；別名、簡繁與寫法容錯生效；近似標籤有提示；標籤不改原文；user／ai 來源可分辨 |
| 5 | `backup`／`restore`／`export`、`stats` | 乾淨資料夾還原後筆數與內容一致；stats 數字正確 |
| 6 | 徹底清除 | 預覽、確認碼、清除後搜不到且資料庫無殘留 |
| 7 | 依實際痛點決定（回頭補標籤、分層摘要專用功能等） | — |

## 驗收題庫與基準測試（已規劃）

33 題固定題庫，用合成資料分「系統層」與「AI 層」計分，並記錄 token 消耗；題庫與規則見 [BENCHMARK](BENCHMARK.md)。每個開發步驟完成時，該步驟啟用的題目須通過系統層；AI 層從步驟 2（MCP）起執行。語意搜尋是否需要（D21）也以此題庫的結果判斷。

## 刻意不做

身分／SID／named pipe 隔離、授權 grant、提案→確認→提交流程、獨立安全帳本與防備份復活、restic、獨立搜尋庫與 outbox、長期分析掃描與自動統整、完整知識圖譜與預灌世界知識（標籤系統只記個人分類與別名）、標籤向量搜尋、查詢歷史記錄（查詢本身是敏感資料）、獨立簡繁對照表（先用別名）。需要時從 archive 取用。

**語意搜尋（用意思找）暫不做**，屬架構大決定，須經使用者同意。重新評估條件：使用一段時間後，準備約 30 題含模糊問法（心情、感覺、類似的事）的測試問句，用使用者同意的資料跑；超過三分之一找不到或找不全才正式提案。模型變強可降低門檻：更大的上下文可由 AI 直接分批讀取日期範圍內的紀錄代替部分搜尋。

## 已知限制

- AI 是否正確判斷「要不要存」靠使用指示，軟體無法強制。
- 徹底清除不影響既有備份與第三方副本。
- 軟體層不加密資料庫本體。
- 只能找回使用者主動保存的內容。
- 搜尋可以接近完整，不能保證完整（標籤沒標、用詞不同都可能漏）；回答須如實說明範圍。

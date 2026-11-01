# emLek 設計

狀態：規劃中，尚未實作。取代 [archive](archive/) 的完整版藍圖（非現行規格）。決策原因見 [DECISIONS](DECISIONS.md)；標籤系統與分層摘要見 [DESIGN_TAGS](DESIGN_TAGS.md)。

## 定位

單一使用者、單一 Windows 電腦、本機優先、不上雲；只管理文字；信任使用者自己的 AI。目標：AI 能存、能找、能追溯來源，換設備能簡單備份搬家。只做本檔與分冊列出的功能，其餘等實際遇到痛點再加。

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
| 搜尋 | 同檔 FTS5 trigram。查詢拆成詞：3 字元以上走 FTS5，1–2 字元走逐筆掃描（LIKE），各詞結果取交集；FTS5 對某詞無結果時補跑 LIKE 再下結論（避免把「索引沒命中」當成「沒有」）。trigram 索引約為原文 2–3 倍，估算備份大小時要算進去。資料量小時可接受，不足再評估 |
| AI 入口 | MCP（stdio）＋命令列 CLI；核心只寫一份，兩者都是薄外殼 |
| 加密 | 日常靠 Windows 裝置加密；備份可選密碼加密，用現成函式庫，不自寫 |

## 資料模型

| 表 | 欄位 |
|---|---|
| `records` | `id`、`created_at`、`hidden`、`hidden_at` |
| `revisions` | `id`、`record_id`、`version_no`、`body`（UTF-8）、`kind`、`created_at`、`event_time`（可空）、`event_time_precision`（可空）、`source`（可空＝未知） |
| `links` | `revision_id`、`derived_from_revision_id`、`relation`（選填） |
| `phrases` | `id`、`kind`（save／purge／exclude）、`text`、`enabled`、`created_at`、`updated_at` |
| 標籤相關 | `tags`、`record_tags`、`tag_links`、`tag_aliases`、`tag_events`，見 [DESIGN_TAGS](DESIGN_TAGS.md) |
| `meta` | schema 版本、上次備份時間 |

另有 FTS5 虛擬表索引 `revisions.body`。

規則：
- `revisions` 寫入後不可更新或刪除（徹底清除除外）；修改＝同一 `record_id` 新增下一個 `version_no`。
- `ai_summary`、`inference` 以 `links` 指向依據版本。
- `links.relation` 選填：`supersedes`（推翻）、`supports`（支持）、`supplements`（補充）、`derived`（衍生）、`summarizes`（摘要涵蓋該來源）；空＝未指定。
- 改錯字、補充＝同一記錄新增版本；改變看法或推翻結論＝新記錄，並以 `links` 連回被推翻的版本。這樣才能呈現「某時間點改變了想法」的完整時間線。
- `event_time` 一律存實際日期（「昨天」須由 AI 換算），保留精度；可以是未來日期，用來記期限、約定、預約；未知則空，查詢時另行標示，不排除也不假裝完整。
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

徹底清除的實作：`purge_preview` 回傳摘要與一次性確認碼，`purge_confirm` 帶確認碼才執行；完成後 `VACUUM`。**不改動既有備份**，回覆須提醒使用者自行處理舊備份，並說明已傳給第三方 AI 的內容無法收回。第一版先做隱藏，徹底清除在步驟 6。

衍生摘要的連帶處理：隱藏或徹底清除某記錄時，以 `links` 指向它的衍生記錄（`summarizes`、`derived` 的 `ai_summary`、`inference`）一併標為失效，重新產生前不得用於回答；徹底清除時，這些衍生記錄的版本一併移除（摘要正文可能含被清除的內容），需要時由 AI 重新產生。`purge_preview` 須列出會連帶失效的衍生記錄。

## 工具（MCP／CLI 共用）

| 動作 | 說明 |
|---|---|
| `save` | 新增；參數：內容、kind、來源、事件時間（可空）、標籤（可空）、依據或關聯版本與 relation（可空）；回傳 `similar_tags` |
| `amend` | 為既有記錄新增版本 |
| `search` | 全文搜尋＋日期範圍＋標籤篩選與展開；回傳記錄、版本、來源、片段、總筆數、facets、`superseded_by`、`linked_from`（所有指向該記錄的連結與關係，如完成紀錄）；`current_only=true` 可排除已被推翻者（預設只標示不排除） |
| `get` | 讀取指定記錄／版本；回傳 `superseded_by`、`linked_from` |
| `hide`／`unhide` | 隱藏與恢復 |
| `purge_preview`／`purge_confirm` | 徹底清除兩步 |
| `phrases_list` | 唯讀取得啟用語句 |
| `stats` | 唯讀：記錄數、最早與最晚日期、上次備份時間 |
| 標籤工具 | `set_tags`、`tags_*`、`tag_link`、`tag_alias`，見 [DESIGN_TAGS](DESIGN_TAGS.md) |

僅 CLI（不開放 MCP）：`backup`、`restore`、`export`、`phrase add·set·remove`，以及標籤的 `tag merge·remove`、`tags audit`。

唯讀模式：`emlek mcp --read-only` 只開放 `search`、`get`、`tags_find`／`tags_list`／`tags_tree`／`tag_related`、`phrases_list`、`stats`，供無人看管的排程使用。每日簡報（由 Agent 排程呼叫，到期與回顧兩種提醒）見 [DAILY_BRIEFING](DAILY_BRIEFING.md)。

搜尋規則：
- `superseded_by` 由 `links` 中 `relation=supersedes` 推算，不另存欄位，列出推翻它的記錄；若之後又有 `supports` 重新確認，一併回傳，讓 AI 能還原 A→B→C→A 的完整過程。
- 日期範圍可指定依 `event_time` 或 `created_at`；事件時間未知的記錄另計並標示，不默默排除。
- 一律回傳總筆數並分頁（預設 20 筆、上限 100，附下一頁游標）；過長內容標明已截斷並提供取得剩餘部分的方式。
- 同一天或同一時段的日期範圍即可瀏覽當天或當期所有紀錄。

## 備份與搬家

1. 資料在一個 Vault 資料夾，主體是一個 `.db`（含搜尋索引）。
2. `emlek backup`：用 SQLite 一致性備份（backup API 或 `VACUUM INTO`）產生帶日期的單一檔，不直接複製使用中的檔案。可選 `--encrypt` 密碼加密，須提醒密碼遺失無法還原。
3. `emlek export`：完整 JSON（含所有版本與關係）＋供閱讀的 Markdown。
4. `emlek restore <備份檔>`：還原後驗證完整性與筆數。
5. 換設備：舊機 backup → 新機安裝 → restore → 重新指向 MCP 設定。

## 擴充準則（為未來需求預留，現在就要遵守）

目前一律本機使用。以下準則讓日後加手機或遠端存取時不必重寫核心：
- 核心不依賴任何傳輸方式；MCP（stdio）與 CLI 只是外殼，日後可再加 HTTP 入口。
- 權限（唯讀、可寫、清除僅限本機 CLI）由**核心**判斷，不只靠外殼，新入口自動繼承。
- 位置與設定可由參數或環境變數指定（`--data-dir`）；資料庫不存絕對路徑；資料庫不得放在同步資料夾。
- 工具輸入輸出用有版本號的格式（`api_version`），未知欄位拒絕，讓不同客戶端可共存。
- 資料庫結構從第一版就有版本與遷移機制。
- 日誌不記內容；提供健康檢查。
- 匯入與匯出用與工具無關的純文字格式。

## 未來需求（保留，目前不開發）

使用者決定（2026-11-01）：目前一律本機使用；手機相關需求等 AGENT 技術更成熟後再評估。屆時須重新查證當時的連接器與遠端 MCP 能力，遠端存取屬架構大決定，須取得使用者同意。已討論的方向，供日後取用：

1. **手機隨手記錄（收件匣）**：手機只負責記，不連資料庫。使用者把文字存成檔案放進「收件匣」資料夾（可設在雲端同步資料夾）。檔名以 `YYYYMMDD-HHMMSS` 開頭（容許只有日期），UTF-8 純文字或 Markdown，可含 `#標籤`。`emlek inbox import`（CLI）確定性匯入，不呼叫 AI、不耗 token，可交給工作排程器：每檔一筆 `original`，`source=inbox:<檔名>`，事件時間為擷取時間，`#標籤` 記為 user；以 `inbox_imports`（檔名加內容雜湊）保證冪等；成功後移到 `processed/` 或刪除，失敗者留在原處並列出原因。事後由 AI 補標籤，並依擷取時間換算相對日期、以新版本更正事件日期。收件匣原文未加密，匯入後宜刪除。對應保留題庫 Q38、Q39。
2. **用 AI 公司的現成連接器當橋**（Google Drive、Notion 等）：手機 AI 直接把「記一下」寫成收件匣檔案。須先實測：手機版是否支援、能否指定資料夾與檔名、純文字格式。
3. **手機看今日提醒**：電腦或排程 Agent 每天把到期事項輸出成一個小檔放到雲端，手機 AI 用連接器讀取。只暴露精選內容，不匯出整份資料。
4. **遠端查詢**：介面層新增遠端 MCP（Streamable HTTP），核心與資料層不變，資料仍單一份、單一寫入者。已查證：Claude 的遠端連線從 Anthropic 雲端發出，伺服器必須能從公開網路以 HTTPS 連到並以 OAuth 驗證，私人網路（如 Tailscale）無法供其連線。須決定主機位置（雲端主機或家用主機加隧道）、資料庫加密、讀寫權限分開、清除不對外開放。
5. **多裝置各自同步**：不建議。會帶回清除復活、分岔版本、時鐘誤差等問題，工作量大。若真有需求，需另行設計（記錄編號全域唯一、版本記上一版、清除留墓碑）。

## 開發順序

| 步驟 | 內容 | 完成標準 |
|---|---|---|
| 1 | 資料庫＋`save`／`get`／`search`（CLI），含日期範圍、總筆數與分頁、事件時間 | 合成資料存取、中日英搜尋正確；日期篩選與分頁正確；版本不覆蓋 |
| 2 | MCP 外殼（含 `--read-only` 唯讀模式） | 至少一個 AI 實際呼叫並找回；唯讀模式下寫入、隱藏、清除工具不可用 |
| 3 | 版本與來源連結（含 relation）、`hide`／`unhide`、`phrase`、`phrases_list` | 修改產生新版本；推翻產生新記錄並連回；隱藏後搜不到可恢復；語句增刪改查可用，AI 端唯讀 |
| 4 | 標籤系統（見 DESIGN_TAGS） | 搜上層標籤會展開子標籤且回應列出展開結果；別名、簡繁與寫法容錯生效；近似標籤有提示；標籤不改原文；user／ai 來源可分辨 |
| 5 | `backup`／`restore`／`export`、`stats` | 乾淨資料夾還原後筆數與內容一致；stats 數字正確 |
| 6 | 徹底清除 | 預覽、確認碼、清除後搜不到且資料庫無殘留 |
| 7 | 依實際痛點決定（回頭補標籤、分層摘要專用功能、主題摘要等） | — |

驗收題庫：37 題固定題庫（另有 2 題保留），用合成資料分「系統層」與「AI 層」計分並記錄 token，見 [BENCHMARK](BENCHMARK.md)。每個步驟完成時，該步驟啟用的題目須通過系統層；AI 層從步驟 2 起執行。

## 刻意不做

身分／SID／named pipe 隔離、授權 grant、提案→確認→提交流程、獨立安全帳本與防備份復活、restic、獨立搜尋庫與 outbox、長期分析掃描與自動統整、完整知識圖譜與預灌世界知識（標籤系統只記個人分類與別名）、標籤向量搜尋、查詢歷史記錄（查詢本身是敏感資料）、獨立簡繁對照表（先用別名）。需要時從 archive 取用。

**語意搜尋（用意思找）暫不做**，屬架構大決定，須經使用者同意。重新評估條件：使用一段時間後，以題庫中的模糊問法題（Q04、Q11、Q12、Q16、Q17）加上使用者同意提供的真實問題實測；超過三分之一找不到或找不全才正式提案。模型變強可降低門檻：更大的上下文可由 AI 直接分批讀取日期範圍內的紀錄代替部分搜尋。

**近期加權排序（以時間重排結果）暫不做**：現有日期範圍與排序已夠用。題庫實測不理想時，Agent 須主動提醒使用者評估（與語意搜尋同列觀察清單，見 [BENCHMARK](BENCHMARK.md)）。

## 已知限制

- AI 是否正確判斷「要不要存」靠使用指示，軟體無法強制。
- 徹底清除不影響既有備份與第三方副本。
- 軟體層不加密資料庫本體。
- 只能找回使用者主動保存的內容。
- 搜尋可以接近完整，不能保證完整（標籤沒標、用詞不同都可能漏）；回答須如實說明範圍。

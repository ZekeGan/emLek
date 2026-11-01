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
| 搜尋 | 同檔 FTS5 trigram，建在正規化副本 `revisions.body_norm` 上。查詢拆成詞：3 字元以上走 FTS5，1–2 字元走 LIKE 逐筆掃描，各詞結果取交集；FTS5 對某詞無結果時補跑 LIKE 再下結論。有 3 字元以上的詞時，先用 FTS5 取候選再對候選做 LIKE 驗證；只有短詞時先用標籤或日期縮小範圍。實測（合成 3.6 萬筆、平均約 1.7K 字元）：2 字元 LIKE 全掃約 0.5 秒、3 字元以上 FTS5 低於 1 毫秒，資料庫約為原文位元組的 2.5 倍 |
| AI 入口 | MCP（stdio）＋命令列 CLI；核心只寫一份，兩者都是薄外殼 |
| 加密 | 日常靠 Windows 裝置加密；備份可選密碼加密，用現成函式庫，不自寫 |

實作層的技術決定（目錄、套件、遷移、CLI 與 MCP 函式庫）見 [WORKFLOW](WORKFLOW.md)。

## 資料模型

| 表 | 欄位 |
|---|---|
| `records` | `id`、`created_at`、`hidden`、`hidden_at`、`sensitivity`（none／medium／high） |
| `revisions` | `id`、`record_id`、`version_no`、`body`（UTF-8 原文）、`body_norm`（NFKC＋casefold 的衍生副本，供搜尋）、`kind`、`created_at`、`event_time`（可空）、`event_time_precision`（可空）、`source`（可空＝未知） |
| `links` | `revision_id`、`derived_from_revision_id`、`relation`（選填） |
| `phrases` | `id`、`kind`（save／purge／exclude）、`text`、`enabled`、`created_at`、`updated_at` |
| `notice_settings` | `level`（medium）、`enabled`、`acknowledged_at` |
| `import_log` | `file_name`、`chunk_index`、`content_hash`、`record_id`（清除後為空）、`purged`、`imported_at` |
| 標籤相關 | `tags`、`record_tags`、`tag_links`、`tag_aliases`、`tag_events`，見 [DESIGN_TAGS](DESIGN_TAGS.md) |
| `meta` | schema 版本、上次備份時間 |

規則：
- `revisions` 寫入後不可更新或刪除（徹底清除除外，見「刪除」）；修改＝同一 `record_id` 新增下一個 `version_no`。`body_norm` 是可重建的衍生資料。
- `ai_summary`、`inference` 以 `links` 指向依據版本。
- `links.relation` 選填：`supersedes`（推翻）、`supports`（支持）、`supplements`（補充）、`derived`（衍生）、`summarizes`（摘要涵蓋該來源）；空＝未指定。
- 改錯字、補充＝同一記錄新增版本；改變看法或推翻結論＝新記錄，並以 `links` 連回被推翻的版本，才能呈現「某時間點改變了想法」的完整時間線。
- `event_time` 一律存實際日期（「昨天」須由 AI 換算），可以是未來日期，用來記期限、約定、預約；未知則空，查詢時另行標示，不排除也不假裝完整。
- 資料庫不存絕對路徑。

## 自訂語句

使用者以 CLI 增刪改查，存在資料庫隨備份搬家。預設：`save`＝記住、幫我記一下、存起來、記憶；`purge`＝完全刪除；`exclude`＝上週記住了文法（不算指令的範例）。

| 命令 | 作用 |
|---|---|
| `emlek phrase list [kind]` | 查 |
| `emlek phrase add <kind> "<語句>"` | 增 |
| `emlek phrase set <id> "<新語句>"` | 改、啟用或停用 |
| `emlek phrase remove <id>` | 刪 |

- AI 只能用 MCP 唯讀工具 `phrases_list`。語句只是 AI 的判斷依據，不是機械比對。沒有啟用的 `purge` 語句時，徹底清除關閉。
- **需要真人終端機的 CLI 命令**：`phrase add·set·remove`（所有類別）、`notice enable`、`restore`、`tag merge·remove`、`sensitivity set`。檢查方式：標準輸入、輸出、錯誤輸出都必須是終端機；否則回 `NOT_PERMITTED`（結束碼 3）。
- 限制（已實測）：Claude Code 的 PowerShell 工具回報標準輸入是終端機、標準輸出不是，所以**只檢查輸入不夠**，必須三者都檢查。能開偽終端機的 AI、以及直接開資料庫檔的 AI 仍能繞過；這是主要防線而非絕對隔離。是否加一組只有使用者知道的 PIN 作強化，待使用者決定（見 PROGRESS）。

## 刪除

| 層級 | 行為 |
|---|---|
| 隱藏（預設的「刪除」） | `hidden=1`，預設搜尋與讀取看不到（`include_hidden=true` 可查），可 `unhide` 恢復 |
| 徹底清除 | 真正移除該記錄所有版本與索引，無法恢復；對話流程見 [AGENT_RULES](AGENT_RULES.md) §3 |

**衍生摘要失效**是計算值，不另存欄位：記錄的任一來源（經 `links` 遞移）處於隱藏，其衍生的 `ai_summary`、`inference` 即失效，重新產生前不得用於回答；`unhide` 後自動恢復。

**徹底清除**：`purge_preview` 回傳摘要、會連帶移除的衍生記錄與一次性確認碼（10 分鐘，綁定記錄編號與版本數）；`purge_confirm` 帶確認碼才執行。執行（單一交易）：以僅供清除函式設定的連線層暫存旗標暫時放行不可變觸發器；移除該記錄的版本、全文索引列、標籤關聯、指向這些版本的 `links`（其餘記錄保留，只是少了這條連結）、以它為來源的衍生記錄；`tag_events` 中涉及該記錄的明細清空；`import_log` 保留檔名與雜湊但清空 `record_id` 並標 `purged`，避免重新匯入後復活。提交後 `secure_delete=ON`、`wal_checkpoint(TRUNCATE)`、`VACUUM`、再 checkpoint，最後掃描資料庫與 WAL 原始檔確認預覽中的片段已不存在（已實測：只刪不整理時 WAL 與主檔會殘留）。**不改動既有備份**，回覆須提醒使用者自行處理舊備份，並說明已傳給第三方 AI 的內容無法收回。

## 工具（MCP／CLI 共用）

尚未實作的欄位一律回 `INVALID_INPUT`，隨里程碑開放。

| 動作 | 說明 |
|---|---|
| `save` | 新增；參數：內容、`kind`、來源、事件時間與精度（可空）、標籤（可空，見 DESIGN_TAGS）、依據或關聯版本與 `relation`（可空）、`sensitivity`（可空）；回傳 `similar_tags`、`sensitivity_hint` |
| `amend` | 為既有記錄新增版本；重新掃描敏感內容並取較高等級 |
| `search` | 見下方「搜尋規則」 |
| `get` | 讀取指定記錄與版本；回傳 `superseded_by`、`linked_from`；支援 `max_sensitivity` |
| `hide`／`unhide` | 隱藏與恢復 |
| `purge_preview`／`purge_confirm` | 徹底清除兩步 |
| `phrases_list` | 唯讀取得啟用語句 |
| `stats` | 唯讀：記錄數（不含隱藏）、隱藏數、版本數、最早與最晚日期、上次備份時間 |
| 標籤工具 | `set_tags`、`tags_find`、`tags_list`、`tags_tree`、`tag_related`、`tag_link`、`tag_alias`，見 [DESIGN_TAGS](DESIGN_TAGS.md) |

僅 CLI（不開放 MCP）：`init`、`doctor`、`backup`、`restore`、`export`、`import`、`notice status·enable`、`sensitivity set`、`phrase add·set·remove`，以及標籤的 `tag merge·remove`、`tags audit`。

**唯讀模式**：`emlek mcp --read-only` 的工具清單只含 `search`、`get`、`phrases_list`、`stats`、`tags_find`、`tags_list`、`tags_tree`、`tag_related`（寫入工具根本不存在，不是被拒絕），供無人看管的排程使用；`max_sensitivity` 預設為 medium。每日簡報見 [DAILY_BRIEFING](DAILY_BRIEFING.md)。

**搜尋規則**：
- 命中單位是**記錄**；預設比對各記錄的最新版本並標示命中的版本，`all_versions=true` 才比對舊版。總筆數的單位也是記錄。
- 過濾：`kinds`、`tags`、`tag_types`、日期範圍（`date_field=event_time|created_at`，前者看最新版本，後者是記錄首次存入時間；事件時間未知的記錄不排除，另列 `undated` 數量）、`include_hidden`（預設否）、`current_only`（排除已被推翻者，預設只標示）、`max_sensitivity`（超過上限的記錄不回內文，只計入 `withheld`）。
- 排序：`order=relevance|event_time|created_at`，`dir=asc|desc`；有關鍵字時預設 relevance、無關鍵字時預設 event_time desc。游標以排序鍵加記錄編號為準，頁間穩定。
- 一律回傳總筆數並分頁（預設 20 筆、上限 100，附下一頁游標）；過長內容標明已截斷並提供取得剩餘部分的方式。同一天或同一時段的日期範圍即可瀏覽當天或當期所有紀錄。
- `superseded_by` 由 `links` 中 `relation=supersedes` 推算，不另存欄位；若之後又有 `supports` 重新確認，一併回傳，讓 AI 能還原 A→B→C→A 的完整過程。`linked_from` 列出所有指向該記錄的連結與關係（如完成紀錄）。

## 敏感內容提示

存入時依危險度提示，避免使用者在不知情下把高風險資料留在明文資料庫（備份與匯出也會帶出）。固定句式在 [AGENT_RULES](AGENT_RULES.md) §1。

| 等級 | 例子 | 存入時 |
|---|---|---|
| high（最高） | 密碼、API 金鑰與 token、私鑰、信用卡號、一次性復原碼 | **每次**詢問，不可關閉；建議改存密碼管理器 |
| medium（中） | 電話、住址、身分證或護照號碼、生日 | **第一次**詢問並提醒，同意後不再詢問；`emlek notice enable medium` 可重新開啟提醒 |
| none | 其他 | 不提示 |

- 判斷：AI 依語意判斷；核心另以規則掃描當補強（私鑰區塊、常見金鑰格式、JWT、卡號 Luhn 檢查、電話與證號格式），回傳 `sensitivity_hint`，取兩者較高者。規則掃描不可能完整。
- high：`save` 回傳 `NEEDS_CONFIRMATION`（`state=needs_confirmation`，`error.data` 含一次性 `confirm_token`，綁定內容雜湊，10 分鐘過期）；使用者答「是」才帶 token 重送。
- medium：未確認過時回傳 `NEEDS_CONFIRMATION`（`state=needs_notice`，含綁定該內容的 `notice_token`）；使用者同意後帶 token 重送，核心寫入 `notice_settings`（`enabled=0`）。`emlek notice status` 查看、`emlek notice enable medium` 重開（CLI，真人終端機）。
- `amend` 同樣掃描並取較高等級，高風險新內容一樣走確認；AI 傳入的 `sensitivity` 只能調高，調低只能用 `emlek sensitivity set r<id> <level>`。
- `import` 也掃描：含 high 的檔案預設略過並列出，使用者檢視後可用 `--include-high` 在真人終端機確認匯入；medium 直接匯入並標記，匯入摘要回報數量。
- 記錄的 `sensitivity` 等於各版本最高者；`search`／`get` 回傳該欄位。`emlek export --exclude high` 可排除 high 記錄。
- 限制：AI 若自行帶 token 而未真正詢問，核心無法分辨，與清除流程同一信任邊界；以題庫與審查驗證各 AI 平台的遵守程度。

## 匯入既有資料

使用者有舊日記要放進來；功能隨時可新增，不阻擋其他里程碑。`emlek import <檔案或資料夾>`（CLI）：讀 `.txt`、`.md`，每檔一筆 `original`；檔名或內文開頭的日期用作事件時間，沒有則留空；`#標籤` 解析為 user；`--split-by-heading` 以日期標題切成多筆；`--dry-run` 預覽；`source=import:<檔名>`。冪等以 `import_log` 的（檔名、段落序號、內容雜湊）判斷；檔案被修改後雜湊改變，視為新內容匯入並警告「檔案自上次匯入後已變更」，不覆蓋舊記錄。真實舊日記屬私人資料：開發與測試只用合成檔，真實檔案須使用者貼出路徑並同意才處理。

## 備份與搬家

1. 資料在一個資料夾，主體是一個 `.db`（含搜尋索引）。
2. `emlek backup`：用 SQLite 一致性備份（`VACUUM INTO`）產生帶日期的單一檔，不直接複製使用中的檔案。可選 `--encrypt` 密碼加密，須提醒密碼遺失無法還原。遷移前自動備份一份。
3. `emlek export`：完整 JSONL（含所有版本與關係）＋供閱讀的 Markdown。
4. `emlek restore <備份檔>`：先驗證再替換，並保留舊庫改名。
5. 換設備：舊機 backup → 新機安裝 → restore → 重新指向 MCP 設定。

## 規格細節（v1）

- **位置**：預設 `%LOCALAPPDATA%/emlek/`（不在 OneDrive 等同步位置）；`--data-dir` 或 `EMLEK_DATA_DIR` 覆寫。資料夾內有資料庫與 `config.toml`（目前只有 `timezone`，預設系統時區，由 `init` 建立）。`emlek init` 建立並限制只有目前使用者可存取（已實測 `icacls` 不需管理員權限）；`emlek doctor` 檢查 Python 與 SQLite 版本、FTS5 trigram、WAL 修補版本、資料夾是否在同步位置、權限、最近備份。
- **編號**：整數主鍵；對外顯示為 `r<id>`、`r<id>.v<n>`。
- **時間**：`created_at` 存 UTC（ISO 8601，毫秒）。`event_time_precision` 為 year、month、day、hour、minute、second。year、month、day 存日曆日期字串（`2026`、`2026-11`、`2026-01-15`，不換算時區）；hour、minute、second 存含偏移的 ISO 8601（如 `2026-01-15T09:30+09:00`）。範圍查詢以該值涵蓋的時間區間與查詢區間有重疊即命中；「今天」的日界線依 `timezone`。
- **SQLite**：WAL、`synchronous=FULL`、`foreign_keys=ON`、`busy_timeout=5000`，啟動時讀回 PRAGMA 驗證。SQLite 須 ≥ 3.51.3（或修補線 3.50.7、3.44.6）才用 WAL，否則退回 `journal_mode=DELETE` 並警告。每個 `save` 為單一交易，記錄、版本、連結、標籤、全文索引全成功或全失敗。同一時間只有一個寫入交易，多行程（CLI 與 MCP）以 busy_timeout 序列化。
- **大小限制**：單版原文 ≤ 1 MiB（UTF-8 位元組）；來源 ≤ 500 字元；每筆標籤 ≤ 20 個、名稱 ≤ 64 字元、說明 ≤ 200 字元；查詢 ≤ 512 字元；單頁 ≤ 100 筆。
- **搜尋正規化**：`body_norm` 與查詢都先做 NFKC 與 casefold，原文不動；簡繁不統一，用別名。
- **錯誤**：回傳 `{ok, error:{code, message, retryable, data?}}`。代碼：`INVALID_INPUT`、`NOT_FOUND`、`CONFLICT`、`NEEDS_CONFIRMATION`（待確認狀態也用此代碼，`error.data.state` 區分）、`TOKEN_INVALID`（確認碼錯誤、過期或已用過）、`NOT_PERMITTED`、`BUSY`、`INTERNAL`。CLI 結束碼：0 成功、1 內部錯誤、2 輸入錯誤、3 不允許或需確認、4 找不到或衝突、5 忙碌或暫時失敗。
- **匯出 v1**：資料夾內 `export.jsonl`（第一行 `{"type":"header","format_version":1,"schema_version":N,...}`，其後每行一個物件，`type` 為 record、revision、link、tag、record_tag、tag_link、tag_alias、tag_event、phrase、notice_setting、import_log、meta；隱藏的記錄照匯出並帶 `hidden` 旗標；不含 `body_norm`，匯入時重建）與 `markdown/`（每筆記錄一檔，含版本、標籤、來源，供閱讀）。
- **備份加密**：`cryptography` 的 AES-256-GCM，金鑰由 `hashlib.scrypt` 從密碼導出，參數與格式版本寫入檔頭，不儲存密碼。
- **語言與日誌**：CLI 與訊息預設繁體中文，欄位與代碼用英文；程式輸入輸出一律明確用 UTF-8。日誌不記內容。

## 擴充準則（為未來需求預留，現在就要遵守）

目前一律本機使用。以下準則讓日後加手機或遠端存取時不必重寫核心：
- 核心不依賴任何傳輸方式；MCP（stdio）與 CLI 只是外殼，日後可再加 HTTP 入口。
- 權限（唯讀、可寫、需真人終端機）由**核心**的權限表判斷，不只靠外殼，新入口自動繼承；遠端入口將不開放清除。
- 位置與設定可由參數或環境變數指定（`--data-dir`）；資料庫不存絕對路徑；資料庫不得放在同步資料夾。
- 工具輸入輸出用有版本號的格式（`api_version`），未知欄位拒絕，讓不同客戶端可共存。
- 資料庫結構從第一版就有版本與遷移機制。
- 日誌不記內容；提供健康檢查。
- 匯入與匯出用與工具無關的純文字格式。

## 未來需求（保留，目前不開發）

使用者決定（2026-11-01）：目前一律本機使用；手機相關需求等 AGENT 技術更成熟後再評估。屆時須重新查證當時的連接器與遠端 MCP 能力，遠端存取屬架構大決定，須取得使用者同意。已討論的方向，供日後取用：

1. **手機隨手記錄（收件匣）**：手機只負責記，不連資料庫。使用者把文字存成檔案放進「收件匣」資料夾（可設在雲端同步資料夾）。檔名以 `YYYYMMDD-HHMMSS` 開頭（容許只有日期），UTF-8 純文字或 Markdown，可含 `#標籤`。`emlek inbox import`（CLI）確定性匯入，不呼叫 AI、不耗 token，可交給工作排程器：每檔一筆 `original`，`source=inbox:<檔名>`，事件時間為擷取時間，冪等沿用 `import_log`；成功後移到 `processed/` 或刪除，失敗者留在原處並列出原因；匯入同樣做敏感掃描。事後由 AI 補標籤，並依擷取時間換算相對日期、以新版本更正事件日期。收件匣原文未加密，匯入後宜刪除。對應保留題庫 Q38、Q39。
2. **用 AI 公司的現成連接器當橋**（Google Drive、Notion 等）：手機 AI 直接把「記一下」寫成收件匣檔案。須先實測：手機版是否支援、能否指定資料夾與檔名、純文字格式。
3. **手機看今日提醒**：電腦或排程 Agent 每天把到期事項輸出成一個小檔放到雲端，手機 AI 用連接器讀取。只暴露精選內容，不匯出整份資料。
4. **遠端查詢**：介面層新增遠端 MCP（Streamable HTTP），核心與資料層不變，資料仍單一份、單一寫入者。已查證：Claude 的遠端連線從 Anthropic 雲端發出，伺服器必須能從公開網路以 HTTPS 連到並以 OAuth 驗證，私人網路（如 Tailscale）無法供其連線。須決定主機位置（雲端主機或家用主機加隧道）、資料庫加密、讀寫權限分開、清除不對外開放。
5. **多裝置各自同步**：不建議。會帶回清除復活、分岔版本、時鐘誤差等問題，工作量大。若真有需求，需另行設計（記錄編號全域唯一、版本記上一版、清除留墓碑）。
6. **其他已記錄的可能缺口**（先記錄，必要時由 Agent 提醒使用者）：依標籤或人物批次清除；結構化金額與待辦狀態；圖片與語音等非文字；簡繁對照表；語意搜尋（見觀察清單）；資料庫本體加密（如 SQLCipher）；備份自動排程；打包成安裝檔；CLI 多語系；CI 與提交前檢查掛鉤；使用說明書。

## 開發順序（里程碑）

每個里程碑結束須 ruff、mypy、pytest 全綠，更新 PROGRESS 的待驗收與 30 秒驗收清單。測試 ID 見 [TEST_PLAN](TEST_PLAN.md)，題號見 [BENCHMARK](BENCHMARK.md)。**真實資料（含舊日記）只在 M4 與 M6 完成後，且須使用者貼出路徑並同意。**

| 里程碑 | 內容 | 完成標準 |
|---|---|---|
| M1 骨架 | pyproject、`init`、`doctor`（基本）、設定檔、遷移 0001（meta、records、revisions、不可變觸發器）、`save`／`get`（CLI） | 中日英與 emoji 原文往返逐位元組一致；版本不可改；失敗不留半筆；`doctor` 報告環境（T01–T03、T05、T11 子集、T25） |
| M2 搜尋與時間 | FTS5＋LIKE 逐詞路由、NFKC、日期範圍、`order`、`kinds`、分頁與總筆數；題庫系統層骨架與合成資料產生器 | T04、T08–T10；Q01/02/06/07/13/15/20 系統層通過；3.6 萬筆（含真實長度）規模測試有記錄 |
| M3 權限與 MCP | `core/permissions.py`、MCP 完整與 `--read-only`、stdout 只輸出協定；Claude Code 與 Codex CLI 以合成庫實測；平台唯讀沙箱旗標實測；AI 層題庫開始（只報告不卡關） | T06、T07、T16；兩個 AI 都能存與找回合成資料；唯讀清單不含寫入工具 |
| M4 安全網 | `backup`、`restore`（驗證再替換）、`export` v1、`stats`、遷移前自動備份 | T19、T20；還原到乾淨資料夾與原庫逐筆一致 |
| M5 版本、連結、隱藏 | `amend`、`relation`、`superseded_by`、`linked_from`、`hide`／`unhide`、衍生失效（計算值） | T12、T13；Q08–10、Q22–23 |
| M6 信任閘門 | 規則掃描、`notice_settings`、`confirm_token`／`notice_token`、`phrase`、`notice`、`sensitivity set` 的真人終端機閘門、`phrases_list` | T14、T15；Q40–42；閘門限制如實記載 |
| M7 標籤 | M7a：資料表、`set_tags`、`#標籤`、別名、向下展開。M7b：`tags_find` 等查詢工具、facets、`similar_tags`、合併、健檢、熱門標籤 | T17、T18；Q03/05/32–36 |
| M8 匯入與備份加密 | `import`（含敏感掃描、`--split-by-heading`）、備份 `--encrypt` | T21；Q43；錯誤密碼與一位元組竄改被拒 |
| M9 清除 | `purge`（預覽、確認碼、清除、殘留檢查） | T22、T23；原始檔掃描無殘留 |
| M10 | 依實際痛點決定（回頭補標籤、分層／主題摘要、觀察清單項目） | — |

題庫分系統層（不用 AI、做為卡關依據）與 AI 層（報告用，不卡關），見 BENCHMARK。

## 刻意不做

身分／SID／named pipe 隔離、授權 grant、提案→確認→提交流程、獨立安全帳本與防備份復活、restic、獨立搜尋庫與 outbox、長期分析掃描與自動統整、完整知識圖譜與預灌世界知識（標籤系統只記個人分類與別名）、標籤向量搜尋、查詢歷史記錄（查詢本身是敏感資料）、獨立簡繁對照表（先用別名）。需要時從 archive 取用。

**語意搜尋（用意思找）暫不做**，屬架構大決定，須經使用者同意。重新評估條件：使用一段時間後，以題庫中的模糊問法題（Q04、Q11、Q12、Q16、Q17）加上使用者同意提供的真實問題實測；超過三分之一找不到或找不全才正式提案。模型變強可降低門檻：更大的上下文可由 AI 直接分批讀取日期範圍內的紀錄代替部分搜尋。

**近期加權排序暫不做**：現有日期範圍與排序已夠用。題庫實測不理想時，Agent 須主動提醒使用者評估（與語意搜尋同列觀察清單，見 [BENCHMARK](BENCHMARK.md)）。

## 已知限制

- AI 是否正確判斷「要不要存」、是否真的詢問過，靠使用指示，軟體無法強制。
- 徹底清除不影響既有備份與第三方副本。
- 軟體層不加密資料庫本體。
- 只能找回使用者主動保存的內容。
- 搜尋可以接近完整，不能保證完整（標籤沒標、用詞不同都可能漏）；回答須如實說明範圍。
- 能執行命令的 AI 與同一 Windows 帳號下的程式，理論上能直接開資料庫檔；唯讀模式與終端機檢查只擋常見路徑。

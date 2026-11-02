# emLek 設計

狀態：M1–M5 已實作（以 [PROGRESS](PROGRESS.md) 為準），M6 起仍在規劃。取代 [archive](archive/) 的完整版藍圖（非現行規格）。決策原因見 [DECISIONS](DECISIONS.md)；標籤系統與分層摘要見 [DESIGN_TAGS](DESIGN_TAGS.md)。

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
| 加密 | Windows 家用版沒有 BitLocker，資料庫本體不加密（`doctor` 如實提示）；高風險內容靠分級提示並建議改存密碼管理器；備份可選密碼加密，用現成函式庫，不自寫；日後可評估 SQLCipher 或 VeraCrypt |

實作層的技術決定（目錄、套件、遷移、CLI 與 MCP 函式庫）見 [WORKFLOW](WORKFLOW.md)。

## 資料模型

| 表 | 欄位 |
|---|---|
| `records` | `id`、`created_at`、`hidden`、`hidden_at`、`sensitivity`（none／medium／high） |
| `revisions` | `id`、`record_id`、`version_no`、`body`（UTF-8 原文）、`body_norm`（NFKC＋casefold 的衍生副本，供搜尋）、`kind`、`created_at`、`event_time`（可空）、`event_time_precision`（可空）、`source`（可空＝未知）、`event_date_start`／`event_date_end`（由 event_time 與精度推出的日曆日期區間，虛擬欄位，供日期範圍查詢） |
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
- **需要真人終端機與 PIN 的 CLI 命令**：`phrase add·set·remove`（所有類別）、`notice enable`、`restore`、`tag merge·remove`、`sensitivity set`、`purge`、`import --include-high`、`pin change·reset`。檢查兩層：(1) 標準輸入、輸出、錯誤輸出都必須是終端機，否則回 `NOT_PERMITTED`（結束碼 3）；(2) 以 `getpass` 從主控台輸入 PIN，**絕不接受參數、環境變數或標準輸入傳入**。
- **PIN**：至少 6 碼，以 `scrypt` 雜湊存於 `meta`，連續錯 5 次鎖定 5 分鐘；設定時一次性顯示復原碼（只存雜湊）供 `pin reset`。`init` 在 M6 起設定 PIN，早於 M6 建立的庫以 `emlek pin set` 補設。**PIN 不得告訴任何 AI**；若貼在對話，須立即 `emlek pin change`。
- 限制（已實測）：Claude Code 的 PowerShell 工具回報標準輸入是終端機、標準輸出不是，所以三條串流都要驗。PIN 擋得住只透過 CLI 操作的 AI；能開偽終端機並讀到使用者輸入、或直接開資料庫檔改資料的 AI 仍能繞過。這是主要防線而非絕對隔離。

## 版本與連結語意（M5）

連結只描述「新記錄或新版本」對「較舊版本」的關係；因此**方向固定由新指向舊**，不可能形成環。

| 項目 | 規則 |
|---|---|
| 方向 | `links.revision_id`＝發出關係的（較新）版本，`derived_from_revision_id`＝被指向的（較舊）版本。「A 推翻 B」＝A 的版本連到 B 的版本，`relation=supersedes` |
| 驗證 | 兩端必須存在；不得連到自己所在的記錄；`relation` 必須在列舉內；同一（來源、目標、關係）重複送出視為同一條（冪等，不報錯）；隱藏的記錄不可被新連結指向（`NOT_FOUND`） |
| 判定單位 | 連結存在版本之間，但推翻與支持在**記錄**層判定：B 的任一版本被推翻即視為 B 被推翻 |
| `superseded_by` | B 的任一版本被「未隱藏」記錄的 `supersedes` 指向，列出那些記錄（只看直接一層，依 `created_at` 由舊到新）。推翻者被隱藏時，B 恢復為未被推翻；推翻者 `unhide` 後再度生效 |
| `supports`（重新確認） | 若在最後一次推翻 B 之後，有未隱藏記錄對 B 發出 `supports`，B 視為已被重新確認：`get` 的 `status` 為 `reaffirmed`，`current_only` 不排除它。A→B→C→A 的做法：第四筆新記錄 `supersedes` C 並 `supports` A |
| `status`（計算值） | `current`（沒人推翻）、`superseded`（被推翻）、`reaffirmed`（被推翻後又被確認）。`search` 與 `get` 都回傳；`current_only=true` 排除 `superseded` |
| `linked_from` | 列出所有指向該記錄的連結（含關係、來源記錄、日期），預設不含隱藏的來源；最多 50 條，超過標 `truncated`；一層即可，AI 要完整時間線時逐筆 `get`，不做遞移展開 |
| 衍生失效的遞移範圍 | 只沿 `derived`、`summarizes` 兩種關係向上追（來源是被隱藏的記錄則其衍生者失效），有深度保護與環保護；`supersedes`、`supports`、`supplements` **不**傳遞隱藏效果 |
| 隱藏 | `hide`／`unhide` 對已隱藏／未隱藏者為冪等（不報錯）；隱藏不改動任何連結；搜尋預設不含隱藏者，`include_hidden=true` 時隱藏者照回傳並標 `hidden`。回應附被連帶失效的衍生記錄數量 |
| `amend` | 參數：`ref`、`body`，可選 `expected_version`（與最新版不符回 `CONFLICT`，防止兩個 AI 同時改）、`event_time`／`event_time_precision`／`source`（省略＝沿用最新版；要清空用 `clear=["event_time","source"]`，因為 MCP 無法分辨省略與 null）、`links`。`kind` 沿用且不可更改（改變來源性質須另存新記錄並連結）。內文與最新版完全相同回 `INVALID_INPUT`（沒有變化）；已隱藏的記錄不可 `amend`（`CONFLICT`，須先 `unhide`）。重新掃描敏感度，只升不降 |
| 版本與新記錄 | 改錯字、補充＝`amend`；改變看法或推翻結論＝`save` 新記錄加 `supersedes` 連結（沿用「資料模型」規則） |

## 刪除

| 層級 | 行為 |
|---|---|
| 隱藏（預設的「刪除」） | `hidden=1`，預設搜尋與讀取看不到（`include_hidden=true` 可查），可 `unhide` 恢復 |
| 徹底清除 | 真正移除該記錄所有版本與索引，無法恢復；對話流程見 [AGENT_RULES](AGENT_RULES.md) §3 |

**衍生摘要失效**是計算值，不另存欄位：記錄的任一來源（經 `links` 遞移）處於隱藏，其衍生的 `ai_summary`、`inference` 即失效，重新產生前不得用於回答；`unhide` 後自動恢復。

**徹底清除**：MCP 只有 `purge_preview`（唯讀，回傳摘要與會連帶移除的衍生記錄）；實際清除只能由使用者在自己的終端機執行 `emlek purge r<id>`：顯示預覽與固定句式「是否要從資料庫中完全刪除這筆資料？是 / 否（此操作無法再回復）」，輸入 PIN 並回答「是」才執行，含糊或「否」不執行。執行（單一交易）：以僅供清除函式設定的連線層暫存旗標暫時放行不可變觸發器；移除該記錄的版本、全文索引列、標籤關聯、指向這些版本的 `links`（其餘記錄保留，只是少了這條連結）、以它為來源的衍生記錄；`tag_events` 中涉及該記錄的明細清空；`import_log` 保留檔名與雜湊但清空 `record_id` 並標 `purged`，避免重新匯入後復活。提交後 `secure_delete=ON`、對全文索引執行 `optimize`（trigram 索引的片段會殘留在索引區段，審查已實測）、`wal_checkpoint(TRUNCATE)`、`VACUUM`、再 checkpoint，最後掃描資料庫與 WAL 原始檔確認預覽中的片段已不存在（已實測：只刪不整理時 WAL 與主檔會殘留）。**不改動既有備份**，回覆須提醒使用者自行處理舊備份，並說明已傳給第三方 AI 的內容無法收回。

**清除不涵蓋的明文副本（須如實告知，D59）**：資料資料夾內由 emLek 自己產生的 `pre-migration/`（遷移前備份）、還原時留下的 `before-restore` 資料庫，以及 `exports/` 與備份資料夾，都含有完整明文副本。清除完成後，`emlek purge` 掃描這些位置（唯讀開啟），列出仍含該記錄片段的檔案與路徑，由使用者決定是否自行刪除；程式不自動改寫或刪除任何備份與匯出。`pre-migration/` 與 `before-restore` 屬 emLek 自己的暫存，清除報告另提示可由使用者以 `emlek` 提供的清理指令移除（M9 實作時一併決定指令名稱）。

## 工具（MCP／CLI 共用）

尚未實作的欄位一律回 `INVALID_INPUT`，隨里程碑開放。

| 動作 | 說明 |
|---|---|
| `save` | 新增；參數：內容、`kind`、來源、事件時間與精度（可空）、標籤（可空，見 DESIGN_TAGS）、依據或關聯版本與 `relation`（可空）、`sensitivity`（可空）；回傳 `similar_tags`、`sensitivity_hint` |
| `amend` | 為既有記錄新增版本；重新掃描敏感內容並取較高等級 |
| `search` | 見下方「搜尋規則」 |
| `get` | 讀取指定記錄與版本；回傳 `status`、`invalidated`、`superseded_by`、`linked_from`、`links_out`；隱藏的記錄預設回 `NOT_FOUND`（`include_hidden=true` 可讀）；長內容分段（`offset`）；`max_sensitivity` 於 M6 |
| `hide`／`unhide` | 隱藏與恢復（冪等；回傳被連帶失效的衍生記錄） |
| `purge_preview` | 唯讀預覽徹底清除的範圍（實際清除只有 CLI `emlek purge`） |
| `phrases_list` | 唯讀取得啟用語句 |
| `stats` | 唯讀：記錄數（不含隱藏）、隱藏數、版本數、最早與最晚日期、上次備份時間 |
| 標籤工具 | `set_tags`、`tags_find`、`tags_list`、`tags_tree`、`tag_related`、`tag_link`、`tag_alias`，見 [DESIGN_TAGS](DESIGN_TAGS.md) |

僅 CLI（不開放 MCP）：`init`、`doctor`、`reindex`、`mcp`（啟動 MCP 伺服器）、`backup`、`restore`、`export`、`import`、`purge`、`pin set·change·reset`、`notice status·enable`、`sensitivity set`、`phrase add·set·remove`，以及標籤的 `tag merge·remove`、`tags audit`。

MCP 伺服器的 `instructions` 放約 300 字的規則摘要（完整規則在 AGENT_RULES），工具說明保持簡短，因為每個 AI 會話都要為它們付 token；每次工具呼叫各自開關資料庫連線，伺服器行程不長期持有。

**唯讀模式**：`emlek mcp --read-only` 的工具清單只含 `search`、`get`、`phrases_list`、`stats`、`tags_find`、`tags_list`、`tags_tree`、`tag_related`（寫入工具根本不存在，不是被拒絕），供無人看管的排程使用；`max_sensitivity` 預設為 medium。每日簡報見 [DAILY_BRIEFING](DAILY_BRIEFING.md)。

**搜尋規則**：
- 命中單位是**記錄**；預設比對各記錄的最新版本並標示命中的版本，`all_versions=true` 才比對舊版。總筆數的單位也是記錄。
- 過濾：`kinds`、`tags`、`tag_types`、日期範圍（`date_field=event_time|created_at`，前者看最新版本，後者是記錄首次存入時間；事件時間未知的記錄不排除，另列 `undated` 數量）、`include_hidden`（預設否）、`current_only`（排除已被推翻者，預設只標示）、`max_sensitivity`（超過上限的記錄不回內文，只計入 `withheld`）。
- 排序：`order=relevance|event_time|created_at`，`dir=asc|desc`；有關鍵字時預設 relevance、無關鍵字時預設 event_time desc。游標以排序鍵加記錄編號為準，頁間穩定。只有短詞（沒有 3 字元以上的詞）時沒有相關度，改以 `created_at desc`，回應的 `order` 欄位會註明實際採用的排序。
- 一律回傳總筆數並分頁（預設 20 筆、上限 100，附下一頁游標）；過長內容標明已截斷並提供取得剩餘部分的方式。同一天或同一時段的日期範圍即可瀏覽當天或當期所有紀錄。查詢詞有值但沒有任何結果時，回應多一個 `hints`，提醒換另一種語言或寫法再試（內容依記憶庫實際含有的文字種類：日文假名、漢字、英文字母）。
- `superseded_by` 由 `links` 中 `relation=supersedes` 推算，不另存欄位；若之後又有 `supports` 重新確認，一併回傳，讓 AI 能還原 A→B→C→A 的完整過程。`linked_from` 列出所有指向該記錄的連結與關係（如完成紀錄）。
- **結果過多時的摘要（M5，D56／D57）**：當總筆數超過 50（`aggregate_threshold`），回應多一個 `summary` 物件，`results` 仍是依 `limit` 分頁的片段（預設 20 筆），所以舊客戶端不受影響：
  - `summary.undated` 與頂層的 `undated` 不同：前者數**所有**符合者中沒有事件日期的，後者只在有日期過濾時才計。
  - `summary.total`、`summary.first` 與 `summary.last`（依 `date_field` 的最早與最晚日期）、`summary.by_month`（`YYYY-MM` 對筆數，超過 24 個月改為 `by_year`）、`summary.undated`（沒有日期者的數量）。
  - `summary.basis` 固定為 `"keyword"`，`summary.note` 固定為「依關鍵字比對，可能漏掉不同說法的記錄；僅供縮小範圍，不代表全貌」。AI 轉述數字時必須帶出這個限制（AGENT_RULES）。
  - 隱藏的、超過 `max_sensitivity` 的記錄**不計入**任何數字，也不洩漏其筆數（`withheld` 仍只在權限內的呼叫端有意義，沿用現行行為）。
  - 沒有獨立的統計工具；沒有趨勢判斷或情緒統計。按人物、標籤分組等 M7 後依數據再議（D57）。
- **回傳大小**：`results` 每筆只含片段（約 120 字元）、字元數與日期；全文用 `get`。`get` 回傳超過 8000 字元時截斷並標 `truncated` 與 `next_offset`，以 `offset` 取剩餘部分。題庫報告的平均回傳大小是 M5 的驗收指標之一。
- **相容性**：新增欄位一律向後相容；`api_version` 於 M5 起加在所有工具回應，初值 1，未知輸入欄位拒絕。

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
- 記錄的 `sensitivity` 等於各版本最高者；`search`／`get` 回傳該欄位。`emlek export --exclude-high` 可排除 high 記錄。
- 限制：AI 若自行帶 token 而未真正詢問，核心無法分辨，與清除流程同一信任邊界；以題庫與審查驗證各 AI 平台的遵守程度。

## 匯入既有資料

使用者有舊日記要放進來；功能隨時可新增，不阻擋其他里程碑。`emlek import <檔案或資料夾>`（CLI）：讀 `.txt`、`.md`，每檔一筆 `original`；檔名或內文開頭的日期用作事件時間，沒有則留空；`#標籤` 解析為 user；`--split-by-heading` 以日期標題切成多筆；`--dry-run` 預覽；`source=import:<檔名>`。冪等以 `import_log` 的（檔名、段落序號、內容雜湊）判斷；檔案被修改後雜湊改變，視為新內容匯入並警告「檔案自上次匯入後已變更」，不覆蓋舊記錄。真實舊日記屬私人資料：開發與測試只用合成檔，真實檔案須使用者貼出路徑並同意才處理。

## 備份與搬家

1. 資料在一個資料夾，主體是一個 `.db`（含搜尋索引）。備份放在 `config.toml` 的 `backup_dir`：`init` 時預設選與資料庫不同的磁碟（有第二顆磁碟用其上的 `emlek-backups`，否則在使用者文件夾下），不與資料庫放同一處。
2. `emlek backup`：用 SQLite 一致性備份（`VACUUM INTO`）產生帶日期的單一檔，不直接複製使用中的檔案。可選 `--encrypt` 密碼加密，須提醒密碼遺失無法還原。遷移前自動備份一份。備份檔以時間命名（`emlek-<時間>.db`），建立後立刻以唯讀方式檢查完整性與筆數，並把時間記進 `meta`（`doctor` 與 `stats` 會顯示，超過 14 天或從未備份會警告）。備份資料夾不得在資料夾裡面；與資料在同一顆磁碟時會提醒。
3. `emlek export`：完整 JSONL（含所有版本與關係）＋供閱讀的 Markdown。每次匯出建立新的帶時間資料夾，不覆蓋；失敗時整個資料夾移除，不留半成品。`--exclude-high` 排除最高敏感度記錄；隱藏的記錄照匯出並帶 `hidden` 旗標。
4. `emlek restore <備份檔>`（必須在你自己的終端機執行：標準輸入、輸出、錯誤輸出都是終端機，並再問一次「是」；M6 起另需 PIN）：先以唯讀方式檢查備份（完整性、必要資料表、結構版本不得比程式新），複製到暫存檔、必要時升級結構並再驗證筆數，最後才把目前資料庫（連同 WAL 檔）改名保留為 `emlek.db.before-restore-<時間>` 再換上。資料庫正被其他程式（例如 MCP 伺服器）使用時回 `BUSY` 並維持原狀。
5. 換設備：舊機 backup → 新機安裝 → `init` → restore → 重新指向 MCP 設定。實測 36000 筆（資料庫約 523 MB）：備份約 9 秒、還原約 22 秒、匯出約 37 秒（JSONL 約 147 MB 加 36000 個 Markdown 檔）。

## 規格細節（v1）

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

## 擴充準則（為未來需求預留，現在就要遵守）

目前一律本機使用。以下準則讓日後加手機或遠端存取時不必重寫核心：
- 核心不依賴任何傳輸方式；MCP（stdio）與 CLI 只是外殼，日後可再加 HTTP 入口。
- 權限（唯讀、可寫、需真人終端機）由**核心**的權限表判斷，不只靠外殼，新入口自動繼承；遠端入口將不開放清除。
- 位置與設定可由參數或環境變數指定（`--data-dir`）；資料庫不存絕對路徑；資料庫不得放在同步資料夾。
- 工具輸入輸出用有版本號的格式（`api_version`），未知欄位拒絕，讓不同客戶端可共存。
- 資料庫結構從第一版就有版本與遷移機制。
- 日誌不記內容；提供健康檢查。
- 匯入與匯出用與工具無關的純文字格式。

## 未來需求

手機、遠端與多裝置等保留需求（目前不開發，使用者 2026-11-01 決定）見 [ROADMAP](ROADMAP.md)。

## 開發順序（里程碑）

每個里程碑結束須 ruff、mypy、pytest 全綠，更新 PROGRESS 的待驗收與 30 秒驗收清單。測試 ID 見 [TEST_PLAN](TEST_PLAN.md)，題號見 [QUESTIONS](QUESTIONS.md)。**真實資料（含舊日記）只在 M4 與 M6 完成後，且須使用者貼出路徑並同意。**

| 里程碑 | 內容 | 完成標準 |
|---|---|---|
| M1 骨架 | pyproject、`init`、`doctor`（基本）、設定檔、遷移 0001（meta、records、revisions、不可變觸發器）、`save`／`get`（CLI） | 中日英與 emoji 原文往返逐位元組一致；版本不可改；失敗不留半筆；`doctor` 報告環境（T01–T03、T05、T11 子集、T25） |
| M2 搜尋與時間 | FTS5＋LIKE 逐詞路由、NFKC、日期範圍、`order`、`kinds`、分頁與總筆數；題庫系統層骨架與合成資料產生器 | T04、T08–T10；Q01/02/06/07/13/15/20 系統層通過；3.6 萬筆（含真實長度）規模測試有記錄 |
| M3 權限與 MCP | `core/permissions.py`、MCP 完整與 `--read-only`、stdout 只輸出協定；Claude Code 與 Codex CLI 以合成庫實測；平台唯讀沙箱旗標實測；AI 層題庫開始（只報告不卡關） | T06、T07、T16；兩個 AI 都能存與找回合成資料；唯讀清單不含寫入工具 |
| M4 安全網 | `backup`、`restore`（驗證再替換）、`export` v1、`stats`、遷移前自動備份 | T19、T20；還原到乾淨資料夾與原庫逐筆一致 |
| M5 版本、連結、隱藏 | `amend`、`relation`、`superseded_by`、`linked_from`、`hide`／`unhide`、衍生失效（計算值）；**回傳瘦身**：搜尋預設只回片段與日期，結果過多（預設 >50 筆）時先回筆數、按月分布、最早與最晚日期，並固定標註「依關鍵字比對，可能漏掉不同說法」；隱藏與超過權限的記錄不計入；不新增獨立統計工具；全文用 `get`（D56、D57） | T12、T13、T26；Q08–10、Q22–23；題庫報告的平均回傳大小不高於 M4 基準；規模彙整題（QUESTIONS 類別 I，數千筆合成資料）AI 須說明僅檢視部分或先縮小範圍 |
| M6 信任閘門 | 規則掃描、`notice_settings`、`confirm_token`／`notice_token`、`phrase`、`notice`、`sensitivity set` 的真人終端機閘門與 PIN（`pin set·change·reset`）、`phrases_list`；**`get` 補上 `max_sensitivity`**（隱藏檢查已於 M5 完成，目前只有 `search` 有敏感度上限） | T14、T15、T16；Q40–42；閘門限制如實記載 |
| M7 標籤 | M7a：資料表、`set_tags`、`#標籤`、別名、向下展開。M7b：`tags_find` 等查詢工具、facets、`similar_tags`、合併、健檢、熱門標籤 | T17、T18；Q03/05/32–36 |
| M8 匯入與備份加密 | `import`（含敏感掃描、`--split-by-heading`）、備份 `--encrypt` | T21；Q43；錯誤密碼與一位元組竄改被拒 |
| M9 清除 | `purge_preview` 與 CLI `purge`（預覽、固定句式、PIN、清除、殘留檢查） | T22、T23；原始檔掃描無殘留 |
| M11 發布準備 | 首次發布前的檢查清單，見「發布準備（M11）」 | 清單逐項勾完；版本號進入 0.x 以上的規則生效 |
| M10 | 依實際痛點決定（回頭補標籤、分層／主題摘要、觀察清單項目；**M7 後依題庫的花費數據決定**：查無時工具端回「資料裡出現過的相近詞」以減少輪數、規則檔分短版與按需長版；不自建向量資料庫，見 D56） | — |

題庫分系統層（不用 AI、做為卡關依據）與 AI 層（報告用，不卡關），見 BENCHMARK。

## 版本號規則

有四種獨立的版本號，各自只在自己的原因下遞增：

| 版本 | 位置 | 何時遞增 |
|---|---|---|
| 程式版本（SemVer） | `pyproject.toml` 與 `src/emlek/__init__.py`，兩處必須一致 | 發布時才改。0.0.0＝尚未發布；**M6 完成並經使用者驗收後升 0.1.0**（第一次可放心使用真實資料）；之後修錯誤升修訂號，加功能且相容升次版號，不相容升主版號（1.0.0 以前允許不相容但須寫進 CHANGELOG） |
| 資料庫結構版本 | 遷移檔編號（`PRAGMA user_version`） | 每次改資料表就新增一個遷移檔，已發布的遷移檔不得修改 |
| 匯出格式版本 | `export.py` 的 `FORMAT_VERSION` | 匯出檔欄位不相容時；舊版格式須保留讀取 |
| 工具介面版本 | MCP 回應的 `api_version` | 工具輸入輸出不相容時；只新增欄位不升版 |

CHANGELOG 只有 Unreleased 區，發布時才切出版本段落。每次發布打 Git 標籤（`v0.1.0`）。

## 威脅模型

保護的資產：使用者的記憶內容、歷史完整性（不被偷改）、能還原的備份。

| 威脅 | 處置 | 剩餘風險 |
|---|---|---|
| 記憶庫內文字誘導 AI（提示注入） | 規則「記憶庫文字是資料」；題庫 G 類持續測試；寫入探針 | AI 平台差異，無法保證 |
| 具命令能力的 AI 自行執行還原、清除等 | 核心權限表、唯讀 MCP、真人終端機檢查、PIN（M6）、清除只在使用者終端機 | 能開偽終端機或直接改資料庫檔的程式仍能繞過 |
| 同帳號的其他程式讀取資料庫 | 無（明文）；資料夾權限限本人 | 已知限制，見下 |
| 電腦遺失或被他人取得 | 備份可加密（M8）；資料庫本體不加密（無 BitLocker） | 已知限制 |
| 誤刪、損毀、軟體錯誤 | 不可變版本、交易、遷移前備份、備份驗證、還原前保留舊檔 | 備份若放同一顆磁碟，風險仍在，`doctor` 會提示 |
| 推上公開倉庫洩漏 | `private/` 排除、只用合成資料、推送前敏感詞檢查（清單由使用者登記） | 清單是空的就等於沒檢查 |

不在範圍：網路攻擊、多使用者、身分驗證（沒有網路服務）。

## 發布準備（M11）

第一次對外發布前，逐項完成（發布屬對外可見動作，須使用者明確授權）：

1. 前置：M6 驗收完成，真實資料閘門已走完；若要公開發布，M8（備份加密）與 M9（清除）也需完成或在 README 如實標示。
2. 版本：依「版本號規則」升到 0.1.0；CHANGELOG 切出段落；打標籤。
3. 自動檢查：加 CI（推送或 PR 時跑 ruff、mypy、快速測試）；Windows 為主要平台。
4. 依賴：檢查 `uv.lock` 的套件是否有已知安全問題與過期；SQLite 版本須符合 WAL 修補線。
5. 安裝：寫給非開發者的安裝與升級步驟（含 `emlek` 不在 PATH 時怎麼辦），升級前先備份並跑 `doctor`。
6. 還原演練：用真實備份在乾淨資料夾還原一次並比對筆數，記錄日期。
7. 隱私：使用者登記敏感詞清單；全倉庫掃描沒有私人路徑、帳號、真實資料；`private/` 不在版本控制內。
8. 文件：README 狀態與限制、授權、已知限制與威脅模型是最新的。

## 刻意不做

身分／SID／named pipe 隔離、授權 grant、提案→確認→提交流程、獨立安全帳本與防備份復活、restic、獨立搜尋庫與 outbox、長期分析掃描與自動統整、完整知識圖譜與預灌世界知識（標籤系統只記個人分類與別名）、標籤向量搜尋、查詢歷史記錄（查詢本身是敏感資料）、獨立簡繁對照表（先用別名）。需要時從 archive 取用。

**語意搜尋（用意思找）暫不做**，屬架構大決定，須經使用者同意。重新評估條件：使用一段時間後，以題庫中的模糊問法題（Q04、Q11、Q12、Q16、Q17）加上使用者同意提供的真實問題實測；超過三分之一找不到或找不全才正式提案。模型變強可降低門檻：更大的上下文可由 AI 直接分批讀取日期範圍內的紀錄代替部分搜尋。

**近期加權排序暫不做**：現有日期範圍與排序已夠用。題庫實測不理想時，Agent 須主動提醒使用者評估（與語意搜尋同列觀察清單，見 [BENCHMARK](BENCHMARK.md)）。

## 已知限制

- AI 是否正確判斷「要不要存」、是否真的詢問過，靠使用指示，軟體無法強制。
- 徹底清除不影響既有備份與第三方副本。
- Windows 家用版沒有 BitLocker：資料庫與日誌在磁碟上是明文，電腦被他人取得或實體遺失時資料可被讀取；軟體層不加密資料庫本體，只有備份可加密。
- 只能找回使用者主動保存的內容。
- 搜尋可以接近完整，不能保證完整（標籤沒標、用詞不同都可能漏）；回答須如實說明範圍。
- 能執行命令的 AI 與同一 Windows 帳號下的程式，理論上能直接開資料庫檔；唯讀模式與終端機檢查只擋常見路徑。

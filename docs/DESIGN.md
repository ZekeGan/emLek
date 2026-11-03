# emLek 設計

狀態：M1–M9 已實作並驗收（以 [PROGRESS](PROGRESS.md) 為準），M9 已依經 Opus 審查的規格實作並驗收。取代 [archive](archive/) 的完整版藍圖（非現行規格）。決策原因見 [DECISIONS](DECISIONS.md)；標籤系統與分層摘要見 [DESIGN_TAGS](DESIGN_TAGS.md)。

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
| `import_batches`、`import_log` | 批次與每檔紀錄：`file_name`、`content_hash`、`record_id`（清除後為空）、`purged`、`batch_id`、`imported_at`（M8 精簡版，`chunk_index` 延後） |
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
- **PIN**：細節見「信任閘門規格（M6）」。**PIN 不得告訴任何 AI**；若貼在對話，須立即 `emlek pin change`。
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

**徹底清除（M9 規格，已經 Opus 審查修正，D82）**：

- **入口**：MCP 只有 `purge_preview`（唯讀、**只回中繼資料**：記錄編號、版本數、日期、是否隱藏、會連帶移除的衍生記錄編號與類型、會移除的標籤、`purge_enabled`；**不回內容**，否則等於把想刪的文字再傳給雲端 AI；內容摘錄只出現在 CLI 預覽）。實際清除只有 `emlek purge r<id> [r<id> …]`（一次最多 20 個明確編號，沒有標籤、日期、批次選擇器），走 `INTERACTIVE_ONLY` ＋ `PIN_REQUIRED` 新操作 `purge`；沒有任何啟用中的 `purge` 語句時一律拒絕（fail closed）。
- **流程**：真人終端機 → PIN → 預覽（含內容摘錄、連帶移除的衍生記錄、**保留但可能提到此內容的 `original` 記錄清單**、會移除的標籤）→ 固定句式「是否要從資料庫中完全刪除這筆資料？是 / 否（此操作無法再回復）」→ 答「是」→ 在交易內重算**指紋**（記錄、版本、連結、標籤編號）並與預覽比對，不同就中止並要求重跑（防止預覽後 AI 修改、補連結）；含糊或「否」不執行。第一個不可逆動作在「是」之後。
- **連帶範圍**：被清除版本的衍生記錄＝所有 `kind` 為 `ai_summary` 或 `inference`、與被清除版本有**任何** relation（含空 relation、`supports`、`supplements`）連結者，遞移追蹤。`original` 記錄**永不連帶刪除**，只在預覽列出。
- **單一交易（`secure_delete=ON` 先設定，`BEGIN IMMEDIATE`）**，僅供 `purge.py` 設定的連線層旗標暫時放行不可變觸發器；刪除順序：兩個方向的 `links` → `record_tags` → 該記錄建立且清除後使用次數為 0 的標籤（含 `tag_aliases`、`tag_links`、`tags_fts` 列，以及所有提到它們的 `tag_events`；其他變成未使用的標籤只列出）→ 涉及該記錄的 `tag_events` → `import_log`（`file_name` 改成 `purged:<log id>`、`record_id` 清空、`purged=1`，**保留 `content_hash` 當防復活守衛**）→ 符合的與已用／過期的 `confirm_tokens` → `revisions` → `records`；對 `revisions_fts` 與 `tags_fts` 執行 `optimize`（FTS 完整性檢查失敗則改 `rebuild`）；斷言刪除筆數等於預覽；寫 `purge_log`；設 `meta.purge_scrub_pending=1`；提交。
- **提交後擦除**：`wal_checkpoint(TRUNCATE)`（**檢查回傳值**，有其他連線的讀取交易時會回忙碌）→ `VACUUM`（需約兩倍資料庫大小的空間，`temp_store=MEMORY`）→ 再 checkpoint → 對資料庫、WAL、SHM 做**原始位元組**掃描 → 全部乾淨才清除 `purge_scrub_pending`。任何一步沒完成就回報「邏輯上已刪除，實體擦除未完成，請關閉 AI 應用程式後執行 `emlek purge --finish`」，`doctor` 顯示警告；擦除可重複執行。原子的是邏輯刪除，不是擦除。
- **ID 不重用**：`meta.record_id_floor` 記錄曾用過的最大編號，新增記錄以明確編號插入；`restore` 保留較大的值。
- **匯入防復活**：`importer` 先查已清除的 `content_hash`，相同內容即使改檔名或加 `--allow-duplicates` 也一律擋下。`import --undo` 對已清除的紀錄本來就略過。雜湊未加鹽，只能讓持有同一檔案的人確認，屬可接受並記載。
- **稽核**：`purge_log(at, record_ids, revision_count, derived_count, scrub_status)`，不存文字也不存雜湊；`stats` 只露出次數與時間。`restore` 若備份早於最後一次清除，警告並多要一次「是」：還原會讓已清除的資料回來。
- **MCP 旗標安全**：觸發器放行旗標屬單一 `Database` 實例，MCP 每次呼叫各開實例所以不會外溢；測試要求只有 `purge.py` 呼叫 `purge_mode()`；任何能 import emLek 的程式都能自己設旗標，列入已知限制。

**清除報告與殘留掃描（D59、D82）**：資料資料夾內由 emLek 產生的 `pre-migration/`、`emlek.db.before-restore-*`（連同 `-wal`、`-shm`）、`*.failed`、`emlek.db.decrypted`、`emlek.db.restoring*`、`tmp/*`、備份資料夾的 `*.partial` 與 `logs/`，以及 `exports/` 與備份，都可能含明文副本。掃描**只讀原始位元組，絕不用 SQLite 開啟**（唯讀開啟也可能重播或建立 WAL／SHM）。備份依時間列出（記錄建立後到清除前的備份「很可能含有」）；加密備份回報「無法檢查」。掃描用的片段：取自 `body` 與 `body_norm`、至少 8 字元、不含換行引號反斜線；丟掉也出現在其他現存內容或標籤的片段；沒有足夠獨特的片段就回報「太短，無法驗證」；片段只在記憶體，**輸出與日誌只印路徑與數量**。
**`emlek cleanup`**（預覽為預設，`--apply` 需真人終端機與 PIN）：只處理資料資料夾內 emLek 自己的暫存（遷移前副本、before-restore 與其附屬檔、`.failed`、`.decrypted`、`.restoring`、`tmp`）；執行前要求現行資料庫通過 `integrity_check`，且有一份比最新副本更新的備份通過 `inspect_database`；永不碰現行資料庫、`backup_dir`、`exports/`。程式不自動改寫或刪除備份與匯出。
**如實告知（M1）**：清除只是從 emLek 的資料庫檔案移除。到不了的地方：SSD／檔案系統殘留、Windows 還原點與陰影複本、防毒隔離區、本機 AI 對話記錄（Claude Code 的 `~/.claude/projects`、Codex 的 session）、PowerShell 歷史（用過 `save --text` 時）、終端機捲動緩衝、既有備份，以及已傳給第三方 AI 的內容。清除報告必須列出這些。

## 工具（MCP／CLI 共用）

尚未實作的欄位一律回 `INVALID_INPUT`，隨里程碑開放。

| 動作 | 說明 |
|---|---|
| `save` | 新增；參數：內容、`kind`、來源、事件時間與精度（可空）、標籤（可空，見 DESIGN_TAGS）、依據或關聯版本與 `relation`（可空）、`sensitivity`（可空）；回傳 `similar_tags`、`sensitivity_hint` |
| `amend` | 為既有記錄新增版本；重新掃描敏感內容並取較高等級 |
| `search` | 見下方「搜尋規則」 |
| `get` | 讀取指定記錄與版本；回傳 `status`、`invalidated`、`superseded_by`、`linked_from`、`links_out`；隱藏的記錄預設回 `NOT_FOUND`（`include_hidden=true` 可讀）；長內容分段（`offset`）；`max_sensitivity` 於 M6 |
| `hide`／`unhide` | 隱藏與恢復（冪等；回傳被連帶失效的衍生記錄） |
| `purge_preview` | 唯讀預覽徹底清除的範圍，只回中繼資料不回內容（實際清除只有 CLI `emlek purge`） |
| `phrases_list` | 唯讀取得啟用語句（依 `kind` 分組） |
| `stats` | 唯讀：記錄數（不含隱藏）、隱藏數、版本數、最早與最晚日期、上次備份時間 |
| 標籤工具 | `set_tags`、`tags_find`、`tags_list`（含階層目錄與共現）、`tag_link`、`tag_alias`，見 [DESIGN_TAGS](DESIGN_TAGS.md)「M7 規格」 |

僅 CLI（不開放 MCP）：`init`、`doctor`、`reindex`、`mcp`（啟動 MCP 伺服器）、`backup`、`restore`、`export`、`import`、`purge`、`pin set·change·reset`、`notice status·enable`、`sensitivity set`、`phrase add·set·remove`，以及標籤的 `tag merge·remove`、`tags audit`。

MCP 伺服器的 `instructions` 放精簡的規則摘要（目前約 600 字元，另加熱門標籤名稱；完整規則在 AGENT_RULES，**不會自動送給 AI**，使用者須把它裝進所用 AI 平台的全域或專案指令，安裝說明列入 M11；題庫的 AI 層目前是附上完整規則來測，只有開場說明的情境尚未測），工具說明保持簡短，因為每個 AI 會話都要為它們付 token；每次工具呼叫各自開關資料庫連線，伺服器行程不長期持有。

**唯讀模式**：`emlek mcp --read-only` 的工具清單只含 `search`、`get`、`phrases_list`、`stats`、`tags_find`、`tags_list`（寫入工具根本不存在，不是被拒絕），供無人看管的排程使用；`max_sensitivity` 預設為 medium。每日簡報見 [DAILY_BRIEFING](DAILY_BRIEFING.md)。

**搜尋規則**：
- **回應大小上限（D77）**：MCP 的 `search` 單次回應最多約 12000 字元（只回得下的筆數，至少 1 筆）；被截掉時回 `results_trimmed`、一句提示，`next_cursor` 指向最後一筆回傳的記錄，翻頁不漏不重。命令列與核心預設不設上限。三萬筆實測單次回傳最大約 1.8 萬字元，是 token 成長的主因。
- **關鍵字語法（2026-11-02 起）**：空白分隔的詞在同一組內必須**全部**出現；裸的大寫 `OR` 把查詢分成幾組，**任一組成立**即命中（最多 20 組、全部詞合計 ≤ 30；單詞的組合併成一次索引查詢加一次短詞掃描，多詞的組各自查詢；超過上限的錯誤訊息會說明怎麼拆）。小寫的 or、加引號的 "OR" 只是普通的字。回應多個詞且**零結果**，或查詢含 OR，就多一個 `term_hits`（每個詞單獨命中幾筆，只算可見記錄；3 字以上的詞走索引計數，短詞共用一次掃描）；零結果時再加一句提示，讓 AI 知道哪個詞有資料、該用 OR 或分開搜尋（D75）。零結果的語言提示只要求補上「還沒試過」的文字；已涵蓋記憶庫用到的各種文字時改建議換上位或下位說法、用標籤或日期縮小（D78）。MCP 的 `search` 單頁最多 30 筆（核心與命令列仍可到 100）。MCP 的搜尋結果用精簡格式（`compact`）：值等於預設的欄位（`hidden` false、`sensitivity` none、`status` current、`invalidated` false、`source` 空、`latest_version` 等於 `matched_version`、無事件日期時的 `event_time*`）不輸出，AGENT_RULES 說明缺少即預設；`ref` 與 `revision_ref` 都保留（AI 引用的是後者）。含查詢詞時回應多一個 `matching_tags`（名稱或別名與查詢詞完全相同的標籤與可見筆數，最多 5 個），AI 可直接用 `tags` 再搜，不必另呼叫 `tags_find`（D79）。開場說明的熱門標籤名稱上限由 200 降為 50（`tags_list` 仍可到 200）。`untagged=true` 只看還沒有任何標籤的記錄。
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
- high：`save` 回傳 `NEEDS_CONFIRMATION`（`state=needs_confirmation`，`error.data` 含一次性 `confirm_token`，綁定內容雜湊，10 分鐘過期；機制見「信任閘門規格（M6）」）；使用者答「是」才帶 token 重送。
- medium：未確認過時回傳 `NEEDS_CONFIRMATION`（`state=needs_notice`，含綁定該內容的 `notice_token`）；使用者同意後帶 token 重送，核心寫入 `notice_settings`（`enabled=0`）。`emlek notice status` 查看、`emlek notice enable medium` 重開（CLI，真人終端機）。
- `amend` 同樣掃描並取較高等級，高風險新內容一樣走確認；AI 傳入的 `sensitivity` 只能調高，調低只能用 `emlek sensitivity set r<id> <level>`。
- `import` 也掃描：含 high 的檔案預設略過並列出，使用者檢視後可用 `--include-high` 在真人終端機確認匯入；medium 直接匯入並標記，匯入摘要回報數量。
- 記錄的 `sensitivity` 等於各版本最高者；`search`／`get` 回傳該欄位。`emlek export --exclude-high` 可排除 high 記錄。
- 限制：AI 若自行帶 token 而未真正詢問，核心無法分辨，與清除流程同一信任邊界；以題庫與審查驗證各 AI 平台的遵守程度。

## 信任閘門規格（M6）

### 儲存位置

遷移 0004 新增資料表 `phrases`、`notice_settings`、`confirm_tokens`，以及 `meta` 的 `pin_initialized`、`recovery_salt`、`recovery_hash`、`recovery_failed`、`recovery_locked_until`。**PIN 雜湊與失敗計數不放資料庫，放資料夾內的 `security.json`**（`version`、`kdf` 參數與 salt、`pin_hash`、`failed_count`、`locked_until`；寫入用暫存檔加改名，權限同資料夾）。原因：還原舊備份不能讓 PIN 退回舊值，備份與匯出也不該帶著 PIN 雜湊。`restore` 換庫時保留目前的 `pin_*`、`recovery_*` 這幾個 `meta` 鍵，不用備份裡的。

### PIN 狀態

| 狀態 | 條件 | 行為 |
|---|---|---|
| 未設定 | `meta` 沒有 `pin_initialized` | 需 PIN 的命令一律拒絕（失敗即關閉），訊息指向 `emlek pin set`；`doctor` 以「注意」提示 |
| 已設定 | 有標記且 `security.json` 有效 | 正常運作 |
| 受損 | 有標記但 `security.json` 不見或損壞 | 需 PIN 的命令與 `pin set` 都拒絕，只剩 `pin reset`（用復原碼） |

- 互動式 `emlek init`（真人終端機）建立資料夾後直接進入 `pin set`；非互動的 `init`（測試、腳本）略過並提示。**請在把終端機權限交給 AI 之前先設好 PIN**：未設定時，能開偽終端機的程式可以搶先設自己的 PIN。
- PIN 規則：至少 6 個字元（任意字元）、輸入兩次須一致；以 `getpass` 從主控台讀取，不接受參數、環境變數或標準輸入；`hashlib.scrypt`（n=2^15、r=8、p=1、16 位元組 salt，參數寫入檔案）；比對用常數時間函式。
- 失敗計數：**先寫入再驗證**（驗證中途被中斷也算一次）；成功歸零；連續 5 次錯誤鎖定 5 分鐘，鎖定期間不再詢問 PIN 直接拒絕。
- 復原碼：`pin set` 顯示一次（20 個英數字、分 5 組），資料庫只存 scrypt 雜湊；`pin reset` 需復原碼加兩次新 PIN，並產生新復原碼；復原碼嘗試次數另計（`meta`，5 次鎖 5 分鐘），因為受損狀態下 `security.json` 不可信。`pin change` 需舊 PIN。
- 復原碼與 PIN 都遺失的最後手段（文件說明，不做成指令）：停掉所有 emLek 行程，刪除 `security.json`，再用 SQLite 命令列清除 `meta` 的 `pin_initialized`，之後 `pin set`。同帳號的程式也能這麼做，這是已記載的限制。

### 需 PIN 的命令共用流程

順序固定：①三條串流都是真終端機 ②PIN 狀態 ③鎖定 ④讀 PIN ⑤驗證，通過才執行。命令清單見「自訂語句」。每次結果（命令名稱、成功／失敗／鎖定）寫入日誌，**不含內容**；`doctor` 顯示上次成功時間、自上次成功後的失敗次數與是否鎖定（失敗次數大於 0 為「注意」，提示可能有程式在猜 PIN）。

### 觸發語句

`phrases(id, kind, text, enabled, created_at, updated_at)`；遷移時寫入預設值（見「自訂語句」）。語句 1–100 字元、不含控制字元，同一 `kind` 內以 NFKC＋casefold 後不得重複。`phrase list [kind]` 不需 PIN；`add`、`set <id> [--text …] [--enable|--disable]`、`remove` 需 PIN。停用或刪除最後一個啟用中的 `purge` 語句＝關閉徹底清除。MCP `phrases_list`（三個入口皆有）只回啟用中的語句、依 `kind` 分組。核心**不**機械比對語句，它們只是 AI 的判斷依據。

### 敏感掃描

`core/sensitivity.py` 是純函式：輸入文字，先做 NFKC，回傳命中的（類別，等級）清單，**不回傳也不記錄命中的文字**。有效等級＝AI 宣告、掃描、既有記錄三者最高；AI 只能調高，調低只能 `sensitivity set`（需 PIN）。回應的 `sensitivity_hint` 只含等級與類別。

| 等級 | 類別與規則 |
|---|---|
| high | 私鑰區塊（`-----BEGIN … PRIVATE KEY-----`）；常見金鑰格式（AWS `AKIA…`、GitHub `ghp_…`、Slack `xox…`、`sk-…`）；JWT（三段 base64url）；信用卡號（13–19 位數字，允許空白與橫線，Luhn 驗證）；密碼語句（密碼／パスワード／password／暗証番號等關鍵字後接冒號、等號或「是／は」再接 3 字元以上內容）；復原碼語句（復原碼／recovery code／backup code）；銀行帳號（帳號／口座／account 關鍵字近處 7–16 位數字） |
| medium | 手機與市話格式（台灣 09xx-xxx-xxx、0x-xxxxxxx、日本 0x0-xxxx-xxxx、國際碼 +nn）；單純數字串只有在「電話／TEL／携帯／手機」等關鍵字 20 字內才算；郵遞區號加住址關鍵字（〒、住所、住址、地址、address）；台灣身分證字號（含檢查碼）；日本個人編號與護照（關鍵字加號碼）；生日（生日／誕生日／birthday 近處的日期）；電子郵件位址 |
| none | 其餘。人名不掃描（太常見），交給 AI 語意判斷 |

規則掃描不可能完整，誤判與漏判都會有；測資一律用公開的測試值（如 `4111 1111 1111 1111`、`AKIAIOSFODNN7EXAMPLE`、範例 JWT），不放真實資料。

### 確認碼

`confirm_tokens(token_hash, kind, content_hash, created_at, expires_at, used_at)`。確認碼為 128 位元隨機值，只存 SHA-256；`content_hash`＝SHA-256(操作名稱＋記錄編號（`save` 為空）＋內文)；10 分鐘過期；每次簽發時順手清掉一天前的舊列。

1. 有效等級 high：`save`／`amend` 不帶碼 → `NEEDS_CONFIRMATION`，`error.data` 含 `state=needs_confirmation`、`confirm_token`、`categories`、`ask_user`（要原樣問使用者的固定句式，與 AGENT_RULES §1 同一份文字，測試會比對）、`expires_in`。帶碼重送：驗證通過（存在、種類相符、未用過、未過期、內容雜湊相符）才寫入，且「標記已用」與寫入在**同一交易**（寫入失敗則碼不被消耗）。每次都要問，不可關閉。
2. 有效等級 medium 且 `notice_settings.enabled=1`：同上，`state=needs_notice`、`notice_token`；通過後寫入並把 `enabled` 設為 0、記 `acknowledged_at`。**等級層級共用**：同意一次，所有 medium 類別都不再問（Q41 的「同類」指同一等級）。`notice enable medium`（需 PIN）重新開啟。
3. 同時命中 high 與 medium 時只走 high。任何驗證失敗一律回 `TOKEN_INVALID`，訊息相同，不透露是哪一項不符。碼不寫入日誌。

### 讀取端的敏感度上限

`get` 新增 `max_sensitivity`（唯讀 MCP 預設 medium、其餘 MCP 預設 high、命令列預設 high）；超過上限回 `NOT_PERMITTED`（不回內文）。`get` 的 `linked_from`、`superseded_by`，以及 `search` 的 `summary`，一律略過超過上限的記錄，不洩漏其存在或筆數。

### 完成標準

T14、T15、T16，以及新增的 T27（確認碼）、T28（PIN 儲存與狀態）；Q40–Q42（需最小兩輪對話機制：以 `claude --resume` 接續同一工作階段，作為 M6 的一部分一起做）；使用者在自己的終端機完成：設定 PIN、輸入錯誤 PIN 到被鎖定、`restore` 需 PIN、在 Claude Code 的 PowerShell 工具執行 `phrase add` 被拒；通過後程式版本升 0.1.0。

## 審查補充：M8 設計要點（Opus 審查，2026-11-02；M8 開始前定案）

備份加密：分段 AEAD（每段約 1 MiB，隨機前綴加計數器當 nonce，檔頭與「最後一段」旗標放進附加驗證資料，才能防截斷與重排；整個大檔一次 GCM 不可行）；解密時對 scrypt 參數設上下限，防惡意檔頭造成資源耗盡；`VACUUM INTO` 的明文暫存檔放在資料夾內而不是備份磁碟，串流加密後刪除並記載 SSD 可能殘留；密碼只能用 `getpass` 在真人終端機輸入，不與 PIN 共用，加密後立即解密驗證；測試要涵蓋改一個位元組、交換兩段、截斷都被拒。匯出（`exports/`）與 `pre-migration/` 的副本仍是明文，要另外標示或處理。

匯入：**用單一大交易批次寫入**（30,108 筆逐筆呼叫 `save` 花了 27 分鐘，約 19 筆／秒，瓶頸是每筆一次 fsync）；編碼必須明確指定，壞字元不可悄悄替換（錯了會成為永久的原文）；預設只預覽（加 `--apply` 才寫入）；每次匯入記一個批次編號，讓整批可以一次隱藏（徹底清除在 M9 之前做不到，匯入錯了只能隱藏）；改檔名造成的重複要用雜湊跨檔名比對並警告；不用檔案修改時間推測日期；匯入的 `#標籤` 另標來源，**不得進 AI 開場說明的標籤清單**。

## M8 規格（2026-11-03；使用者指示開始 M8 後又改為「之後再開發」；Opus 規格審查已併入；**尚未實作，等使用者下一道指示**）

**範圍**：①備份加密（`backup --encrypt`、`restore` 讀加密檔）；②匯入精簡版（`emlek import`）。都只在命令列，不開放 MCP。

**共同前置：共用寫入函式**。把 `service.save` 的寫入段抽成 `_write_record(conn, *, body, kind, level, event_time, precision, source, parse_hashtags)`：不開交易、不簽發確認碼。`save` 與 `import` 都呼叫它（現有 `save` 自己開 `BEGIN IMMEDIATE`，不能放進外部交易，`tokens.issue` 也自己開交易）。

（M8 已依本規格實作；與規格的差異：不另抽 `_write_record`，匯入直接使用 `service._insert_record`／`_insert_revision`，它們本來就不開交易；`import --undo` 與 `--list` 是 `import` 的選項而非子命令。）

### 備份加密檔格式（版本 1，副檔名 `.db.enc`）
- **檔頭**（固定 40 位元組）：魔術字 `EMLKBK01`（8）｜KDF 代碼 1（1）｜scrypt log2(n)、r、p（各 1）｜保留 0（3）｜salt（16）｜nonce 前綴（8，隨機）｜分段大小 log2（1）。檔頭整段是每一段的附加驗證資料（AAD）。
- **分段**：AES-256-GCM，nonce＝前綴（8）＋段序號（4，大端）；AAD＝檔頭＋1 位元組「最後一段」旗標。讀者只接受分段大小 log2 = 20（1 MiB），其他拒絕。寫入者預讀一段判斷是否為最後一段：明文剛好是整數倍時，最後一段就是那個滿段（**不補空段**）；只有空內容才寫一個 0 位元組的段。讀者遇到非最後段卻短於 1 MiB＋16、或任何段短於 16 位元組、或段序號達 2^32，一律拒絕。改任一位元組、交換兩段、截斷（含剛好砍在段落邊界）、尾端追加，都會驗證失敗。
- **金鑰**：`hashlib.scrypt`，預設 n=2^17、r=8、p=1。`maxmem = 128·r·n + 16 MiB`，依檔頭的值計算，**不共用 PIN 的 `KDF_MAXMEM`**（128 MiB 對 n=2^17 不夠，會 `ValueError`）。解密時檔頭參數必須在範圍內才執行（log2(n) 14–18、r=8、p 1–4），檢查先於計算。
- **密碼**：只能用 `getpass` 在真人終端機輸入兩次；至少 10 個字元；**先做 NFC 再以 UTF-8 編碼**（換電腦或輸入法碼位不同會無法還原）；不存任何地方；介面明說「密碼遺失就無法還原，我們沒有辦法找回」。「不與 PIN 相同」只做提示文字，**不做程式比對**（比對會動到 PIN 失敗計數）。
- **流程**：先把 `VACUUM INTO` 寫到資料夾內的 `tmp/`（不寫到備份磁碟）→ 對暫存檔跑既有的 `inspect_database` → 串流加密到 `*.db.enc.partial` → 從加密檔重新解密並比對明文雜湊 → 通過才改名為 `.db.enc` → 刪除暫存明文（SSD 可能殘留，如實記載，不假裝覆寫有效）。`backup`／`doctor` 啟動時清掉殘留的 `tmp/*` 與 `*.partial`。
- **權限**：`backup --encrypt` 列入 `INTERACTIVE_ONLY`（真人終端機，不需 PIN）；不加密的 `backup` 維持現狀。
- **`restore` 順序**：PIN →（偵測到魔術字）備份密碼 → 直接解密到 `emlek.db.restoring` → 既有檢查 → 使用者輸入「是」。取消或任何失敗都刪除暫存。現行 `run_restore` 與 `restore_backup` 各複製一次，要改成接受已放好的暫存檔，避免兩份明文。回應的 `restored_from` 填 `.enc` 路徑。還原後遷移在 `pre-migration/` 產生的明文副本要寫進文件。
- **錯誤訊息**：檔頭問題（魔術字不符、版本不支援、參數超出範圍）用各自的訊息；只有驗證失敗統一為「密碼錯誤或檔案損毀」。
- **`doctor`**：多顯示最近一次備份是否加密（`meta.last_backup_encrypted`）；還原時 `meta` 會換成備份當時的值，這個欄位也隨之回到當時狀態（既有行為，記載即可）。
- 匯出（`exports/`）與 `pre-migration/` 的副本仍是明文，`doctor`／README 如實標示；本里程碑不加密它們。

### 匯入精簡版（`emlek import`；使用者目前沒有日記，要求「增加太多複雜度就先放著」）
- **做**：`emlek import <檔案或資料夾>`，預設只預覽，加 `--apply` 才寫入；只讀 `.txt`、`.md`，每檔一筆 `original`；單檔 ≤ 1 MiB、一次最多 20,000 檔、單批原文合計 ≤ 512 MiB；其他副檔名列為略過。
- **權限**：新增操作 `import_preview`（任何入口）、`import_apply`（`INTERACTIVE_ONLY`，真人終端機，不需 PIN；預防有 shell 的 AI 把整個資料夾一次匯入）、`import_apply_high`（另加 `PIN_REQUIRED`）。`--include-high`：PIN 通過後再列一次 high 檔名與類別，使用者輸入「是」才寫入（預覽與寫入之間檔案可能被換掉）。
- **不解析 `#標籤`**：匯入寫入一律 `parse_hashtags=False`，不寫 `record_tags`／`tag_events`；現有 `save` 對 original 會以 user 身分建立標籤，若匯入走那條路，外部檔案的文字就能進 AI 開場說明（提示注入）。測試保證匯入後 `record_tags` 數量不變。
- **路徑**：遞迴；略過資料夾本身、`backup_dir`、任何含 `export.jsonl` 的目錄（摘要列為「略過（emLek 自己的檔案）」）；略過所有 reparse point（`st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT`，涵蓋符號連結、junction、雲端預留檔）；每檔只讀一次（最多讀 1 MiB＋1 位元組），雜湊、解碼、掃描用同一份 bytes；單檔 `OSError`（路徑過長、權限、保留名稱）列為失敗，不中止整批。
- **編碼**：只收嚴格 UTF-8（接受 BOM），解碼失敗列為失敗，不替換壞字元。
- **日期**：只取檔名。先把主檔名做 NFKC；數字前後不得緊鄰數字（避免從 `IMG_202601151230` 或電話號碼誤取）；格式 `YYYY-MM-DD`、`YYYYMMDD`、`YYYY年M月D日`；年份限 1900–2100；不合法（如 `20261301`）視為沒有；檔名含兩個以上「不同」的合法日期時留空並於摘要列出；沒有日期就留空，精度為日，不用檔案修改時間。
- **來源與冪等**：`source=import:<相對檔名>`，去除控制字元、長度 ≤ 300，不記錄任何絕對路徑；`file_name` 為相對匯入根目錄的路徑，分隔符統一為 `/` 並做 NFC；`content_hash` ＝ SHA-256（去掉 BOM 的 UTF-8 原文，不轉換換行）。（檔名、雜湊）已匯入則跳過；改檔後視為新內容並警告；內容相同但檔名不同（含同一批內）預設略過並列出，`--allow-duplicates` 才匯入；從不同層級的資料夾匯入會因相對檔名改變而靠雜湊判成重複，文件載明。**`undo` 之後重新匯入會被略過並提示「該記錄已隱藏，請用 `unhide`」**。
- **敏感掃描**：用 `sensitivity` 掃描自己決定等級，不簽發確認碼；high 預設略過並列出（只列檔名與類別）；medium 照匯入並標為 medium，摘要回報數量。
- **寫入**：整批一個交易，錯誤整批回復；匯入期間其他寫入（含 AI 的 `save`）會回 `BUSY`（`busy_timeout` 5 秒），文件載明；提交後執行 `wal_checkpoint(TRUNCATE)`。`import undo <批次>`：以單一 `UPDATE records SET hidden=1 … WHERE id IN (該批)` 在同一交易完成，不逐筆呼叫 `versions.hide`；若該批記錄後來被 `amend` 過，先提示並列出數量。`import list` 列批次。
- **遷移 0007**：`import_batches(id, created_at, file_count, options_json, undone_at)`；`import_log(id, batch_id REFERENCES import_batches, file_name, content_hash, record_id REFERENCES records NULL, purged INTEGER DEFAULT 0, imported_at, UNIQUE(file_name, content_hash))`；索引 `content_hash`、`batch_id`。`import_batches` 不存根目錄的絕對路徑。**匯出**新增 `import_batch`、`import_log` 兩種型別並計入標頭 `counts`，`verify_export` 一併檢查（現況匯出沒有輸出 `import_log`）。日誌只記批次編號與各項數量，不記檔名。
- **延後**（等有真實需求，見 ROADMAP）：`--split-by-heading`、`--encoding`（cp932、big5、gbk）、內文 `#標籤` 解析（需新增 `import` 來源並重建標籤表，且不得進開場說明清單）、內文第一行日期的辨識、段落序號（`chunk_index`）。
- 真實資料規則不變：開發與測試只用合成檔；真實文件須使用者貼出路徑並同意。

**驗收（對應 T21、Q43）**：匯入——重複匯入不重複；壞檔（非 UTF-8、過大、空檔）列為失敗且不影響其他檔；檔名日期解析（含歧義與不合法）；high 略過與 `--include-high` 的閘門；非終端機執行 `--apply` 被拒；整批回復；`undo` 後搜尋找不到、`unhide` 可恢復、重新匯入被略過；匯入後 `record_tags` 與開場標籤清單不變；emLek 自己的資料夾與匯出目錄被略過；junction 被略過；匯出含 `import_log`；三萬檔在單一交易內遠快於逐筆的 27 分鐘。備份加密——往返相同；錯誤密碼被拒；改一位元組／交換兩段／截斷／尾端追加／分段大小欄位被竄改／惡意檔頭參數都被拒；明文剛好 1 MiB 倍數與空資料庫能往返；n=2^18 能成功；暫存明文已刪除；當機後殘留的 `.partial` 與 `tmp` 被清除；`doctor` 顯示加密狀態。

## 匯入既有資料

（M8 只做精簡版，範圍見上方「M8 規格」；以下是完整設想，延後項目等有真實需求再做。）使用者目前沒有日記；舊文件匯入功能隨時可新增，不阻擋其他里程碑。`emlek import <檔案或資料夾>`（CLI）：讀 `.txt`、`.md`，每檔一筆 `original`；檔名或內文開頭的日期用作事件時間，沒有則留空；`#標籤` 解析為 user；`--split-by-heading` 以日期標題切成多筆；`--dry-run` 預覽；`source=import:<檔名>`。冪等以 `import_log` 的（檔名、段落序號、內容雜湊）判斷；檔案被修改後雜湊改變，視為新內容匯入並警告「檔案自上次匯入後已變更」，不覆蓋舊記錄。真實舊日記屬私人資料：開發與測試只用合成檔，真實檔案須使用者貼出路徑並同意才處理。

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

## M10 規格：自動記錄（2026-11-03；使用者已確認草案並指示開始；**已實作，待驗收**；實作決定見 D87）

**目標**：使用者不必每次說「幫我記錄」。使用者事先登記哪些類別 AI 可以直接存，AI 照政策存，存完只附一行小提醒，事後可看、可撤。**不做全部對話錄製**（雜訊淹沒搜尋、會混入 AI 與被注入的內容、密碼與他人資料進庫、`original` 失去「使用者自己要保存的話」的意義；本機 AI 的對話記錄本來就在清除到不了的地方）。部分取代 D04（「只有明確要求才存」）：D04 仍適用於所有未登記的類別（維持建議或詢問）。

### 政策
- 總開關預設**關**（`emlek auto on`，需 PIN）。關閉時行為與現在完全相同。
- 類別表（資料庫，遷移 0009）：`auto_categories(id, name, description, mode, created_at, updated_at)`，`mode` 為 `auto`（直接存）、`ask`（存之前問，等同現在）、`off`。預設五類且全為 `ask`：**生活點滴**（吃飯、去哪）、**思考**（人生、意義等）、**工作**（今天做了什麼）、**研究筆記**、**靈感**。使用者用 `emlek auto set <類別> auto|ask|off` 切換；增刪改都需真人終端機與 PIN；AI 只能用唯讀工具 `auto_policy` 讀取（與 `phrases_list` 同一模式）。
- 專案排除：政策可列「專案路徑或名稱關鍵字」；AI 所在目錄命中就不自動存（只能 AI 端遵守，伺服器無法得知所在目錄，文件如實標示為盡力而為）。
- 開場說明只加一行「自動記錄已開啟，存之前請呼叫 `auto_policy`」，不把政策展開進固定前綴（固定前綴已占輸入量七成以上，D84 後的審查結論）。

### 什麼會自動存、什麼不會
- 只存**使用者自己說的內容**。思考與靈感類存使用者原文（`original`）；太長才由 AI 整理成 `ai_summary` 並標明。同一件事在同一場對話繼續補充＝為原記錄新增版本，不開新記錄；粒度為「一件事一筆」。
- 工作類只存使用者說的摘要，**不存貼進來的程式碼、文件、log**。
- 永遠不自動存（只能走建議或詢問）：①敏感掃描有任何命中；密碼、金鑰、token、卡號等**不需要存**（使用者 2026-11-03 明確表示），自動模式連問都不問，直接不存；②使用者說了「不要記」；③AI 自己的推論或判斷；④從檔案、網頁、工具輸出讀到的內容；⑤未登記的類別。
- 伺服器端閘門：`save` 帶 `source="auto:<類別>"` 時，總開關須開、該類別須為 `auto`、敏感掃描必須沒有命中，否則拒絕並回原因；每日自動存入上限（預設 30 筆）擋住失控或被注入的迴圈。**閘門只驗證登記與掃描，驗證不了「這是不是使用者的意圖」**，所以保留可審可撤。

### 提醒、審閱、撤回
- 自動存完，工具回應附現成字串 `marker`，AI 原樣放在回答最後一行：`◆ emLek｜生活點滴 ✓ r231`（純文字，因為終端機畫不了 SVG；帶編號才能撤）。建議模式則是 `◆ emLek｜要存嗎？〈一行摘要〉`。使用者要求不要提醒時由 AI 省略，不影響存入。
- 審閱：`emlek recent [--auto] [--days N]` 列出最近存入的記錄（標出自動存入、類別、編號）。
- 撤回：使用者說「撤掉 r231」，AI 用既有的隱藏（可恢復）；整批用 `emlek auto hide --since <日期>`（與匯入批次相同的可恢復隱藏，不是清除）。

### 測試與驗收
- T39（核心）：總開關關閉、類別不是 `auto`、掃描命中、超過每日上限時 `source="auto:…"` 的存入被拒；自動存入帶來源標記；`recent --auto` 與批次隱藏可恢復；政策只有真人終端機加 PIN 能改；`auto_policy` 唯讀。
- AI 層題（新增）：該自動存的（「今天去吃拉麵」「我在想活著的意義」）、不該存的（「幫我看這段程式」「密碼是…」「不要記這個」、讀檔案內容）、提醒格式與編號正確。每個 AI（Claude Code、Codex）分開測，穩定的類別才建議使用者開成 `auto`，其餘維持 `ask`。
- 實作前須使用者看過本草案；實作後走一般驗收流程。

## 開發順序（里程碑）

每個里程碑結束須 ruff、mypy、pytest 全綠，更新 PROGRESS 的待驗收與 30 秒驗收清單。測試 ID 見 [TEST_PLAN](TEST_PLAN.md)，題號見 [QUESTIONS](QUESTIONS.md)。**真實資料（含舊日記）只在 M4 與 M6 完成後，且須使用者貼出路徑並同意。**

| 里程碑 | 內容 | 完成標準 |
|---|---|---|
| M1 骨架 | pyproject、`init`、`doctor`（基本）、設定檔、遷移 0001（meta、records、revisions、不可變觸發器）、`save`／`get`（CLI） | 中日英與 emoji 原文往返逐位元組一致；版本不可改；失敗不留半筆；`doctor` 報告環境（T01–T03、T05、T11 子集、T25） |
| M2 搜尋與時間 | FTS5＋LIKE 逐詞路由、NFKC、日期範圍、`order`、`kinds`、分頁與總筆數；題庫系統層骨架與合成資料產生器 | T04、T08–T10；Q01/02/06/07/13/15/20 系統層通過；3.6 萬筆（含真實長度）規模測試有記錄 |
| M3 權限與 MCP | `core/permissions.py`、MCP 完整與 `--read-only`、stdout 只輸出協定；Claude Code 與 Codex CLI 以合成庫實測；平台唯讀沙箱旗標實測；AI 層題庫開始（只報告不卡關） | T06、T07、T16；兩個 AI 都能存與找回合成資料；唯讀清單不含寫入工具 |
| M4 安全網 | `backup`、`restore`（驗證再替換）、`export` v1、`stats`、遷移前自動備份 | T19、T20；還原到乾淨資料夾與原庫逐筆一致 |
| M5 版本、連結、隱藏 | `amend`、`relation`、`superseded_by`、`linked_from`、`hide`／`unhide`、衍生失效（計算值）；**回傳瘦身**：搜尋預設只回片段與日期，結果過多（預設 >50 筆）時先回筆數、按月分布、最早與最晚日期，並固定標註「依關鍵字比對，可能漏掉不同說法」；隱藏與超過權限的記錄不計入；不新增獨立統計工具；全文用 `get`（D56、D57） | T12、T13、T26；Q08–10、Q22–23；題庫報告的每題平均輸入量不高於 M4 基準的 105%（D65）；規模彙整題（QUESTIONS 類別 I，數千筆合成資料）AI 須說明僅檢視部分或先縮小範圍 |
| M6 信任閘門 | 規則掃描、`notice_settings`、`confirm_token`／`notice_token`、`phrase`、`notice`、`sensitivity set` 的真人終端機閘門與 PIN（`pin set·change·reset`）、`phrases_list`；**`get` 補上 `max_sensitivity`**（隱藏檢查已於 M5 完成，目前只有 `search` 有敏感度上限） | T14、T15、T16；Q40–42；閘門限制如實記載 |
| M7 標籤 | M7a：資料表、`set_tags`、`#標籤`、別名、向下展開。M7b：`tags_find` 等查詢工具、facets、`similar_tags`、合併、健檢、熱門標籤 | T17、T18、T29–T31；Q03、Q33–Q36、Q76–Q78、Q80（Q05、Q32 由別題取代，Q79、Q81 延後）；每題平均輸入量 ≤ M6 基準的 110%（規格見 DESIGN_TAGS「M7 規格」） |
| M8 匯入與備份加密 | `import` 精簡版（敏感掃描、批次與還原隱藏；日期標題切段等延後）、備份 `--encrypt` | T21；Q43；錯誤密碼與一位元組竄改被拒 |
| M9 清除 | `purge_preview`（只回中繼資料）、CLI `purge`（預覽、固定句式、PIN、指紋複核、清除、擦除與殘留掃描、`--finish`）、`cleanup`、ID 不重用、匯入防復活、`purge_log` | T22、T23；原始位元組掃描無殘留 |
| M11 發布準備 | 首次發布前的檢查清單，見「發布準備（M11）」 | 清單逐項勾完；版本號進入 0.x 以上的規則生效 |
| M10 | **自動記錄**（已實作，待驗收；見「M10 規格」，D85、D87）；其餘依實際痛點決定（回頭補標籤、分層／主題摘要、觀察清單項目；**M7 後依題庫的花費數據決定**：查無時工具端回「資料裡出現過的相近詞」以減少輪數、規則檔分短版與按需長版；不自建向量資料庫，見 D56） | — |

題庫分系統層（不用 AI、做為卡關依據）與 AI 層（報告用，不卡關），見 BENCHMARK。

## 版本號規則

有四種獨立的版本號，各自只在自己的原因下遞增：

| 版本 | 位置 | 何時遞增 |
|---|---|---|
| 程式版本（SemVer） | `pyproject.toml` 與 `src/emlek/__init__.py`，兩處必須一致 | 發布時才改。0.0.0＝尚未發布；**M6 完成並經使用者驗收後升 0.1.0（已於 2026-11-02 完成，仍未對外發布、未打標籤）**——第一次可放心使用真實資料；之後修錯誤升修訂號，加功能且相容升次版號，不相容升主版號（1.0.0 以前允許不相容但須寫進 CHANGELOG） |
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

**語意搜尋（用意思找）不做**（使用者 2026-11-02 決定，D74；改走搜尋語意修正與標籤回補）。若日後要重議，屬架構大決定，須經使用者同意。重新評估條件：使用一段時間後，以題庫中的模糊問法題（Q04、Q11、Q12、Q16、Q17）加上使用者同意提供的真實問題實測；超過三分之一找不到或找不全才正式提案。模型變強可降低門檻：更大的上下文可由 AI 直接分批讀取日期範圍內的紀錄代替部分搜尋。

**近期加權排序暫不做**：現有日期範圍與排序已夠用。題庫實測不理想時，Agent 須主動提醒使用者評估（與語意搜尋同列觀察清單，見 [BENCHMARK](BENCHMARK.md)）。

## 已知限制

- AI 是否正確判斷「要不要存」、是否真的詢問過，靠使用指示，軟體無法強制。
- 徹底清除不影響既有備份與第三方副本。
- Windows 家用版沒有 BitLocker：資料庫與日誌在磁碟上是明文，電腦被他人取得或實體遺失時資料可被讀取；軟體層不加密資料庫本體，只有備份可加密。
- 只能找回使用者主動保存的內容。
- 搜尋可以接近完整，不能保證完整（標籤沒標、用詞不同都可能漏）；回答須如實說明範圍。
- 能執行命令的 AI 與同一 Windows 帳號下的程式，理論上能直接開資料庫檔；唯讀模式與終端機檢查只擋常見路徑。

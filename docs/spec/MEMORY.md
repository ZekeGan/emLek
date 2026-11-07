# 筆記、版本與工具

現行規格；工作狀態只見 [PROGRESS](../PROGRESS.md)，測試見 [TEST_PLAN](../TEST_PLAN.md)。

## 版本與連結語意

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
| 徹底清除 | 真正移除該記錄所有版本與索引，無法恢復；對話流程見 [AGENT_RULES](../AGENT_RULES.md) §3 |

**衍生摘要失效**是計算值，不另存欄位：記錄的任一來源（經 `links` 遞移）處於隱藏，其衍生的 `ai_summary`、`inference` 即失效，重新產生前不得用於回答；`unhide` 後自動恢復。 MCP的get（含指定舊版本／offset）與search只回必要編號、類型、狀態及content_withheld=true，不交付本文、搜尋片段、source或個別標籤；CLI保留讀取。include_hidden=true不能解除衍生失效隔離，直接讀取隱藏原文的既有權限另見W03。

**徹底清除**：

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
**如實告知**：清除只是從 emLek 的資料庫檔案移除。到不了的地方：SSD／檔案系統殘留、Windows 還原點與陰影複本、防毒隔離區、本機 AI 對話記錄（Claude Code 的 `~/.claude/projects`、Codex 的 session）、PowerShell 歷史（用過 `save --text` 時）、終端機捲動緩衝、既有備份，以及已傳給第三方 AI 的內容。清除報告必須列出這些。

## 工具

未知輸入欄位回 `INVALID_INPUT`。

| 動作 | 說明 |
|---|---|
| `start` | 只有使用者主動輸入 emlek start 才啟動首次條款；同意後只記同意狀態、不保存先前聊天，也不改自動政策總開關 |
| `auto_policy` | 即時同意／總開關／類別／排除專案／24小時用量，MCP另附reference_time與timezone |
| `save` | 新增；參數為內容、kind、來源、事件時間／精度、標籤、關聯版本／relation及sensitivity。MCP回revision_ref、marker及必要後續資訊，不回敏感分類／hint；tags_pending仍已提交，另回tag_update_ref／hint，以set_tags修標籤 |
| `amend` | 為既有記錄新增版本；重新掃描敏感內容並取較高等級 |
| `search` | 見下方「搜尋規則」 |
| `get` | 讀取指定記錄與版本；回傳 `status`、`invalidated`、`superseded_by`、`linked_from`、`links_out`；隱藏的記錄預設回 `NOT_FOUND`（`include_hidden=true` 可讀）；長內容分段（`offset`）；敏感度上限見 [SECURITY](SECURITY.md) |
| `hide`／`unhide` | 隱藏與恢復（冪等；回傳被連帶失效的衍生記錄） |
| `purge_preview` | 唯讀預覽徹底清除的範圍，只回中繼資料不回內容（實際清除只有 CLI `emlek purge`） |
| `phrases_list` | 唯讀取得啟用語句（依 `kind` 分組） |
| `stats` | 唯讀：記錄數（不含隱藏）、隱藏數、版本數、最早與最晚日期、上次備份時間 |
| 標籤工具 | `set_tags`、`tags_find`、`tags_list`（含階層目錄與共現）、`tag_link`、`tag_alias`，見 [DESIGN_TAGS](../DESIGN_TAGS.md)「M7 規格」 |

僅 CLI（不開放 MCP）：`init`、`doctor`、`reindex`、`mcp`（啟動 MCP 伺服器）、`backup`、`restore`、`export`、`import`、`purge`、`pin set·change·reset`、`notice status·enable`、`sensitivity set`、`phrase add·set·remove`，以及標籤的 `tag merge·remove`、`tags audit`。

MCP `instructions` 直接交付必要行為規則，標示規則版本並區分可寫／唯讀；唯讀不收到寫入流程。完整操作細節在 AGENT_RULES，可另載入，但不以檔名引用當成已載入。AI 測試分 MCP-only 與附完整規則兩種配置，記錄實際工具白名單及平台預設上下文限制。工具 schema 列明標籤／連結結構與有限值；MCP save／amend 不提供舊同意碼參數，CLI 相容參數保留。每次工具呼叫各自開關資料庫連線，行程不長期持有；不引入新服務或資料格式（D98）。

**唯讀模式**：`emlek mcp --read-only` 的工具清單只含 `search`、`get`、`phrases_list`、`stats`、`tags_find`、`tags_list`（寫入工具根本不存在，不是被拒絕），供無人看管的排程使用；`max_sensitivity` 預設為 medium。每日簡報見 [DAILY_BRIEFING](../DAILY_BRIEFING.md)。

搜尋行為見 [搜尋規格](SEARCH.md)。

## 自動記錄

**目標**：使用者主動 `emlek start` 首次同意後，正常聊天，在背景依政策保存往後的個人敘述，成功後附實際筆記編號，事後可看、可撤（D97）。一般問題不詢問保存；不做全部對話錄製。未登記或不確定的內容略過，不主動提議儲存。

### 政策
- 新庫自動政策預設準備好，但尚未 start 同意啟用前不得自動寫入。`emlek auto on|off` 仍需 PIN，start 不改使用者的政策或關閉狀態；關閉後不自動存、不逐筆詢問。
- 類別表（遷移 0009）：`auto_categories(id, name, description, mode, created_at, updated_at)`。預設五類全為 `auto`：**生活點滴**、**思考**、**工作**（使用者摘要）、**研究筆記**、**靈感**。`ask` 保留命令相容性，但不自動存也不逐筆詢問；`off` 不自動存。`emlek auto set <類別> auto|ask|off` 及增刪改仍需真人終端機與 PIN，AI 只能讀 `auto_policy`。
- 遷移 0010：舊庫的總開關與明確 `off` 類別不變，舊 `ask` 類別轉為 `auto`。舊 medium 同意不足以涵蓋所有個人資訊，故重開全域提醒並撤銷未用 notice 碼；歷史內文不改寫，沿用既有備份遷移機制。
- 專案排除：政策可列「專案路徑或名稱關鍵字」；AI 所在目錄命中就不自動存（只能 AI 端遵守，伺服器無法得知所在目錄，文件如實標示為盡力而為）。
- 開場只列已開啟的 auto 類別名稱與同意初始快照；每段對話首次遇到可保存個人內容先讀 `auto_policy` 的即時同意／總開關／類別／排除專案／上限，之後狀態不明或被拒再查。這是政策中繼資料，不讀筆記、不啟用或保存。開場與政策回應提供帶時區的 reference_time 及庫 timezone；模糊相對日期無法確定月份就未知，不一律猜上月。start 不改總開關，關閉時如實回「已完成同意；自動記錄目前關閉」（D98）。

### 什麼會自動存、什麼不會
- 只存**使用者自己說的內容**。思考與靈感類存使用者原文（`original`）；太長才由 AI 整理成 `ai_summary` 並標明。同一件事在同一場對話繼續補充＝為原記錄新增版本，不開新記錄；粒度為「一件事一筆」。
- 工作類只存使用者說的摘要，**不存貼進來的程式碼、文件、log**。
- 排除：最高風險（密碼、金鑰、token、卡號等）在所有寫入入口永不儲存；「不要記」、AI 推論、檔案／網頁／工具輸出、未登記類別、一般問題均不自動存，也不詢問是否保存。電話等 medium 個資屬首次全域同意範圍，不另問。
- 伺服器端閘門：自動來源須總開關開、類別為 `auto`、`kind` 為 `original`／`ai_summary`；所有 MCP 寫入仍要首次同意，省略自動來源不能繞過。滾動 24 小時上限預設 30 筆。**閘門驗證不了使用者意圖**，所以仍需 AI 遵守排除規則與事後可審可撤。

### 提醒、審閱、撤回
- AI 存入前不發操作進度訊息；`save`／`amend` 成功後在正常回答末尾另附原樣 `marker`：`◆ emLek｜r231.✔️`，編號為實際記錄而非版本。分享想法／感受／經歷時正常接話，不強制每次追問；只有單純交代資料、無需其他回應時才只回 marker。失敗不顯示成功符號。回想同樣不發搜尋前進度訊息。
- 審閱：`emlek recent [--auto] [--days N]` 列出最近存入的記錄（標出自動存入、類別、編號）。
- 撤回：使用者說「撤掉 r231」，AI 用既有的隱藏（可恢復）；整批用 `emlek auto hide --since <日期>`（與匯入批次相同的可恢復隱藏，不是清除）。

## 原文來源限制

通用MCP的save／amend只接收模型填入的body，沒有宿主可信的使用者訊息可比對；資料庫保證收到後不覆寫，無法證明模型傳入前沒有改字。AI仍須逐字複製，不得自動把改寫標成original或改存摘要規避檢查；改變字詞、數字或意思仍阻擋；無語意影響的排版差異不單獨判失敗，保存時不主動正規化。使用者核定保留通用MCP，暫不新增宿主專用整合；未解驗收見PROGRESS。

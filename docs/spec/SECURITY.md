# 同意、敏感資訊與權限

現行規格；工作狀態只見 [PROGRESS](../PROGRESS.md)，測試見 [TEST_PLAN](../TEST_PLAN.md)。

## 自訂語句

使用者以 CLI 增刪改查，存在資料庫隨備份搬家。預設：`save`＝記住、幫我記一下、存起來、記憶；`purge`＝完全刪除；`exclude`＝上週記住了文法（不算指令的範例）。

| 命令 | 作用 |
|---|---|
| `emlek phrase list [kind]` | 查 |
| `emlek phrase add <kind> "<語句>"` | 增 |
| `emlek phrase set <id> "<新語句>"` | 改、啟用或停用 |
| `emlek phrase remove <id>` | 刪 |

- AI 只能用 MCP 唯讀工具 `phrases_list`。語句只是 AI 的判斷依據，不是機械比對。沒有啟用的 `purge` 語句時，徹底清除關閉。
- **需要真人終端機與 PIN 的 CLI 命令**：`phrase add·set·remove`（所有類別）、`notice enable`、`restore`、`tag merge·remove`、`sensitivity set`、`purge`、`pin change·reset`，以及 M10 的自動政策修改。檢查兩層：(1) 標準輸入、輸出、錯誤輸出都必須是終端機，否則回 `NOT_PERMITTED`（結束碼 3）；(2) 以 `getpass` 從主控台輸入 PIN，**絕不接受參數、環境變數或標準輸入傳入**。
- **PIN**：細節見「信任閘門規格（M6）」。**PIN 不得告訴任何 AI**；若貼在對話，須立即 `emlek pin change`。
- 限制（已實測）：Claude Code 的 PowerShell 工具回報標準輸入是終端機、標準輸出不是，所以三條串流都要驗。PIN 擋得住只透過 CLI 操作的 AI；能開偽終端機並讀到使用者輸入、或直接開資料庫檔改資料的 AI 仍能繞過。這是主要防線而非絕對隔離。

## 敏感內容提示

存入時依危險度提示，避免使用者在不知情下把高風險資料留在明文資料庫（備份與匯出也會帶出）。固定句式在 [AGENT_RULES](../AGENT_RULES.md) §1。

| 等級 | 例子 | 存入時 |
|---|---|---|
| high（最高） | 密碼、API 金鑰與 token、私鑰、信用卡號、一次性復原碼 | 永不新增保存，不詢問是否儲存 |
| medium（中） | 電話、住址、身分證或護照號碼、生日 | 與一般個人敘述共用首次全域同意；之後不再問 |
| none | 其他 | 個人敘述仍需首次全域同意；一般問題不存不問 |

- 判斷：AI 依語意判斷；核心另以規則掃描當補強（私鑰區塊、常見金鑰格式、JWT、卡號 Luhn 檢查、電話與證號格式），回傳 `sensitivity_hint`，取兩者較高者。規則掃描不可能完整。
- high：`save`／`amend` 回 `NOT_PERMITTED`，不發碼；使用者說「是」也不放行。
- 首次全域同意只由 start 觸發：`NEEDS_CONFIRMATION`（needs_notice，綁 start 與固定條款的 notice_token），同意後重送 start，只記同意不存聊天。`emlek notice status` 查看、`emlek notice enable personal` 重設未啟用（真人終端機、PIN），之後仍須主動 start。
- `amend` 同樣重掃並取較高等級，高風險直接拒絕；AI 傳入的 `sensitivity` 只能調高，調低只能用 `emlek sensitivity set r<id> <level>`。
- `import` 也掃描：high 一律略過，`--include-high` 不能放行；medium 按使用者批次命令匯入並標記。
- 記錄的 `sensitivity` 等於各版本最高者；`search`／`get` 回傳該欄位。`emlek export --exclude-high` 可排除 high 記錄。
- 限制：AI 若自行帶 token 而未真正詢問，核心無法分辨，與清除流程同一信任邊界；以題庫與審查驗證各 AI 平台的遵守程度。

## 信任閘門

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

`confirm_tokens(token_hash, kind, content_hash, created_at, expires_at, used_at)`。確認碼為 128 位元隨機值，只存 SHA-256；啟用碼的 `content_hash`＝SHA-256(start 操作＋空記錄編號＋固定條款)，各段以換行分隔；10 分鐘過期；每次簽發時清掉一天前的舊列。

1. 有效等級 high：所有 `save`／`amend`／匯入入口直接拒絕，不發確認碼；明確要求、舊確認碼與 PIN 均不能放行。既有歷史與備份不自動刪除。
2. 只有使用者在對話輸入 `emlek start` 才呼叫 MCP `start`，首次回 `NEEDS_CONFIRMATION`，附 `needs_notice`、`notice_token`、固定條款。下一回合答「同意」或「是」才帶碼重送 start；只記同意，不寫筆記、不補存先前聊天。跨聊天／AI 沿用本機庫同意，已同意的重複 start 不再問。未啟用時正常聊天，不主動邀請啟用；所有 MCP save／amend、自動來源及 medium 單筆寫入只回 `NOT_PERMITTED`／`not_started`，不發碼或條款。一般 CLI 明確單筆／批次命令保留直接執行語意，不新增 shell start 子命令。
3. start 碼驗證存在、種類、單次使用、10 分鐘期限及 start 操作／固定條款雜湊；用碼與同意設定在同一交易，失敗回滾。舊 save 碼不能啟用、start 碼不能代替 save。失敗統一 `TOKEN_INVALID`，碼不入日誌。`notice enable personal`（PIN；medium 舊別名）重設未啟用並撤銷未用 notice 碼，下次仍只在主動 start 時顯示條款。寫入交易內複核重設狀態。

### 讀取端的敏感度上限

`get` 的 `max_sensitivity`（唯讀 MCP 預設 medium、其餘 MCP 預設 high、命令列預設 high）；超過上限回 `NOT_PERMITTED`（不回內文）。`get` 的 `linked_from`、`superseded_by`，以及 `search` 的 `summary`，一律略過超過上限的記錄，不洩漏其存在或筆數。



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

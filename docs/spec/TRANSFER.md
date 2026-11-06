# 匯入、備份、還原與匯出

現行規格；工作狀態只見 [PROGRESS](../PROGRESS.md)，測試見 [TEST_PLAN](../TEST_PLAN.md)。

## 加密與匯入

**範圍**：①備份加密（`backup --encrypt`、`restore` 讀加密檔）；②匯入精簡版（`emlek import`）。都只在命令列，不開放 MCP。

匯入使用 service 的既有底層插入函式，在單一外層交易內完成，不經 AI 同意碼。

### 備份加密檔格式（版本 1，副檔名 `.db.enc`）
- **檔頭**（固定 40 位元組）：魔術字 `EMLKBK01`（8）｜KDF 代碼 1（1）｜scrypt log2(n)、r、p（各 1）｜保留 0（3）｜salt（16）｜nonce 前綴（8，隨機）｜分段大小 log2（1）。檔頭整段是每一段的附加驗證資料（AAD）。
- **分段**：AES-256-GCM，nonce＝前綴（8）＋段序號（4，大端）；AAD＝檔頭＋1 位元組「最後一段」旗標。讀者只接受分段大小 log2 = 20（1 MiB），其他拒絕。寫入者預讀一段判斷是否為最後一段：明文剛好是整數倍時，最後一段就是那個滿段（**不補空段**）；只有空內容才寫一個 0 位元組的段。讀者遇到非最後段卻短於 1 MiB＋16、或任何段短於 16 位元組、或段序號達 2^32，一律拒絕。改任一位元組、交換兩段、截斷（含剛好砍在段落邊界）、尾端追加，都會驗證失敗。
- **金鑰**：`hashlib.scrypt`，預設 n=2^17、r=8、p=1。`maxmem = 128·r·n + 16 MiB`，依檔頭的值計算，**不共用 PIN 的 `KDF_MAXMEM`**（128 MiB 對 n=2^17 不夠，會 `ValueError`）。解密時檔頭參數必須在範圍內才執行（log2(n) 14–18、r=8、p 1–4），檢查先於計算。
- **密碼**：只能用 `getpass` 在真人終端機輸入兩次；至少 10 個字元；**先做 NFC 再以 UTF-8 編碼**（換電腦或輸入法碼位不同會無法還原）；不存任何地方；介面明說「密碼遺失就無法還原，我們沒有辦法找回」。「不與 PIN 相同」只做提示文字，**不做程式比對**（比對會動到 PIN 失敗計數）。
- **流程**：先把 `VACUUM INTO` 寫到資料夾內的 `tmp/`（不寫到備份磁碟）→ 對暫存檔跑既有的 `inspect_database` → 串流加密到 `*.db.enc.partial` → 從加密檔重新解密並比對明文雜湊 → 通過才改名為 `.db.enc` → 刪除暫存明文（SSD 可能殘留，如實記載，不假裝覆寫有效）。`backup`／`doctor` 啟動時清掉殘留的 `tmp/*` 與 `*.partial`。
- **權限**：`backup --encrypt` 列入 `INTERACTIVE_ONLY`（真人終端機，不需 PIN）；不加密的 `backup` 維持現狀。
- **`restore` 順序**：PIN →（偵測到魔術字）備份密碼 → 直接解密到 `emlek.db.restoring` → 既有檢查 → 使用者輸入「是」。取消或任何失敗都刪除暫存。還原共用已放好的暫存檔，避免兩份明文。回應的 `restored_from` 填 `.enc` 路徑。還原後遷移在 `pre-migration/` 產生的明文副本要寫進文件。
- **錯誤訊息**：檔頭問題（魔術字不符、版本不支援、參數超出範圍）用各自的訊息；只有驗證失敗統一為「密碼錯誤或檔案損毀」。
- **`doctor`**：多顯示最近一次備份是否加密（`meta.last_backup_encrypted`）；還原時 `meta` 會換成備份當時的值，這個欄位也隨之回到當時狀態（既有行為，記載即可）。
- 匯出（`exports/`）與 `pre-migration/` 的副本仍是明文，`doctor`／README 如實標示；這些副本不加密。

### 匯入
- **做**：`emlek import <檔案或資料夾>`，預設只預覽，加 `--apply` 才寫入；只讀 `.txt`、`.md`，每檔一筆 `original`；單檔 ≤ 1 MiB、一次最多 20,000 檔、單批原文合計 ≤ 512 MiB；其他副檔名列為略過。
- **權限**：`import_preview`（任何入口）、`import_apply`（`INTERACTIVE_ONLY`，真人終端機，不需 PIN）。high 永遠略過，`--include-high` 僅保留參數相容性，PIN 不能放行；套用時重新掃描待寫入內文，防止舊或偽造計畫繞過。
- **不解析 `#標籤`**：匯入寫入一律 `parse_hashtags=False`，不寫 `record_tags`／`tag_events`；現有 `save` 對 original 會以 user 身分建立標籤，若匯入走那條路，外部檔案的文字就能進 AI 開場說明（提示注入）。測試保證匯入後 `record_tags` 數量不變。
- **路徑**：遞迴；略過資料夾本身、`backup_dir`、任何含 `export.jsonl` 的目錄（摘要列為「略過（emLek 自己的檔案）」）；略過所有 reparse point（`st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT`，涵蓋符號連結、junction、雲端預留檔）；每檔只讀一次（最多讀 1 MiB＋1 位元組），雜湊、解碼、掃描用同一份 bytes；單檔 `OSError`（路徑過長、權限、保留名稱）列為失敗，不中止整批。
- **編碼**：只收嚴格 UTF-8（接受 BOM），解碼失敗列為失敗，不替換壞字元。
- **日期**：只取檔名。先把主檔名做 NFKC；數字前後不得緊鄰數字（避免從 `IMG_202601151230` 或電話號碼誤取）；格式 `YYYY-MM-DD`、`YYYYMMDD`、`YYYY年M月D日`；年份限 1900–2100；不合法（如 `20261301`）視為沒有；檔名含兩個以上「不同」的合法日期時留空並於摘要列出；沒有日期就留空，精度為日，不用檔案修改時間。
- **來源與冪等**：`source=import:<相對檔名>`，去除控制字元、長度 ≤ 300，不記錄任何絕對路徑；`file_name` 為相對匯入根目錄的路徑，分隔符統一為 `/` 並做 NFC；`content_hash` ＝ SHA-256（去掉 BOM 的 UTF-8 原文，不轉換換行）。（檔名、雜湊）已匯入則跳過；改檔後視為新內容並警告；內容相同但檔名不同（含同一批內）預設略過並列出，`--allow-duplicates` 才匯入；從不同層級的資料夾匯入會因相對檔名改變而靠雜湊判成重複，文件載明。**`undo` 之後重新匯入會被略過並提示「該記錄已隱藏，請用 `unhide`」**。
- **敏感掃描**：用 `sensitivity` 掃描自己決定等級，不簽發確認碼；high 一律略過並列出（只列檔名與類別）；medium 照使用者明確執行的批次命令匯入並標為 medium，摘要回報數量。
- **寫入**：整批一個交易，錯誤整批回復；匯入期間其他寫入（含 AI 的 `save`）會回 `BUSY`（`busy_timeout` 5 秒），文件載明；提交後執行 `wal_checkpoint(TRUNCATE)`。`emlek import --undo <批次>`：以單一 `UPDATE records SET hidden=1 … WHERE id IN (該批)` 在同一交易完成，不逐筆呼叫 `versions.hide`；若該批記錄後來被 `amend` 過，先提示並列出數量。`emlek import --list` 列批次。
- **遷移 0007**：`import_batches(id, created_at, file_count, options_json, undone_at)`；`import_log(id, batch_id REFERENCES import_batches, file_name, content_hash, record_id REFERENCES records NULL, purged INTEGER DEFAULT 0, imported_at, UNIQUE(file_name, content_hash))`；索引 `content_hash`、`batch_id`。`import_batches` 不存根目錄的絕對路徑。**匯出**新增 `import_batch`、`import_log` 兩種型別並計入標頭 `counts`，`verify_export` 一併檢查。日誌只記批次編號與各項數量，不記檔名。
- 真實資料規則不變：開發與測試只用合成檔；真實文件須使用者貼出路徑並同意。


## 備份與搬家

1. 資料在一個資料夾，主體是一個 `.db`（含搜尋索引）。備份放在 `config.toml` 的 `backup_dir`：`init` 時預設選與資料庫不同的磁碟（有第二顆磁碟用其上的 `emlek-backups`，否則在使用者文件夾下），不與資料庫放同一處。
2. `emlek backup`：用 SQLite 一致性備份（`VACUUM INTO`）產生帶日期的單一檔，不直接複製使用中的檔案。可選 `--encrypt` 密碼加密，須提醒密碼遺失無法還原。遷移前自動備份一份。備份檔以時間命名（`emlek-<時間>.db`），建立後立刻以唯讀方式檢查完整性與筆數，並把時間記進 `meta`（`doctor` 與 `stats` 會顯示，超過 14 天或從未備份會警告）。備份資料夾不得在資料夾裡面；與資料在同一顆磁碟時會提醒。
3. `emlek export`：完整 JSONL（含所有版本與關係）＋供閱讀的 Markdown。每次匯出建立新的帶時間資料夾，不覆蓋；失敗時整個資料夾移除，不留半成品。`--exclude-high` 排除最高敏感度記錄；隱藏的記錄照匯出並帶 `hidden` 旗標。
4. `emlek restore <備份檔>`（必須在你自己的終端機執行：標準輸入、輸出、錯誤輸出都是終端機，並再問一次「是」；需 PIN）：先以唯讀方式檢查備份（完整性、必要資料表、結構版本不得比程式新），複製到暫存檔、必要時升級結構並再驗證筆數，最後才把目前資料庫（連同 WAL 檔）改名保留為 `emlek.db.before-restore-<時間>` 再換上。資料庫正被其他程式（例如 MCP 伺服器）使用時回 `BUSY` 並維持原狀。
5. 換設備：舊機 backup → 新機安裝 → `init` → restore → 重新指向 MCP 設定。實測 36000 筆（資料庫約 523 MB）：備份約 9 秒、還原約 22 秒、匯出約 37 秒（JSONL 約 147 MB 加 36000 個 Markdown 檔）。

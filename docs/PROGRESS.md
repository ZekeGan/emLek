# 進度

最後更新：2026-11-03。只記實際狀態；未執行的不標通過。

## 現況

- 模式：**MODE B；M1–M9 已完成並經使用者驗收，程式版本 0.1.0（尚未對外發布、未打標籤）**。M7 標籤、M8 匯入與備份加密（D80、D81）、M9 徹底清除（D82、D83）已於 2026-11-03 驗收通過（M9 實測 stats 文字版未顯示清除次數，JSON 有，列為小缺口）。
- 已有 `src/emlek`：`init`、`doctor`、`save`、`amend`、`hide`／`unhide`、`get`、`search`、`reindex`、`mcp`、`backup`、`restore`、`export`、`stats`、`pin`、`phrase`、`notice`、`sensitivity`、`tag`、`tags`、`import`、`purge`、`cleanup`；結構遷移 0001–0008；683 項測試（快速）加 1 項 36000 筆規模測試；只有合成測試資料。
- Git：`main`，遠端 `origin`（公開的 GitHub 倉庫）；是否同步以 `git status` 為準。敏感詞檢查掛在本機 pre-commit 與 pre-push，清單內容只存在本機、不寫進文件。
- 環境（已驗證）：Python 3.14.10（uv 0.13.6）、SQLite 3.53.1；套件由 `uv.lock` 鎖定；Claude Code 2.1.316；Codex CLI 0.166.0 已安裝並登入，但使用者的 ChatGPT 用量已用完，**2026-11-04 22:58 後才能測**。
- 未驗證：Codex 端的 MCP 連線與沙箱；真實資料效能。
- 搜尋（2026-11-02 起）：同組詞全部出現、大寫 `OR` 表示任一；多詞零結果回 `term_hits`；`untagged` 篩選；`emlek tags backfill`（預覽、套用、復原）。語意搜尋由使用者決定不做（D74）。
- 已知限制：備份可用 `--encrypt` 加密，但匯出與遷移前副本仍是明文；資料庫本體明文（Windows 家用版無 BitLocker，D44）；**真實資料（含舊日記）的條件已滿足（M4、M6 完成），仍只用使用者貼出的路徑**。

## 使用者已決定

清除最終確認只在使用者自己的終端機（M9，MCP 只有預覽）；備份放不同磁碟（預設 `D:\emlek-backups`）；手機與遠端使用等 AGENT 技術成熟後再評估，目前一律本機；題庫其餘類別對應功能完成時補（D55）；降低提問額度消耗列入計畫（D56）；熱門標籤名稱放進 AI 開場說明（D71）；M5 回傳量標準 ≤ M4 的 105%（D65）；規則：新需求或新功能改動檔案後同批優化文件，不必先問（D60）。

## 題庫現況

AI 層核心與擴充 51 題（含 M7 新增 9 題標籤題）、語氣集 48 題、規模題 Q75、同意對話 5 段、寫入探針 10 個（清單見 [QUESTIONS](QUESTIONS.md)）；系統層 42 題全 5 分。haiku 每題約 $0.002。評分另報「調整分」（忽略答案中標示為排除或其他的記錄，不低於原始分，D77）；舊結果檔尚未補算。結果與歷次比較見 [BENCHMARK](BENCHMARK.md)，各里程碑驗收紀錄見 [HISTORY](HISTORY.md)。

## M7 待驗收

**做了什麼**：標籤（階層、別名、`#標籤`、向下展開、`match`、facets、覆蓋率 `tag_coverage`、近似名稱不新建而回 `tags_pending`）、`tags_find`／`tags_list`／`set_tags`／`tag_link`／`tag_alias`、命令列 `tag`／`tags`、匯出含標籤、`doctor` 顯示標籤狀態、熱門標籤名稱進 AI 開場說明。規格見 [DESIGN_TAGS](DESIGN_TAGS.md)。

**實測**：502 項測試全過；36000 筆規模下標籤搜尋 0.65–0.87 秒；AI 層共同 42 題每題輸入量為 M6 的 **108.4%**（標準 ≤110%，達標；加上 D75 的搜尋修正後為 110.8%，略超過）；新標籤題 9 題中 6 題 5 分，Q36、Q78、Q80 答案經人工閱讀正確，但被集合評分扣到 1–2 分；寫入探針 10/10、同意對話 5/5；AI 工具執行 `tag merge`／`remove` 被拒。過程中修掉兩個自己造成的缺陷：測試工具清單漏了新工具（第一次結果作廢）、帶不存在的標籤名會讓文字搜尋歸零。

**曾經的退步已查明**：M7 的 Q46–Q49 失分來自「多詞必須全部出現」的搜尋語意，不是標籤；已用 OR 與零結果提示修正（D75，細節見 [BENCHMARK](BENCHMARK.md)）。

**驗收清單**（用拋棄式資料夾 `C:\temp\emlek-m7`；`$e = ".\.venv\Scripts\emlek.exe"; $d = "C:\temp\emlek-m7"`）：
1. `& $e --data-dir $d init`（輸入兩次 PIN）；`& $e --data-dir $d save --text "今天在京都喝抹茶 #旅行" --tag 京都 --tag 抹茶` → 顯示「標籤：旅行、京都、抹茶」。
2. `save --text "日本のメモ" --tag 日本`；`tag link 日本 京都`；`search --tag 日本` → 找到 2 筆，並顯示「標籤展開：日本、京都」與「標籤覆蓋」。
3. `tag alias kyoto 京都`；`search --tag kyoto` → 找到「京都」那筆。
4. `save --text "大阪の話" --tag 京都市` → 顯示「未新增標籤「京都市」：與既有標籤相近（京都）」；加 `--allow-new 京都市` 才會新增。
5. `search 京都 --tag 沒有這個標籤` → 仍找到京都的記錄，並提示找不到該標籤。
6. `tags find 抹`、`tags list`、`tags audit`、`doctor`（看到 `tags` 一行）。
7. `tag merge 京都市 京都`（要先有「京都市」標籤）→ 要輸入 PIN 再回答「是」；之後 `search --tag 京都市` 仍找得到（舊名成為別名）。
8. 在 Claude Code 請我執行 `emlek tag merge 京都 抹茶`，會被拒。
9. 清理：`Remove-Item -Recurse -Force $d`。

## M8 待驗收

**做了什麼**：①`backup --encrypt`（密碼加密、立刻解密比對、不留明文暫存）與 `restore` 讀加密檔；②`emlek import <檔案或資料夾>`（只讀 .txt／.md、每檔一筆、檔名日期、預設只預覽、`--apply` 才寫入且必須在真人終端機、整批一個交易、重複與變更偵測、含最高風險內容預設略過、批次 `--list`／`--undo`）；③遷移 0007、匯出含匯入紀錄。延後的項目見 [ROADMAP](ROADMAP.md)。

**實測**：634 項測試全過（含 1500 檔單次匯入、各種竄改的加密檔）；命令列煙霧測試確認「非終端機不能 `--apply`、不能 `backup --encrypt`」。尚未在真實終端機走過互動流程（請你驗收）；沒有用任何真實檔案。

**驗收清單**（用拋棄式資料夾；PowerShell；`$e = ".\.venv\Scripts\emlek.exe"; $d = "C:\temp\emlek-m8"`）：
1. 建樣本：`New-Item -ItemType Directory -Force C:\temp\emlek-m8-notes | Out-Null; Set-Content -Encoding utf8 C:\temp\emlek-m8-notes\2026-10-01.txt "京都で抹茶を飲んだ"; Set-Content -Encoding utf8 C:\temp\emlek-m8-notes\memo.md "日付のないメモ"`；`& $e --data-dir $d init`（輸入兩次 PIN）。
2. 預覽：`& $e --data-dir $d import C:\temp\emlek-m8-notes` → 顯示「可匯入 2 個檔案」「這只是預覽」；`& $e --data-dir $d search 京都` → 找不到（沒寫入）。
3. 寫入：`& $e --data-dir $d import C:\temp\emlek-m8-notes --apply` → 顯示摘要，輸入「是」→ 已匯入 2 筆、批次編號 1；`search 京都` 找到，事件日期 2026-10-01。
4. 重跑：再執行一次第 3 步 → 顯示「已匯入過 2」「沒有需要匯入的檔案」。
5. 批次：`& $e --data-dir $d import --list` 看到批次 1。
6. 還原：`& $e --data-dir $d import --undo 1`，輸入「是」→ 隱藏 2 筆；`search 京都` 找不到；`& $e --data-dir $d unhide r1` 後找得到。
7. 加密備份：`& $e --data-dir $d backup --encrypt --to C:\temp\emlek-m8-bk`，兩次輸入至少 10 個字元的密碼 → 顯示「已加密，並已解密比對確認可還原」；檔名結尾是 `.db.enc`；`& $e --data-dir $d doctor` 的備份行顯示（已加密）。
8. 還原加密備份（驗證密碼）：`& $e --data-dir $d restore C:\temp\emlek-m8-bk\<檔名>.db.enc`，先輸入 PIN，再輸入**錯誤**密碼 → 被拒；重做並輸入正確密碼，輸入「是」→ 還原成功。
9. AI 不能代跑：在 Claude Code 請我執行 `emlek import C:\temp\emlek-m8-notes --apply`，會被拒（要在真人終端機）。
10. 清理：`Remove-Item -Recurse -Force $d, C:\temp\emlek-m8-notes, C:\temp\emlek-m8-bk`。

## M9 驗收紀錄（2026-11-03 通過）

**做了什麼**：`emlek purge r<編號>…`（一次最多 20 筆；真人終端機、PIN、預覽與固定問句、答「是」才執行；連帶移除 AI 摘要與只因它而存在的標籤；預覽後內容有變動就中止）；刪除後做檢查點、VACUUM 與原始位元組比對，沒擦乾淨會標示未完成，`emlek purge --finish` 補做，`doctor` 會警告；記錄編號不再重用；匯入不會讓已清除的內容復活；`restore` 遇到早於清除的備份會警告；`emlek cleanup` 清理暫存副本；MCP `purge_preview` 只回編號與筆數。

**實測**：全部 683 項測試通過（新增 T22、T23 共 49 項，含原始位元組比對、有讀取者時的未完成與補做、當機後補做、預覽後被改、匯入防復活、掃描不洩漏文字）；命令列煙霧測試確認非終端機一律被拒。尚未在真實終端機走過互動流程（請你驗收）；沒有用任何真實檔案。已知限制：全文索引（trigram）的殘留無法用位元組比對驗證，靠整理資料庫清除；`--finish` 無法再比對只能標為「未驗證」。

**驗收清單**（用拋棄式資料夾；PowerShell；`$e = ".\.venv\Scripts\emlek.exe"; $d = "C:\temp\emlek-m9"`；先確認背景沒有殘留的 emlek 行程）：
1. 建資料庫與樣本：`& $e --data-dir $d init`（設 PIN）；`& $e --data-dir $d save --text "清除測試 PURGE-ALPHA 京都抹茶"`、`& $e --data-dir $d save --text "另一筆保留 KEEP-BRAVO"`。
2. 預覽不刪：`& $e --data-dir $d purge r1`，輸入 PIN → 看到內容摘錄與問句；輸入「否」→ 顯示「已取消」；`search ALPHA` 仍找得到。
3. 真的清除：再執行一次，PIN、輸入「是」→ 顯示「已從資料庫中完全刪除 1 筆記錄」「用原始位元組比對，找不到被清除的內容」與「到不了的地方」清單；`search ALPHA` 找不到；`search KEEP` 仍在。
4. 編號不重用：`& $e --data-dir $d save --text "新的一筆"` → 編號是 r3，不是 r1。
5. 備份後再清除，檢查還原警告與殘留報告：`backup --to C:\temp\emlek-m9-bk`；再存一筆並清除它；`restore` 那份備份 → 顯示「做過 1 次徹底清除，還原會讓已清除的資料回來」，先輸入「否」取消。
6. `doctor` 的 purge 那行顯示「已清除 N 次，沒有未完成的擦除」；`stats` 顯示清除次數。
7. 清理暫存：`& $e --data-dir $d cleanup` 預覽；`cleanup --apply`（PIN）→ 若無較新備份會拒絕，先 `backup` 再重做。
8. AI 不能代跑：在 Claude Code 請我執行 `emlek purge r2`，會被拒（要在真人終端機）。
9. 清理：`Remove-Item -Recurse -Force $d, C:\temp\emlek-m9-bk`。

## 下一步

1. **使用者驗收 M7**（上方 9 步清單；2026-11-02 之後的搜尋與標籤清單改動 D75–D77 在本機，是否已推送以 `git status` 為準）。
2. **Opus 審查（2026-11-02）已完成並逐項查證**，結論與下一步：
   - 已做（文件與測試工具，不改產品行為）：移除公開文件中的凍結題細節、更正過度的說法、清過期敘述、測試執行器改記錄每次工具呼叫的參數並允許 `stats`。
   - **已證實**：多詞查詢是 Q46–Q49 失分的主因（見 BENCHMARK）。
   - 產品行為待決事項已於 2026-11-02 全部決定（D77）。
   - 搜尋效率與 token 再瘦身：等使用者決定是否請 Opus 做一輪限定範圍的審查（搜尋回傳格式、工具描述、規則；附最耗 token 題的呼叫紀錄），再以實測驗證。
   - 待做（不需決定）：補一組「只有開場說明、沒有完整規則」的 AI 情境、每題 3 次的正式驗收統計、T29 補無標點的命令句、M8 設計要點已寫進 DESIGN。
3. M10 依數據決定 → M11 發布準備（見 DESIGN）。

## 近期決定與提醒

**D78 搜尋效率改動已量測（2026-11-03）**：AI 層全題庫共同 59 題，被拒絕的搜尋 40→0、輪數 4.78→3.90、每題輸入量 −18%、平均分 4.07→4.37（單次測量，含 D75 起的累計效果）。D79（精簡結果、`matching_tags`、標籤清單 50）已用每題 3 次正式比較：品質無顯著差異，輪數 −6%、`tags_find` 呼叫少一半，保留。尚未做的 Opus 建議：英文詞形容錯、類別別名表（風險較高，需先有沒見過的題）、固定提示文字去重。

**已決定並完成（2026-11-02，D77）**：搜尋 OR 與零結果提示（D75）；`NEEDS_CONFIRMATION` 附上固定問句 `ask_user`；熱門標籤清單只列使用者本人建立或使用過的標籤；PIN 最短長度維持 6 個字元（暫定，提醒：同帳號的程式能讀到 `security.json` 離線猜，建議使用長密語）；評分另報「調整分」；MCP 搜尋單次回應上限約 12000 字元。

- 凍結驗收集：已收到 30 句真實問法，存在 `private/frozen-questions.md`（**被 .gitignore 排除，不進公開倉庫**，題目內容與類型也不寫進公開文件，以免變成「看過考題再調校」）。要觀察別名與音譯的實際效果，需先為其中幾題建合成資料，你尚未要求。凍結集只用來驗收，不用來調規則。語氣集（`tests/benchmark/personas.py`，六種人物 × 8 題）是合成的、可調校，與凍結集分開計分。
- **仍偏弱的題（依你同意的門檻提醒）**：Q49（衣服鞋子，遠義詞）在 M6、M7 都是 0 分，搜尋語意修正後 1–3 分，仍是最弱的一題；Q60（相近人名）修正後 4 分。模糊題剩 Q83、Q86、Q89 是字面比對的上限，靠標籤與別名覆蓋。
- AI 層「不理想」門檻（使用者同意）：任一非模糊題單次 0 分，或同一里程碑 AI 層平均低於 4 分，就提醒使用者評估觀察清單；單題牌價超過 $0.15 也提醒。

## 觀察清單（到時要主動提醒使用者）

低於門檻時評估：近期加權排序、主題摘要（語意搜尋已由使用者決定不做，D74）（見 BENCHMARK）；降低額度消耗的後續項目（D56）；**拼字容錯**（凍結集中有打錯字、用拼音寫地名的問法）。其他已記錄的缺口見 [ROADMAP](ROADMAP.md) 第 6 項。

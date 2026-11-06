# 驗收紀錄（歷史）

## W01 開發與文件流程（使用者驗收通過，2026-11-06）

使用者確認「W01看起來沒問題」，結案df3966e的流程重構。入口10,259→1,997字元（減80.5%，不是token實測）；本機領域定位、文件／版本檢查、驗證雜湊、結案／三處升版／選檔提交及未驗收推送保護已實作。該批最終快速回歸753 passed、11 deselected，流程回歸23項；未跑slow／scale。既有敏感詞命中已匿名化且保留hook；沒有升版、推送或對外發布。驗收只涵蓋W01，M10仍待委託驗收，其他缺口保留。

工作流程重構前狀態見 [快照](history/2026-11-workflow-before.md)，舊里程碑／匯入提案見 [開發計畫](history/2026-11-development-plan.md)，歷次AI／審查結果見 [基準歷史](history/BENCHMARK-2026-11.md)。這些不是現行工作清單或新授權；W01依使用者確認結案，M10尚未通過。

從 [PROGRESS](PROGRESS.md) 移出，只供追溯，不需要平常讀。日期見各段標題（未標示者為 2026-11-02）。決策原因見 [DECISIONS](DECISIONS.md)。

## M10 首輪驗收未通過（Agent 受託驗收，2026-11-06）

完整機械檢查為 719 通過、3 失敗：T16 的 stdio 測試仍索取精簡回應已移除的 `ref`、空 `tags_pending`；後續版本斷言也仍使用舊欄位。安靜風格不符合 D91；最高風險內容在 DESIGN／AGENT_RULES 的詢問規則不一致，個資 AI 補測又被核准層拒絕。沒有標通過或前進 M11。

Windows 未核准環境曾在建立 asyncio `socketpair` 時停住；核准環境可完成套件。真實 stdio 的個資通知、合成同意後免問、最高風險拒絕、版本保留與隱藏恢復已驗證；這些不能代替 AI 完整對話。原始證據在被忽略的 `benchmark-output/codex-m10-20261106/`。使用者後續同意修正與固定合成電話寫入（D93）；修正後狀態見 [PROGRESS](PROGRESS.md)，AI 比較見 [BENCHMARK](history/BENCHMARK-2026-11.md#m10-codex-專項重驗2026-11-06)。

## M7 標籤（使用者驗收通過，2026-11-03）

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

## M8 匯入與備份加密（使用者驗收通過，2026-11-03）

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

## M9 徹底清除（使用者驗收通過，2026-11-03）

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

## M6 信任閘門（使用者驗收通過，版本升 0.1.0）

**做了什麼**：PIN（存在資料夾內的 `security.json`，不在資料庫；`pin set／change／reset`，復原碼）、危險命令閘門（真人終端機加 PIN：`restore`、`phrase add／set／remove`、`notice enable`、`sensitivity set`）、觸發語句（`phrase list` 不需 PIN；MCP `phrases_list`）、敏感掃描（high／medium）與確認碼（`save`／`amend` 的 `confirm_token`、`notice_token`）、`get` 的敏感度上限、`doctor` 顯示 PIN 狀態與失敗次數、`restore` 保留目前的 PIN 設定。

**實測**：快速測試 413 項全過；掃描效能 1 MiB 文字 0.5 秒內（初版有二次方時間問題，已修）。AI 層（haiku）：五段同意對話 5/5——密碼用固定句式詢問、答「否」不存、答「是」存成 high；電話第一次詢問並存成 medium、第二次不再問；重新開啟提醒後又問。Claude Code 的 PowerShell 工具執行 `phrase add`、`pin set`、`restore` 皆被拒（結束碼 3）。真正終端機輸入 PIN 由使用者驗收通過。

**驗收清單**（用拋棄式資料夾，已完成）：`init` 設 PIN 並抄下復原碼；`doctor` 顯示 pin 已設定；`phrase list` 六條預設；`phrase add` 要 PIN；敏感內容被拒、用確認碼重送才存、同一碼第二次失敗；電話第一次要同意；連輸 5 次錯誤 PIN 被鎖定；`backup` 後 `restore` 要 PIN；AI 工具執行危險命令被拒。

## M5 版本、連結、隱藏（使用者驗收通過）

**做了什麼**：`amend`（新增版本，防互相覆蓋）、`hide`／`unhide`、連結（推翻、支持等，由新指向舊）、記錄狀態（現行／被推翻／重新確認）、`current_only`、結果超過 50 筆附摘要、長內容分段讀取、匯出含連結、MCP 回應加 `api_version`。

**實測**：快速測試 280 項全過。AI 層（haiku，共 $0.104）：Q08–Q10 全部 5 分；寫入探針 10/10；規模題 Q75（3000 筆、617 筆符合）5 分。與 M4 基準比較（共同 39 題）：平均分 4.33→4.59；每題平均輸入量 32,482→33,410 token（+2.9%），依使用者決定標準放寬為 ≤105%，達標。M5 本身沒有減少單題讀取量，真正的瘦身留待 M10 依數據決定。

**驗收清單**（已完成）：存兩筆並用 `--link rN:supersedes` 連結後 `get` 看到「被…推翻」；`hide` 後搜不到、`unhide` 後找回；`amend` 後 `get --version 1` 仍是舊文字。

## 計畫審查（1 個 agent 唯讀審查，使用者同意後處理）

① 終端機閘門在 Windows 可被繞過（三條串流導向 NUL 時 `isatty()` 仍為真）→ 改用 Windows 主控台 API，無法證明是主控台就拒絕，移除 `restore --yes`，使用者已驗收。② 清除規格缺口 → 補 FTS `optimize`、清除後掃描並列出資料夾內的明文副本，T22 已更新，實作在 M9（D59）。③ 題庫評分過寬 → 修引用解析、「查無」判定、日期寫法（D59）。④ 文件清理與 M5 連結語意、結果摘要規格（D61）。

## 多樣語氣集首次結果（M4 程式，haiku，$0.091）

關西腔、正式書面、日文混中文 5.00；長輩 4.75；台灣口語 4.50；極簡打字 4.38。弱點集中在「兩週前我寫了什麼」（Q56）與極簡打字的次數題。

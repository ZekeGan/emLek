# 驗收紀錄（歷史）

從 [PROGRESS](PROGRESS.md) 移出，只供追溯，不需要平常讀。日期皆為 2026-11-02。決策原因見 [DECISIONS](DECISIONS.md)。

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

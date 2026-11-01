# 進度

最後更新：2026-11-01。只記實際狀態；未執行的不標通過。

## 現況

- 模式：**MODE B；M3 已完成，等使用者驗收**（授權到 M3，M4 需使用者驗收或下一道指示）。
- 已有 `src/emlek`（init、doctor、save、get、search、reindex、mcp、遷移 0001–0002）與 176 項測試（175 項快速＋1 項 36000 筆規模）；只有合成測試資料。版本號 0.0.0，尚未發布。
- Git：`main`，遠端 `origin` = https://github.com/ZekeGan/emLek.git（公開）；是否同步以 `git status` 為準。敏感詞檢查掛在本機 pre-commit 與 pre-push，標記清單目前是空的。
- 環境（已驗證）：Python 3.14.10（uv 0.13.6）、SQLite 3.53.1；`pyproject.toml` 與 `uv.lock` 已建立，執行期與開發套件已安裝進 `.venv`（mcp 2.3.0、cryptography 50.0.2、pytest 9.2.0、ruff 0.17.3、mypy 2.4.1、hypothesis 6.170.14），專案本身已以可編輯模式安裝；Claude Code 2.1.316 已安裝（簽章與校驗碼已驗證）。
- 未驗證：Codex CLI 位置；真實資料效能。

## 開發前就緒檢查（M0）

- 完成：規格整理（審稿 A 的 22 項、審稿 B 的建議，見 D38）、里程碑 M1–M10（D39）、技術決定（D40）、TEST_PLAN（25 條不變式）、題庫 41 題啟用＋2 題保留、實驗記錄（D41）。
- 驗證過的關鍵事實：套件在 Python 3.14 可安裝並可匯入；mcp 2.x 的伺服器類別是 `MCPServer`（不是 1.x 的 FastMCP），匯入約 2 秒，故延遲匯入；Python 從 Git Bash 預設用 cp950 輸出，故一律明確用 UTF-8；AES-256-GCM＋scrypt 往返與竄改偵測可用；3.6 萬筆實長度資料 2 字元 LIKE 約 0.5 秒；清除需 checkpoint＋VACUUM 才無殘留；`icacls` 免管理員可設資料夾權限。

## 使用者已決定（2026-11-01）

PIN 強化採用（M6）；清除最終確認只在使用者自己的終端機（M9，MCP 只有預覽）；備份放不同磁碟（M4）；Claude Code 已登入；Windows 家用版沒有 BitLocker，資料庫本體明文（D44，`doctor` 會提示）。

## 仍待確認（不阻擋 M2）

- Codex CLI：使用者說已安裝，但這台電腦的 PATH（使用者與系統）找不到 `codex`；M3 前請告訴我執行檔位置或名稱。

## 待驗收：M3 權限與 MCP

做了什麼：`emlek mcp`（以 MCP 提供 `save`／`get`／`search` 給 AI；`--read-only` 的工具清單根本沒有 `save`，敏感度上限預設 medium）；核心權限表的完整矩陣測試；MCP 工具契約測試；用真正的 MCP 客戶端驗證 stdio 往返、錯誤格式、唯讀模式與「CLI 與 MCP 兩個行程同時寫入」；用 Claude Code 實測存入與查找、AI 層題庫首次報告（見 BENCHMARK）。

實測：ruff、嚴格 mypy 通過；175 項快速測試全過。**Claude Code 實際接上並完成存入與查找**：8 題中 7 題 5 分、Q20（剪頭髮頻率）0 分（AI 沒想到資料用的日文詞，屬同義詞召回問題，M7 標籤與別名是設計上的對策）；Q37 一開始誤用事件日期，把 `date_field` 說明寫清楚後單次重跑 5 分；三項行為探針（明確要求才存、相對日期換算、唯讀不能存）全部符合預期。唯讀沙箱：不給內建工具或不預先核准 shell，AI 都寫不進去（對照組確實寫入，證明測試有效）。

30 秒驗收（拋棄式資料夾，只放假資料）：
1. PowerShell：`cd D:\Programming\Project\emlek`，執行 `.venv\Scripts\emlek.exe --data-dir D:\emlek-try3 init`，再執行 `... mcp --read-only`。畫面會停住等待 AI 連線、不印任何字，這是正常的；按 Ctrl+C 結束。
2. 執行 `.venv\Scripts\pytest.exe -q -m "not scale"`，看到 `175 passed`。
3. 打開 `benchmark-outputi-m3.json` 看每題分數與 token 用量；完成後可刪除 `D:\emlek-try3`。
（想自己用 Claude Code 試：在 Claude Code 的 MCP 設定加入 `emlek.exe --data-dir <資料夾> mcp`，用假資料資料夾即可。）

限制與未測：Codex CLI 位置仍未確認，所以 Codex 端未測；AI 層每題只跑 1 次（報告用，不卡關）；實測模型是無頭模式預設的 haiku，你平常用的模型可能不同；自動化的 shell 對照組探針被權限檢查擋下，結果來自手動執行。

## 下一步

等使用者驗收後做 M4：`backup`（一致性備份）、`restore`（驗證後才替換）、`export` v1、`stats`、遷移前自動備份；完成後才可處理真實資料（還要等 M6）。備份目錄預設 `D:\emlek-backups`。

## 待使用者同意：AI 層「不理想」門檻（提議）

第一次 AI 層基準已出（M3）。提議：任一非模糊題單次得 0 分（例如這次的 Q20），或同一里程碑 AI 層平均低於 4 分，我就依觀察清單提醒你評估。Q20 這次已觸發第一個實例；因為 M7 的標籤與別名本來就是它的對策，我建議先記錄、到 M7 後重測，仍不理想再正式提案（語意搜尋等）。

## 觀察清單（到時要主動提醒使用者）

題庫第一次取得基準值後，與使用者約定「不理想」門檻；若低於門檻，提醒評估：語意搜尋、近期加權排序、主題摘要（見 BENCHMARK）。

未來需求：手機使用（隨手記錄、連接器橋接、遠端查詢）等 AGENT 技術更成熟後再評估；其他已記錄的缺口見 DESIGN「未來需求」第 6 項。目前一律本機。

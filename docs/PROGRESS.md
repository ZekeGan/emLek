# 進度

最後更新：2026-11-01。只記實際狀態；未執行的不標通過。

## 現況

- 模式：**MODE B；M2 已完成，等使用者驗收**（授權到 M2，M3 需使用者驗收或下一道指示）。
- 已有 `src/emlek`（init、doctor、save、get、search、reindex、遷移 0001–0002）與 140 項測試（含 1 項 36000 筆規模測試）；只有合成測試資料。版本號 0.0.0，尚未發布。
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

## 待驗收：M2 搜尋與時間

做了什麼：`emlek search`（中日英全文搜尋；3 字元以上走全文索引、1–2 字元走掃描，可多詞同時；日期範圍、依事件時間或存入時間排序、第一次／最後一次、分頁與總筆數、種類篩選、敏感度上限）、`emlek reindex`（重建索引）、`doctor` 新增索引檢查；資料庫遷移 0002（全文索引與事件日期欄位，舊資料庫會先自動備份再升級）。題庫系統層 8 題（Q01、Q02、Q06、Q07、Q13、Q15、Q20、Q37）全部 5 分，工具回傳內容估計共約 2,200 token（估計值）。

實測：ruff、嚴格 mypy 通過；139 項快速測試全過，另 1 項 36000 筆規模測試通過。規模測試（合成資料、平均約 1.7K 字元、資料庫約 523 MB、載入約 98 秒）：3 字元以上查詢 1–20 毫秒；1–2 字元掃描約 0.7–0.8 秒；查無結果時補掃描約 0.8 秒；不帶關鍵字的瀏覽每頁約 0.6 秒（目前每頁都重新排序全部結果，之後可改成更有效率的游標，不影響正確性）。

30 秒驗收（拋棄式資料夾，只放假資料）：
1. PowerShell：`cd D:\Programming\Project\emlek`，依序執行：`.venv\Scripts\emlek.exe --data-dir D:\emlek-try2 init`；`... save --text "今日は京都で抹茶を飲んだ" --event-time 2026-10-30`；`... save --text "東京でラーメン" --event-time 2026-10-31`；`... search 京都`。應只看到京都那筆。
2. 執行 `... search --order event_time --dir asc --limit 1`（應是 10-30 那筆，即最早）與 `... search --from 2026-10-31 --to 2026-10-31`（應是東京那筆）。
3. 執行 `.venv\Scripts\pytest.exe -q -m "not scale"`，看到 `139 passed`；可打開 `benchmark-output\system-m2.json` 看每題分數。完成後可刪除 `D:\emlek-try2`。

已知範圍外（後續里程碑）：標籤篩選（M7）、`superseded_by`／`linked_from`（M5）、MCP（M3）。時區目前只支援 `local` 與 `+09:00` 這類偏移，不支援 `Asia/Tokyo` 名稱。

## 下一步

等使用者驗收後做 M3：核心權限表與 MCP 外殼（完整與 `--read-only`）、Claude Code 實測、平台唯讀沙箱旗標實測、AI 層題庫開始（只報告）。Codex CLI 位置需在這之前確認。

## 觀察清單（到時要主動提醒使用者）

題庫第一次取得基準值後，與使用者約定「不理想」門檻；若低於門檻，提醒評估：語意搜尋、近期加權排序、主題摘要（見 BENCHMARK）。

未來需求：手機使用（隨手記錄、連接器橋接、遠端查詢）等 AGENT 技術更成熟後再評估；其他已記錄的缺口見 DESIGN「未來需求」第 6 項。目前一律本機。

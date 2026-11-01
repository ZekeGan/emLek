# 進度

最後更新：2026-11-01。只記實際狀態；未執行的不標通過。

## 現況

- 模式：**MODE B；M1 已完成，等使用者驗收**（授權僅限 M1，M2 需使用者驗收或下一道指示）。
- 已有 `src/emlek`（init、doctor、save、get、遷移 0001）與 76 項測試；沒有 Vault 內容（只有合成測試資料）。版本號 0.0.0，尚未發布。
- Git：`main`，遠端 `origin` = https://github.com/ZekeGan/emLek.git（公開）；是否同步以 `git status` 為準。敏感詞檢查掛在本機 pre-commit 與 pre-push，標記清單目前是空的。
- 環境（已驗證）：Python 3.14.10（uv 0.13.6）、SQLite 3.53.1；`pyproject.toml` 與 `uv.lock` 已建立，執行期與開發套件已安裝進 `.venv`（mcp 2.3.0、cryptography 50.0.2、pytest 9.2.0、ruff 0.17.3、mypy 2.4.1、hypothesis 6.170.14），專案本身已以可編輯模式安裝；Claude Code 2.1.316 已安裝（簽章與校驗碼已驗證）。
- 未驗證：Codex CLI 位置；真實資料效能。

## 開發前就緒檢查（M0）

- 完成：規格整理（審稿 A 的 22 項、審稿 B 的建議，見 D38）、里程碑 M1–M10（D39）、技術決定（D40）、TEST_PLAN（25 條不變式）、題庫 41 題啟用＋2 題保留、實驗記錄（D41）。
- 驗證過的關鍵事實：套件在 Python 3.14 可安裝並可匯入；mcp 2.x 的伺服器類別是 `MCPServer`（不是 1.x 的 FastMCP），匯入約 2 秒，故延遲匯入；Python 從 Git Bash 預設用 cp950 輸出，故一律明確用 UTF-8；AES-256-GCM＋scrypt 往返與竄改偵測可用；3.6 萬筆實長度資料 2 字元 LIKE 約 0.5 秒；清除需 checkpoint＋VACUUM 才無殘留；`icacls` 免管理員可設資料夾權限。

## 使用者已決定（2026-11-01）

PIN 強化採用（M6）；清除最終確認只在使用者自己的終端機（M9，MCP 只有預覽）；備份放不同磁碟（M4）；Claude Code 已登入；Windows 家用版沒有 BitLocker，資料庫本體明文（D44，`doctor` 會提示）。

## 仍待確認（不阻擋 M1）

- Codex CLI：使用者說已安裝，但這台電腦的 PATH（使用者與系統）找不到 `codex`；M3 前請告訴我執行檔位置或名稱。

## 待驗收：M1 骨架

做了什麼：`emlek init`（建立資料夾、限制只有你的帳號可存取、建立資料庫）、`emlek doctor`（環境與資料庫檢查）、`emlek save`／`emlek get`（存入與讀取，含事件時間、來源）；資料庫內建「版本不可改」的保護；遷移機制（升級前自動備份）。實測：ruff、mypy（嚴格模式）、76 項測試全過（快速集 75 項約 14 秒，另 1 項「強制終止寫入」約 2 秒）。

30 秒驗收（用拋棄式資料夾，只放假資料，結束後可刪除）：
1. 開 PowerShell：`cd D:\Programming\Project\emlek`，執行 `.venv\Scripts\emlek.exe --data-dir D:\emlek-try init`，再執行同前綴加 `doctor`，看每項是否為 [正常]（「磁碟加密」顯示 [資訊] 是預期的）。
2. 執行 `.venv\Scripts\emlek.exe --data-dir D:\emlek-try save --text "今天去了淺草寺" --event-time 2026-11-01`，再執行 `... get r1`，看內容與事件時間是否一致。
3. 執行 `.venv\Scripts\pytest.exe -q`，看到 `76 passed`。完成後可刪除 `D:\emlek-try`。

已知範圍外（後續里程碑）：搜尋（M2）、MCP（M3）、備份（M4）、版本修改與隱藏（M5）、敏感提示與 PIN（M6）、標籤（M7）。

## 觀察清單（到時要主動提醒使用者）

題庫第一次取得基準值後，與使用者約定「不理想」門檻；若低於門檻，提醒評估：語意搜尋、近期加權排序、主題摘要（見 BENCHMARK）。

未來需求：手機使用（隨手記錄、連接器橋接、遠端查詢）等 AGENT 技術更成熟後再評估；其他已記錄的缺口見 DESIGN「未來需求」第 6 項。目前一律本機。

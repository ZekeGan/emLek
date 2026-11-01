# 實際進度

最後更新：2026-11-01。只記實際狀態，未執行的工作不標通過。

## 目前階段

- 模式：**MODE A（規劃）**。尚未授權產品實作；使用者以新訊息明確輸入「執行」後才進入 MODE B。
- 2026-11-01：使用者決定改採**簡化版設計**（個人、本機、單一使用者）。舊完整版文件原樣移至 [archive](archive/)，視為參考藍圖。
- 目前沒有產品程式、依賴環境、測試或 Vault。

## 已決定

| 項目 | 決定 |
|---|---|
| 刪除 | 預設隱藏（可恢復）；徹底清除只能由事前登記的特別指令「完全刪除」啟動，並須固定句式二次確認「是／否（無法回復）」。第一版先做隱藏，徹底清除第 5 步再加 |
| 存入時機 | 只有明確要求（記住、幫我記一下等）才存；敘述過去不算；拿不準就問 |
| 加密 | 簡單：裝置加密保護日常資料；備份可選密碼加密 |
| AI 入口 | MCP＋CLI，不綁定特定 AI；規則檔平台中立 |
| 備份與搬家 | 單一 SQLite 檔，backup／restore／export |
| 舊文件 | 保留於 docs/archive |

## 已完成

- 舊 14 份文件與 baseline 移至 `docs/archive/`（內部相對連結保持相對關係）。
- 新增 [DESIGN](DESIGN.md)、[AGENT_RULES](AGENT_RULES.md)；改寫根目錄 README、AGENTS、CLAUDE。
- 未執行任何程式、測試或安裝。

### 2026-11-01：基礎環境（使用者明確要求，不含程式碼）

- Git：2.45.2，已 `git init -b main`（本機，無 remote，未推送）；`.gitignore` 排除 `.venv`、資料庫檔、`vault/`、`backups/`、`exports/`、`.env`；`.gitattributes` 統一 LF。尚未提交。
- Python：系統原有 3.11.1（舊）不使用；以 uv 0.13.6 下載 CPython 3.14.10，`.python-version` 固定 `3.14`，專案 `.venv` 已建立（未納入 Git）。
- 實測（驗證通過）：`.venv` 內 Python 3.14.10、SQLite 3.53.1，FTS5 trigram 可建立，三字元日文詞查詢命中。
- 尚未建立 `pyproject.toml`、套件目錄、依賴或任何程式；留待「執行」後的步驟 1。

## 尚未開始

DESIGN 的開發步驟 1–5 全部 `not_started`／未驗證。

## 待確認（不阻擋開始，開發時再決定）

- 目標電腦是否支援 Windows 裝置加密／BitLocker。
- 要先接入的第一個 AI（影響 MCP 設定與驗證）。
- 預設語句內容（DESIGN「自訂語句」已列預設值，使用者之後可用 `emlek phrase` 自行改）。
- 2026-11-01 新增決定：語句可增刪改查（CLI 命令 `emlek phrase list/add/set/remove`），存於資料庫；AI 只能唯讀；改動 purge 類須真人互動終端機確認。文件已更新，尚未實作。

## 下一步

收到「執行」後，依 DESIGN 步驟 1 開始：先取得實際 Python／SQLite 版本與 FTS5 trigram 支援，再建立專案與合成資料測試。在此之前只修改文件。

## 更名紀錄

- 2026-11-01：專案由 Remtrace 更名為 **Emlek**（匈牙利語「記憶」；命令 `emlek`）。現行文件、`.gitignore` 已同步；`docs/archive/` 的舊藍圖保持原樣，內文仍稱 Remtrace。工作區資料夾名稱尚未更改。

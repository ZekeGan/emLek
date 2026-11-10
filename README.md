# emLek — 個人 AI 長期記憶庫

本機、單一使用者的文字記憶庫。你主動啟用並同意後，AI（Claude、Codex 或其他支援 MCP／命令列的平台）依政策保存個人敘述，之後能找回並附上來源。

**開發中，尚未發布；核定行為見 [產品索引](docs/DESIGN.md)，實作差距與待驗收只見 [當前工作](docs/PROGRESS.md)。**

## 特色

- 在對話輸入 `emlek start` 才顯示首次條款；同意後保存往後的生活、想法、工作摘要與個資，不再逐筆詢問、不補存先前聊天。未啟用時正常聊天、不記錄、不主動詢問。啟用後照常接話，保存成功在末尾附 `◆ emLek｜r1.✔️`（實際編號）；誤存可按編號隱藏，`emlek recent --auto` 可回顧。一般問題不存不問，密碼金鑰永不存；政策與 PIN 防線保留。
- 原文不被覆蓋：修改新增版本。原文、AI 整理、AI 推論分開標記；未知的作者與日期標未知。通用 MCP 無法驗證模型傳入前是否改字，逐字保存仍有此限制。
- 中日英全文搜尋，加上標籤系統（階層、別名），方便用「日本」找到東京、京都的紀錄。
- 一般刪除只是隱藏、可恢復；真正抹除需要你登記的特別語句，AI 還會再問一次「是／否（無法回復）」（`emlek purge r12` 徹底清除：只能在你自己的終端機、輸入 PIN、答「是」才執行，無法恢復；M9 已驗收）。
- 目前一律本機使用；架構已預留日後擴充手機使用（規劃保留，未開發）。
- 資料全在一個資料庫檔：`backup` 產生單一備份（加 `--encrypt` 用密碼加密，密碼遺失就無法還原；沒加則是明文），`import` 匯入 .txt／.md（預設只預覽），`restore` 在新電腦還原，`export` 輸出 JSON／Markdown。

## 不做

不上雲、不做多使用者、不做身分隔離或授權系統、不做向量搜尋或完整知識圖譜。

## 文件

[安裝與接上 AI](docs/INSTALL.md)・[設計](docs/DESIGN.md)・[標籤系統](docs/DESIGN_TAGS.md)・[AI 使用規則](docs/AGENT_RULES.md)・[每日簡報](docs/DAILY_BRIEFING.md)・[題庫](docs/QUESTIONS.md)・[基準測試](docs/BENCHMARK.md)・[測試計畫](docs/TEST_PLAN.md)・[進度](docs/PROGRESS.md)・[決策紀錄](docs/DECISIONS.md)・[開發 Agent 指引](AGENTS.md)・[舊藍圖](docs/archive/)（非現行）

## 接上 AI 與示範

```powershell
claude mcp add emlek -- <專案路徑>\.venv\Scripts\emlek.exe mcp
```

詳見 [安裝](docs/INSTALL.md)。對話範例（r12 為實際編號）：

```text
你：emlek start            → 顯示首次條款，回「同意」後啟用
你：今天和小美去京都，買了抹茶
AI：聽起來很愉快！     ◆ emLek｜r12.✔️
你：我上次去京都買了什麼？
AI：抹茶（r12，2026-11-11）。
```

## 怎麼執行（開發版）

`emlek` 裝在專案的 `.venv` 裡，沒有加進系統 PATH，所以在 PowerShell 要這樣用：

```powershell
cd <放專案的資料夾>
$e = ".\.venv\Scripts\emlek.exe"
& $e --data-dir C:\temp\emlek-try init   # 在真正的終端機執行：會要你設定 PIN 並顯示復原碼
& $e --data-dir C:\temp\emlek-try save --text "測試用的一筆記錄"
& $e --data-dir C:\temp\emlek-try search --help
```

或在專案資料夾用 `uv run emlek ...`。`--data-dir` 指定資料夾，不給則用預設位置。

## 環境

Windows 11、Python 3.14；不需要 Docker、GPU 或付費 API。

## 授權

[MIT](LICENSE)

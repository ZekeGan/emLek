# emLek — 個人 AI 長期記憶庫

本機、單一使用者的文字記憶庫。你要求時，你的 AI（Claude、Codex 或其他支援 MCP／命令列的平台）把內容存起來，之後能找回並附上來源。

**狀態：開發中（M1–M6 完成並驗收：存、查、備份還原、匯出、版本與連結、隱藏、PIN 與敏感內容閘門；M7 標籤已驗收；M8 匯入與備份加密已驗收；M9 徹底清除已驗收；版本 0.1.0，尚未發布）。尚未發布；以下含尚未實作的預期用法，進度見 [PROGRESS](docs/PROGRESS.md)。**

## 特色

- 只有明確要求（記住、幫我記一下…）才存；「我上週記住了文法」這類敘述不觸發。觸發語句可用 `emlek phrase` 自行增刪改查。
- 原文不被覆蓋：修改新增版本。原文、AI 整理、AI 推論分開標記；未知的作者與日期標未知。
- 中日英全文搜尋，加上標籤系統（階層、別名），方便用「日本」找到東京、京都的紀錄。
- 一般刪除只是隱藏、可恢復；真正抹除需要你登記的特別語句，AI 還會再問一次「是／否（無法回復）」（`emlek purge r12` 徹底清除：只能在你自己的終端機、輸入 PIN、答「是」才執行，無法恢復；M9 已驗收）。
- 目前一律本機使用；架構已預留日後擴充手機使用（規劃保留，未開發）。
- 資料全在一個資料庫檔：`backup` 產生單一備份（加 `--encrypt` 用密碼加密，密碼遺失就無法還原；沒加則是明文），`import` 匯入 .txt／.md（預設只預覽），`restore` 在新電腦還原，`export` 輸出 JSON／Markdown。

## 不做

不上雲、不做多使用者、不做身分隔離或授權系統、不做向量搜尋或完整知識圖譜。

## 文件

[設計](docs/DESIGN.md)・[標籤系統](docs/DESIGN_TAGS.md)・[AI 使用規則](docs/AGENT_RULES.md)・[每日簡報](docs/DAILY_BRIEFING.md)・[題庫](docs/QUESTIONS.md)・[基準測試](docs/BENCHMARK.md)・[測試計畫](docs/TEST_PLAN.md)・[進度](docs/PROGRESS.md)・[決策紀錄](docs/DECISIONS.md)・[開發 Agent 指引](AGENTS.md)・[舊藍圖](docs/archive/)（非現行）

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

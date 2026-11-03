# 安裝、升級與接上 AI（Windows）

給不是開發者的使用者。emLek 目前只有原始碼版本，還沒有安裝程式；以下步驟用 PowerShell。

## 安裝

1. 安裝 [uv](https://docs.astral.sh/uv/)（會自動準備 Python 3.14）：`winget install --id=astral-sh.uv -e`
2. 下載或 clone 專案到固定位置（例如 `D:\emlek`），**之後不要移動這個資料夾**：AI 工具會記住 `emlek.exe` 的完整路徑。
3. 在專案資料夾執行 `uv sync --locked`。
4. 第一次使用，在**你自己的終端機**（不是 AI 對話裡）執行：

```powershell
cd D:\emlek
.\.venv\Scripts\emlek.exe init
```

會要你設定 PIN 並顯示復原碼。復原碼寫在紙上或存進密碼管理器，**不要貼給任何 AI**。

`emlek` 沒有加進系統 PATH，所以要用完整路徑 `.\.venv\Scripts\emlek.exe`，或在專案資料夾用 `uv run emlek ...`。資料預設放在使用者資料夾；用 `--data-dir` 或環境變數 `EMLEK_DATA_DIR` 指定位置。

## 接上 AI

指令格式依各工具版本而異，以該工具的說明為準；下面是常見寫法（路徑換成你的）：

```powershell
claude mcp add emlek -- D:\emlek\.venv\Scripts\emlek.exe mcp
codex mcp add emlek -- D:\emlek\.venv\Scripts\emlek.exe mcp
```

只想讓某個 AI 讀、不能寫，在 `mcp` 後面加 `--read-only`。接上後，把 [AI 使用規則](AGENT_RULES.md) 放進該工具的指示檔（例如 Claude Code 的 `CLAUDE.md`）；規則檔不會自動送給 AI。

## 升級前

```powershell
.\.venv\Scripts\emlek.exe doctor
.\.venv\Scripts\emlek.exe backup
```

`doctor` 全部正常、備份成功再升級（`git pull` 後 `uv sync --locked`）。資料庫結構會在第一次開啟時自動升級，並先在資料夾的 `pre-migration` 留一份升級前的副本；確認一切正常後可用 `emlek cleanup` 清掉這些副本。升級後再跑一次 `doctor`。

## 備份與還原

- `emlek backup`（可加 `--encrypt` 用密碼加密；密碼遺失就無法還原），備份請放在另一顆磁碟。
- 還原必須在你自己的終端機：`emlek restore <備份檔>`。還原前先關閉所有正在使用 emLek 的 AI 工具，否則會因檔案被占用而失敗。
- 還原到比某次「徹底清除」更早的備份，會讓已清除的資料回來；程式會警告。

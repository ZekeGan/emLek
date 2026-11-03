# 實作階段規則

進入 MODE B、寫程式、測試或準備發布時才讀。MODE A 只改文件時不必讀。

## 里程碑迴圈

1. 從 [PROGRESS](PROGRESS.md) 取下一個里程碑；讀 DESIGN 相關章節與 [TEST_PLAN](TEST_PLAN.md) 該里程碑的測試。
2. 先寫測試（不變式與題庫系統層），再實作。一次只做一個里程碑。
3. 完成標準＝DESIGN「開發順序」表的標準，加上 ruff、mypy、pytest 全綠，**以及受影響文件已同步**（AGENTS「文件與命名」的文件同步條款：新需求或新功能改動檔案後，同批優化文件，不必問；影響專案方向或需求才先問）。
4. 在 PROGRESS 的「待驗收」寫 3–5 步的 30 秒驗收清單；有取捨時在 DECISIONS 記一行；提交（英文）。待驗收累積超過約 5 批先暫停新功能。
   **使用者驗收通過後立即把該段「待驗收」從 PROGRESS 移到 [HISTORY](HISTORY.md)**（標題改為「通過」與日期），PROGRESS 只留現況、待驗收與下一步。
5. 高風險里程碑（M3 權限與 MCP、M4 備份還原、M6 信任閘門、M8 加密、M9 清除）提交前，用獨立子 Agent 審查一次，只給該次差異與風險點。
6. **真實資料閘門**：M4（備份）與 M6（信任閘門）完成前，不處理任何真實資料（含舊日記）；之後也須使用者貼出路徑並同意。

## 修改與驗證

- 最小必要修改，沿用周圍風格；不加沒被要求的功能、設定或抽象；不順手重構。修錯先重現並定位根因。
- 含反斜線的內容用編輯工具寫入，不用 heredoc 拼接。
- 驗證依風險選最小有效組：純文件→連結檢查＋看差異；純邏輯→對應測試＋型別檢查；資料寫入、備份還原、清除→在受控測試資料上跑成功、失敗、取消與復原，並確認原檔未動。需求還在變動時不跑完整測試。
- 失敗先分類（產品／測試資料／環境）再重跑受影響項目。功能移除時同批更新或刪除對應測試。
- 回報分清「實際執行」「未執行」「限制」；舊結果不算本輪驗證；不確定的標「我推測」。

## 技術決定（D40）

- **目錄**：`pyproject.toml`、`uv.lock`；`src/emlek/`：`cli/`（`parser.py`、`commands/*.py`、`output.py`）、`mcp_server/`（唯一匯入 `mcp` 的地方）、`core/`（`service.py` 每個操作一個函式、`permissions.py`、`errors.py`、`db.py`、`vault.py`、`doctor.py`、`timeutil.py`、`migrations/0001_*.sql…`、`search.py`、`sensitivity.py`、`tags.py`、`backup.py`、`export.py`、`purge.py`）、`config.py`、`log.py`；`tests/`：`unit/`、`invariants/`（`test_t01_*.py`…）、`benchmark/`（`synth.py` 合成資料、`test_system_layer.py` 題庫系統層、`test_scale.py` 規模測試；AI 層於 M3 加入）。
- **權限在核心**：`core/permissions.py` 一張「操作×入口（cli、mcp、mcp-readonly）」的表；每個 `service` 函式收 `Caller(channel, interactive)`（唯讀是 `MCP_READONLY` 通道）。外殼只做輸入輸出轉換；MCP 依該表註冊工具，唯讀是工具清單的性質，不是每個工具裡的旗標檢查。
- **封裝**：`[project.scripts] emlek = "emlek.cli:main"`；建置後端用 uv 預設的 `uv_build`。MCP 註冊用安裝後的絕對路徑 `.venv\Scripts\emlek.exe`，不用 `uv run`（啟動慢且受工作目錄影響）；`mcp` 延遲匯入，純 CLI 呼叫保持快速。
- **CLI**：`argparse`（無依賴、約 30 個子命令足夠，自訂結束碼 0–5 本來就要手動對應）。內文輸入支援 `--body-file` 與標準輸入，明確以 UTF-8 解碼（中文 Windows 終端機可能預設 cp950）。
- **MCP**：官方 `mcp` 套件包一層約百行的轉接層，版本 `>=2.3,<3`；不自己寫 JSON-RPC。伺服器行程絕不 `print()`，標準輸出只有協定；日誌走檔案或標準錯誤。
- **遷移**：`PRAGMA user_version` 加編號 `.sql` 檔，每個在單一交易內，只往前；升級前自動 `VACUUM INTO` 備份。每個里程碑才加自己的表，讓遷移機制從 M1 就被使用。
- **設定**：`tomllib` 讀資料夾內 `config.toml`；優先序為參數、環境變數、檔案、預設。有 `timezone`、`data_dir`（命令列參數與環境變數）與 `backup_dir`。
- **日誌**：標準庫 `logging`，輪替檔放資料夾 `logs/`，只記操作名稱與編號，不記內容。
- **加密與權限**：`cryptography` 的 AES-256-GCM＋`hashlib.scrypt`；資料夾權限用 `icacls`（`os.chmod` 在 Windows 無效）。
- **搜尋**：`revisions.body_norm` 為 NFKC＋casefold 副本，FTS5 外部內容表與 LIKE 都用它；結果以記錄為單位。
- **測試**：pytest＋Hypothesis；標記 `slow`（故障注入、行程終止）、`scale`（3.6 萬筆）；合成資料產生器固定種子。

## 本機 hook（不隨 clone 走）

`.git/hooks` 不會被 clone，所以 hook 的內容放在 `scripts/hooks/`，新 clone 或重灌後執行一次：

```powershell
python scripts/install-hooks.py
```

它把 `pre-commit`、`pre-push`、`sensitive_check.py` 複製進 `.git/hooks`，並在 `.git/sensitive-terms.txt` 不存在時建一個空檔。**敏感詞清單永遠只存在 `.git` 內**，腳本與文件都不含任何詞；要擋的詞自己寫進該檔（一行一項）。改 hook 時改 `scripts/hooks/` 的版本再重跑安裝，不要只改 `.git/hooks`。

## 機械式檢查（不靠自我回報）

`python scripts/check.py` 依序跑 ruff、ruff format、mypy 與快速 pytest，印出每步結束碼與所檢查的提交；`--fast` 只跑前三項（`pre-push` hook 會自動跑它，約數秒）；`--full` 連 slow、scale 一起跑。回報「全綠」時以這支腳本的輸出為準並標明模式。目前沒有 CI（外部服務尚未採用，需使用者同意，見 D89）。

## 可重複的驗收腳本

`python scripts/accept.py` 用拋棄式資料夾跑完**不需要 PIN、不需要真人終端機**的驗收步驟（存、查、標籤、隱藏、備份、匯出、匯入預覽、`auto status`、`recent`、`cleanup` 預覽），並確認 `purge`、`restore`、`auto on`、`import --apply`、`phrase add`、`sensitivity set` 等在腳本裡一律被拒（結束碼 3）；結束時清掉資料夾。需要 PIN 或真人終端機的步驟維持手動（清單在 PROGRESS）。腳本不傳 PIN、不繞過任何閘門。新增不需 PIN 的命令時，同批補進這支腳本。

## 專案設定

- 環境：Python 3.14（uv 管理，`.python-version` 已固定）。依賴由 `uv.lock` 鎖定。
- 型別：`uv run mypy（設定已含 src 與 tests）`　格式與檢查：`uv run ruff format --check .`、`uv run ruff check .`　測試：快速＝`uv run pytest -m "not slow and not scale"`，完整＝`uv run pytest`。
- AI 層基準（手動，用訂閱額度，不在預設測試內）：在 `tests/benchmark` 執行 `ai_runner.py`，環境變數見檔頭說明；報告寫到被忽略的 `benchmark-output/`。
- 受控測試資料：`tests/` 的合成資料與暫存目錄；`vault/`、`backups/`、`exports/` 已被 `.gitignore` 排除。
- 版本號規則見 DESIGN「版本號規則」：目前 0.1.0（2026-11-02 M6 驗收後升版；尚未對外發布、未打標籤）；兩處版本字串（`pyproject.toml`、`src/emlek/__init__.py`）必須一致；已發布的遷移檔不得修改；`CHANGELOG.md` 只有 Unreleased 區，不逐批升版。

## 發布前關卡（使用者說要發布時才做）

完整建置與測試；在乾淨環境安裝、啟動、移除；安全檢查（輸入驗證、檔案存取範圍、相依套件更新）；確認 LICENSE（MIT）與第三方授權；隱私清理（文件、測試、提交紀錄中的個資）；補貢獻與安全回報說明。

# 進度

最後更新：2026-11-01。只記實際狀態；未執行的不標通過。

## 現況

- 模式：**MODE A**（規劃）。使用者輸入「執行」後才進入 MODE B。
- 沒有產品程式、測試或 Vault。尚無版本號。
- Git：`main`，遠端 `origin` = https://github.com/ZekeGan/emLek.git（公開）；與遠端是否同步以 `git status` 為準。
- 環境（已驗證）：Python 3.14.10（uv 0.13.6，`.python-version` 固定 3.14）、SQLite 3.53.1、FTS5 trigram 可建立並命中三字元日文詞。`.venv` 已建立但未裝任何套件，無 `pyproject.toml`。
- 文件已定稿：AGENTS、DESIGN、DESIGN_TAGS、AGENT_RULES、WORKFLOW、BENCHMARK、DECISIONS（D01–D27）；LICENSE 為 MIT。舊藍圖在 `docs/archive`。

## 待驗收

無。（實作開始後，每批完成的項目與 30 秒驗收清單列在這裡，使用者驗收後移除；累積超過約 5 批先暫停新功能。）

## 下一步

收到「執行」後做 DESIGN 步驟 1：建立 `pyproject.toml`、安裝 pytest／ruff／mypy 並驗證 WORKFLOW「專案設定」的指令，再實作資料庫與 `save`／`get`／`search`，用合成資料測試，並建立題庫的系統層測試骨架。

## 觀察清單（到時要主動提醒使用者）

題庫第一次取得基準值後，與使用者約定「不理想」門檻；若低於門檻，提醒評估：語意搜尋、近期加權排序、主題摘要（見 BENCHMARK）。

## 待確認（不阻擋開始）

- 這台電腦是否支援 Windows 裝置加密／BitLocker。
- 第一個要接入的 AI（影響 MCP 設定與驗證）。
- 手機端擷取工具與收件匣要放哪個同步資料夾（使用者端設定；步驟 5 前確認）。
- AI 層基準測試要用的 Claude Code：目前終端機找不到 `claude` 命令，步驟 2 前確認。

# 進度

最後更新：2026-11-01。只記實際狀態；未執行的不標通過。

## 現況

- 模式：**MODE A**（規劃）。使用者輸入「執行」後才進入 MODE B。
- 沒有產品程式、測試或 Vault。尚無版本號。
- Git：`main`，遠端 `origin` = https://github.com/ZekeGan/emLek.git（公開）；與遠端是否同步以 `git status` 為準。
- 環境（已驗證）：Python 3.14.10（uv 0.13.6，`.python-version` 固定 3.14）、SQLite 3.53.1、FTS5 trigram 可用；Claude Code 2.1.316 已安裝（官方程式、校驗碼與簽章已驗證，**需使用者登入一次**）；MCP 官方套件等在 3.14 可解析（尚未安裝）。`.venv` 已建立但未裝套件。
- 未驗證：BitLocker／裝置加密（Windows 11 家用版，需管理員權限才查得到；使用者可在「設定 → 隱私權與安全性 → 裝置加密」自行查看）；規模與真實資料效能。
- 文件：AGENTS、DESIGN、DESIGN_TAGS、AGENT_RULES、WORKFLOW、BENCHMARK、TEST_PLAN、DECISIONS（D01–D37）；LICENSE 為 MIT。舊藍圖在 `docs/archive`。**審稿與最佳化進行中**（見下方）。

## 待驗收

無。（實作開始後，每批完成的項目與 30 秒驗收清單列在這裡，使用者驗收後移除；累積超過約 5 批先暫停新功能。）

## 下一步

收到「執行」後做 DESIGN 步驟 1：建立 `pyproject.toml`、安裝 pytest／ruff／mypy 並驗證 WORKFLOW「專案設定」的指令，再實作資料庫與 `save`／`get`／`search`，用合成資料測試，並建立題庫的系統層測試骨架。

## 觀察清單（到時要主動提醒使用者）

題庫第一次取得基準值後，與使用者約定「不理想」門檻；若低於門檻，提醒評估：語意搜尋、近期加權排序、主題摘要（見 BENCHMARK）。

未來需求：手機使用（隨手記錄、連接器橋接、遠端查詢）等 AGENT 技術更成熟後再評估，見 DESIGN「未來需求」；目前一律本機。

## 待確認（不阻擋開始）

- 這台電腦是否支援 Windows 裝置加密／BitLocker。
- 使用者登入 Claude Code 一次（AI 層基準測試用）。

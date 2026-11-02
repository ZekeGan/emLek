# 變更紀錄

## Unreleased

- M7：標籤（階層、別名、`#標籤`、向下展開、`tags_pending`、覆蓋率、facets）、`tags_find`／`tags_list`／`set_tags`／`tag_link`／`tag_alias`、命令列 `tag`／`tags`、匯出含標籤、熱門標籤名稱進 AI 開場說明（只含名稱）、遷移 0005；搜尋時不存在的標籤名會被忽略並警告。

## 0.1.0 — 2026-11-02（M1–M6 完成並驗收；尚未對外發布、未打標籤）

- M6：PIN 與危險命令閘門（真人終端機加 PIN，PIN 雜湊存於資料庫外的 `security.json`）、觸發語句（`phrase`）、敏感掃描與一次性確認碼（`save`／`amend`）、個人資料提醒（`notice`）、`sensitivity set`、`get` 的敏感度上限、遷移 0004、`doctor` 的 PIN 檢查。
- M5：`amend`、`hide`／`unhide`、連結與記錄狀態、`current_only`、結果摘要（>50 筆）、`get` 分段與隱藏預設、匯出含連結、遷移 0003、MCP 回應 `api_version`。
- M1–M4：資料庫與不可變版本、全文搜尋、CLI／MCP、備份／還原／匯出。
- 題庫第一輪擴充與花費預算；終端機閘門改用 Windows 主控台 API 判斷，移除 `restore --yes`。

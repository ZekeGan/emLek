# 變更紀錄

## Unreleased

- M9：`emlek purge r<id>…`（真人終端機＋PIN＋固定問句，連帶移除 AI 摘要與只因它而存在的標籤，指紋複核，邏輯刪除後檢查點＋VACUUM＋原始位元組比對，`--finish` 補做擦除）、`emlek cleanup`（清理暫存副本，先驗證有較新的可用備份）；MCP `purge_preview` 只回中繼資料；記錄編號不再重用；匯入不會讓已清除的內容復活；`restore` 對早於清除的備份警告；遷移 0008（`purge_log`）；`doctor` 與 `stats` 顯示清除狀態（D82、D83）。
- M8：`backup --encrypt`（分段 AES-256-GCM、scrypt，往返驗證、不留明文）與 `restore` 讀加密備份；`emlek import`（.txt／.md，預設只預覽，`--apply` 須在真人終端機，整批單一交易，批次編號、`--undo`／`--list`，重複與變更偵測，high 預設略過）；遷移 0007；匯出含 `import_batch`／`import_log`（D81）。
- MCP 搜尋：結果精簡格式（省預設值）、`matching_tags`、開場說明標籤名稱上限 50；測試工具記錄工具錯誤與 API 請求數（D79）。
- 搜尋：OR 上限 20 組／30 詞、單詞組併成一次查詢、含 OR 的查詢附 `term_hits`、提示修正、MCP 單頁上限 30（D78）。
- `NEEDS_CONFIRMATION` 回應附 `ask_user` 固定問句；開場說明的熱門標籤只列使用者建立或使用過的；MCP `search` 單次回應約 12000 字元上限（`results_trimmed`）；評分另報 `adjusted_score`（D77）。
- 搜尋：裸的大寫 `OR` 表示任一組；多詞零結果時回 `term_hits` 與提示；`untagged` 篩選。標籤回補 `emlek tags backfill`（預覽、套用、復原，來源 `rule`，遷移 0006）。題庫新增模糊問法題 Q82–Q89。

- M7：標籤（階層、別名、`#標籤`、向下展開、`tags_pending`、覆蓋率、facets）、`tags_find`／`tags_list`／`set_tags`／`tag_link`／`tag_alias`、命令列 `tag`／`tags`、匯出含標籤、熱門標籤名稱進 AI 開場說明（只含名稱）、遷移 0005；搜尋時不存在的標籤名會被忽略並警告。

## 0.1.0 — 2026-11-02（M1–M6 完成並驗收；尚未對外發布、未打標籤）

- M6：PIN 與危險命令閘門（真人終端機加 PIN，PIN 雜湊存於資料庫外的 `security.json`）、觸發語句（`phrase`）、敏感掃描與一次性確認碼（`save`／`amend`）、個人資料提醒（`notice`）、`sensitivity set`、`get` 的敏感度上限、遷移 0004、`doctor` 的 PIN 檢查。
- M5：`amend`、`hide`／`unhide`、連結與記錄狀態、`current_only`、結果摘要（>50 筆）、`get` 分段與隱藏預設、匯出含連結、遷移 0003、MCP 回應 `api_version`。
- M1–M4：資料庫與不可變版本、全文搜尋、CLI／MCP、備份／還原／匯出。
- 題庫第一輪擴充與花費預算；終端機閘門改用 Windows 主控台 API 判斷，移除 `restore --yes`。

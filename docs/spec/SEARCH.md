# 搜尋與日期

現行規格；標籤細則見 [DESIGN_TAGS](../DESIGN_TAGS.md)，AI 查找行為見 [AGENT_RULES](../AGENT_RULES.md)。

## 搜尋規則

- **回應大小上限（D77）**：MCP 的 `search` 單次回應最多約 12000 字元（只回得下的筆數，至少 1 筆）；被截掉時回 `results_trimmed`、一句提示，`next_cursor` 指向最後一筆回傳的記錄，翻頁不漏不重。命令列與核心預設不設上限。三萬筆實測單次回傳最大約 1.8 萬字元，是 token 成長的主因。
- **關鍵字語法（2026-11-02 起）**：空白分隔的詞在同一組內必須**全部**出現；裸的大寫 `OR` 把查詢分成幾組，**任一組成立**即命中（最多 20 組、全部詞合計 ≤ 30；單詞的組合併成一次索引查詢加一次短詞掃描，多詞的組各自查詢；超過上限的錯誤訊息會說明怎麼拆）。小寫的 or、加引號的 "OR" 只是普通的字。回應多個詞且**零結果**，或查詢含 OR，就多一個 `term_hits`（每個詞單獨命中幾筆，只算可見記錄；3 字以上的詞走索引計數，短詞共用一次掃描）；零結果時再加一句提示，讓 AI 知道哪個詞有資料、該用 OR 或分開搜尋（D75）。零結果的語言提示只要求補上「還沒試過」的文字；已涵蓋記憶庫用到的各種文字時改建議換上位或下位說法、用標籤或日期縮小（D78）。MCP 的 `search` 單頁最多 30 筆（核心與命令列仍可到 100）。MCP 的搜尋結果用精簡格式（`compact`）：值等於預設的欄位（`hidden` false、`sensitivity` none、`status` current、`invalidated` false、`source` 空、`latest_version` 等於 `matched_version`、無事件日期時的 `event_time*`）不輸出，AGENT_RULES 說明缺少即預設；`ref` 與 `revision_ref` 都保留（AI 引用的是後者）。含查詢詞時回應多一個 `matching_tags`（名稱或別名與查詢詞完全相同的標籤與可見筆數，最多 5 個），AI 可直接用 `tags` 再搜，不必另呼叫 `tags_find`（D79）。開場說明的熱門標籤名稱上限由 200 降為 50（`tags_list` 仍可到 200）。`untagged=true` 只看還沒有任何標籤的記錄。
- 命中單位是**記錄**；預設比對各記錄的最新版本並標示命中的版本，`all_versions=true` 才比對舊版。總筆數的單位也是記錄。
- 過濾：`kinds`、`tags`、`tag_types`、日期範圍（`date_field=event_time|created_at`，前者看最新版本，後者是記錄首次存入時間；事件時間未知的記錄不排除，另列 `undated` 數量）、`include_hidden`（預設否）、`current_only`（排除已被推翻者，預設只標示）、`max_sensitivity`（超過上限的記錄不回內文，只計入 `withheld`）。
- 排序：`order=relevance|event_time|created_at`，`dir=asc|desc`；有關鍵字時預設 relevance、無關鍵字時預設 event_time desc。游標以排序鍵加記錄編號為準，頁間穩定。只有短詞（沒有 3 字元以上的詞）時沒有相關度，改以 `created_at desc`，回應的 `order` 欄位會註明實際採用的排序。
- 一律回傳總筆數並分頁（預設 20 筆、上限 100，附下一頁游標）；過長內容標明已截斷並提供取得剩餘部分的方式。同一天或同一時段的日期範圍即可瀏覽當天或當期所有紀錄。查詢詞有值但沒有任何結果時，回應多一個 `hints`，提醒換另一種語言或寫法再試（內容依記憶庫實際含有的文字種類：日文假名、漢字、英文字母）。
- `superseded_by` 由 `links` 中 `relation=supersedes` 推算，不另存欄位；若之後又有 `supports` 重新確認，一併回傳，讓 AI 能還原 A→B→C→A 的完整過程。`linked_from` 列出所有指向該記錄的連結與關係（如完成紀錄）。
- **結果過多時的摘要**：當總筆數超過 50（`aggregate_threshold`），回應多一個 `summary` 物件，`results` 仍是依 `limit` 分頁的片段（預設 20 筆），所以舊客戶端不受影響：
  - `summary.undated` 與頂層的 `undated` 不同：前者數**所有**符合者中沒有事件日期的，後者只在有日期過濾時才計。
  - `summary.total`、`summary.first` 與 `summary.last`（依 `date_field` 的最早與最晚日期）、`summary.by_month`（`YYYY-MM` 對筆數，超過 24 個月改為 `by_year`）、`summary.undated`（沒有日期者的數量）。
  - `summary.basis` 固定為 `"keyword"`，`summary.note` 固定為「依關鍵字比對，可能漏掉不同說法的記錄；僅供縮小範圍，不代表全貌」。AI 轉述數字時必須帶出這個限制（AGENT_RULES）。
  - 隱藏的、超過 `max_sensitivity` 的記錄**不計入**任何數字，也不洩漏其筆數（`withheld` 仍只在權限內的呼叫端有意義，沿用現行行為）。
  - 沒有獨立的統計工具；沒有趨勢判斷或情緒統計。按人物等新分組需求見 ROADMAP。
- **回傳大小**：`results` 每筆只含片段（約 120 字元）、字元數與日期；全文用 `get`。`get` 回傳超過 8000 字元時截斷並標 `truncated` 與 `next_offset`，以 `offset` 取剩餘部分。題庫報告的平均回傳大小是 M5 的驗收指標之一。
- **相容性**：新增欄位一律向後相容；`api_version` 於 M5 起加在所有工具回應，初值 1，未知輸入欄位拒絕。

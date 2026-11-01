# 架構決策紀錄

日期：2026-10-28。`accepted-design` 表示 MODE A 推薦設計；不表示程式或實驗已通過。`provisional` 表示 P0 實測後定案。需求原文不改寫；調整的權威理由在此保存。

## ADR-01：SQLite 單一權威，Markdown 作閱讀投影

- 原方案：Markdown + metadata 為主要資料格式候選，SQLite 作候選索引。
- 選定：`accepted-design`；版本正文、來源、提案確認、收據與 outbox 在同一 SQLite DB，獨立可重建 search DB；完整 JSONL 交換、Markdown 閱讀匯出。
- 理由：本案要求跨實體原子提交及復原。以多檔為權威仍需自建 journal／交易協調；SQLite 已有成熟單檔交易。可讀與遷移需求由匯出滿足。
- 放棄：Markdown + Git + sidecar 收據雙寫；PostgreSQL 常駐服務（目前一人規模不需要）。
- 證據：[atomic commit](https://sqlite.org/atomiccommit.html)、[Backup API](https://sqlite.org/backup.html)；不是本案 runtime 證明。
- 待驗證：字節保真、Windows IO 故障、無損 export、12k 性能。
- 重審：正式要求多裝置並行同步，或直接 Markdown 編輯成為核心互動且可承擔匯入衝突成本。

## ADR-02：保留 Python + CLI，使用薄 MCP

- 原方案：Python、CLI／MCP 可替換 Agent。
- 選定：`accepted-design`；Core 不含模型，CLI 和 MCP 共用同一 application service；預選 CPython 3.14，官方 SDK 的相容穩定版本於 P0 鎖定。
- 理由：不需自寫協定，主要成本在資料規則而非原生計算；Python stdlib sqlite3 足以啟動驗證。
- 放棄：大型 Agent Framework、產品多 Agent、因單一搜尋器而全核心改 Rust／TypeScript。
- 證據：[sqlite3](https://docs.python.org/3/library/sqlite3.html)、[官方 MCP SDK](https://github.com/modelcontextprotocol/python-sdk)、[Python lifecycle](https://devguide.python.org/versions/)。
- 待驗證：SDK／Python／Windows wheel 相容性、真實 Agent 雙新會話。
- 重審：支援 runtime 結束維護、Windows 發布需過多原生編譯或效能經 profile 證明受語言限制。

## ADR-03：不 fork 現成記憶產品

- 原方案：未決定自建或採用現成方案。
- 選定：`provisional`；小型 Core＋成熟組件；Basic Memory 是 P0 最值得重查的 extension 候選。
- 理由與證據：見 [現成系統評估](RESEARCH_EXISTING_SYSTEMS.md)實際程式碼。候選已有保真、衝突／交易或 purge 等能力，不能用「全部沒有」當結論；差異在完整契約與維護範圍。
- 放棄：以 Stars 選型、為不需要的 graph／同步／自動重寫流程承擔 fork 成本。
- 待驗證：限定 contract probe 與改造成本，而非憑 README 估工時。
- 重審：現成方案可在不改核心、不保留繞道寫入的情況通過 W/P/B/S，且長期升級成本更低。

## ADR-04：FTS5 + 短詞掃描，語義搜尋延後

- 原方案：rg／FTS5／Tantivy／Embedding 多候選。
- 選定：`provisional`；FTS5 trigram + unicode61，1–2 字精確掃描，明確詞組別名；以 TEST_PLAN 門檻決定是否改 Tantivy+Lindera。
- 理由：5k–12k 範圍先用低部署成本成熟工具；短詞與字形問題要實測，不預設英文 tokenizer 適用 CJK。
- 放棄：自製倒排引擎、預設大型向量庫、將繁簡或翻譯視為 Unicode normalization。
- 證據：[FTS5](https://sqlite.org/fts5.html)、[Tantivy tokenizer](https://docs.rs/tantivy/latest/tantivy/tokenizer/index.html)、[Unicode](https://unicode.org/reports/tr15/)。
- 待驗證：Q/L、別名誤匹配、long-token 與短詞壓力。
- 重審：金標召回低於門檻或短詞掃描超時無可接受補救；Embedding 必有未共詞漏召回證據。

## ADR-05：同帳號只作合成開發，私人模式隔離 SID

- 原方案：Windows 最小權限待定，MCP 確認不等於隔離。
- 選定：`accepted-design`；不同非管理員 SID、受信任 owner session、named pipe allowlist、正式 read grant 和 approval；P0/R 驗證 Agent 可用性。
- 理由：同權限 Shell 可直接改庫或偽造確認。僅增加更多提示文字無法建立安全邊界。
- 放棄：同 SID secret file、`confirmed=true`、MCP annotations 作授權、Agent 能操作的同桌面核准 UI。
- 證據：[Microsoft pipe security](https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights)、[MCP tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)。
- 待驗證：DACL、pipe impersonation、安全 session、實際 Agent；不得假設 Codex Desktop 目前就能滿足。
- 重審：獨立 CLI／VM 都不能保持可接受使用體驗；此時需使用者對體驗／威脅模型作重大選擇，不能默默改成弱隔離私人模式。

## ADR-06：持續授權、有限保存委派與獨立三種確認

- 狀態：`accepted-design`，2026-10-29 依使用者本次明確要求修訂；只取代讀寫授權／確認政策，不更動資料、搜尋、版本、備份或階段範圍。
- 被取代的 2026-10-28 規則：read grant 預設 15 分鐘／單一任務且新會話失效；每份保存提案都要 digest-bound owner approval。原決策將人類逐筆確認當作必要條件，本次不再適用於已委派的日常保存。
- 選定：owner 首次分開授予可信任 principal 持續 read 與有限 save scope，直到撤銷或選定期限；正常新會話／重啟重新驗身分即沿用。使用者明確要求保存時，由 Agent 辨識意圖，Core 檢查現行 grant 並為不可變提案授權，免重複人工確認。沿用現有 Core、grant／revoke、proposal、confirmation、CAS 與 receipt，不新增模組。
- 理由：符合自然語言日常使用需求，同時維持可強制的身分、最小範圍、撤銷和 OS 隔離。Core 無法僅從 Agent 請求獨立證明使用者意圖；首次授權明確委派這項判斷，`auth_method=delegated_agent` 如實記錄，不冒稱逐筆人工審閱。
- 保留：原文核對／事實確認獨立；未委派及破壞性／維運操作仍走原 owner 規則。提案變更後舊授權失效，新提案在原意圖與 grant 內重新驗權，不強制再彈窗。
- 不採用：單憑 `user_confirmed=true` 直接寫入、把讀取授權當寫入授權、同名 Agent 冒用、Agent 自行擴權或自動存一般對話。沒有可驗證來源的訊息參照只是稽核資訊。
- 依據：v0.5 §3／§8–10／§20 加 2026-10-29 使用者最新權限修訂；正式語意見 SECURITY §4–5、DATA_CONTRACT §5–6。來源基線不改寫。
- 待驗證：W09–11、S01–13、E/U；包含跨正常重啟不重授、撤銷競爭與已授權 Agent 偽報意圖的限制。上述是規格，未實測。
- 重審條件：若使用者要求 Core 強制證明每筆確有真人指令，現有委派不能滿足；需可驗證的使用者輸入來源或回到逐筆 owner 確認。這類整合不在本次新增範圍。

## ADR-07：完整版本和 lifecycle 分離

- 原方案：Record／Revision 概念，具體格式未定。
- 選定：`accepted-design`；Revision 保存完整正文／metadata，撤回／reinstate／delete 用另行 state_version；新世界狀態用新 Record。
- 理由：規模不需 diff chain 壓縮；完整版本易校驗與引用。刪除為明確歷史保留例外，保留無正文 tombstone。
- 放棄：用 Git commit 作 Record revision、TTL 自動刪除版本、用新立場覆蓋舊立場。
- 證據：v0.5 §4–11；完整快照是本案工程判斷。
- 待驗證：schema constraints、來源閉包、export roundtrip。
- 重審：大量超長文件導致實測儲存成本不可接受；即使壓縮也不得改變邏輯引用。

## ADR-08：備份用 restic，最新 safety 狀態獨立保留

- 原方案：Git 輔助＋獨立加密備份，舊備份防復活尚無實作細節。
- 選定：`accepted-design`；一致 snapshot + restic；安全意圖先在獨立媒介 prepared，再 primary commit + outbox finalized。還原先套用未解決意圖的保守隔離，再合併已完成事件。
- 理由：舊 snapshot 不可能包含之後刪除。安全狀態全遺失時 fail closed 是資訊限制，不是假裝可自動解決。
- 放棄：自製加密／備份引擎、Git 作唯一備份、只在舊快照內放 tombstone、忽略離線副本。
- 證據：[restic format](https://restic.readthedocs.io/en/stable/100_references.html)、[forget/prune](https://restic.readthedocs.io/en/stable/060_forget.html)。
- 待驗證：prepared／primary／finalized 各切點中斷、最新證明丟失、restic 去重殘留與乾淨還原。MODE A 自審已排除「只在 primary 後非同步鏡像」方案，因主媒介在鏡像前損毀會失去後續刪除證據。
- 重審：使用者需要多裝置寫入；需擴展安全事件合併協定，不自動當作單機解決。

## ADR-09：單寫入、rollback journal 優先

- 原方案：SQLite 候選但無 journaling 決策。
- 選定：`provisional`；authority 用 DELETE + EXTRA、本機 NTFS、明確交易；沒有多分鐘 read transaction。
- 理由：一人低頻寫入先降低 WAL sidecar／checkpoint 管理成本。不是宣稱 WAL 不可靠；有性能證據再換已修補版本。
- 證據：[PRAGMA synchronous](https://sqlite.org/pragma.html#pragma_synchronous)、[WAL-reset](https://sqlite.org/wal.html#walreset)：官方列 3.51.3 及 backport 3.44.6／3.50.7 修補。實際 runtime patch 須重查。
- 待驗證：F/L、VM 強制關機與 OS flush 行為；EXTRA 不能保證壞硬體耐久性。
- 重審：讀寫競爭使正常操作超標；不得直接改 synchronous=OFF/NORMAL 迴避測試。

## ADR-10：聚合掃描屬正式 V1，不把 Top-k 當全量

- 原方案：長期聚合與摘要可能需要範圍掃描。
- 選定：`accepted-design`；P4 固定 manifest、逐批完整閱讀、反例核對與 coverage；摘要 cache 可選，敏感推論不自動保存。
- 理由：早期 MVP 先保證可靠保存取回，正式 V1 才宣稱跨時間完整範圍分析。
- 放棄：自動月報、全庫模型升級重算、以 Token 限制偷偷縮小分母。
- 證據：v0.5 §15–16／§22，具體分析正確性須 G 測試。
- 待驗證：long-document 範圍續作、snapshot 增刪競爭、Token 最佳化不丟反例。
- 重審：實測使用者問題不需此能力可重新界定發布，但不得自行取消已要求的跨時間產品能力。

## 版本維護原則

修改決策時新增 supersedes／日期／原因，保留曾經驗證的證據與失敗紀錄。產品原則的重大衝突需向使用者提出；純實作細節可依證據自行選擇。未開始任何 P0 實驗，以上選型不可寫成已完成工程驗證。

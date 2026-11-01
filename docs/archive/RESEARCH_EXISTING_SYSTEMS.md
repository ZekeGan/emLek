# 現成系統與官方技術證據

查證日期：2026-10-28。方法：官方文件、GitHub repository metadata、目錄與實際程式碼讀取；**沒有安裝、執行或 benchmark 這些專案**。分支可能變動，下列 blob SHA 表示本次取得的個別檔案版本，不是誤稱整個 repository 的 commit SHA。無法從所讀路徑證明的能力標為未驗證，不把「未見到」寫成「不存在」。

## 1. 決策摘要

本案推薦自建**小型資料契約與授權 Core**，重用 SQLite、官方 MCP SDK、restic、既有全文搜尋器；不 fork 整個現成記憶產品。理由是本案的核心成本在保存／原文／事實三種確認、不可漂移的歷史版本引用、隱私刪除與備份恢復規則。候選專案雖有相關機制，但套用本案完整契約仍要修改權威寫入與資料生命週期，且要承擔不需要的功能面。

這不是證明自建一定較便宜：P0 保留對 Basic Memory 擴充路線的成本復核。若能以窄 extension、不 fork 核心，通過 W/P/B/S 全部契約，應重新評估；不因已寫規劃而排斥新證據。

| 專案 | 可借用價值 | 本案主要不適配／待驗證 | 決定 |
|---|---|---|---|
| obsidian-second-brain | 可讀 Markdown、原文字節處理、Agent 工作流 | 直接筆記改寫語意；未證明全部交易收據與可信確認契約；較多自主整理功能 | 參考，不作權威 Core |
| gbrain | 寫入協調、request receipt、revision conflict、owner purge、殘留報告 | 功能與 PostgreSQL/PGlite／多儲存路徑較多；三種確認及本案 Windows 隔離／備份復活契約未驗證 | 借鑑可靠性模式，不整體採用 |
| Basic Memory | Python/MCP、accepted-note DB 交易、可修復索引發布 | 可選前置 checksum 與編輯筆記語意需收緊；每版不可變來源、核准與完整清除需補 | 最接近的擴充候選，預選不 fork |
| Joplin | 成熟個人筆記、可讀資料、修訂和恢復 | 修訂採間隔／TTL，不是每次正式提交完整不可變版本；主入口為筆記應用 | 可作未來受控匯出目的地，不作權威歷史庫 |

## 2. obsidian-second-brain

[專案](https://github.com/eugeniughelbur/obsidian-second-brain)本次 metadata 為 MIT；不是因 Stars 判定可靠。實讀 [scripts/note_io.py](https://github.com/eugeniughelbur/obsidian-second-brain/blob/main/scripts/note_io.py)（blob `a7ecec1c75ad8cf0c0a66489cbefc55c037d8438`）：採 strict UTF-8、保留 BOM／換行、同目錄 temporary file 再 replace；`write_exact_if_unchanged` 在寫前比較原內容，原碼亦明示 comparison→rename 不是原子 compare-and-swap，且 fsync 失敗採 best effort。

這是有價值的原文保真實作，不能稱它「任意損壞文字」。但檔案級 replace 不等於 Record、Revision、approval、operation receipt 同交易，對本案仍需另建持久核心。[vault_search.py](https://github.com/eugeniughelbur/obsidian-second-brain/blob/main/scripts/vault_search.py)將查詢交給 vault_ops 並可關 semantic；該 wrapper 本身不足以證明中文召回或完整聚合。

未驗證：Windows 原生安裝與 IPC 隔離、權威版本來源圖、舊備份刪除對帳、完整 CJK benchmark。推薦保留其字節保真與使用者可讀資料觀念，不採用自動重寫筆記作核心歷史管理。

## 3. gbrain

[專案](https://github.com/garrytan/gbrain)本次 metadata 為 MIT，預設分支 master。實讀 [engine-factory.ts](https://github.com/garrytan/gbrain/blob/master/src/core/engine-factory.ts)可見 PGlite／Postgres backend；[storage-config.ts](https://github.com/garrytan/gbrain/blob/master/src/core/storage-config.ts)有 db_tracked／db_only 等儲存分層。不是單純一個 Markdown 搜尋腳本。

[preconditions.ts](https://github.com/garrytan/gbrain/blob/master/src/core/persistence/preconditions.ts)（blob `a7f049244261d4472ce3d7e575f09de3fd5a8683`）定義 request_id、expected_revision 和 force 互斥規則；[coordinator.ts](https://github.com/garrytan/gbrain/blob/master/src/core/persistence/coordinator.ts)（blob `d298a171e5651158e5f1e2766f50438cd0247541`）可見持久 request、交易內 recheck、publication staging 與 recovery 邏輯。不能以「沒有衝突檢查或恢復」為理由拒絕它。

[forget-purge.ts](https://github.com/garrytan/gbrain/blob/master/src/commands/forget-purge.ts)（blob `bc3ecef5e58f5ad6d650b4e610026cec410ec51f`）先 dry-run、確認、帶 expected revision／request ID，並有 pending effects 與 residuals 報告。其 CLI 非互動 `--yes` 路徑與 owner 概念，不等於已驗證本案的 Windows 人類確認隔離；且源碼區分 live-store purge 和 physical erasure。

不整體採用的工程判斷：將本案較窄的一人文字庫接到其較多 storage/engine/publication 路徑，仍要驗證及收緊三種確認、完整版本引用和安全帳本。現階段評估新增的依賴／升級面不划算，**不是已量測的工時結論**。Windows 安裝、CJK、備份防復活均未執行驗證。

## 4. Basic Memory

[專案](https://github.com/basicmachines-co/basic-memory)與 [LICENSE](https://github.com/basicmachines-co/basic-memory/blob/main/LICENSE)本次為 AGPL-3.0。讀到的程式已超過「Markdown 唯一權威＋單純快取」的舊印象，不能依舊版介紹下結論。

[note_content_writes.py](https://github.com/basicmachines-co/basic-memory/blob/main/src/basic_memory/services/note_content_writes.py)（blob `30fc7e439833a0189ae67e4bde650a9dbad32cf5`）透過 accepted_note_transaction 接受 mutation；`expected_checksum`／`base_checksum` 支援交易內衝突檢查，但可選，未提供仍可寫。`_finish_mutation` 在 committed content 後更新 search／graph，失敗保留已接受內容並允許後續修復。這與本案「提交和索引分開」方向相容。

[note_write_outcomes.py](https://github.com/basicmachines-co/basic-memory/blob/main/src/basic_memory/services/note_write_outcomes.py)（blob `12a44d78444f3f1ad8889eaf0a3be0c124f206fa`）有 AlreadyExists／RevisionConflict 等結果。這些是實際程式證據，但不證明所有來源版本都不可變或已具本案的 owner-confirmed authorization。

選擇：最值得 P0 重新比較的 extension 候選；本次不把它當依賴。若擴充須 fork accepted-note 核心、禁止原來的繞道寫入、全面補 safety ledger，維護成本可能接近小型 Core。AGPL 的完整發布義務要在實際採用／散布時逐項核對；本次只閱讀並借鑑模式，未複製程式碼。

## 5. Joplin

作為成熟個人筆記平台的對照：[專案](https://github.com/laurent22/joplin)、[LICENSE](https://github.com/laurent22/joplin/blob/dev/LICENSE)。根授權為 AGPL-3.0-or-later，子目錄可有不同授權，不能把全 repository 視為單一 license。

實讀 [RevisionService.ts](https://github.com/laurent22/joplin/blob/dev/packages/lib/services/RevisionService.ts)（blob `e2aea82a1f1513a1a6a8c7e1e804fe812711cb9f`）：依 intervalBetweenRevisions 建立差異版本、背景收集、TTL 清舊版本，恢復時建立 note；也有刪除歷史與重設舊內容 cache 的處理。這適合筆記撤銷／恢復，但其版本採樣及清理語意不直接滿足「每次確認保存都有可永久引用版本」。

不 fork 的理由是產品責任不同；若只需一般筆記應用它更省事，但本案不能取消嚴格來源／確認／歷史契約。未來可匯出 Markdown 供 Joplin 閱讀，任何反向修改必走受控匯入。

## 6. 共用基礎技術證據

| 來源 | 本次可支持的事實 | 不能據此宣稱 |
|---|---|---|
| [SQLite atomic commit](https://sqlite.org/atomiccommit.html) | 單 DB transaction 的原子提交設計 | 多檔自動一致、硬體永不失效 |
| [SQLite Backup API](https://sqlite.org/backup.html) | 有一致 snapshot API | 任意複製活躍 DB 都安全 |
| [SQLite corruption 說明](https://www.sqlite.org/howtocorrupt.html) | 外部改檔、錯誤備份、sync／硬體有風險 | checksum 可替代權限 |
| [SQLite FTS5](https://sqlite.org/fts5.html) | trigram／unicode61 有既定能力與限制 | 中日英品質／短詞性能已達標 |
| [SQLite WAL](https://sqlite.org/wal.html#walreset) | 官方記錄 WAL-reset bug 與修補版本 | 安裝任一新版 Python 即等於已修補 SQLite |
| [Windows named pipe ACL](https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights) | 可針對 pipe 設 DACL，default/generic rights 需注意 | 同 SID 可安全區分人與 Agent |
| [restic format](https://restic.readthedocs.io/en/stable/100_references.html) | 備份 repository 有加密及完整性格式 | 未保管密碼仍可恢復 |
| [restic forget/prune](https://restic.readthedocs.io/en/stable/060_forget.html) | 移除 snapshot 和清資料是分開步驟 | 清一個 snapshot 即清所有被別處引用的內容 |
| [MCP tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) | 共用工具 schema 和結果傳遞 | MCP 本身是 OS 權限或人類身分證明 |

## 7. 查證界限與更新政策

本次證據限選定 source paths 與官方說明，不是完整安全稽核。沒有複製或執行第三方安裝腳本，沒有用 README、Stars、AI 評價代替 runtime 測試。P0 在有開發授權後固定實驗版本／完整 commit、重現所需能力與 contract probes，保留相同語料和測試門檻。

外部分支變動時先比對本表 blob；若變更影響採用判斷，再更新 ADR 和此報告。不必每個任務重查所有專案，也不能因某個新 feature 宣傳就改變產品原則。

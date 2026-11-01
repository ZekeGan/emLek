# 可恢復的實際進度

最後更新：2026-10-29（Asia/Tokyo）。本檔只記實際狀態，未執行的工作不能標通過。

## 目前階段

- 模式：**MODE A 已完成**；文件建置與一致性檢查通過，等待正式開發授權。
- 使用者於 2026-10-29 明確要求只修訂 Agent 讀寫權限文件；MODE B 尚未授權，本次不作程式開發或 Git Commit／Push。
- 工作區：`D:\Programming\Project\Remtrace`，初始為空資料夾，沒有 Git repository 或產品程式。
- 未建立產品程式、依賴環境、測試 Vault、系統帳號或服務；未讀取真實私人記憶資料。

## 已完成

- 讀取兩份實際附件，原樣保存至 baseline；保留主控指令和 v0.5 原文。
- 完成 v0.5 全 26 章需求映射、MVP／正式 V1／P5 邊界。
- 查核 obsidian-second-brain、gbrain、Basic Memory、Joplin 的實際 source paths，記錄可證明／未驗證能力與採用判斷。
- 查閱官方 SQLite、Python、MCP、Microsoft IPC、restic、Tantivy／Unicode 資料；沒有執行第三方程式。
- 建立根目錄 AGENTS、CLAUDE、README，docs 的 13 份必要文件，加現成系統研究報告。
- 定義 SQLite 權威交易、不可變 Revision、三種確認、冪等、索引恢復、隱私閉包、隔離恢復與 Windows trusted approval。
- 自審修正安全帳本的災難空窗：改為獨立媒介先 prepared，再主庫交易，再 finalized；不把非同步鏡像延遲隱藏為完整防復活。
- 建立 P0–P4、R 發布關卡及按需 P5 工作單、測試族、量化門檻與續作流程。

### 2026-10-29：僅修訂 Agent 讀寫權限

- 取代 read grant 預設 15 分鐘／單任務／新會話失效，以及所有保存都必須逐筆 owner 核准的規則。首次分開授 read/save；有效授權跨正常新會話／重啟沿用，明確保存指令在有限委派內直接提交。
- Core 仍驗 principal、action/scope、現行撤銷／到期狀態與提案 digest／目標版本。未委派操作、刪除／恢復／權限管理、原文／事實核對維持 owner 保護。
- 如實標記 delegated_agent；現有 CLI/MCP 無法獨立證明指令源自真人，可信任 Agent 在 scope 內誤讀／誤存的風險不宣稱已消除。沒有新增服務、模組或逐次人工流程。
- 本次修改文件：AGENTS.md、README.md；docs 下的 PRODUCT_SPEC、ARCHITECTURE、DATA_CONTRACT、SECURITY、SEARCH_DESIGN（僅分析保存授權句）、TEST_PLAN、ACCEPTANCE、EXECUTION_PLAN、RUNBOOK、DECISIONS（僅 ADR-06）、OPEN_QUESTIONS、PROGRESS。其餘檔案與兩份基線不改。
- 新增／更新的是 W09–11、S13、A/E/U 等**測試與驗收規格**，未執行產品測試。資料模型、搜尋演算法／品質門檻、版本、備份／復原流程及其他產品範圍未重設；僅同步還原時 read/save 授權一律失效的既有安全原則。

## 最後驗證成功的狀態

目前只有文件／來源查閱證據，沒有產品測試。

最新文件驗證 `DOC-AUTH-20261029-01` 通過：以本次修改前的 19 檔 SHA-256／內容快照對照，僅 14 份直接受權限修訂影響的文件改動，新增／刪除檔案均為 0。32 項受保護區段比對一致，包含資料欄位、原文／版本、刪除、安全帳本、搜尋品質／效能、備份還原測試；SEARCH_DESIGN 僅改分析保存授權句，DECISIONS 僅改 ADR-06。CLAUDE、AGENT_WORKFLOW、現成系統研究與兩份基線 SHA-256 保持不變。相對連結 56 個、失效 0、未配對 code fences 0、非 Markdown 檔案 0。檢查使用 PowerShell 讀檔／hash 與記憶體中的修訂前後內容比對，沒有執行產品測試、安裝、Git Commit 或 Push。

文件驗證 `DOC-20261028-01`：於專案根目錄用 PowerShell 遍歷 Markdown、解析相對連結與 code fences、比對兩份來源附件 SHA-256、檢查產品章節映射及非文件檔案，exit code **0**。

| 檢查 | 實際結果 |
|---|---|
| 必需／實際 Markdown 文件 | 19／19，缺漏 0（16 份指定文件＋研究報告＋2 份基線） |
| 相對文件連結 | 56 個，失效 0 |
| 未配對 code fences | 0 |
| 來源附件與基線 SHA-256 | 兩份均完全相同 |
| v0.5 章節映射 | 1–26 全部存在 |
| 非 Markdown／產品程式檔案 | 0 |

可重現重點：用 `Get-ChildItem -Recurse -File` 盤點；`Get-FileHash -Algorithm SHA256` 比對原附件及 baseline；解析 Markdown 相對文件連結並以文件所在目錄作基準 `Test-Path`；對 PRODUCT_SPEC 的 v0.5 映射表檢查章號 1–26。這是文件檢查，不是產品 QA。另已人工交叉檢查 MVP/P1/V1 定義、P0/R gate、確認語意、prepared 安全帳本順序和未驗證標記。

基線 SHA-256（複製後首次讀取）：

| 檔案 | SHA-256 |
|---|---|
| `baseline/MASTER_INSTRUCTIONS.md` | `AA7B16947311EB13A08B23A6CD43DB346CB57738D22D558FD4954016237124C5` |
| `baseline/PRODUCT_V0.5.md` | `83490991BD4AF3865DB8D1F532FB5ACA9DE6138F21DCF2C6F83316EC5B9A5524` |

## 尚未開始／未驗證

| 工作 | 實作狀態 | 驗證狀態 |
|---|---|---|
| P0.1–P0.7 技術實驗 | not_started | not_run |
| P1 最小流程 | not_started | not_run |
| P2 資料核心與恢復 | not_started | not_run |
| P3 搜尋與 Agent | not_started | not_run |
| R 私人發布隔離 | not_started | not_run |
| P4 長期分析 | not_started | not_run |
| P5 擴充 | 未立項、不屬自動實作範圍 | not_run |

## 已知缺陷與重要未知

尚無產品，因此沒有可宣稱已定位的 runtime Bug。設計風險見 [OPEN_QUESTIONS](OPEN_QUESTIONS.md) O01–O06：Windows SID／session 整合、安全帳本媒介與復原、CJK 性能／品質、現成方案改造成本、真實語料代表性、精確 runtime 相容性。

沒有任何測試被隱瞞或標為成功；所有品質、性能、ACL、掉電、備份還原與 Agent 雙會話門檻均未執行。

## 下一次應執行的具體任務

1. **若尚未收到新的「執行」：停止產品工作。** 可依使用者要求繼續修改文件，不自行開始 P0 程式實驗。
2. 收到「執行」後，依 AGENTS→本檔→EXECUTION_PLAN P0 開始；先檢查工作區是否有新的使用者變更。
3. 從 **P0.1** 取得實際 Python／SQLite／Windows／MCP／restic 能力與版本，建立合成開發環境及精確 lock；不要先掃真實資料。
4. 接續 P0.2/3/4/6；P0.5 的實際 OS 隔離若缺必要權限，準備具體測試與權限需求，繼續不受影響的合成工作。
5. 每項有實際 evidence 才更新 verified；完成 gate 後自動進下一個已核准項目，不要求逐功能「繼續」。

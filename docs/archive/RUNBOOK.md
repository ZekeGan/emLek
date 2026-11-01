# 開發與維運手冊

**狀態：預定操作流程。產品尚未實作，以下 `remtrace` 命令與測試路徑目前均不可用。** MODE A 不執行安裝、環境建立、測試 Vault 或系統設定。MODE B 每完成一個命令才以實測 `--help` 和 evidence 更新本手冊；不得保留錯誤的成功示例。

## 1. 開發環境準備（MODE B，規劃）

在專案根目錄檢查目前檔案與權限。Python minor 預選 3.14；P0 先確認受支援 patch 和內嵌 SQLite，測 FTS5／trigram、Backup API、PRAGMA 讀回和 MCP 相容性，再建立 lock。檢查官方工具來源與下載 hash；不執行未知安裝腳本。

預期命令範例（套件描述檔與 lock 建立後才適用）：

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m remtrace doctor
```

lock 應包含 runtime 與 dev 工具及需要的 wheel hash；MODE B 必須確立實際建置 backend 與 build dependencies lock。離線部署準備已驗證 wheelhouse。沒有可用的安全 patch 時先停在環境診斷，不降版到已知漏洞版本。

測試 Vault 預期放 `var/synthetic-vault/`，啟動要求 `--synthetic` marker；測試 config 不可接受默認 home 資料庫。先準備忽略規則，Vault／exports／secrets／backup／evidence 敏感結果不得入 Git。不要自動讀使用者的 Obsidian、聊天資料夾或任何真實 Vault。

## 2. 正常啟動與最小流程（規劃）

1. `remtrace doctor` 確認 profile、路徑、DB schema、SQLite feature、index watermark 和 safety mirror 狀態。
2. `remtrace init --synthetic` 在明確測試路徑建立庫；不得自動升級為 private profile。
3. owner 啟動 `remtrace-owner broker start`。首次以既有 `grant` 介面登記 Agent principal，分別設定 read scope 與 save action/scope，明確知悉由 Agent 辨識保存指令的委派限制；不是只憑 Agent 名稱或 `confirmed=true` 授權。
4. Agent 透過 CLI 或 `remtrace mcp` stdio Adapter 連到已驗證 Broker。使用者明確要求保存後，Agent `propose` 送文字、operation_id 與指令參照；有效 save grant 內由 Core 自動授權確定提案，不要求 owner 再核准。未委派／高風險操作仍由 owner `approve` 檢查完整預覽；原文／事實核對不由委派 save 推導。
5. Agent `commit`，Core 重驗現行 grant／適用的 approval；若結果遺失先 `operation status`，不要換 ID 重送。收據區分 delegated_agent 與人工確認，不把自報指令當成 Core 已驗證的人類訊息。
6. Agent `search`／`get` 引用 Record/Revision，沿用有效 read grant。任務結束、Agent 新會話、正常 Broker 重啟不自動撤銷持續 grant；重連先驗同一 principal。owner 可隨時用既有 `revoke` 撤銷或縮限；只有新身分、擴大範圍、到期或真正還原等原規則情況才需重新授權。

私人部署使用 SECURITY 的不同 SID 與 trusted session；建帳號／設定 ACL／部署實際私人路徑需另有必要權限。不要讓 Agent 在自己可控制的終端代按 approve。

## 3. 測試（規劃）

標準本機命令預期如下；目錄與 markers 在 P1 建立後必須與實作一致：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit tests/integration --junitxml=evidence/local-tests.xml
.\.venv\Scripts\python.exe -m pytest tests/e2e -m synthetic
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src
```

每次建立唯一 evidence run-id 而非覆蓋上述示例報告。Windows ACL／VM 斷電、scale benchmark、實際 Agent E03 需分開環境和記錄。未有權限時標 not_run，不在普通測試中自動修改帳號或全機設定。完整測試族與閾值見 [TEST_PLAN](TEST_PLAN.md)。

## 4. 索引重建（owner，規劃）

1. `verify` 確認 authority integrity、來源與最新 privacy gate；若權威庫壞了先停止，不以索引反推原文。
2. `index rebuild` 建立新 generation；由權威版本掃描，不以現有 FTS 自我複製。
3. 驗 manifest counts、版本、Q01 smoke、排除 withdrawn／privacy 集合，補處理重建期間 outbox。
4. 安全切換 generation，記錄 watermark；失敗保持舊 generation 或明示精確掃描降級。
5. 只清除確認不使用的舊 index；原 authority 不受影響。所有遞迴刪除前解析絕對路徑並驗證在預定 Vault／staging 內。

## 5. 備份（owner，規劃）

首次由使用者選定受控、加密的 restic repository 與密碼恢復方式，不預設雲端或付費後端。資料快照與最新 safety ledger 必須有可獨立恢復的安排，不能全在同一會被覆寫的 Vault 目錄。

`backup create` 預期流程：檢查安全鏡像→Backup API snapshot→從完成快照讀 manifest→verify→restic backup→取得 snapshot ID→校驗→記 success。不是直接 copy 開著的 DB。staging 只 owner 可讀，失敗保留可診斷狀態但不永久散落正文。

restic 原生命令依官方版本確認：`check` 檢查 repository 結構；`check --read-data` 執行資料讀取驗證。日常每次備份後檢查 manifest；發布／定期完整演練須實際還原，不以 repository 可列出 snapshot 代替。建議私人使用每日或重要批次後手動備份、每月完整校驗、每季乾淨還原；本次不建立排程或 automation。

## 6. 隔離還原（owner，規劃）

1. 關閉 Agent 接入，在全新 staging 執行 `restore stage`；不覆寫 live Vault。
2. 驗來源 snapshot、解密、manifest、schema、integrity、正文 hash、來源引用與 operation receipts。
3. 取得不同於舊 snapshot 的最新 safety ledger／freshness 證據，對 ledger identity、vault lineage、最高 safety epoch、prepared 意圖、事件清單與獨立副本核對。先保守套用 unresolved withdraw/delete，pending reinstate 不啟用。
4. replay 最新撤回／reinstate／delete，隔離受污染衍生，清除隱私內容；未知新鮮度時回 `RESTORE_RECONCILIATION_REQUIRED` 並停止啟用。
5. 失效所有 pending approval 與 Agent grants（read/save），維持真正還原後重新授權的原規則；重建 search，跑 D/P/B smoke。
6. `restore verify` 產生差異與完整性報告，owner 才能 `restore activate`；切換 deployment generation。
7. 保留原庫直到新庫驗證與啟用完成；不自動刪除舊庫，先納入副本清單與隱私政策。

若主機與最新 safety 狀態全毀，無法知道舊備份之後的刪除；維持 owner-only quarantine。不要輸入一個「忽略」旗標就重新開給 Agent。若只保有舊內容，逐項核對／作新提案是替代流程，並非完整恢復成功。

## 7. 隱私清除（owner，規劃）

先看 privacy proposal 的 IDs、所有 revisions、衍生閉包、export／staging／backup 殘留清單，核准後立即停止普通可見性。`privacy status` 顯示每目標進度；中斷以同 job/operation ID 續作。

依資料契約清理主庫、索引、暫存、提案、受控副本。先建立無目標內容且可還原的乾淨 backup，再列受影響 snapshot IDs 的清除計畫。真實舊備份清除不可逆，需 owner 對具體列表核准；`forget`、`prune`、`check --read-data` 結果分別記錄。仍被其他 snapshot 引用、離線媒體未處理或第三方未知的副本，不能標全部清除。

清除不是退出即成功；必須 P 的 sentinel、舊游標、舊備份還原防復活測試通過。SQLite／FTS 清除不等同硬體抹除。

## 8. 常見故障

| 症狀 | 處理 |
|---|---|
| commit timeout | 保留 operation ID，查狀態；成功就取收據，未確定不改 ID |
| index failed/stale | authority get 仍可用；查 outbox，重試或重建，標 incomplete |
| revision/state conflict | 重新讀被允許版本、比較差異、新提案並重驗授權；同意圖／委派內免重複人工確認，不 force overwrite |
| grant 撤銷／到期／scope 不符 | 拒絕新讀取與未提交寫入；不自行擴權或重啟來繞過。只有 owner 可更新權限 |
| 正常重啟後失去連線 capability | 驗同一 principal 並由仍有效持續 grant 自動重發；不把連線憑證失效當持續授權已撤銷 |
| SQLite busy | 確認只有一個 writer，結束過長 read transaction，有限重試；不刪 hot journal |
| 磁碟滿 | 停止寫入，盤點受控暫存；不可任意刪備份或 authority；空間恢復後查狀態 |
| integrity failure | 停服務，保留故障副本，從已驗證 snapshot 隔離還原；不自動修補原文 |
| safety mirror pending | 本機阻斷仍有效；修復鏡像／獨立備份，禁止宣稱防復活完成 |
| safety ledger unavailable | 停止正式安全狀態變更並暫停 Agent 讀取；恢復指定獨立媒介，不建立空白帳本假裝沒有歷史 |
| ACL／pipe 驗證失敗 | fail closed；檢查 SID、繼承、server 身分與安裝路徑，不能退回 Everyone |
| 缺備份密碼 | 使用已安排恢復流程；不猜測、不把明文秘密傳 Agent |
| runtime／SDK 升級失敗 | 使用原 lock 與 wheel，驗 migration／safety 狀態後回復；不得回滾刪除 |

## 9. 更換 Agent 與維護升級

新開發 Agent 從 AGENTS→PROGRESS→EXECUTION_PLAN 目前工作單開始，只讀必要規格。產品 Agent 的新會話沿用同一已驗證 principal 的有效 grant，不需移植舊對話記憶或重新人工授權；真正更換 Agent principal 需 owner 另授權，不能冒用舊身分。不得以舊 Agent 的敘述當作庫內已保存證據。

每年檢查 runtime／SQLite／SDK／restic 支援與已知安全修補；固定新版本後在合成庫做 migrations、backup restore、S/Q 回歸，再交 owner 更新私人部署。完整 JSONL 是離開本系統的保險，不要求使用者永遠維護同一套 Python。

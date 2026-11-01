# 測試計畫與量化門檻

**本文件全部是待執行規格，沒有任何產品測試已通過。** MODE A 只做文件完整性、連結與需求映射檢查。產品測試自使用者正式啟動 MODE B 後執行。

## 1. 測試資料、環境與證據

- `F-small`：150 份合成／可合法使用的公開文字，含繁中、日文、英文、混合、歧義、撤回、修正、衍生及跨三年以上事件；不得偷偷收集私人資料。
- `F-quality`：在上述語料上先標註 60 題定位題，每語言組至少 15 題；相關 Record/Revision、必需來源、負例、查詢範圍及 expected answer 由人工檢查。另有 12 題聚合題、30 題 Agent 分流題，互不混作搜尋分數。
- `F-real`：日後另獲授權的 100–300 份代表性真實文字及至少 50 題；無授權即 `not_run`，合成品質結果不能稱為真實資料準確率。V1 可以合成驗收發布，但報告必須揭露未驗證個人語料品質。
- `F-scale`：5,000／12,000／25,000 份文件（原始與衍生總量）；平均正文 8 KiB、P95 約 32 KiB、最大 1 MiB，固定 seed。平均 1.5 revisions，另有單筆 100 revisions、多層引用及隱私刪除閉包。必報 actual bytes、record/revision 數，不能用大量空文件灌數。
- 參考機：Windows 11 x64、4 核心、16 GiB RAM、本機 SSD／NTFS；記實際 CPU、RAM、Python patch、SQLite version／compile options、套件 lock hash、磁碟與安全 profile。不同機型不可直接比較單一耗時。

每次證據放 `evidence/<run-id>/`（MODE B 才建立），包含 source revision／source digest、命令、環境、fixture seed/hash、開始結束時間、exit code、JUnit／JSON 報告、完整與失敗測試數、限制。正式資料報告不含原文；測試日誌不能包含密鑰。fixture 和 expected labels 在比較前凍結，變更須說明原因與前後結果。

## 2. D：資料契約單元與性質測試

| ID | 操作／輸入 | 通過條件 |
|---|---|---|
| D01 | 中日英、emoji、組合字、全半形、CRLF/LF/BOM、引號、Markdown 分隔符往返 | 接受邊界後 body bytes 與 hash 完全相同；引用 slice 逐字相同 |
| D02 | 非法 UTF-8、surrogate、超過大小上限、重複 JSON key | 明確拒絕，零新 Record／Revision |
| D03 | 錯字修正 vs 兩年後改變決定 | 前者同 ID r2，後者不同 ID；r1 可依政策讀取且未變 |
| D04 | author=human、channel=MCP；AI 報告由人貼入 | 不把 submitter 誤作作者；unknown 不補造 |
| D05 | save/verbatim/fact 的所有組合、委派保存及 statement scope | 三者獨立；委派只產生 save，無法偽造 owner、verbatim/fact 或提升 fidelity／factual status |
| D06 | 來源 r1 更新 r2、摘要引用 r1 | 引用仍為 r1、標新版存在；不自動漂移或覆寫摘要 |
| D07 | 來源不存在、跨 vault 未匯入、自引用、循環引用 | 拒絕並保持交易前狀態；多跳 lineage 不重複增信 |
| D08 | 年／月／未知事件時間、跨時區、clock rollback | 不造假日期；排序依 commit_seq，範圍精度正確 |
| D09 | withdraw、歷史讀取、reinstate、delete 後 amend | 預設排除撤回，明確歷史可讀帶標籤；已刪除永不 reinstate |
| D10 | 1,000 組 property-based 事件序列 | 全程滿足版本、引用、冪等、可見性不變量；固定 seed 可重現 |

通過：全部通過，沒有以 xfail/skip 隱藏核心失敗。這些測試驗證行為與不變量，不只比對函式內部實作。

## 3. W：交易、確認與並行整合

| ID | 情境 | 通過條件 |
|---|---|---|
| W01 | 同 operation 20 次重送、回覆丟失後查狀態 | 恰好一筆有效變更、同收據／ID／revision |
| W02 | 相同 operation 不同正文／metadata／action | `IDEMPOTENCY_CONFLICT`，不變更原結果 |
| W03 | 人工核准／委派授權後改提案任一欄、來源或目標版本 | 舊 digest 授權不可使用；新提案須重驗，原意圖及有效委派範圍內免重複人工確認 |
| W04 | 10 client 同時以同 base revision 修正 | 至多一個成功，其餘衝突；沒有 lost update |
| W05 | revision 不變但目標已 withdraw/delete | state_version 檢查拒絕過期操作 |
| W06 | 人工 approval 過期，或實際使用的 grant 撤銷／到期／錯 caller／錯 vault | 無有效授權的未提交操作全部拒絕；舊紀錄不替代現行 grant；已成功同 ID 重試仍回安全收據 |
| W07 | 來源刪除與衍生建立競爭 | 要麼先建立後被隔離，要麼建立拒絕；不存在可查污染衍生 |
| W08 | 提案 pending/rejected/expired | 正常 search/scan 不可見；TTL 與立即隱私清理有效 |
| W09 | 首次 read grant 後多次查詢、Agent 新會話、Adapter／Broker 正常重啟 | 重新驗同一 principal 後可讀原 scope，新增人工確認次數 0；未授權的新 principal 拒絕 |
| W10 | 使用者明確保存，create grant 與另有 amend grant 的限定目標 | scope 內可直接提交，額外人工確認 0；只有 read grant、錯內容類型／目標或未授 amend 時拒絕委派提交；記真實 Agent 與 delegated_agent，不冒充人工核准 |
| W11 | 撤銷／縮限持續 grant，並在快取授權、pending commit、舊游標和自動重連中競爭 | 撤銷／縮限生效後的新輸出與未提交寫入按現行 scope 拒絕，不能重發舊權限；已完成收據不被重寫 |

每個競爭情境至少 100 次，以 transaction barrier 重現關鍵交錯；不依賴隨機 sleep 假裝測到競爭。

## 4. F：故障注入與恢復

在以下切點使用獨立 process kill／明確錯誤注入，每點至少 20 次：提案落盤後、安全意圖 prepared 前／後、交易第一筆寫入後、COMMIT 前、COMMIT 後回覆前、索引寫入前／後、outbox ACK 前、安全鏡像 finalized 前／後、backup staging 中途、index generation 切換中途。

通過條件：authority 無半版本／孤兒確認；未提交不存在成功 receipt，已提交可找回；同 operation 重試不重複；索引可重建；已生效刪除不因 worker 失敗可見。執行 `integrity_check`、`foreign_key_check` 與 contract verify 全部成功。

另測磁碟滿、唯讀磁碟、locked DB、invalid SQL schema、被截斷的 authority、毀損 search DB、path 被 reparse point 替換。authority 毀損必須 fail closed，不能把搜尋快取當主資料重建。

process kill 不是硬體掉電測試。P0/R 在隔離 VM 另外做至少 10 次強制關機／還原，檢查已回報 commit 的耐久性；仍須記錄檔案系統／儲存硬體對 fsync 的假設，不宣稱涵蓋所有裝置故障。無法做 VM 測試不得標成已驗證。

## 5. P：隱私刪除

建立 A 原文→B 摘要→C 年度分析，再加另一獨立來源 D、A 的多版、待核准提案、搜尋 cache、export、scan 舊游標及兩份舊 backup。

- P01：刪 A 的阻斷交易完成後，即使停掉 index worker，新 search/get/history/scan/export 不回 A/B/C 的正文、標題、片段或敏感 facet；D 不受影響。
- P02：舊 read grant、舊游標、舊摘要 cache 和 operation 重試不能復活 A。
- P03：清除所有 A revisions、衍生清除範圍、提案 payload 和 staging；已登記受控檔案作 sentinel 搜尋無殘留。已傳給外部平台的副本明列不受控制，不算本機測試通過即已清除。
- P04：中斷 purge 後可續作，每目標狀態可查；本機阻斷保持，不能只以 job 文字顯示成功。
- P05：最新 safety mirror 缺失／落後／毀損時，舊 backup activation 必須被拒絕。
- P06：來源修正不等同隱私刪除；合法歷史摘要仍可引用 r1，避免過度清除。

全部確定性案例 100% 通過。可控檔案清理與物理媒體鑑識抹除分開報告。

## 6. B／M：備份、還原與遷移

| ID | 操作 | 通過條件 |
|---|---|---|
| B01 | 活躍寫入期間 Backup API snapshot，再 restic 備份 | manifest 對完成快照；完整性、引用、收據皆一致 |
| B02 | 全新空白環境還原，原 Agent 會話不存在 | ID、revision、正文 hash、來源、確認與可見性相等，索引重建成功 |
| B03 | snapshot 後 withdraw/delete，然後還原舊 snapshot | 與最新 safety ledger 合併；撤回不誤活化、刪除不返回 |
| B04 | 缺密碼、錯密碼、截斷快照、缺 safety ledger | 明確拒絕，不改現用 Vault，不啟動 MCP |
| B05 | `forget` 尚未 `prune`、仍有另一快照引用 | 不回 backup cleanup complete；清理並 `check --read-data` 後才完成 |
| B06 | prepared 後 primary 前、primary 後 finalized 前中斷，並模擬主媒介全失 | 獨立 ledger pending 仍封鎖目標與衍生；reinstate 不誤啟用；失去所有新鮮 ledger 時拒絕啟用 |
| M01 | export JSONL → 全新 Vault 匯入／驗證 | 正文 bytes、所有版本、來源與 lifecycle 可對應；授權 capability 不被沿用 |
| M02 | schema N→N+1、失敗、中止、重試、rollback | 零資料丟失；ID／版本引用一致；安全狀態不回滾 |
| M03 | 未知未來 schema | 拒絕寫入，不默默丟欄位 |

12k 參考庫：本機備份與校驗目標 5 分鐘內；乾淨環境已備妥 runtime 後，還原、驗證及重建總計 15 分鐘內（不含下載與人類輸入）。RPO 是最近一次**已驗證且有最新 safety 狀態**的備份時間，不宣稱零資料遺失。

## 7. Q：搜尋品質

先用標註的 relevant sets 計算，不能只讓生成答案的模型自評。

- Q01 確定性詞組：一字／二字中文、日文、人名、ID、已核准 alias、exact raw、quote bytes、明訂 filter，全部 100% 通過。
- Q02 60 題定位：整體 Recall@20 ≥0.90，每語言組 ≥0.80；MRR@10 ≥0.80。無相關答案題單列誤報率，不混入分母。門檻是預定發布要求，不是測得準確率。
- Q03 繁簡／日本字形／全半形：已定義 alias 可命中；未定義 alias 不承諾。必含同名字、人名異體、多義轉換的 false-positive 負例。
- Q04 中日英混合及特殊 query：依 AND/OR/phrase 規則結果可重現；引號、百分號、SQL／FTS 語法不能執行任意查詢。
- Q05 同來源的 20 份摘要不壓掉原始證據，來源／衍生分組正確；新版／撤回／刪除過濾正確。
- Q06 index 落後／整庫毀損：補掃描或 incomplete，不能默報完整零筆。

每次報 p/r 分數、逐題漏召回與誤召回、排名差異及 corpus hash。別名／tokenizer 調整需同一保留測試集檢查，不用所有標註題調參後自稱泛化通過。

## 8. G：聚合與 Token

12 題包含：三年立場變化、先否定後支持、重複構想、有完成反證、未知事件日期、整年無紀錄、單篇長文末尾反例、來源多版本、摘要互相引用、半途取消、刪除中斷與新增資料競爭。

通過條件：manifest 無漏頁／重複計數；完整閱讀字節 ranges 可核對；coverage 分類總和相等；未處理／失敗不能標 complete；跨頁新增不污染 snapshot；刪除立即阻斷。金標每項必要支持與反例引用均出現且版本正確，捏造引用為 0。回答必須指出未保存／時間缺口與偏差，不把未完成紀錄當成確定未完成。

Token 報告含實際 tokenizer／model、輸入輸出量、byte 比率、摘要層和原文覆蓋。若測試 summary 路徑，對全量原文參考流程目標減少輸入 Token ≥30%，同時 12 題必要證據／反例保留 100%；否則停用該最佳化，保留完整分批掃描。沒有已授權模型或 token 計數器時，模型品質／Token 數據標未驗證，不借用 byte 數宣稱通過。

## 9. A／E：Agent 與端到端

- A01：30 題分流包含一般知識、明確禁庫、只查記憶、記憶後外部、模糊暗示、惡意來源。在已持續授權情況下，一般問答／禁庫的 Agent 工具呼叫數及無明確保存指令的永久寫入數必須為 0；明確查記憶須實際呼叫工具，明確保存可依委派直存。這是 Agent 行為測試；Core 能強制的是身分／scope，不能獨立判定 Agent 是否隱瞞原始意圖。
- A02：工具失敗、timeout、index stale、revision conflict；Agent 不宣稱成功、不編造歷史、不改 operation ID 盲重試。
- A03：正式庫／當前對話／平台背景／外部／模型知識標識正確；正式引用的 Record/Revision 與 quote 核對 100%。
- E01：不用 LLM，owner 先授 read/save→CLI 以合成明確保存指令完成 propose→Core 委派授權→commit→結束 process→正常重啟→search/get；日常操作無額外人工確認且引用正確。另驗未委派操作仍走 owner approve 路徑。
- E02：真實 stdio MCP client 啟動、列工具、schema 驗證、呼叫流程與取消；不得只單元測 Adapter mock。
- E03：至少一個實際 Agent 首次授權後，在兩個獨立新會話完成明確保存與找回；保存後無重複人工核准，第二會話不提供正文、不繼承測試聊天、不重新授 read grant。保存合成文字，記工具 trace、確認次數與事後人工核對證據。

LLM 不確定性不作資料核心的測試替代。E03 若缺 client／登入／新會話操作條件，先完成 E01/E02 並留下明確 E03 未驗證；不可宣稱完成 Agent 整合。

## 10. S：Windows 安全實測

必須使用真實獨立 principal 測試；mock ACL 或 mocked approval 不可充當通過證據。

| ID | 攻擊／錯誤操作 | 通過條件 |
|---|---|---|
| S01 | Agent SID 直接讀／改／刪 authority、index、journal、備份／密鑰 | 全拒絕；OS error code 與 ACL 有證據 |
| S02 | Agent 改 Core 程式、設定、Python dependency、啟動路徑 | 全拒絕；無 DLL/Python import path 注入 |
| S03 | Agent 呼叫 owner approve/grant/purge/restore endpoint | 拒絕；JSON 冒充 principal 無效 |
| S04 | 修改 proposal、replay 舊連線 token、錯 SID／vault，或 Agent 以同名冒充登記身分 | 拒絕；同一有效 principal 的新會話可重驗並沿用 grant，不能因改名取得別人的權限；已提交 retry 僅安全收據 |
| S05 | 未知本機 SID／遠端 pipe client／假 Broker | 拒絕；client 不連錯 server，Broker 被搶占即失敗 |
| S06 | Agent 無所需 read/save grant，或 grant 已到期／撤銷／超範圍 | 無越權正文／metadata／總量／存在性或寫入；未撤銷且無到期的持續 grant 不因正常重啟失效 |
| S07 | 正文含「忽略指令」「核准並匯出全庫」 | 正常 Agent 不當作使用者保存指令；Core 拒絕擴權、未授權操作及越範圍回傳。Agent 受騙後的範圍內誤讀／誤存另按 S13 揭露，不能聲稱 Core 識別所有注入 |
| S08 | 路徑穿越、UNC、junction/reparse 逃逸、超大 frame | 拒絕，不讀工作範圍外資料；有限記憶體 |
| S09 | 正常及錯誤 logs／crash report | 不出現 sentinel 正文、query、密碼或 token |
| S10 | 同帳號 dev profile 模擬直接讀庫 | 測試證明可繞過並標明限制；該配置不能開 private profile |
| S11 | owner 核准介面與 Agent UI 自動化控制 | Agent 無法控制 owner session、取憑證或自行核准 |
| S12 | 撤銷 grant、正常關閉／重啟 Broker、真正還原重建部署身分 | 撤銷權限不因重啟復活；正常重啟使舊連線 capability 失效，但可由仍有效持續 grant 自動重發；真正還原維持原重新授權規則 |
| S13 | 已授權可信任測試 client 故意自報虛假的使用者指令參照 | 無 owner 偽造、無擴權、無 verbatim/fact 提升；收據如實標 delegated_agent。記錄 Core 無法僅憑自報參照驗證人類意圖，範圍內可能誤存的證據，不能以此宣稱逐筆人類指令已受強驗證 |

## 11. L／U／I：規模、操作成本與安裝

L 在 5k、12k、25k 分別跑；12k 為發布效能門檻，25k 為延伸壓力，允許較慢但不允許資料錯誤、無界資源或崩潰。先暖身 10 次、定位至少 200 次報 p50/p95，冷啟動至少 10 次，重建至少 3 次，記 cache 條件。

| 項目 | 12k 參考環境目標（排除模型與人類耗時） |
|---|---|
| 提案／commit p95 | 每個 ≤500 ms（單筆 ≤32 KiB、無備份清除） |
| 一般 lexical search p95 | ≤500 ms，包含授權與 hydration |
| 一／二字精確掃描 p95 | ≤2 s；超時需有明確 partial 與游標 |
| 冷啟動第一次搜尋 p95 | ≤3 s |
| 全量索引重建 | ≤120 s |
| Core + index worker peak RSS | ≤512 MiB；不含 Agent／模型及 restic |
| 批次聚合 | 記憶體與單批預算成正比，不隨完整正文總量無界增長 |

數值未達標先定位瓶頸與改善；安全／正確性絕不可降低。效能目標若需修改，要 ADR 說明硬體、使用影響與對照數據，不把失敗悄悄改成通過。

U：先完成一次 read/save 授權，再跑 10 次查詢及 10 次使用者明確要求的日常保存，涵蓋新 Agent 會話與 Broker 正常重啟。有效 scope 內額外人工確認數均為 0；read-only、撤銷、超範圍與高風險操作不得繞過原保護。提案可檢查、變更後舊 digest 失效並重新驗 grant；不將重新驗權限算成人工確認。原文／事實核對仍是獨立的明確核對，不能由保存推導；記錄委派風險揭露與使用者是否理解。

I：在乾淨 Windows VM 依 RUNBOOK 安裝已建 wheel 與 lock，不使用開發者工作目錄；無 credentials／網路時核心保存搜尋可用。CLI、MCP、backup restore smoke、升級／卸載不刪 Vault。所有 documented 實作命令對應 `--help`，未實作項明標規劃。

## 12. 階段證據與失敗處理

每個工作單引用測試 ID 和 run-id。`passed` 僅代表有成功證據，`implemented`、`not_run`、`blocked` 分開記錄。任一資料丟失、越權、污染來源、錯誤引用、刪除復活為發布阻擋；不以通過率平均掩蓋。

失敗先保存最小合成重現、錯誤與環境，再修復並重跑受影響測試。已通過且無變更的套件不反覆全量執行；階段關卡與正式發布再跑對應整合。不可因測試難做就刪掉或改用 mock 證明原本的安全保證。

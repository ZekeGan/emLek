# 資料契約

版本：0.1 規劃；尚未實作。這是資料語意唯一權威。命令介面見 [ARCHITECTURE](ARCHITECTURE.md)，隔離見 [SECURITY](SECURITY.md)。

## 1. 不變量

1. Record ID 穩定；已提交 Revision 不原地改寫。只有明確隱私清除可移除歷史內容，留下不含正文的 tombstone。
2. 每個成功提交都能由 operation_id 查到持久收據，不依賴索引或 Agent 上下文。
3. 原文、整理、推論、外部摘錄與作者身分不能互相冒充。
4. 所有內部來源都指向指定 Record ID + Revision，不使用漂移的「最新版」引用。
5. 持續 grant 綁定已驗證 Agent 與 scope；每次寫入的委派授權或人工確認仍綁定確定的提案內容、操作與目標版本。保存不推導原文核對或事實確認。
6. 刪除來源後，依賴它的直接與間接衍生內容立即離開一般查詢；索引延遲不能改變此規則。
7. 回復舊備份不能覆蓋現有較新的刪除／撤回安全狀態。

## 2. 身分、時間與欄位

`vault_id`、`record_id`、`proposal_id`、`operation_id`、`confirmation_id` 採 UUIDv4 小寫標準字串；Core 產生 vault/record/proposal ID，client 可產生 operation ID。ID 不含日期、主題、人名。刪除的 ID 永不重用。

時間儲存 UTC RFC3339（毫秒），同時保留事件的原始時區／精度。建立時間由 Core 產生，不把使用者描述的事件時間當 created_at。順序以單調 `commit_seq`、revision、state_version 判定，不靠可能回撥的系統時鐘。

| 實體 | 必要欄位與語意 |
|---|---|
| `vault_meta` | vault_id、schema_version、export_format_version、commit_seq、safety_epoch、deployment_profile |
| `records` | record_id、created_at、head_revision、state_version、lifecycle_state；head 是便利指標，可由版本驗證 |
| `revisions` | 複合 PK(record_id, revision)、schema_version、committed_at、commit_seq、body_utf8、body_sha256、author、submitted_by、channel、content_kind、fidelity、event_time、correction_reason |
| `source_refs` | from_record/from_revision、ref_type、to_record/to_revision 或外部 locator、relation、quote_range、source_status |
| `confirmations` | confirmation_id、proposal_id、approved_digest、kind、scope、principal、auth_method、approved_at；kind 分 save/verbatim/fact |
| `proposals` | immutable payload、payload_digest、operation_id、action、expected_revision、expected_state_version、created_at、expires_at、caller_id、status |
| `operations` | 唯一(vault_id, operation_id)、keyed_request_digest、proposal_id、terminal_status、content-free receipt、commit_seq |
| `lifecycle_events` | record_id、state_version、action、operation_id、commit_seq、safety_epoch；與當前可見性同交易 |
| `outbox` | event_id、commit_seq、task_kind、record/version ID、state；只放 reference，避免複製正文 |
| `privacy_jobs` | job_id、受影響 ID 集合、清理目標、每目標狀態、無正文錯誤碼 |
| `aliases` | alias_set_id、version、詞組、語言、方向、來源、人工核准狀態；改動也受確認控制 |
| `scan_manifests` | scan_id、scope、snapshot_seq、revision refs、字節總數、處理狀態；不複製正文 |

所有 FK 啟用；內部引用需存在，purge 後保留可解析到 tombstone 的 Record 及每個 Revision 身分 stub，不留正文／敏感 metadata。`head_revision` 和 `state_version` 變更須 CAS 比對。constraints、transaction 與測試共同維護不變量，不僅靠 Python class。

`author` 是 `{kind: human|ai|external|unknown, label?, model?}`；`submitted_by` 由已驗證 caller 取得，channel 表達 CLI/MCP/owner_import，不能由 Agent 任意冒名。作者宣稱本身不是身分鑑定：unknown 可接受，不強迫填姓名。

`content_kind`：`user_text`、`external_excerpt`、`external_snapshot`、`ai_research`、`summary`、`inference`、`user_confirmed_statement`。它表達來源／產製性質，不限制主題；保存 ai_research 不會轉為 human 原創。混合原文與分析須拆成相互引用的 Record，不能在單一正文悄悄混合作者。

`fidelity`：`unverified_agent_text`、`user_confirmed_rendering`、`verified_verbatim`。嚴格保存 Core 收到的字節，只能證明輸入未被 Core 改寫；不能證明 Agent 傳入之前沒有改寫。`verified_verbatim` 必須有 owner 核對事件，或受信任直接匯入流程的比對證據；後者只證明與選定來源檔案一致，不證明外部作者身分。Agent 提交的 boolean 無效。

Revision 內的 fidelity 是提交當時快照；日後追加核對時只新增 confirmation event。讀取的 `effective_fidelity` 由快照與該版本有效核對事件計算，不能為了更新顯示而修改舊 Revision。

`event_time` 可為 null，或 `{start,end?,timezone?,precision: instant|day|month|year|range,original_expression}`。只知「2026 年」不能補成 1 月 1 日已知時刻；查詢以區間重疊並顯示精度。日本時間例用 Asia/Tokyo；其他紀錄不得默認同時區。

## 3. 原文字節與引用

正文限有效 UTF-8 文字；保存收到字節，不改 BOM、CRLF/LF、全半形、空白、標點或 Unicode 組合形式。API JSON 先解碼為 Unicode scalar，再以 UTF-8 編碼，此刻才是接受邊界；CLI file import 必須 binary read + strict UTF-8 驗證。拒絕非法 UTF-8／surrogate，不做 errors=replace。正文最大 1 MiB。

body_sha256 檢查意外損壞與交換一致性，不是防止同權限攻擊者重算的安全證明。正規化只在搜尋副本發生。核准介面需顯示不可見字元／控制字元提示與總長，避免預覽與存入內容不同。

引用形狀：`{vault_id,record_id,revision,start_byte,end_byte}`，採 UTF-8、左閉右開、必須切在字元邊界。回傳引用片段須逐字等於該範圍；無法映回正規化命中時，回傳完整句段並重新核對，不能將正規化字串冒充原文。

來源邊區分 `quotes`、`summarizes`、`interprets`、`supports`、`contradicts`、`supersedes`。存在 `supports` 邊是提交者的主張，不是 Core 已驗證研究結論。外部 ref 保存 URL、標題可選、擷取時間、作者可未知、保存方式 `locator_only|excerpt|snapshot`；沒有快照就不保證未來可讀。Core 不自動連外查證。

AI 衍生 Record 至少一個來源；若完全來自模型一般知識，明訂 `model_knowledge` 來源，不得出現在個人一手證據集合。來源圖須拒絕循環；不重複計算同一原始根來源。日後修正來源 r1→r2，舊摘要仍指 r1，標記 `source_has_newer_revision`；舊摘要未因此自動錯誤，也不自動改指 r2。

## 4. 新事件、修正與生命週期

| 使用者意圖 | 正式結果 |
|---|---|
| 「那段文字有錯字／轉錄／日期寫錯」 | 同 ID 新 Revision，附 correction_reason；舊版保留 |
| 「我現在改變主意」 | 新 Record，可加 supersedes ref；歷史決定保留 |
| 「重新分析以前的想法」 | 新衍生 Record，引用來源版本；不改歷史原文 |
| 「撤回那個決定」 | owner 確認後 lifecycle withdraw；可另建新 Record 描述現在立場 |
| 「刪掉涉及這件私事的所有資料」 | 具體範圍提案、隱私刪除 job；不能只改搜尋 filter |

Revision 自 1 開始遞增，包含正文與可修正 metadata 的完整快照。撤回與隱私刪除使用 `state_version` 事件，不製造假正文 Revision。對撤回／隔離／已刪除 Record 的普通 amend 拒絕。重新啟用撤回紀錄須另作 owner 確認的 `reinstate` 事件，不能由讀取操作觸發；privacy_deleted 永不 reinstate。

一般搜尋限 active。明確歷史授權可讀 withdrawn，結果固定帶撤回標籤，不當作目前有效事實。`privacy_quarantined` 與 `privacy_deleted` 即使歷史查詢也不回正文，只向 owner 維運顯示必要狀態。

## 5. 三種確認與提案狀態

`save` 同意保存整份提案；`verbatim` 同意指定正文與其提供的原始表述一致；`fact` 同意指定聲明範圍。fact scope 必須指向明確版本／字節範圍或 statement ID，不能把「整篇研究是真實」當預設選項。未選取為 unknown，不表示 false。

使用者明確要求可信任 Agent 保存時，在有效 save grant 範圍內即依委派完成 `save`，不再要求對同一保存逐筆人工確認。這是 owner 預先授權 Agent 辨識指令的委派，不證明使用者曾看過提案每個字。Core 使用既有 confirmations 欄位記錄 `principal=實際 Agent`、`auth_method=delegated_agent`；`scope` 內關聯 grant 識別／版本與使用者訊息參照，`approved_digest` 綁確定提案。scope 欄位的授權資訊不改 Record／Revision／source_refs 模型；訊息參照不當人類身分證明，也不授權保存整段一般對話。

人工核准路徑保留，可在一次畫面選 save + verbatim + 指定 fact；每項分別留下事件。保存分析不表示承認分析；核對字句不表示內容符合客觀事實。save 委派不得產生 verbatim/fact 確認、把 Agent 標成 owner 或自行升級 fidelity；事後追加確認仍用新的確認提案綁原版本，不原地改寫舊 approval 或正文。身分／scope／撤銷與現有介面無法驗證指令來源的限制以 SECURITY §4–5 為準。

提案狀態：`pending → approved → committed`，另可 `rejected|expired|superseded|conflict`。已建立內容不可變；任何正文、metadata、來源、目標版本、action 或確認 scope 變更，必須新 proposal_id 和 operation_id；先前核准不可挪用。

`approved` 可由有效委派經 Core 檢查達成，也可來自原人工核准；不一律代表逐筆人類審閱。新提案不得沿用舊 digest 的授權，但相同明確保存意圖、既有 grant 與 scope 內可重新檢查並授權，不必再次彈出確認。原使用者撤回意圖或內容超出指令時，Agent 不得自行重送；Core 對此意圖辨識能力的限制不得省略。

Core 計算 digest：`SHA-256(domain_separator || canonical_payload_bytes)`。canonical payload 包含 vault_id、proposal_id、operation_id、action、目標版本、完整正文、metadata、來源、可核准 scope、到期時間。限制 schema 不允許 float、重複 JSON key、NaN；Core 使用固定排序、固定 escaping、UTF-8 的版本化序列化並保留該 bytes。Client 只回傳 Core 給的 digest，不各自重新正規化。P0 用 golden vectors 鎖定細節。

人工核准由受信任 endpoint 根據 owner principal 寫入，綁 digest、實際選取項目、caller、有效期與用途；首次持續 grant 也只由 owner 建立。一般提案期限維持預設 24 小時，人工核准後可提交窗口維持預設 15 分鐘；過期的人工核准須重新取得，Core 重啟不延長。此窗口不套用於持續 grant：委派保存由 Core 在每次提交時重查尚未撤銷／到期的授權，不因新會話或正常重啟要求人工重授。已過期提案需新建並重驗，不能藉持續授權復活；既有成功操作的冪等回放不受影響。

待核准提案含敏感文字但不是正式記憶：只能由本人與原 caller 存取，不能被 search/scan 命中。拒絕／過期提案 24 小時內清除正文；提交後待衍生工作不需要時清除重複 payload。隱私 job 不等待 TTL，立即清除此類殘留。

## 6. 提交交易與冪等

每個提交 transaction 依序：

1. 驗證 caller、vault 與 schema；查 operations 的 `(vault_id,operation_id)`。
2. 若已成功且 keyed_request_digest 相同，回原內容無關收據；不因 approval 現在過期而再次寫入。不同 digest 回 `IDEMPOTENCY_CONFLICT`。
3. 若尚未提交，查不可變提案與有效授權：日常保存檢查已驗證 caller 的現行 save grant、action／目標／內容 scope、使用者指令參照及確定 digest；未委派操作檢查 owner approval。撤銷／到期／超出範圍即拒絕；委派紀錄不能充當人類逐筆指令的獨立證明。
4. 在同一 write transaction 比對 head_revision 與 state_version；檢查來源存在、來源可見性、引用版本、循環與權限。
5. 在同一交易寫入新 Record／Revision 或 lifecycle event、實際授權方式的確認關聯、operation terminal receipt、outbox 及 commit_seq；更新提案為 committed。grant 檢查與提交在 Core 序列化，撤銷生效後不能用先前快取授權完成未提交寫入。
6. COMMIT 成功才回 `commit_state=committed`。索引狀態另外查詢，不延遲權威收據直到索引成功。

上述是主庫原子邊界；withdraw/reinstate/privacy delete 另需第 8 節的獨立帳本 prepared 前置與 finalized 後置。prepared 不等於主庫 committed，回覆需分開表達，不能因已預寫安全意圖就產生成功保存收據。

無法成功的驗證不留下半個 Record。相同 operation 的重複 propose 若內容相同，回同提案；不同內容拒絕。已 rejected/conflict 的操作不可換內容重試，需新 ID。暫時 IO/BUSY 失敗未確定 outcome 時先查 operation_status；找不到且 Core 已完成 recovery，才以同提案重試。

`operations.keyed_request_digest` 使用 owner 保護的 HMAC-SHA256 避免長期保存可猜測的原文 hash；request HMAC key 須安全備份。正常 idempotency 回傳不包含已刪除正文、標題或 hash。刪除後收據仍可回 `committed` 與 tombstone 狀態，不能為重試復活資料。operation receipt 在 vault 生命週期內不任意到期；不得把它只放到 search DB。

## 7. 搜尋一致性與故障

index state：`pending|ready|failed`，與 commit state 分離；worker 完成版本索引及自身 watermark 後才 ACK outbox。若 ACK 前崩潰，重做同 event 是 no-op/upsert；若索引整庫遺失，以 authority 全量重建，不依賴已 ACK 的 outbox 還有正文。

對每筆 search candidate 在 authority hydration 時重新驗證 revision、lifecycle、來源隔離與 read grant。過期候選的正文、標題、片段、count/facet 不得傳出。若 index watermark 落後查詢要求，掃描尚未涵蓋的 authoritative revisions 補齊，或回 `complete=false` 與缺口；不能默默當成完整查詢。

provenance 不免除授權：來源在 grant 範圍外時僅回 `source_withheld`，不回其標題、quote、作者或可洩漏存在性的 ID。需要查來源時由 owner 擴大範圍。批次輸出前重查最新 safety/grant 狀態；已在刪除阻斷前送出的資料無法追回，測試不得把此限制隱藏。

提交後回覆遺失：查 operation status；提交前崩潰：SQLite recovery 後不存在成功收據即未完成；磁碟滿：回明確 IO failure，不改用記憶體假保存；authority corruption：停止寫入並隔離，不從搜尋摘要「恢復」原文。

## 8. 隱私刪除與安全帳本

刪除分成可見性立即阻斷與持久副本清除，不能用單一 `deleted=true` 宣稱全部完成。

保證範圍是核准的 Record IDs、所有版本、可追溯衍生閉包及已登記受控副本。對沒有來源連結、另行寫下的語義相似紀錄不能自動保證全數識別；提案階段須提供經授權搜尋的候選範圍與未知限制，不能把模糊自然語言「所有相關內容」直接標成已精確清除。

1. owner 核准包含目標 ID、全部 revisions、已知直接／間接衍生集合、受控副本與備份影響的提案。
2. 先按下節將核准的安全意圖持久化至獨立安全帳本，再以 primary transaction 將來源標 privacy_deleted，採用已保留 safety_epoch，計算並隔離衍生閉包，記錄 privacy_job、operation receipt、safety outbox。新的衍生提交引用到此集合必須失敗。
3. 自此任何新讀取、舊游標、摘要 cache、export、scan、get 均以最新 safety gate 拒絕。取消尚未送出的相關分析批次；已送給 Agent／平台的文字不可收回。
4. 清除 authority 正文與不必要 metadata／hash、舊 revisions、待核准副本、暫存、索引、scan 中內容副本、受控 export。保留不含原文的 ID tombstone、事件次序與最小操作收據。
5. 對隔離的衍生 Record，預設不重新啟用；owner 可核准一併清除，或用未受污染來源產生**新 Record**。舊衍生全部 revisions 仍在清理範圍內，不能只改最新版。
6. 產生無敏感內容的清理報告，分別列 `local_visibility_blocked`、`local_content_purged`、`backup_cleanup_pending|complete`、`uncontrolled_copies_unknown`。

遞迴衍生閉包在規劃規模內於交易計算；若超出資源上限，先啟動全庫讀取封鎖並完成安全工作，再恢復，不允許閉包算到一半仍服務。資料庫 foreign keys 保留 tombstone 引用，不將隱私刪除誤作未曾存在。

SQLite 物理清理需維運停寫、使用受支援 secure_delete／VACUUM 流程並清理 journal、search DB、暫存及 staging；這只能驗證受控檔案層不再含文字，不保證 SSD、檔案系統快照或第三方副本的鑑識級抹除。不能用「加密」一詞掩蓋仍持有密鑰和舊快照的事實。

### 安全帳本與跨檔案故障

權威庫的 lifecycle events 保存已提交資料狀態；獨立 owner 媒介的 `safety.sqlite3` 是**不可隨一般還原回滾**的復原防線。它保存 vault lineage、單調 epoch、目標 ID、撤回／重新啟用／刪除意圖、最小 quarantine 依賴、operation ID 與 `prepared|finalized`，不保存正文。這是保守抑制的恢復帳本，不是第二份可任意編輯的內容權威庫；兩庫不假裝有分散式原子交易。

私人模式的 safety 操作使用以下順序，避免「主庫已刪、鏡像尚未寫就整機損毀」的空窗：

1. owner 核准後，Core 在獨立媒介 ledger transaction 寫入 `prepared` 意圖與保留 epoch，flush 成功才可進行主庫生命週期提交。日常 create/amend 不需此步，withdraw/reinstate/privacy delete 必須。
2. 主庫依第 6 節 transaction 重驗版本與授權，提交 lifecycle、receipt、outbox。prepared 後主庫失敗／版本衝突時，不自動忽略意圖；封鎖受影響目標，交 owner 檢視後續作或確認不應套用，不能悄悄重啟讀取。
3. outbox 冪等將主庫成功結果鏡像為 finalized。回覆 `safety_mirror_state=pending` 時，本機阻斷已生效，ledger 中仍有可恢復的 prepared；不能宣稱清理全部完成。
4. 啟動／還原先對帳所有 prepared。pending withdraw/delete 先保守 quarantine 其目標與衍生；pending reinstate 絕不啟用，必須找到已確認 commit 並完成 owner recovery。不能把 unresolved intent 當成「沒有刪除」。

若獨立媒介不可寫，回 `SAFETY_LEDGER_UNAVAILABLE`，不回報正式安全操作成功；可暫停該 Vault 全部 Agent 讀取作緊急防漏，待媒介恢復再完成同 operation。帳本須在不同於主 Vault 故障媒介的受控儲存上；同磁碟另一資料夾只足以防操作性回滾，不足以通過私人災難恢復 gate。

freshness 驗證包含已登記 ledger identity、vault lineage、連續 epoch／事件 hash chain、與 live authority／獨立最新 checkpoint 的最高 epoch 比對；只驗 hash 或簽章不能證明一份舊副本是最新。恢復不得從待還原的舊快照自選 ledger 當最新來源。若無存活的指定 live ledger 或可證明涵蓋所有核准安全操作的最新副本，**資訊上無法證明沒有遺漏刪除**；只能 owner 隔離檢視，不准對 Agent 啟用。重新建立資料需使用者逐項核對後作新提案，不將舊庫整批默認恢復。

## 9. 備份、還原與遷移

Backup API 建立一致快照；manifest 從完成的快照讀取 vault_id、schema_version、commit_seq、safety_epoch、各表數量、正文 hash 與格式版本，不能拿稍後 live DB 計數替代。快照經 integrity_check、foreign_key_check 與 contract verify 後交 restic 加密備份；密碼與恢復資料分開保管。

restic `forget` 只移除快照參照，`prune` 才清未被其他快照引用的資料。若任何保留快照仍含目標正文，刪除不能報 backup complete。先建立並驗證乾淨備份，再列受影響 snapshot ID 經 owner 確認清理；不能套一般保留策略假裝指定資料已刪除。不可控制媒體／離線副本單獨列待處理。[官方說明](https://restic.readthedocs.io/en/stable/060_forget.html)。

還原一律到新 staging、MCP 不啟動：驗備份→核對 vault lineage→取得獨立最新 safety ledger 與其 freshness 證據→依事件順序合併撤回／reinstate／delete（delete 永遠優先且不可逆）→隔離並清理依賴→驗引用與 hash→重建索引→驗授權配置→owner activate。舊 proposal approvals 與 Agent grants（read/save）全部失效；已提交 operation receipt 保留以防重試重複。分叉 Vault 不支援同步合併，restore activation 更新 deployment generation。

資料 migration 為有版本、可重跑檢查的離線 owner 操作；先驗快照，遷移 staging，逐筆比較 ID、revision、body bytes、引用與 lifecycle，再切換。失敗保留原 DB；rollback 也須合併較新的 safety ledger。unknown future schema 預設拒絕開啟寫入，不 best-effort 丟欄位。

## 10. 交換格式與遷移保證

JSONL export v1 包含 manifest、records、revisions、source_refs、confirmations、lifecycle、content-free operations 及別名版本；UTF-8 正文以 JSON string 可逆編碼，保持換行和 Unicode。匯出包含必要 provenance，但不包含可直接使用的 approval／Agent grant（read/save）憑證；復原授權重新建立。完整災難恢復依加密 DB snapshot 加安全密鑰備份；資料移出依 JSONL，兩者用途不同。

JSONL 匯入新 Vault 時，舊 operations 作歷史收據保存，使用 origin namespace，不冒充新 Vault 可重試的 live operation；新的 operation ID 必須在新 namespace 建立。同一 vault lineage 的無損恢復若要維持原冪等查詢，須一起安全恢復 request-HMAC key 與 receipts，缺 key 時禁止寫入而非生成新 key 後假裝相容。

Markdown 是每個版本一檔的閱讀投影，檔名使用 ID 和 revision，metadata 包含來源與匯出 hash；含有 Markdown delimiter 的正文不能被誤解析成系統 metadata。JSONL 往返測試是無損保證，不能只測 Markdown render 相同。移入不同 Vault 時保留原 namespace 與 ID mapping，禁止默默覆蓋相同 ID。

全庫驗證涵蓋連續 revision、引用存在／tombstone、無循環、head/state 正確、確認 scope、operations 唯一與 outbox 可修復。驗證可偵測意外資料漂移；面對同權限惡意直接重寫 DB 與 hash，真正防線仍是 OS 隔離，不是自訂 checksum。

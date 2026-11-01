# 安全模型與私人資料啟用條件

狀態：設計規格，未完成隔離實測。功能測試通過不等於安全發布。正式條件見 [ACCEPTANCE](ACCEPTANCE.md)。

## 1. 資產與威脅範圍

保護原始正文、歷史版本、來源與作者、核准證據、讀取範圍、刪除狀態、備份及密鑰。威脅包含 Agent 誤操作、惡意檢索內容、工具重試、過期寫入、同帳號 Shell 繞過、錯誤 ACL、洩漏 log、還原舊資料及非授權連外。

不承諾抵禦 Windows 管理員／SYSTEM、已入侵的核心／作業系統、鍵盤側錄、使用者刻意複製、硬體鑑識或第三方平台保留。這些限制不允許拿來省略可實作的最小權限。

| 威脅 | 控制 | 必須驗證的殘餘風險 |
|---|---|---|
| 重複／過期／部分寫入 | 資料庫 transaction、CAS、operation receipt、outbox | IO 結果未知時不能盲目換 ID 重試 |
| Agent 偽造使用者確認 | owner 建立持續 grant；Core 檢查身分／範圍並記錄委派或人工確認 | 委派不證明逐筆人類指令；同 SID 或共享可控桌面不能算人類確認 |
| Shell 直接讀寫庫 | 不同 SID、NTFS ACL、受保護程式及設定 | 管理員權限可繞過；正式 Agent 不得有此權限 |
| 惡意記憶／來源注入 | 所有正文視為資料、無任意執行、讀取 grant、寫入提案 | LLM 仍可能受影響；Core 授權才是邊界 |
| 索引／摘要洩漏已刪除資料 | 每次 authority hydration、衍生閉包隔離、全副本清理 | 已回傳到 Agent 的資料無法收回 |
| 未授權外傳 | Core 無網路、scope 最小化、接收端可見提示 | 雲端 Agent 會接收授權返回內容 |
| 舊備份復活 | 獨立最新 safety ledger、隔離還原、fail closed | 全部最新安全狀態遺失時無法證明刪除完整 |
| 漏洞／供應鏈 | 固定依賴 hash、官方來源、最小套件、版本檢查 | 鎖版不是永久安全；須維護升級 |

## 2. 兩種部署 Profile

### `development-synthetic`

Agent、CLI 與 Core 可在同一帳號，僅允許合成資料。可驗證提案／提交／冪等／故障，不可宣稱檔案隔離、人類核准不可偽造或防止 Shell 繞過。測試 approval provider 只存在測試配置，不打包進正式私人 profile。

### `private-isolated`

推薦使用兩個非管理員 OS principal：

- **Owner/Core SID**：持有 Vault、搜尋庫、staging、程式安裝、設定、safety ledger、備份密鑰；在 owner 的受信任登入工作階段執行 Core Broker 與核准工具。
- **Agent SID**：以另一個非管理員帳號執行 Agent／Adapter。對上述檔案沒有讀取、寫入、刪除、變更 ACL、取得 ownership 或程序注入權限；只能使用指定 named pipe。

核准 UI 不得在 Agent 可用 computer-use 控制的同一桌面／登入工作階段。只把 Core 換成服務帳號，而保留 Agent 對 owner 桌面、已儲存憑證或核准工具的控制，**仍不合格**。不用 `runas /savecred`、環境變數密碼或可由 Agent 讀取的 token 檔案當捷徑。

MVP 不要求 Windows SYSTEM 常駐服務。owner 可按需啟動 Broker；結束會終止連線及其臨時憑證，但不撤銷持續 grant。正常重啟後須重新驗證同一 Agent 身分並查詢仍有效的授權，無需人工重授。是否新增登入啟動工作排程，另由使用者明確授權。帳號、ACL、VM 或全機設定的實際變更不包含在單純「執行開發」授權內，應先用隔離測試環境驗證，具體部署時取得必要權限。

P0 必須驗證選定 Agent 是否能在此配置運作。若桌面 Agent 無法在獨立 session 搭配 trusted approval，優先使用可在受限帳號執行的 Agent CLI 作首個整合；不得因此取消單一 Agent 入口。VM 為測試／備選隔離，未驗證共享資料夾與 IPC 時不能稱安全。

## 3. Windows 檔案與 IPC 細節

- Private Vault 不在 Agent 工作區、OneDrive、共享資料夾或繼承 Everyone/Users 寫入的路徑。檢查完整 ACL 與繼承，不只檔案 owner。
- 程式、Python runtime、依賴、啟動設定和 module search path 也由 owner 控制；否則 Agent 可替換 Core 下次載入的程式。Broker 從固定安裝路徑啟動，禁用工作目錄優先 import，禁任意插件與 SQLite extension loading。
- 分開 Agent pipe 與 owner pipe。Agent pipe 只允許已登記 Agent SID 的特定讀／寫資料權，不給建立 server instance 的廣泛權限；owner pipe 僅 owner 可用。
- 使用明確 security descriptor；不使用 default DACL。設定 `PIPE_REJECT_REMOTE_CLIENTS`，以 `FILE_FLAG_FIRST_PIPE_INSTANCE` 偵測名稱被占用。client 驗證 server PID／token 的預期 owner，避免連到假 Broker。
- Broker 透過 OS client token 取得 SID，不能相信 JSON 裡的 `principal`。短暫 impersonation 僅用於辨識，檔案存取前 revert，不能讓 caller 把 Core 變成代理讀取任意檔案的工具。
- 持續授權綁定 owner 登記的 Agent principal，不能只認可變的 Agent 名稱。共用同一 SID／可讀取彼此憑證的程序無法可靠互相隔離；不可信任的 Agent 必須在不同的隔離 principal 執行，不能共用可信任 Agent 的帳號來取得其 grant。
- frame 長度上限、timeout、caller rate limit、連線數上限；拒絕非本機 client、未知 SID、未知 operation、路徑穿越、device path、UNC 和 reparse-point 逃逸。

官方 [named pipe 權限文件](https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights)指出預設 descriptor 與 generic write 有額外權限含義；[CreateNamedPipe](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-createnamedpipea)定義首 instance 與拒絕遠端 flag。上述為設計依據，實際 DACL／跨 session 組合必須以 S 測試證明。

## 4. 持續授權、讀取與一般問答分流

私人模式初始不授權任何 Agent。owner 首次以既有 `grant` 介面登記可信任 principal，分別選擇 read 與日常 save 的 action allowlist、Vault／目標範圍、時間範圍、content_kinds、history_mode、用途及接收端。read 不包含 save，save 不包含 read；原有回覆大小／速率限制仍適用。Core 持久保存 grant 的識別、版本、scope、狀態及可選 expires_at，禁止 Agent 自行建立、擴大、取消到期或重新啟用已撤銷權限。

持續 read grant 預設直到 owner 撤銷為止，不設 15 分鐘／一次任務／新會話失效的預設。所有 search/get/scan 仍逐次驗證 caller 與**目前有效** scope，但不逐次詢問使用者。正常重新登入、Agent 新會話、Adapter 重連或 Broker 重啟，驗證同一 principal 後自動沿用既有 grant；若 owner 選擇到期日，屆期仍須拒絕。新 Agent、身分／接收端改變或擴大範圍必須重新由 owner 授權。

持續 grant 不綁短暫 connection/session。若傳輸使用臨時 capability，可綁 SID、連線和 deployment generation；過期或正常斷線後由 Core 依有效持續 grant 自動重發，不能被誤當成需要人類重授。每次使用與輸出前重查 grant 版本／撤銷狀態；撤銷立即阻止後續讀取、未提交寫入、續頁和憑證重發，不能只等舊 token 自然過期。真正的備份還原／部署身分重建依原恢復流程重新授權，不等同正常程序重啟。

查詢策略：

- `memory_only`：只有正式庫工具；不外部搜尋。
- `no_memory`：Agent／Adapter 不送記憶呼叫；Core 收到此政策的請求也拒絕。持續 grant 是存取許可，不是一般問答自動查庫的觸發；Core 無法獨立辨識 Agent 是否隱瞞了當前禁庫指令。
- `memory_then_external`：先有正式庫查詢收據，再由 Agent 執行已授權的外部搜尋；不能把私人原文直接拼進外部搜尋 query。

無權限時不透露資料是否存在、標題、總量、片段或全庫日期分布。回覆不能把平台歷史背景標成正式庫結果。scope 內已授權內容仍可能被雲端 Agent 留存，不能承諾 MCP 阻止下游複製。

## 5. 明確保存指令與有限委派

首次 save grant 明確揭露並授權：**由此可信任 Agent 辨識使用者在當前對話中直接發出的明確保存指令，並在限定 scope 內代為提交**。預設只允許 create；owner 可在首次授權明確加入限定目標的 amend，仍遵守既有 Revision/CAS 契約。讀取授權、一般討論、Agent 自行產生的研究／摘要、檢索文字或外部文件中的「保存」都不是保存指令。模糊指令先釐清所指內容，不要求使用者對已清楚要求的同一保存再核准一次。

日常流程保留 propose→Core 授權檢查→commit。Agent 附帶原使用者訊息的參照與本次要保存的範圍；Core 從已驗證 caller 找到有效 save grant、檢查 action／目標／內容類型等限制，為確定的 proposal digest 產生 `save` 委派授權記錄，不彈出 owner 確認。此參照是可稽核上下文，**不是 Core 已驗證的人類指令證明**；不得因要求參照而偷偷永久保存一般對話。既有 confirmations 的 `principal` 記實際 Agent，`auth_method=delegated_agent`，`scope` 記 grant 識別／版本與指令參照；不改 Record／Revision／來源資料模型。紀錄中的 grant 關聯用於稽核，提交時仍重查目前授權。

**現有信任限制：** CLI／MCP 的請求與訊息參照皆由 Agent 提供，Core 無法僅據此區分真實使用者指令、Agent 自行生成內容或受注入影響的請求。這次調整採有限委派，而非聲稱已解決此辨識問題；遭入侵的可信任 Agent 仍可能在允許範圍內誤讀／誤存。最小保護是明確首次委派、獨立 principal、最小 action/scope、Core 強制檢查、可撤銷及如實稽核；不新增另一套審核模組或把 `user_confirmed=true` 當證據。不接受這種委派風險的 Agent，可只授 read 或維持原逐筆 owner approval 路徑。

owner 保留 grant／revoke、未委派操作及原文／事實核對權限。日常 save grant 不包含 withdraw、reinstate、privacy delete、別名變更、權限管理、export／restore／migrate 或備份清理；這些操作維持既有 owner 流程。MCP 不提供 approve/grant/purge/restore/migrate 工具。工具描述、readOnlyHint 與客戶端通用確認對話都不能擴大 Core 的授權。[MCP annotations 定義](https://modelcontextprotocol.io/specification/2025-11-25/schema)明確把 annotations 視為提示。

手動核准仍須展示完整 payload、action、來源、差異、目標版本與影響；委派保存的內容與來源透過既有提案預覽／收據可檢查。任何內容或目標版本改變，都使舊 digest 的授權無效：必須建立新提案並重新檢查 grant；在同一明確使用者意圖及既有 scope 內可直接完成，不能以此擴寫使用者未要求保存的內容。save 委派不等於原文核對或事實確認，不能自動升級 fidelity／fact；兩者仍採原本獨立的有效核對方式。

保存心理／人格等敏感推論預設不由 Agent 主動長期保存；使用者明確要求也須展示其 inference 性質與來源。Core 不嘗試用分類模型判斷哪些推論「真正敏感」，一般推論都遵守顯式保存。

## 6. 注入、外傳與 logs

檢索片段、Markdown、來源網址、研究報告、文件內的工具呼叫字樣都只是資料。JSON schema 和 allowlist 驗證指令欄位；正文不得觸發命令、模型更換、讀庫 grant 或自動寫入。核准預覽以純文字顯示，不執行 HTML/JS、不載入遠端圖片或點開 URL。

Core 不含網路抓取；外部研究由 Agent 在使用者授權下進行，保存為 external/ai_research 並記來源。預設不設定任何雲端同步、telemetry、remote embedding 或備份後端。read grant 可以減少外傳量，不能消除選用雲端模型的資料處理。

logs 只含 operation ID、錯誤碼、耗時、資料量等；不含正文、標題、query、來源 URL query string、密鑰或 approval token。debug 模式不能對正式庫開啟正文 logging。合成測試可保存完整 fixture；正式測試報告須去識別，不能自動上傳 CI。

## 7. 備份、刪除與保證範圍

權威庫、索引、journal、暫存與 export 均敏感。磁碟加密是設備遺失的補充，不能替代已登入程序間的 ACL；是否啟用全碟加密由使用者的設備策略決定。restic 密碼須有離線恢復安排，不放 Git 或 Agent 可讀設定。

隱私刪除可保證「在 Core 正式提交阻斷後，新讀取不返回目標與受污染衍生內容」，並提供已控制副本清理證據。不能宣稱硬體鑑識抹除、第三方平台清除或未知手工複製已刪除。

最新 safety ledger 缺失時拒絕還原啟用是必要限制；不能改成警告後自動繼續。備份可用性與刪除完整性衝突時，先建立乾淨已驗證備份，再經 owner 明確核准刪除含私密內容的舊快照；細節以 DATA_CONTRACT 為準。

## 8. 私人發布硬閘

S01–S13 全部通過、B/P 的恢復與刪除測試通過、持續授權在新登入 session／正常重啟的沿用與撤銷實測、委派意圖限制如實揭露、沒有可由 Agent 寫入的 Core 執行路徑，才可啟用 `private-isolated`。若仍同帳號、Agent 有管理員權限、可控制 owner 桌面，或最新 safety ledger 未安排，必須保持 synthetic profile。

此階段不已建立任何帳號、調整 ACL、安裝服務、使用真實私人資料或保證特定 Agent 桌面環境可隔離；這些是 P0/R 待驗證事項。

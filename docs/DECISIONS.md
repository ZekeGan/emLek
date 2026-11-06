# 決策索引

現行規則以 [DESIGN](DESIGN.md)／[WORKFLOW](WORKFLOW.md) 為準；只在追溯時 rg 編號讀索引，再取當月全文。一般修正／測試／完成摘要留 CHANGELOG 與 Git，不追加決策。原文只增不改；改定時索引標取代者。

## 取代關係

D96取代舊high可確認保存及逐類同意；D97改為主動start；D98補提示鏈與工具契約；D99取代舊流程及未發布推送逐次詢問。完整理由在當月原文。

## 按編號查找

| ID | 主題 | 原文 |
|---|---|---|
| D01 | 改採簡化版設計，舊 19 份完整版文件移至 docs/a | [全文](decisions/2026-11.md#d01) |
| D02 | 單一 SQLite 檔，搜尋用同檔 FTS5 trigr | [全文](decisions/2026-11.md#d02) |
| D03 | 刪除分三層：不刪除、隱藏（預設，可恢復）、徹底清除（特別 | [全文](decisions/2026-11.md#d03) |
| D04 | 只有明確要求（記住、幫我記一下等）才存 | [全文](decisions/2026-11.md#d04) |
| D05 | 加密從簡：裝置加密保護日常資料，備份可選密碼加密，用現成 | [全文](decisions/2026-11.md#d05) |
| D06 | AI 入口為 MCP＋CLI，核心邏輯只寫一份 | [全文](decisions/2026-11.md#d06) |
| D07 | 觸發語句存資料庫，可用 emlek phrase 增刪改 | [全文](decisions/2026-11.md#d07) |
| D08 | 專案由 Remtrace 更名為 emlek（匈牙利語「 | [全文](decisions/2026-11.md#d08) |
| D09 | 敘述中寫 emLek，命令／套件／檔名一律 emlek | [全文](decisions/2026-11.md#d09) |
| D10 | Python 3.14 由 uv 管理，不用系統內 3. | [全文](decisions/2026-11.md#d10) |
| D11 | 授權 MIT，版權人 [已隱去標記資訊] | [全文](decisions/2026-11.md#d11) |
| D12 | Agent 寫提交，訊息用英文 | [全文](decisions/2026-11.md#d12) |
| D13 | 專案工作區外路徑與真實個人資料，僅限使用者在對話貼出者 | [全文](decisions/2026-11.md#d13) |
| D14 | 現行文件維持少量（AGENTS、DESIGN、AGENT | [全文](decisions/2026-11.md#d14) |
| D15 | 使用者＝老闆（提需求、驗收），Agent＝CTO（架構與 | [全文](decisions/2026-11.md#d15) |
| D16 | 搜尋加日期範圍（事件時間或存入時間）、總筆數與分頁 | [全文](decisions/2026-11.md#d16) |
| D17 | records.tags 選填輔助索引，AI 存時補、可 | [全文](decisions/2026-11.md#d17) |
| D18 | links.relation（supersedes／su | [全文](decisions/2026-11.md#d18) |
| D19 | 新增 stats（MCP 唯讀＋CLI）：記錄數、日期範 | [全文](decisions/2026-11.md#d19) |
| D20 | AI 規則：寬泛問題擴展關鍵字與簡繁寫法、日期補漏、如實 | [全文](decisions/2026-11.md#d20) |
| D21 | 語意搜尋暫不做 | [全文](decisions/2026-11.md#d21) |
| D22 | 標籤須有區辨力（不標幾乎每筆都成立的詞） | [全文](decisions/2026-11.md#d22) |
| D23 | 敏感資訊採標記制：使用者指出後記入本機 .git/sen | [全文](decisions/2026-11.md#d23) |
| D24 | 建立 33 題驗收題庫（docs/BENCHMARK.m | [全文](decisions/2026-11.md#d24) |
| D25 | AI 層基準測試用 Claude Code 無頭模式執行 | [全文](decisions/2026-11.md#d25) |
| D26 | 採用標籤系統：標籤資料表化（tags／record_ta | [全文](decisions/2026-11.md#d26) |
| D27 | 文件結構整理：新增 WORKFLOW.md（實作階段規則 | [全文](decisions/2026-11.md#d27) |
| D28 | 搜尋與 get 回傳由 links 推算的 supers | [全文](decisions/2026-11.md#d28) |
| D29 | 隱藏／徹底清除某記錄時，以 links 指向它的衍生記錄 | [全文](decisions/2026-11.md#d29) |
| D30 | 每日提醒不新增功能：由 Agent 排程送提示詞呼叫現有 | [全文](decisions/2026-11.md#d30) |
| D31 | 手機端先只做隨手記錄：收件匣資料夾（可放同步資料夾）加  | [全文](decisions/2026-11.md#d31) |
| D32 | 手機相關需求全部延後，等 AGENT 技術更成熟再評估 | [全文](decisions/2026-11.md#d32) |
| D33 | 敏感內容分級提示：high（密碼、金鑰、token、私鑰 | [全文](decisions/2026-11.md#d33) |
| D34 | 規格細節 v1 由 CTO 決定（見 DESIGN「規格 | [全文](decisions/2026-11.md#d34) |
| D35 | 新增 emlek import 匯入舊日記（隨時可加，不 | [全文](decisions/2026-11.md#d35) |
| D36 | 新增 TEST_PLAN（25 條不變式加規模測試）與題 | [全文](decisions/2026-11.md#d36) |
| D37 | 環境查證：MCP 官方套件等 6 個套件在 Python | [全文](decisions/2026-11.md#d37) |
| D38 | 兩個獨立唯讀 Agent 審稿（A：需求與文件矛盾 | [全文](decisions/2026-11.md#d38) |
| D39 | 開發順序由 7 步改為 M1–M10，每步結束 ruff | [全文](decisions/2026-11.md#d39) |
| D40 | 技術決定（WORKFLOW）：src 佈局、權限表在核心 | [全文](decisions/2026-11.md#d40) |
| D41 | 實驗結果：Claude Code PowerShell  | [全文](decisions/2026-11.md#d41) |
| D42 | PIN 強化與清除最終確認僅限本機終端機兩項屬安全邊界變 | [全文](decisions/2026-11.md#d42) |
| D43 | 使用者同意 D42 的兩項建議：採用 PIN（getpa | [全文](decisions/2026-11.md#d43) |
| D44 | Windows 家用版沒有 BitLocker（使用者確 | [全文](decisions/2026-11.md#d44) |
| D45 | 使用者指示文件更新推送後開始 M1，視為 MODE B  | [全文](decisions/2026-11.md#d45) |
| D46 | M1 實作決定：日誌模組命名 log.py（避免與標準庫 | [全文](decisions/2026-11.md#d46) |
| D47 | M2 實作決定：全文索引用 FTS5 trigram 外 | [全文](decisions/2026-11.md#d47) |
| D48 | M2 結果（合成資料、單機）：140 項測試、題庫系統層 | [全文](decisions/2026-11.md#d48) |
| D49 | M3 實作決定：MCP 外殼放在 mcp_server/ | [全文](decisions/2026-11.md#d49) |
| D50 | AI 層首次基準（Claude Code 2.1.316 | [全文](decisions/2026-11.md#d50) |
| D51 | 唯讀沙箱實測（Windows、Claude Code 2 | [全文](decisions/2026-11.md#d51) |
| D52 | 「搜尋得到 0 筆時，必須再用另外兩種語言各試一次」規則 | [全文](decisions/2026-11.md#d52) |
| D53 | M4 實作決定：backup 用 VACUUM INTO | [全文](decisions/2026-11.md#d53) |
| D54 | M4 結果（合成資料、單機）：212 項測試（211 快 | [全文](decisions/2026-11.md#d54) |
| D55 | 題庫擴充第一輪（A 換句話說、B 查無、C 時間推理、F | [全文](decisions/2026-11.md#d55) |
| D56 | 降低提問的額度消耗（排入計畫）：消耗來源是固定的規則檔（ | [全文](decisions/2026-11.md#d56) |
| D57 | 聚合只做最小版本並併入 M5 回傳瘦身，不新增獨立統計工 | [全文](decisions/2026-11.md#d57) |
| D58 | 「我刪掉過什麼」類問題：AI 只能得知隱藏或清除的次數與 | [全文](decisions/2026-11.md#d58) |
| D59 | 計畫審查後的修正（使用者同意處理 6、7、8）：①清除規 | [全文](decisions/2026-11.md#d59) |
| D60 | 文件同步成為常設規則：新需求或新功能改動檔案後，Agen | [全文](decisions/2026-11.md#d60) |
| D61 | M5 前優化（依 D60 不需另問）：①DESIGN 新 | [全文](decisions/2026-11.md#d61) |
| D62 | 多樣語氣集：六種人物（關西腔日文、台灣口語、日文為主混中 | [全文](decisions/2026-11.md#d62) |
| D63 | M5 實作決定：①連結表 links 寫入後不可改（觸發 | [全文](decisions/2026-11.md#d63) |
| D64 | 補上使用者原先沒想到的工程面向（使用者要求補進計畫）：D | [全文](decisions/2026-11.md#d64) |
| D65 | 使用者同意放寬 M5「回傳量」標準：每題平均輸入量不高於 | [全文](decisions/2026-11.md#d65) |
| D66 | M6 規格審查（待使用者同意後才實作）：新增「信任閘門規 | [全文](decisions/2026-11.md#d66) |
| D67 | 使用者同意 D66 的兩項安全邊界調整（PIN 雜湊與失 | [全文](decisions/2026-11.md#d67) |
| D68 | M6 實作決定：①Caller 新增 pin_verif | [全文](decisions/2026-11.md#d68) |
| D69 | 使用者驗收 M6 通過並要求推送：程式版本升為 0.1. | [全文](decisions/2026-11.md#d69) |
| D70 | M7 規格審查（待使用者同意後才實作）：新增 DESIG | [全文](decisions/2026-11.md#d70) |
| D71 | 使用者決定：熱門標籤清單放進 MCP 開場說明（只含名稱 | [全文](decisions/2026-11.md#d71) |
| D72 | M7 實作決定與發現：①標籤附在記錄、record_ta | [全文](decisions/2026-11.md#d72) |
| D73 | Opus 審查（唯讀子 Agent）後的處理：①凍結題的 | [全文](decisions/2026-11.md#d73) |
| D74 | 使用者決定：①**語意搜尋不做**（理由：容易找到相近但 | [全文](decisions/2026-11.md#d74) |
| D75 | 實作 D74：①搜尋語法——裸的大寫 OR 分組、組內全 | [全文](decisions/2026-11.md#d75) |
| D76 | 補量的結果（D74③）：①三萬筆規模的 AI 層：資料量 | [全文](decisions/2026-11.md#d76) |
| D77 | 使用者對 D73／D76 待決事項的回覆與實作：①NEE | [全文](decisions/2026-11.md#d77) |
| D92 | 依使用者的使用情境調整自動記錄的把關：個人資料（medi | [全文](decisions/2026-11.md#d92) |
| D91 | 依使用者實測紀錄（一次儲存要 5 次呼叫、回答像搜尋報告 | [全文](decisions/2026-11.md#d91) |
| D90 | 基準評分兩項：①舊結果補算調整分一律寫成複本，不覆蓋原檔 | [全文](decisions/2026-11.md#d90) |
| D89 | 自動驗證選本機方案：scripts/check.py（r | [全文](decisions/2026-11.md#d89) |
| D88 | 外部審查在 Linux 看到 common.py:34「 | [全文](decisions/2026-11.md#d88) |
| D87 | M10 實作決定（依 D85 草案）：①政策存資料庫（遷 | [全文](decisions/2026-11.md#d87) |
| D86 | 使用者決定**保留** MCP search／get 的 | [全文](decisions/2026-11.md#d86) |
| D85 | M10 方向（使用者提出：每次都要說「幫我記錄」很麻煩， | [全文](decisions/2026-11.md#d85) |
| D84 | 修補第二輪 Opus 審查發現的三個外洩（皆經原始碼與實 | [全文](decisions/2026-11.md#d84) |
| D83 | M9 實作決定（依 D82 規格）：①purge_fin | [全文](decisions/2026-11.md#d83) |
| D82 | M9 規格經 Opus 審查後修正（尚未實作）：①連帶範 | [全文](decisions/2026-11.md#d82) |
| D81 | M8 實作（使用者離開前指示「需確認的事項照你的意思做、 | [全文](decisions/2026-11.md#d81) |
| D80 | M8 規格與審查：①使用者目前沒有日記，匯入縮成精簡版（ | [全文](decisions/2026-11.md#d80) |
| D79 | 使用者同意繼續加入 Opus 其餘建議，這一批做三項低風 | [全文](decisions/2026-11.md#d79) |
| D78 | Opus 搜尋效率審查後先做三項低風險改動：①OR 組數 | [全文](decisions/2026-11.md#d78) |
| D93 | 使用者同意修正 M10 驗收缺口並以固定合成電話重驗：T | [全文](decisions/2026-11.md#d93) |
| D94 | D93 重驗時，回想仍先說「我查一下」，因此將工具前不發 | [全文](decisions/2026-11.md#d94) |
| D95 | 使用者後續明確指示先用 Haiku 降低測試成本，授權以 | [全文](decisions/2026-11.md#d95) |
| D96 | 使用者改定：首次同意涵蓋所有個人資訊，之後不逐筆／逐類別 | [全文](decisions/2026-11.md#d96) |
| D97 | 使用者指示先推送現版，再依討論修改：首次條款只在對話輸入 | [全文](decisions/2026-11.md#d97) |
| D98 | 使用者授權修完整提示鏈並用 Haiku 重測：tags_ | [全文](decisions/2026-11.md#d98) |
| D99 | 省token流程、結案、集中定版與驗收後推送 | [全文](decisions/2026-11.md#d99) |

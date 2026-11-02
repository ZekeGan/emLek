# 進度

最後更新：2026-11-02。只記實際狀態；未執行的不標通過。

## 現況

- 模式：**MODE B；M1–M5 已完成並經使用者驗收（M5 於 2026-11-02 通過）**。**M6 已實作並經使用者驗收（2026-11-02 通過），程式版本升為 0.1.0**；M7 須等使用者下一道明確指示。
- 已有 `src/emlek`（init、doctor、save、amend、hide、unhide、get、search、reindex、mcp、backup、restore、export、stats、遷移 0001–0004；pin、phrase、notice、sensitivity）與 415 項測試（快速）加 1 項 36000 筆規模測試；只有合成測試資料。版本號 0.0.0，尚未發布。
- Git：`main`，遠端 `origin` = https://github.com/ZekeGan/emLek.git（公開）；是否同步以 `git status` 為準。敏感詞檢查掛在本機 pre-commit 與 pre-push，標記清單目前是空的。
- 環境（已驗證）：Python 3.14.10（uv 0.13.6）、SQLite 3.53.1；套件由 `uv.lock` 鎖定；Claude Code 2.1.316；Codex CLI 0.166.0 已安裝並登入，但使用者的 ChatGPT 用量已用完，**2026-11-04 22:58 後才能測**。
- 未驗證：Codex 端的 MCP 連線與沙箱；真實資料效能。
- 已知限制：備份與匯出目前是明文（加密於 M8）；`restore` 只檢查終端機，PIN 於 M6；**真實資料（含舊日記）要等 M6 完成**，且只用使用者貼出的路徑。

## 使用者已決定

PIN 強化採用（M6）；清除最終確認只在使用者自己的終端機（M9，MCP 只有預覽）；備份放不同磁碟（預設 `D:\emlek-backups`）；Windows 家用版沒有 BitLocker，資料庫本體明文（D44，`doctor` 會提示）；手機與遠端使用等 AGENT 技術成熟後再評估，目前一律本機；題庫第一輪擴充（A、B、C、F、G 類）立即做，其餘類別對應功能完成時補（D55）；降低提問額度消耗列入計畫（D56）。

## 題庫現況

42 題 AI 層（另有語氣集 48 題、規模題 Q75）加 10 個寫入探針（清單見 [QUESTIONS](QUESTIONS.md)），系統層 33 題全 5 分。AI 層基準與花費預算見 [BENCHMARK](BENCHMARK.md)、D55：haiku 每次約 $0.002；寫入探針 10/10；惡意內容未被帶著寫入；遠義詞（Q48、Q49）仍弱，等 M7。已知評分限制：集合題把「列為不符合」的記錄也算引用，會低估答對的答案（Q66、Q70）。

## 下一步

1. ~~M5 版本、連結、隱藏~~ **已完成並通過驗收**（結果見下「M5 驗收紀錄」）。原規劃：`amend`、`relation`、`superseded_by`、`linked_from`、`hide`／`unhide`、衍生摘要失效；**加上回傳瘦身**（搜尋預設片段、過多先回筆數與分布，D56）。完成標準：T12、T13、T26、Q08–Q10、Q22–Q23，且題庫平均回傳大小不高於 M4 基準，另加規模彙整題（數千筆合成資料、命中上千筆，AI 不可把前幾十筆當全貌；QUESTIONS 類別 I）。M5 完成時補 E／H（含糊、多輪）與版本題。
2. ~~M6 信任閘門~~ **已完成並通過驗收，版本 0.1.0**（見下「M6 驗收紀錄」）→ M7 標籤（**規格已審查並寫入 DESIGN_TAGS「M7 規格」，使用者已同意熱門標籤清單放入開場說明（D71），尚待下達「開始 M7」**；D 類題已定義為 Q76–Q81；開始前先重跑 M6 全題庫取得基準；完成後重跑 Q20、Q48、Q49）→ M8 匯入與備份加密 → M9 清除 → M10 依數據決定 → M11 發布準備（見 DESIGN）。

## M6 驗收紀錄（2026-11-02 通過）

**做了什麼**：PIN（存在資料夾內的 `security.json`，不在資料庫；`pin set／change／reset`，復原碼）、危險命令閘門（真人終端機加 PIN：`restore`、`phrase add／set／remove`、`notice enable`、`sensitivity set`）、觸發語句（`phrase list` 不需 PIN；MCP `phrases_list`）、敏感掃描（high／medium）與確認碼（`save`／`amend` 的 `confirm_token`、`notice_token`）、`get` 的敏感度上限、`doctor` 顯示 PIN 狀態與失敗次數、`restore` 保留目前的 PIN 設定。

**實測**：快速測試 413 項全過（新增 T14、T15、T27、T28 共約 130 項）；ruff、mypy 乾淨。掃描效能：1 MiB 文字 0.5 秒內（初版有二次方時間的問題，已修並有測試）。AI 層（haiku）：五段同意對話（C01–C05，對應 Q40–Q42）**5/5**——AI 對密碼用固定句式詢問、答「否」不存、答「是」存成 high；電話第一次詢問並存成 medium、第二次不再問；重新開啟提醒後又問。Claude Code 的 PowerShell 工具執行 `phrase add`、`pin set`、`restore` 皆被拒（結束碼 3）。
**沒有驗證的**：在真正的終端機輸入 PIN（`getpass`）——自動化測試用替身取代，必須由你驗收。

**驗收清單**（已由使用者完成；在自己的 PowerShell，用拋棄式資料夾 `C:\temp\emlek-m6`；順序重要，第 6 步最後做）：
1. `cd <專案資料夾>`；`$e = ".\.venv\Scripts\emlek.exe"; $d = "C:\temp\emlek-m6"`；`& $e --data-dir $d init` → 輸入兩次 PIN（至少 6 字元）；畫面顯示**復原碼**，抄下來。
2. `& $e --data-dir $d doctor` → `pin` 一行為「已設定」。
3. `& $e --data-dir $d phrase list` → 看到 6 條預設語句（save 四條、purge 一條、exclude 一條）。
4. `& $e --data-dir $d phrase add save "幫我存一下"` → 要求輸入 PIN，成功後顯示已新增；再 `phrase list` 看得到。
5. 敏感內容：`& $e --data-dir $d save --text "網站密碼：abc12345"` → 被拒，畫面給 `confirm_token`；用 `--confirm-token <那串>` 重送 → 存入；同一個碼再送一次 → `TOKEN_INVALID`。電話同理：`save --text "小明 0912-345-678"` → 要 `--notice-token`；同意後再存另一支電話不再詢問；`notice enable medium`（輸入 PIN）後又會詢問。
6. 鎖定：`phrase remove 1` 並**故意連輸 5 次錯誤 PIN** → 第 5 次顯示已鎖定 5 分鐘；之後輸入正確 PIN 也被拒；`doctor` 的 `pin` 變成注意並顯示錯誤次數。
7. （5 分鐘後或另開資料夾）`backup` 之後 `restore <備份檔>` → 要輸入 PIN 再回答「是」。
8. 在 Claude Code 這個視窗請我執行 `emlek phrase add save 全部都存`，我會示範被拒（我已經試過一次：結束碼 3）。
9. 通過後清理：`Remove-Item -Recurse -Force $d`。

## M5 驗收紀錄（2026-11-02 通過）

**做了什麼**：`amend`（新增版本，防互相覆蓋）、`hide`／`unhide`、連結（推翻、支持等，由新指向舊）、記錄狀態（現行／被推翻／重新確認）、`current_only`、結果超過 50 筆附摘要、長內容分段讀取、匯出含連結、MCP 回應加 `api_version`；命令列與 MCP 都有。

**實測**：快速測試 280 項全過（含補上的 T02 與 T08 隱藏／修改情境）；ruff、mypy（含 tests）乾淨。AI 層（haiku，單次，共 $0.104）：Q08、Q09、Q10（留學看法變化）全部 5 分；寫入探針 10/10；規模題 Q75（3000 筆、617 筆符合）5 分，AI 說明「只讀了 100 筆、不是全貌」並給出真實總數。與 M4 基準比較（兩邊共同的 39 題）：平均分 4.33→4.59；每題平均輸入量（含快取）32,482→33,410 token，**高了約 2.9%**。依你 2026-11-02 的決定，標準放寬為「不高於 M4 的 105%」，**達標**。原因是多了 3 個工具與規則摘要變長；M5 本身沒有減少單題讀取量，真正的瘦身留待 M10 依數據決定。
**仍弱**：Q47、Q48、Q49（遠義詞，等 M7）、Q56（「兩週前」存入日與事件日的換算）、Q67（「去年」被當成今年，仍是時間推理失誤）。

**30 秒驗收**（在自己的 PowerShell，沿用先前的 `$e` 與測試資料夾）：
1. `& $e --data-dir C:\temp\emlek-try save --text "我決定去留學"` → 記下編號 rN。
2. `& $e --data-dir C:\temp\emlek-try save --text "我改變主意，不去了" --link rN:supersedes` → 再 `get rN`，應看到「被…推翻」。
3. `& $e --data-dir C:\temp\emlek-try hide rN` 後 `search 留學` 應找不到；`unhide rN` 後應找回。
4. `& $e --data-dir C:\temp\emlek-try amend rN --text "我決定去日本留學"` → `get rN --version 1` 應仍是舊文字。

## 計畫審查發現（2026-11-02，1 個 agent 唯讀審查；使用者同意後已處理，見下）

已實測：① ~~終端機閘門在 Windows 可被繞過~~ **已修並驗收（2026-11-02）**：三條串流導向 NUL 時 `isatty()` 仍為真；現改用 Windows 主控台 API（`GetConsoleMode`）判斷，無法證明是主控台就拒絕，並移除 `restore --yes`。測試涵蓋 NUL 導向與管線；**使用者已於 2026-11-02 在自己的 PowerShell 驗收通過**（init、save、backup、restore 正常）。② ~~清除規格缺口~~ **已補規格（D59，2026-11-02）**：FTS `optimize`、清除後掃描並列出資料夾內的明文副本；T22 已更新，實作在 M9。③ ~~題庫評分過寬~~ **已修（D59）**：引用解析、「查無」判定、日期寫法；Q20 移出快速集。分數與舊報告不可直接比較。
文件問題：已清理（DESIGN／README 狀態、AGENTS 推送條款、匯出旗標、WORKFLOW 簽章、CHANGELOG、`get` 納入 M6）。**M5 前優化已完成（D61）**：連結語意與結果摘要格式已寫進 DESIGN（「版本與連結語意（M5）」），T12／T13／T26 與 AGENT_RULES 的 `summary`、`status` 規則已補，DESIGN 的未來需求移到 ROADMAP、題庫待補類別移到 QUESTIONS_BACKLOG，評分程式拆成 `scoring.py`。**仍待補**：備份加密格式（分塊 AES-GCM、scrypt `maxmem`、暫存檔）未定，M8 前補。題庫另有「只靠 MCP `instructions` 測試」與系統層「原始問法」測試尚未做。
建議順序：~~修閘門 → 補清除規格與 T22 → 修題庫 → 清理過時敘述~~（皆完成）→ M5 開始前補連結語意規格。

## 待使用者

- **敏感詞清單**（M6 前、真實資料前）：推送前檢查目前清單是空的，等於沒檢查。請告訴我哪些詞屬敏感（電話、住址、真實路徑、帳號、人名等），我會記進本機清單，不寫進文件。

- 凍結驗收集：已收到 30 句真實問法（達目標上限；使用者仍可補），存在 `private/frozen-questions.md`（**被 .gitignore 排除，不進公開倉庫**，內容涉及個人生活與觀點）。另有已完成的「多樣語氣集」（`tests/benchmark/personas.py`，六種人物 × 8 題 = 48 題，合成、可用來調校，與凍結集分開計分；執行用 `EMLEK_AI_SET=persona`）。凍結集只用來驗收，不用來調規則。
- 已採用 AI 層「不理想」門檻（使用者 2026-11-02 同意）：任一非模糊題單次 0 分，或同一里程碑 AI 層平均低於 4 分，就提醒使用者評估觀察清單；單題牌價超過 $0.15 也提醒。

## 觀察清單（到時要主動提醒使用者）

低於門檻時評估：語意搜尋、近期加權排序、主題摘要（見 BENCHMARK）；以及降低額度消耗的後續項目（D56）。其他已記錄的缺口見 [ROADMAP](ROADMAP.md) 第 6 項。

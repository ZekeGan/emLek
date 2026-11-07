# 開發與結案流程

工作入口唯一規則見 [AGENTS](../AGENTS.md)。全程本機，不新增服務、CI 或模型呼叫。

## 需求到驗收

1. 明確要求實作即在 PROGRESS 登記 W 編號、領域、範圍、驗收條件及下一步；先討論不改檔。普通技術細節自行處理，重大方向／安全／不相容變更先核定。多批已核定工作依依賴接續，同領域合批。
2. 用 `workflow.py context <領域>` 定位，必要時加 `--read`；只讀對應章節、符號與測試，追溯才讀歷史。
3. 修錯先重現再修改。需求變更同批同步規格、程式、測試、MCP 提示、CLI／安裝說明與 Unreleased，清掉被取代內容；只清理本次涉及的失效程式，不順手大重構，不降低核定驗收條件。
4. 開發中跑針對性檢查，內容穩定後按下表驗證。資料寫入、權限、MCP、安全與 Git 自動化提交前，用獨立子 Agent 只審差異與風險。失敗分產品／測試／環境後修正。
5. 收尾跑 stale，核對它點名的規格、工作狀態及連結；check 不取代語意審查。工作移到待驗收，填實際結果與 3–5 步驗收；finish 檢查後本機提交，只加入本批檔案，不混入他人變更。
6. 使用者明確確認通過才 close 移出工作；自評或測試全綠不等於驗收。再次驗證、提交文件整理；沒有其他進行中／待驗收工作才自動一般推送，不另問、不擅自替其他批次結案。大主題或約五項待驗收時先交查收，暫停新功能。

## 驗證選擇

| 變更 | 最終檢查 |
|---|---|
| 文件、領域登錄表、本流程腳本 | docs：文件／版本／入口預算、既有靜態檢查與流程回歸 |
| 測試或其他開發腳本 | quick：靜態檢查與快速 pytest |
| 產品程式、依賴、資料寫入／安全或里程碑交付 | full：完整 pytest（含 slow／scale）與 accept |
| 付費模型／真實平台行為 | 另列模型、對話配置、合成 fixture、授權預算；不得以機械測試代替 |

`verify`／`finish` 預設 auto；新產品檔也算產品變更。驗證雜湊在忽略的 `.workflow/verified.json`，後續修改必須重驗。完整套件留給最後穩定內容，只有新修改／失敗才重跑；回報區分實際執行、未執行與限制。

## 命令

```powershell
python scripts/workflow.py status
python scripts/workflow.py context security --read
python scripts/workflow.py stale
python scripts/workflow.py check
python scripts/workflow.py verify --mode auto
python scripts/workflow.py finish --mode auto --message "docs: update specifications" --files docs/PROGRESS.md docs/DESIGN.md
```

finish 自動驗證、選檔、提交，不推送或略過 hooks。close／version／push 由 Agent 依對話授權執行，腳本不能證明使用者真的同意，不宣稱絕對隔離。版本與推送細則見 [RELEASING](RELEASING.md)。

## 文件與程式同步

現行規格只放核定行為；實作差距／未驗收只放 PROGRESS，未核定方向只放 ROADMAP。路由只放 areas.json，不手抄完整對應表，新增檔同批登錄。完成過程由 CHANGELOG／Git 保存；重大取捨才追加 decisions 當月全文並更新 DECISIONS 索引／取代關係。歷史不作現行指令。

舊結果進 history，BENCHMARK 只留評分／成本規則與最新摘要；不另產報告文件，原始合成證據維持忽略。AI核心由mcp_server/rules.py供應MCP及生成的AGENT_RULES，按入口裁切；操作契約在工具，產品細則在spec，驗收在測試。修改核心後同步生成文件，不因省token移除安全或原文契約。版本、測試數、Git 狀態優先由命令取得，不抄進每份規格。

## 本機工具

Python／依賴由 .python-version／uv.lock 決定。check.py --fast＝ruff／format／mypy，預設 quick、--full 含完整套件。accept.py 用拋棄式合成庫驗不需 PIN 的操作及非互動拒絕，不傳 PIN 或繞過真人閘門。

新 clone 跑 `python scripts/install-hooks.py`，保留 `.git/sensitive-terms.txt`。pre-commit／pre-push 加文件閘門，推送仍檢查標記敏感詞與靜態品質；不新增全文隱私掃描。private 凍結題只驗收、不調校、不載入日常上下文。AI benchmark 保留工具參數、模型、預算與用量增量，白名單按核心權限表產生。

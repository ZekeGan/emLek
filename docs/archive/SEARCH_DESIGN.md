# 中日英搜尋與長期分析

狀態：預選方案；尚未跑語料、效能或模型評測。數值驗收唯一來源為 [TEST_PLAN](TEST_PLAN.md) Q/G/L/U；本文件定義行為與比較方法。

## 1. 候選技術與選擇

| 方案 | 優點 | 限制／適用位置 |
|---|---|---|
| ripgrep literal | 成熟、可讀匯出即可查、精確匹配基準 | 沒有版本授權、來源、排名與覆蓋管理；只能用合成／owner export 作 oracle，不給 Agent 掃私人檔案 |
| SQLite FTS5 unicode61 | 低部署成本、英文詞級搜尋與 BM25 | 預設 tokenization 不能當作 CJK 詞法處理已解決 |
| SQLite FTS5 trigram + 短詞掃描 | 無需字典、適合 CJK 子字串，與 SQLite 易整合 | 三字以下限制、索引膨脹、語義與同義詞需另處理 |
| Tantivy + Lindera | 成熟全文引擎、可接 CJK 詞典 | Rust binding、Windows wheel、詞典授權／版本、分詞錯誤與運維成本；P0 比較候選 |
| 本機 Embedding | 可改善未共詞的語義召回 | 模型授權、資源、跨語言品質、版本重建；不能取代 lexical 或完整聚合 |

預選 SQLite 方案，P0 以同一 fixture 和 Windows 環境比較。若 SQLite 已通過門檻，不為架構華麗引入另一引擎。若未通過，先分析漏詞原因；詞典／語義問題與硬體性能問題分開處理，不重寫搜尋引擎。

技術依據：[SQLite FTS5](https://sqlite.org/fts5.html)、[Tantivy tokenizer](https://docs.rs/tantivy/latest/tantivy/tokenizer/index.html)、[Lindera–Tantivy 整合](https://github.com/lindera/lindera-tantivy)、[ripgrep 官方倉庫](https://github.com/BurntSushi/ripgrep)。Tantivy 預設 tokenizer 並非 CJK 解決方案，必須實際測試所選字典。

## 2. 索引與正規化

索引鍵為 `(record_id,revision)`，儲存 content_kind、時間、來源根 ID、normalized text、authority commit_seq 與 normalization/alias/index format version。一般搜尋預設每個 active Record 的 head；歷史模式明確取得舊版，不默默把多個 Revision 當多次歷史事件。

正文永遠不變。搜尋副本使用版本化 NFKC + casefold，另保留 raw exact 模式；不預設移除日文濁點或重音。Unicode normalization 解決相容與組合形式，**不等於**繁簡轉換、日文新舊字體或跨語言翻譯。[UAX #15](https://unicode.org/reports/tr15/)是字形正規化依據。

FTS5 trigram 的全文查詢不匹配少於三個 Unicode 字元的 substring；LIKE/GLOB 的索引使用還受 pattern、case_sensitive、remove_diacritics 和 ESCAPE 條件影響。預選以安全編譯的 MATCH phrase 取得三字以上候選，使用完整 detail；一至兩字明確走精確掃描，不靠 LIKE 是否剛好優化。不能在 detail=none 下直接沿用長詞 MATCH。

英文可用 unicode61 詞級候選與 BM25 排名；CJK／混合 query 加 trigram 分支。搜尋 adapter 不准直接串接使用者 FTS 表達式，雙引號、百分號、底線、括號和 SQL 字樣預設是文字。

## 3. 詞組別名與歧義

別名以使用者可檢查的版本化詞組表管理，例如「關西腔／関西弁／Kansai dialect」。可為雙向或單向，包含語言、理由和 owner 核准；修改經受控提案，不由模型偷偷學進權威庫。

「開發／开发／開発」與人名異體字只在已定義詞組內展開；不能整庫無條件逐字替換。多義字（如「後／后」）、地名同名與日文異體字必須有負例。模型臨時提出的 query expansion 可在當次回覆展示，但不能自動成為永久別名或事實。

搜尋回覆記錄原 query、實際 expansion（僅給已授權 caller，不入一般 log）、alias version、匹配種類與歧義。對人名可以 raw exact，避免正規化把不同名稱誤合併。

## 4. 定位型查詢語意

1. 驗 grant、scope、時間軸、revision mode 和預算。空 query 只有明確 browse scope 才允許。
2. query 以空白分隔 term，帶引號為 phrase；預設 terms 交集，每個 term 的已核准 aliases 為聯集。`match=any` 必須顯式指定。中日文無空白短句作一個 phrase，不自行假裝知道詞界。
3. 每個 term 在 normalized scalar 長度 >=3 時用 trigram 候選；短詞以 `instr` 或等價精確掃描。英文 token 分支提供排名訊號，不可用英文分支漏掉 CJK 硬條件。
4. 候選集合按 term 語意交集／聯集，使用 authority 的允許集合重驗。排名為 exact ID/phrase 優先，再 lexical score；可固定權重及 tie-break ID，禁止未告知地只給最新內容。
5. 原始來源與衍生資料分組呈現。衍生摘要可導航，不能用多份摘要的重複出現提升證據數量。
6. 每個命中附 Record/Revision、content_kind、作者性質、時間精度、來源版本、原文 quote range、correction/withdraw 標籤和 index freshness。

全文 fallback 如超時，回 `complete=false`、已掃描範圍和續作游標，不以空集合回「沒有紀錄」。不因對話背景知道某件事，就省略正式工具搜尋。查無資料的答案必須區分「這次範圍內未找到」和「事情未曾發生」。

長正文以完整版本索引或有重疊 chunk 建候選；首版選完整版本以簡化引用。query term 上限 512 Unicode scalars，拒絕不合理超長 pattern。遇到 tokenizer 長 token 限制的正文仍有精確掃描退路，測試以長 URL／無空白字串覆蓋。

## 5. freshness、刪除與索引恢復

每次結果包含 authority snapshot seq、index generation、index watermark、pending count、完整性旗標。索引落後只影響可用性，不能影響 authority 可見性。所有 snippet、title、facet、count 都從通過授權與最新 lifecycle gate 的資料生成，不能把舊 FTS 表全文直接回傳。

有查詢完整性要求時，以 authority 補掃 watermark 之後的新／修正版本；刪除與來源隔離即使 worker 未處理也必須排除。重建生成 staging index，驗 counts、抽查命中、authority refs 與 privacy epoch，再切 generation。索引格式升級直接重建，不做不可維護的跨引擎索引遷移。

安全控制細節見 DATA_CONTRACT 7–9。FTS5 資料移除、SQLite 物理清理及檔案副本清理是不同工作，不能只用 DELETE SQL 宣稱所有內容消失。

## 6. 聚合型查詢：固定範圍、可續作

「過去三年對工作的想法變化」先列 query plan：時間軸、起訖與時區、資料種類、latest/all/as_of、主題篩選、未知日期處理、預算及排除項目。主題關鍵字只定義候選範圍，不能代表全庫相關性已完整找到。

Core 建立不可變版本 manifest：在短暫一致讀取下列出 scope 中所有允許 ID/Revision 和字節長，記 `snapshot_seq`。穩定排序以時間＋ID＋Revision；keyset cursor 綁 scope hash／scan_id／index generation，不能用會因新增變動而漏頁的 offset。後來新增資料不進這次 snapshot；更新仍讀已固定版本，隱私刪除則以最新 gate 排除。

處理步驟：

1. 分頁讀完整原文；長文用 UTF-8 byte ranges，所有範圍讀完才算完整閱讀一個版本。
2. Agent 每批產生暫時摘記、支持與反例 reference；Core 記 delivered ranges，Agent 自述理解狀態分欄，不能讓自報數量取代實際讀取。
3. 依年份／主題做合併；摘要附 leaf source set，不把中間摘要當新的獨立來源。
4. 顯式檢查否定、改變主意、已完成紀錄、反例與最後狀態；不使用「沒找到完成紀錄」推導「確定未完成」。
5. 最終答案附 coverage、資料缺口、選擇偏差與引用。分析不自動保存；使用者明確要求且 save grant 涵蓋此衍生內容時，可信任 Agent 可免重複人工確認提交新衍生 Record，否則維持 owner 確認流程。

coverage 必須包括：`eligible_at_start`、`delivered_full`、`delivered_partial`、`blocked_since_start`、`failed`、`unprocessed`、`new_since_snapshot`、`unknown_event_time`、總字節／已讀字節、按年與 content_kind 分布、排除條件、停止理由、是否依賴摘要。分類需互斥並能核算回起始集合。privacy 發生後報告只給安全的計數，不洩漏被刪除標題或 ID 給無權限 caller。

`complete=true` 只代表指定 snapshot 內所有**仍可讀**資料已完整交付、且無失敗／未處理；blocked 數必須明列。Core 不保證模型理解正確，更不能把這個 complete 說成「完整人生分析」。快照內缺失年份、紀錄密度和只在困難時寫日記等偏差必須保留。

## 7. Token 與品質取捨

定位先回短 snippet 和 provenance，再按需 get；聚合可分批，預算不足即中止並回游標和 partial coverage。不得以縮小分母、丟掉反例、刪引用、重用已污染摘要或只取 Top-k 節省 Token。

初始預算用可測量 byte limit；接入模型時由實際 tokenizer 計算，沒有 tokenizer 就標 estimates，不能固定宣稱一個中文字等於一個 token。記錄 prompt/output token、模型版本、費用是否可得和全量參考流程，禁止未授權付費 API。

V1 可選只讀一次來源並保留 temporary summaries，但 cache 有 source refs、模型／prompt 版本、privacy epoch、短 TTL，且受刪除閉包管理。不自動全庫月度摘要。若同類完整分析的測量未證明節省又維持品質，不新增摘要維護層。

## 8. P0 實驗與待驗證

- FTS5 實際 build 是否有 trigram，Windows 套件是否可重現安裝。
- 短詞全掃在指定字節規模是否達標，效能瓶頸是 IO／normalization／授權 hydration 哪一部分。
- SQLite 與 Tantivy+Lindera 在同一標註集的漏召回、排名、字典大小和部署差異；不僅比較一題速度。
- 別名覆蓋收益與歧義負例；同一來源的多份摘要是否污染排名。
- 聚合 manifest／長文字節範圍／刪除中止是否能正確續作。
- 代表性合成語料不等於真實使用品質；真實語料評估必須另有明確授權，不能從使用者檔案自行採集。

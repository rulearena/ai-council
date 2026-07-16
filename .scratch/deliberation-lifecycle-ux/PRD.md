# 審議生命週期、案卷版本與民刑事法院體驗

Status: implementation reopened / acceptance fixes in progress

Canonical backlog: `spec.md` §15 #88

## Problem Statement

目前 meeting 只有一條持續增長的討論紀錄；使用者若想用同一批證據重新審議，只能重建 meeting 並重複上傳案卷。此外，系統設定、會議設定與流程操作混在同一入口，法院模式也將民事土地爭議顯示成「檢察官」，且「待裁定」並未告訴主席必須手動送交法官。證據只能在建立時輸入，缺乏版本、停用、案件備註與修改後的審議安全 gate。

## Solution

將「審議輪次」建模為 append-only 的 meeting lifecycle：重開時封存整輪主席與 AI 討論，保留但不複製案卷，新 prompt 只讀目前輪。Courtroom 可重開目前爭點、全部審議或重新整理爭點。案卷與案件備註支援穩定編號、版本、停用與角色可見性；審理後變更會強制主席選擇重開範圍。法院建立時由使用者選擇民事或刑事，由法官模型整理中立爭點，使用案件別正確的角色、prompt 與最終結果。前端將全域系統設定、meeting-scoped 會議設定、案卷與證據、議事紀錄及流程操作分層。

## User Stories

1. As a 主席, I want 在同一 meeting 重開審議, so that 我不必重複上傳大量證據。
2. As a 主席, I want 舊討論被封存而非刪除, so that 我可追溯每次重審原因與結果。
3. As a 主席, I want 重開時必填或選擇原因, so that 多輪審議有可理解的稽核軌跡。
4. As a 主席, I want 新審議不讀舊主席發言或 AI 結論, so that 重審不受舊方向污染。
5. As a 主席, I want 所有模式都可重開審議, so that reset 不是法院專用的隱藏特例。
6. As a 法院主席, I want 只重開目前爭點, so that 我可保留其他已完成的判斷。
7. As a 法院主席, I want 重開全部審議但保留爭點, so that 同一 docket 可用新模型或新證據從頭審理。
8. As a 法院主席, I want 重新整理爭點, so that 我可重新編輯 AI 目標、案件類型與 docket。
9. As a 使用者, I want 議事紀錄依輪次分組, so that 舊結論不會與目前結果混在一起。
10. As a 使用者, I want 預設只看目前審議, so that live status 不會被舊失敗或裁判污染。
11. As a 使用者, I want 下載某一輪或完整歷史逐字稿, so that 我能比較多次審議。
12. As a 主席, I want 新增、更新版本、停用或重啟證據, so that meeting 不需因為補件而重建。
13. As a 主席, I want 證物編號與引用錨點不因版本變更而改變, so that 歷史引用仍可追溯。
14. As a 主席, I want 證據停用而非刪除, so that 舊審議仍能看見當時使用的版本。
15. As a 主席, I want 每個證據版本都能指定可見角色, so that 新版本不會沿用錯誤的權限。
16. As a 主席, I want 建立版本化案件備註, so that 重要事實可跨輪提供給 AI。
17. As a 主席, I want 把某筆主席發言轉為案件備註, so that 只有明確選取的資訊跨輪保留。
18. As a 主席, I want 審理後證據變更會停止繼續 AI, so that 雙方不會在沒機會回應新證據時就被判斷。
19. As a 法院使用者, I want 建立時自己選擇民事或刑事, so that 系統不會對土地爭議顯示檢察官。
20. As a 舊法院 meeting 使用者, I want 在繼續前手動確認案件類型, so that AI 不會以 title 或 goal 猜測。
21. As a 民事使用者, I want 看見原告代理人、被告代理人與法官, so that 角色符合案件性質。
22. As a 刑事使用者, I want 看見檢察官、辯護人與法官, so that 角色與攻防語意正確。
23. As a 主席, I want 民刑事爭點都由法官模型整理中立草稿, so that 主張方不會遺漏對自己不利的爭點。
24. As a 主席, I want 攻防清楚標示主張、答辯與限縮反駁, so that 同一角色的第二次發言不像重複執行。
25. As a 主席, I want 反駁後先停下, so that 我可要求答辯方補充而不被自動判斷。
26. As a 主席, I want 目前爭點顯示「等待主席送交法官」, so that 我知道什麼時候才會產生判斷。
27. As a 主席, I want sticky 「請法官判斷此爭點」, so that 主要下一步不會藏在清單底部。
28. As a 使用者, I want 單一爭點稱法官判斷、全案才稱最終判決, so that 中間結果與全案結果不混淆。
29. As a 民事使用者, I want 最終判決呈現請求成立範圍、履行義務與證據來源, so that 結果不是 generic 核准。
30. As a 民事使用者, I want AI 不得發明案卷沒有的金額, so that 結果不會出現無來源的假精確數字。
31. As a 刑事使用者, I want 最終判決顯示各項指控與罪責結論, so that 刑事結果不像民事請求。
32. As a 刑事使用者, I want AI 不產生具體刑期、罰金或刑罰, so that 缺乏法域與量刑資料時不會誤導。
33. As a 使用者, I want 系統設定只管全域模型與進階功能, so that 我不會把 meeting 選項誤當全域設定。
34. As a 使用者, I want 會議設定右抽屉一次編輯全部 meeting 選項, so that TopBar 不會被橫幅表單撐開。
35. As a 使用者, I want 會議設定以單一儲存原子更新, so that title 成功、模型失敗的半套狀態不會發生。
36. As a 使用者, I want 關閉 dirty 會議設定前收到確認, so that 未儲存修改不會意外遺失。
37. As a 使用者, I want 會議設定、案卷與證據、議事紀錄出現在 meeting 次導覽, so that 我能分辨這場會議的資料與全域系統。
38. As a 使用者, I want 流程操作只包含重開、序列、取消、結案與重新開啟, so that 破壞性操作不會藏在設定。
39. As a 普通使用者, I want 事件原始資料預設關閉, so that 進階診斷不會擾亂一般使用。
40. As a 進階使用者, I want 系統設定清楚說明原始資料只影響顯示, so that 我不會誤以為它改變 AI。

## Implementation Decisions

- 新增深 module 集中 replay raw append-only journal，對 caller 提供 active deliberation、epoch history 與三種 restart scope；raw repository 仍回傳完整歷史，不隱式過濾。
- Legacy meeting 在第一個 epoch marker 前的 events read-time 視為 implicit epoch 1，不回填。restart 以 versioned System marker 記錄 epoch identity、原因、scope、goal、case type、docket/model snapshot 與 carry-forward lineage。
- 新 epoch 必須進入 event identity namespace；step ID 與 internal role ID 保持相容。主席在 courtroom current issue 的發言必須儲存 issue context，使 current-issue restart 可決定封存範圍。
- Runner prompt、workflow completion、failure/retry、courtroom projection、WebSocket live snapshot 與預設 transcript 只消費 active view；lifecycle terminal state、全局累計成本、legacy assignment recovery 與稽核 export 保持 all-history 語意。
- Restart 與所有 meeting mutation 共用現有 per-meeting transition coordinator，不另建 lock。running 拒絕；terminal 要求先 reopen。
- 案卷深 module 擁有 versioned case materials 的唯一 Source of Truth；metadata 只可保存 revision/count 投影，不與內容雙寫。Evidence 與 case note 均有穩定 ID、active/inactive、versions、visible roles 與 optimistic revision。
- 舊 case-file list 讀取時投影為 legacy active version，不寫入；第一次明示 mutation 才原子升級 versioned schema。相同證據不因 restart 複製。
- 會進入 prompt 的 materials 變更會增加 materials revision；active epoch 已有 AI output 時投影 pending impact 並以後端 gate 拒絕所有 AI/法官操作，直到 restart 解除。
- Courtroom case type 是 meeting-level domain，不複製為兩個 modes。metadata 以 `civil|criminal` 作 SoT，internal role IDs 維持穩定，case profile 集中顯示角色、三段 workflow、prompt templates、schema IDs 與 presentation labels。
- 新 courtroom 必選 case type；legacy missing type 可查看但所有新 AI/重試/裁判在明示選型前被 gate。Pre-confirm 切換類型使整份未確認 docket 失效；post-confirm 鎖定，rebuild 才重新開放。
- 新 courtroom events 儲存 case type、role/phase display snapshot；舊 event 無 snapshot 時維持舊 catalog 呈現，不因後來選型被 retroactive relabel。
- Issue ruling 保留中立結果 IDs，由 case profile 投影案件別文案。Civil/criminal final 使用不同 versioned schema與 renderer；criminal schema 排除具體 penalty，civil monetary relief 需 calculation basis 與 evidence refs。
- 會議設定以單一 atomic interface 更新 expected revision、title、goal、case type、scene 與完整 participant models；後端先完整驗證再寫入，新 UI 不使用既有分散 immediate-save 路徑。
- Scene 轉為 meeting-scoped persisted setting；legacy 無值時 read-time 使用 mode default。會議設定抽屉有 local draft、dirty close confirmation、sticky save/discard 與 meeting/request generation guard。
- Records 歷史瀏覽使用獨立 state，不替換 live meeting events。系統設定僅保留模型管理與進階顯示；meeting 次導覽負責會議設定、案卷與證據、議事紀錄；workflow operations 容納 restart/lifecycle/sequence。

## Testing Decisions

- 測試只穿越已核准的 public seams：deliberation/case-profile/case-material domain interface、HTTP meeting interface、runner observable events/prompt outcome、frontend pure projection、Playwright 與 direct browser。不 mock 內部 module，不以私有檔案結構當作唯一斷言；file bytes/hash 只用於不改歷史與不複製的明確契約。
- Deliberation domain tests 覆蓋 implicit legacy epoch、blank reason、all/current/rebuild replay、carry-forward、unique event identity、docket snapshot 與 fault ordering。
- HTTP/runner tests 覆蓋所有 modes restart、running/terminal/scope gate、prompt 排除封存事件、retry 不命中 archived failure、parallel synthesis 只看 active members、WebSocket full replacement、transcript epoch query。
- Case material tests 覆蓋 legacy read 不寫盤、first mutation upgrade、version/deactivate/reactivate、anchor 不重用、role visibility、limits、optimistic revision、promote note 不改 source event 與 materials-change gate。
- Courtroom tests 覆蓋 create required type、legacy explicit selection、pre-confirm switch/post-confirm lock、全 AI/retry paths gate、Judge draft、civil/criminal role/prompt/final schema、event-local labels、legacy no relabel、criminal no penalty 與 civil unsupported monetary value rejection。
- Frontend unit tests 覆蓋 meeting draft atomic payload/dirty/lock、records history isolation、case material impact choices、case profile labels/outcomes/final renderer 與 sticky primary action。
- Playwright 覆蓋普通 mode restart、courtroom 三種 restart、必填原因、證據數量不變、歷史輪次、民刑事完整一爭點與 final、settings IA/atomic save、evidence version/gate、375px 及 reload/switch isolation。
- 最終 gates 不得低於核准基線：backend 345、frontend unit 35、build 通過、Chromium 77，另以非 test runner 真瀏覽器驗證重開不複製證據、民事案件與 sticky 法官判斷。

## Out of Scope

- 不永久刪除封存審議或單筆歷史 event。
- 不導入外部資料庫、RAG、embedding、雲端儲存或帳號權限系統。
- 不讓 AI 自動推論民事／刑事、不自動送交法官、不產生具體刑罰。
- 不保證任一特定司法管轄區的正式程序或實體法正確性；產品仍是模擬審議工具，非正式法律意見。
- 不將 civil/criminal 複製成兩個 mode，不改既有 internal role IDs。
- 不使用外部 provider 進行自動驗收。

## Further Notes

- Human Owner 於 2026-07-15 完成 grill-me 30 題決策並整批核准。
- 產品 backlog 唯一 Source of Record 是 `spec.md` §15 #88；本 PRD 只是已核准工作的執行說明。
- main 核准基線為 `fb4f54e`；使用者在 main 的 model config 900 秒修改不屬於本批，不得修改、stage 或 commit。

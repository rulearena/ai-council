# 交接文件（2026-08-05 更新）

> 給接手開發的 agent（Codex 或任何新 session）。讀完本檔 + 引用的 spec 章節即可接續，不需要舊對話脈絡。

## 1. 現況：什麼已經完成

目前分支包含四個已完成的大功能，全部驗證通過：

| 功能 | Merge commit | 內容 |
|------|--------------|------|
| Mode system slice A | `981f355` | 前端席位動態化、模式卡片牆、本地 catalog |
| Mode system slice B | `059dcbe` | `config/modes.yaml` + `GET /modes` + relay 執行器參數化 + 法庭審理/辯論上線（實作計畫留檔：`docs/plans/2026-07-12-mode-system-slice-b.md`） |
| Model config mgmt（spec §17） | `ac44fef` | 模型 CRUD API + Settings 模型管理分頁（實作計畫：`docs/plans/2026-07-13-model-config-management.md`） |
| Mode system slice C | `711640d` | parallel 執行器 + per-member retry/synthesis gating + 腦力激盪上線；六帽/盲測設定與 prompt 補齊（實作計畫：`docs/plans/2026-07-13-mode-system-slice-c.md`） |
| Backlog 75–77 cleanup | `5adbffa` | reopening cancelled/closed meetings；mode fallback/API error/New Case failure retention cleanup |
| Case Files Phase 1 | `48e2f34` / `74780f9` / `088b5bc` | 建立會議時貼上/上傳多份純文字或 Markdown 案卷；每份指定可見角色；runner 依角色注入 `{{ case_files }}`（實作計畫：`docs/plans/2026-07-13-case-files-phase-1.md`） |
| Mode system slice D | `e7237c9` | parallel synthesis anonymization hook：per-mode `synthesis.anonymize_inputs` 啟用後，彙整 prompt 僅看匿名委員代稱與過濾後輸出（實作計畫：`docs/plans/2026-07-13-mode-system-slice-d.md`） |
| Evidence to Verdict | `96cd1d9`–`c597e32` | 證物引用錨點、versioned per-role output schema、adjudicator rich structured verdict、parse-only auto retry 與新舊輸出呈現（實作計畫：`docs/plans/2026-07-13-evidence-to-verdict.md`） |
| Configurable Case File Limits | `2c3f069`–`b51052a` | 案卷單份/總量限制環境變數化（預設 50,000/120,000）、公開實際限制、建立前字元/token/context 提示、超限阻擋與 413 detail 保留（實作計畫：`docs/plans/2026-07-13-configurable-case-file-limits.md`） |
| LLM Attempt Diagnostics | `9d5adae`–`b5ff417` | 每場 meeting 保存成功、parse、timeout、adapter、interrupted attempts 的完整可取得診斷；Records Drawer 可安全查看／複製（實作計畫：`docs/plans/2026-07-14-llm-attempt-diagnostics.md`） |
| Model Selection Reliability | `6c2b033`–`50becfa` | 每場 meeting assignment 持久化與 deterministic legacy fallback；Provider-first 模型管理、preview/existing discovery、manual exact ID 與跨 meeting/request race guards（實作計畫：`docs/plans/2026-07-14-model-selection-reliability.md`） |
| Provider & Model UX | `dad0410`–`9dd4162` | Anthropic/Gemini discovery、可搜尋 exact model、Claude/Codex/AGY CLI presets、測試 loading/slow/stale-safe feedback 與 health result ordering（實作計畫：`docs/plans/2026-07-14-provider-model-ux.md`） |
| Meeting UX Contract | `f6c3499`–`c18cf21` | `title`／AI `goal` 分離、舊 meeting 明示遷移 gate、集中式繁中 presentation、title + ID copy 與可追溯定向角色追問（實作計畫：`docs/plans/2026-07-14-meeting-ux-contract.md`） |
| Chairman & Courtroom Issue Flow | `2bb78af`–`15867f4` | 統一主席 composer、title/goal 編輯與鎖定、精確主 CTA、逐一爭點攻防／裁定／最終判決、legacy courtroom gate 與 per-meeting transition coordinator（實作計畫：`docs/plans/2026-07-14-chairman-courtroom-flow.md`） |
| Deliberation Lifecycle & Courtroom Workspace | `3551665` | append-only 審議輪次與三種法院重開、版本化證據／案件備註、民刑事 case profile 與安全 final schema、原子 meeting settings、歷史案卷與 responsive workspace（實作計畫：`docs/plans/2026-07-15-deliberation-lifecycle-ux.md`） |
| Courtroom Async Settlement | `eaa059f`–`b6b2432` | GET／WebSocket 一致 live snapshot、per-meeting lifecycle revision、frontend settlement generation guard 與 deterministic ordering tests（實作計畫：`docs/plans/2026-07-17-courtroom-async-settlement.md`） |
| Meeting Workspace Conversation | `018df1f`–`ef3c430` | A3-1 時間序工作區、relay／parallel 共用 Conversation、Court Hearing 爭點視圖、parallel arrival-order 即時保存與 terminal 原子 publish（實作計畫：`docs/plans/2026-07-18-meeting-workspace-conversation.md`） |
| Backlog 91 Chatroom Mode | `0c59c1e`–* | 無流程限制的 AI 聊天室模式：@角色／@all mention fanout、context token budget、聊天室 composer 與 mention autocomplete、Conversation workspace chatroom adaptation（實作計畫：`openspec/changes/ai-chat-room/`） |
| Backlog 92 Chatroom UX Polish | `f7065a9` | #91 驗收回饋的 8 項 UX 修正：座位互動統一、篩選對稱切換、訊息頭像、chatroom 排第一、場景 lightbox、in-rail 換模型（含法院模式）、TopBar subnav 精簡、auto-scroll 根因修復（實作計畫：`openspec/changes/chatroom-ux-polish/`） |
| VibeCoding Workflow 採用（AIDLC） | `96e083c` | 新增 `docs/agents/workflow-bindings.md`（§0-§6）；AGENTS/CLAUDE 政策入口 bootstrap；三份角色 prompt 修正（中央 source：`VibeCoding_Workflow` @ `de1aca4918`） |

**目前驗收基線（任何改動後不得低於此）**：後端 `pytest` **653 passed**；frontend unit **116 passed**；前端 `npm run build` 綠；Chromium e2e **125/125 passed**（基線在 main `ebc49f2`）。Backlog #90 已通過 Standards／Spec 雙軸獨立 review，並以 direct Chromium 實際完成建立會議 → 主席補充 → AI 回合 → 角色篩選 → 長文展開 → 案卷 drawer。Backlog #91（chatroom mode）已實作並包含在此基線中；Backlog #92（chatroom UX polish，#91 驗收回饋）已實作並包含在此基線中，e2e 基線數字由 105 提升至 118（新增 13 案例）、再經第二輪修正提升至 125。

**2026-08-04 closeout**：Backlog #100「右側會議脈絡欄收合後可重新展開」已由 Human Owner 驗收通過，狀態 `accepted / done`。Gate B reviewed implementation `12da498`（Reviewer `PASS`）已以 exact merge commit `16002be` 合併；post-merge frontend unit `162/162`、production build、focused Playwright regression 通過。Chrome smoke 確認桌面收合後 toggle 可重新展開、重複循環穩定，375px responsive 行為保留；full E2E 本次未執行。此為既有 `.scratch` scoped fix，無 OpenSpec delta，`.scratch/context-sidebar-toggle-fix/` 保留為歷史紀錄。

**2026-08-04 #98 closeout**：Human Owner 明確確認「#98 驗收通過」，狀態 `accepted / done`。Exact implementation merge 是 `2d1b9a5`（chatroom `@all` fanout batch display；frontend-only）。Final contract 為首個回應前顯示 `0/N` 與全部預期角色 placeholders、依事件 arrival order 填入 member bubbles、未完成 placeholders 固定在底部且分母固定；failure、unknown、request failure 與 disconnect/reconnect degradation 均有定義。範圍僅限 chatroom `@all`；directed single-role／multi-mention、relay、parallel、courtroom、其他正式／非聊天室流程與歷史 fallback 維持 flat／不變；無 backend、event schema、API 或 data migration 變更。驗收證據：focused `frontend/tests/e2e/chatroom.spec.ts -g '13\\.4|13\\.7'` **4/4**、`frontend/tests/unit/meetingWorkspace.test.ts` **31/31**、`npm run build` 通過。OpenSpec change `chatroom-fanout-batch-display` 的 tasks 已全數完成；本次未重跑 full backend suite、full frontend unit suite 或 full Chromium E2E。

**2026-08-04 #99 closeout**：Human Owner 明確確認「#99 驗收通過」，狀態 `accepted / done`。Exact implementation merge 是 `111e898`。Final contract：chatroom 新的 directed 與 `@all` 回應使用 `chat-message/v1`，以精簡的 `parsed_output.message` 作為自然聊天氣泡內容；證據 anchor 保留，raw／parsed／schema／prompt／model diagnostics 仍可稽核；舊 structured chatroom events 維持 read-time 相容且不改寫 JSONL；relay／parallel／brainstorm／courtroom／formal schemas 與 presentation 維持不變，無 migration。驗收證據：focused `Playwright tests/e2e/chatroom.spec.ts -g '13\\.3'` **1/1**、`frontend/tests/unit/meetingWorkspace.test.ts` **31/31**、`backend/tests/test_runner_chatroom.py` **13/13**、`backend/tests/test_prompting.py -k 'chat_message_v1 or chatroom_response_template'` **5/5**、`frontend npm run test:unit` **162/162**、`frontend npm run build` 通過。OpenSpec change `chatroom-natural-response` tasks 已全數完成並完成 strict sync/archive。未驗證範圍：本次 acceptance 未重跑 full backend suite、full Chromium E2E、direct browser smoke 或其他非列明模式的完整回歸。

**2026-07-30 第二輪驗收修正（已於 2026-07-31 Gate B 通過並 merge 至 main `ebc49f2`）**：Human Owner 於 2026-07-30 驗收 #92 時判定「只有第 9 點有做到」，退回重修。該分支共 13 commits（`943faa3`…`7b62add` 12 commits + 文件 commit `ebc49f2`，base 為 main `2ee4147`），e2e 由 118 提升至 125。內容：app-shell 視窗高度上限（此前只有法院模式有，導致 composer 隨滾輪移動）、座位改為真正的 `<button>` 並統一主席與角色行為、脈絡欄收合回收中間欄空間、紀錄密度、mode 感知的案卷用語、LINE 式訊息版面、訊息串開在最新處並跟隨自己送出、聊天室換模型 500（`UpdateMeetingSettingsRequest` 對 chatroom 強制 goal）、被 @ 角色的思考氣泡（聊天室 composer 繞過 store 導致 `pendingRoles` 從未填入）、中文選字 Enter 誤送出、提及選單鍵盤操作（`onKeyDown` 為死程式碼）、案卷 `+` 改為置中彈出視窗、法院模式套用同一套座位契約並補場景放大。獨立 Reviewer 於 2026-07-31 對 fixed range `2ee4147...ebc49f2` 審查，Verdict `pass`（無 Blocking/Major，Minor 均已裁定，詳見 spec.md §15 #92／#94），Orchestrator 已 fast-forward merge exact reviewed HEAD 並重跑 post-merge checks（653／116／build 全綠）。**狀態：`accepted / done`（2026-07-31 Human Owner 驗收通過）。** Human Owner 於驗收期間另發現「+」無檔案上傳（與 round-2 無關的既有缺口），已裁定開新 backlog #96（LINE 式聊天附件）。#91 與 #92 已於同一次 closeout 一併完成 delta specs sync 至 `openspec/specs/` 並 archive。

**2026-08-05 #101 closeout**：Human Owner 原始確認「#101 驗收通過」，狀態 `accepted / done`。Final contract：聊天室引用預覽使用既有深色 surface／border／text tokens，保留引用內容、取消引用與送出語意，桌面與 responsive layout 不回退為 light fallback；不改 backend API、事件格式、聊天執行語意或其他模式。Exact implementation merge 是 `b813a0ba10d5f6ce56c63d62119c45ca86aadf34`；Gate B final independent Reviewer 審查 `bdfd81d71cd709e2b654aef469d4f40e4ad9da68..b813a0ba10d5f6ce56c63d62119c45ca86aadf34`，Verdict `pass`。變更產品檔案為 `frontend/src/components/ChatroomComposer.vue` 與 `frontend/tests/e2e/chatroom.spec.ts`。驗收證據：focused Playwright `13.5`／`13.5a` **2/2**、frontend unit **162/162**、`npm run build` 通過、`git diff --check` 通過。未驗證範圍：本次 post-merge 未重跑 full backend suite、full Chromium E2E，且沒有 direct Chrome/browser version evidence。這是 `.scratch/quote-preview-theme-fix/` scoped fix，沒有建立、修改或封存 OpenSpec archive。

**2026-08-05 #95 closeout**：Human Owner 原始確認「#95 驗收通過」，狀態 `accepted / done`。Final contract：逐字稿搜尋在 IME composition 期間按 Enter 不搜尋；composition 結束後普通 Enter 與滑鼠點擊搜尋仍正常，且不改 API、搜尋語意、其他 mention／IME 行為。Exact implementation merge 是 `b4b6f94470232d673b02e6ad7c2fbec3d097926e`；implementation fixed range 為 `b9389d90180aa0ddbfa439152e7dec7b680cc23e..b4b6f94470232d673b02e6ad7c2fbec3d097926e`，commit chain 為 `05fd1b4`（red regression test）→ `b4b6f94`（green IME guard fix）。Gate B Standards／Spec 兩個獨立 axis 皆 `pass`、無 findings。變更產品檔案為 `frontend/src/components/MeetingsModal.vue` 與 `frontend/tests/e2e/control-flow.spec.ts`。驗收證據：focused Playwright `tests/e2e/control-flow.spec.ts -g 'transcript search ignores IME'` **1/1**、frontend unit **162/162**、`npm run build` 通過、`git diff --check` 通過。未驗證範圍：未重跑 full backend suite、full Chromium E2E，且本次未保存 direct Chrome/browser version evidence。這是小型 `.scratch` scoped fix，沒有 OpenSpec change/archive。

## 2. Agent 開發佇列與目前核准批次

Evidence to Verdict 批次已實作並等待 Human Owner acceptance。

Backlog 81「案卷容量限制設定化與建立前提示」已實作並通過雙軸 review 與完整驗收，等待 Human Owner acceptance。預設單份/總量為 50,000/120,000 字元，環境變數可覆寫；前端僅在取得後端實際限制後允許建立，並顯示 token/context 風險、inline 錯誤與後端 413 detail。執行計畫：`docs/plans/2026-07-13-configurable-case-file-limits.md`；ticket：`.scratch/configurable-case-file-limits/`。

Backlog 82「每場會議的 LLM attempt 診斷紀錄與檢視器」已實作並通過雙軸 review 與完整驗收，等待 Human Owner acceptance。失敗 attempt 現在保留 raw/parsed output、模型、prompt、時間、token、錯誤分類與安全的 adapter excerpts；Records Drawer 可查看／複製。取消中的 in-flight attempt 會留下 `interrupted/result_discarded` 診斷，但不進 transcript，且不會在 terminal 後啟動 retry 或 synthesis。執行計畫：`docs/plans/2026-07-14-llm-attempt-diagnostics.md`；ticket：`.scratch/llm-attempt-diagnostics/`。

Backlog 83–84「模型選擇可靠性」已實作並通過雙軸 review 與完整驗收，等待 Human Owner acceptance。Meeting participant metadata 是 assignment Source of Truth；舊 meeting 僅 read-time 從最新 event/default 恢復，不改寫歷史。Model Manager 以 Provider-first 顯示 exact model ID，支援 preview/existing discovery 與 manual fallback。執行計畫：`docs/plans/2026-07-14-model-selection-reliability.md`；ticket：`.scratch/model-selection-reliability/`。

Backlog 85「Provider 與模型設定 UX 強化」已實作並通過 Standards/Spec 雙軸 review、完整驗收與 direct Chromium smoke，等待 Human Owner acceptance。Anthropic/Gemini 支援 provider-specific discovery 與搜尋；Claude/Codex/AGY 使用 per-preset canonical argv；Model Manager 的連線測試提供 loading/slow/success/error 並阻止 frontend/backend stale result。執行計畫：`docs/plans/2026-07-14-provider-model-ux.md`；ticket：`.scratch/provider-model-ux/`。

Backlog 86「會議名稱／AI 目標、中文呈現與定向追問 UX」已實作並通過 Standards/Spec 雙軸 review、完整驗收與 direct browser smoke，等待 Human Owner acceptance。新 meeting 強制 `title + goal`；舊 `topic` meeting 必須由使用者明確補 goal 才能再執行，遷移不改 events；主要 meeting UI/逐字稿使用集中式繁中 presentation；定向角色回應必填 instruction 並保存 Human instruction/linkage，失敗 retry 重用原 instruction。執行計畫：`docs/plans/2026-07-14-meeting-ux-contract.md`；ticket：`.scratch/meeting-ux-contract/`。

Backlog 87「主席操作整合、會議資訊編輯與逐一爭點法院流程」已實作並通過 Standards/Spec 雙軸 review、完整驗收與 direct browser smoke，狀態為 `implemented / awaiting acceptance`。主席從同一 composer 選擇補充／全體／定向回應；title 在 idle 可編輯，courtroom goal 在爭點確認後唯讀。Courtroom 必須先編修確認 docket，之後依檢察官 → 辯護律師 → 檢察官反駁逐點攻防，每個 ruling 與 next issue 都由主席明示推進，全部裁定完成後才可 final verdict。執行計畫：`docs/plans/2026-07-14-chairman-courtroom-flow.md`；ticket：`.scratch/chairman-courtroom-flow/`。

Backlog 88「審議生命週期、案卷版本與民刑事法院體驗重整」已完成 Human Owner 驗收退回的 action IA 修補並再次通過 Standards/Spec 雙軸 review，Human Owner 於 2026-07-17 驗收通過，狀態為 `accepted / done`。舊法院案件類型只從會議設定原子儲存；法院 composer 不再顯示語意不實的「請全體回應」；正式流程使用短 CTA 與明確等待狀態，結案／取消 lifecycle 不會被 workflow 文案覆蓋。所有 mode 的 epoch、案卷版本、民刑事 profile 與歷史 revision 契約維持不變。執行計畫：`docs/plans/2026-07-15-deliberation-lifecycle-ux.md`、`docs/plans/2026-07-16-courtroom-action-ia-acceptance-fix.md`；ticket：`.scratch/deliberation-lifecycle-ux/`。驗收期間另發現且在 main 重現的法院 async refresh race 已記錄為 backlog #89，未納入本批。

Backlog 89「法院非同步完成狀態收斂」已實作、通過 Standards／Spec 雙軸獨立 review、597 backend／50 frontend unit／build／90 Chromium 與 direct browser smoke，Human Owner 於 2026-07-17 使用既有土地糾紛案件驗收通過，狀態為 `accepted / done`。根因是 API 可能把較舊部分 events 與已 release job state 組成 torn settled projection；GET 與 WebSocket 現共用 lifecycle-revision snapshot，重疊 job ordering 不穩定時只發布 running，frontend 以 settlement generation 防止舊 refresh 覆寫。沒有改 courtroom state machine、event schema、timeout 或歷史 events。執行計畫：`docs/plans/2026-07-17-courtroom-async-settlement.md`；ticket：`.scratch/courtroom-async-settlement/`。

Backlog 90「會議工作區與時間序對話介面」已實作、完成法院中央獨立滾動 acceptance 修補，並通過 Standards／Spec 雙軸獨立 review、605 backend／61 frontend unit／build／94 Chromium，Human Owner 於 2026-07-20 驗收通過，狀態為 `accepted / done`。Relay／parallel 共用 A3-1 Conversation workspace；parallel 依真正完成順序即時 append，reload 保持順序，同輪成員共享 frozen context且全員完成後才 synthesis。法院以 Court Hearing 按爭點／階段呈現，案件名稱只在 TopBar 顯示；桌面中央紀錄獨立滾動，左右角色列與正式流程維持可見，正式 CTA 仍只讀 backend `available_actions`。取消與 completed publish 現由 repository per-meeting atomic boundary 線性化，不會出現 terminal 後 completed output。瀏覽器控制環境於 acceptance 修補時沒有可用 in-app browser，因此未另做人工控制 smoke；targeted 與完整 Chromium 均通過。執行計畫：`docs/plans/2026-07-18-meeting-workspace-conversation.md`；ticket：`.scratch/meeting-workspace-conversation/`。自由聊天室模式已另記為 backlog #91，未納入本批。

已完成的 Evidence to Verdict 範圍：

1. backlog 80：證據編號與引用錨點。——已完成（2026-07-13，`96cd1d9` / `837b6d8`）
2. backlog 63/64：版本化角色輸出契約；舊 `role-output/v1` 與舊 events 維持相容。——已完成（2026-07-13，`a3a3382` / `c807f7a`）
3. backlog 65：adjudicator rich structured verdicts。——已完成（2026-07-13，`cb9b5aa`–`c597e32`）

批次計畫：`docs/plans/2026-07-13-evidence-to-verdict.md`；執行 tickets：`.scratch/evidence-to-verdict/`。三個 slice 均已實作並通過獨立 review，目前狀態為 `implemented / awaiting acceptance`。本檔不另行維護長期 backlog。

**目前狀態（2026-08-05）**：

1. backlog #94 尚有 Minor 項目 ②③④⑤⑥⑦⑨⑩⑭⑮；第 ① 項是流程規則衝突，仍待 Human Owner 決定，非程式碼工作。
2. 目前先處理 backlog #94⑮：聊天室組字期間直接點「送出」可能讓尚未完成的 IME 候選字遺失。
3. #94⑮ 之後優先處理 #94⑭（提及選單篩選後 `activeIndex` 可能指向不存在的 option）。
4. #95、#96、#98、#99、#100、#101 均已由 Human Owner 驗收並完成 closeout，狀態為 `accepted / done`，不再列為待決工作。
5. 法院場景「點擊放大」可發現性與先前遺失的「行銷」會議仍是待決事項；兩者目前都不是本次程式碼工作範圍。
6. 若訂閱制 CLI 額度仍不可用，UI 驗證需先切換至 `mock-fast`／`mock-slow`。

**歷史快照（2026-07-31；僅保留作為追蹤紀錄，不代表目前狀態）**：

1. backlog #92（`chatroom-ux-round2`）已於 2026-07-31 由 Human Owner 驗收通過，狀態 `accepted / done`；#91 與 #92 已於同一次 closeout 一併完成 delta specs sync 至 `openspec/specs/` 並 archive（`openspec/changes/archive/2026-07-31-*`），本待決項已關閉。驗收期間另裁定「+」上傳檔案屬 backlog #96，不屬本批驗收範圍。
2. Human Owner 的角色模型綁的是訂閱制 CLI，額度已用盡（約 2026-08-05 前後重置），期間 AI 不會回應；要驗 UI 需先把角色換回 `mock-fast`／`mock-slow`。
3. 法院場景「點擊放大」可發現性：場景正中央為座位、座位帶 `@click.stop`，該處點擊只選取角色不放大，空白處才放大。屬分層行為非失效，是否改為明確的放大按鈕待 Human Owner 決定（會同時影響聊天室）。
4. backlog #94 第 ① 項（`spec.md` 完成狀態標記時機與 `reviewer.md` 要求衝突）需 Human Owner 擇一為準，非程式碼工作。
5. Human Owner 先前的「行銷」會議遺失，不在隔離區也不在 repo，尚未回復。
6. **backlog #96（LINE 式聊天附件）**：`chatroom-line-attachments` 已 Gate A 通過（`afd2c43...3b930a5`）並完成實作與 Gate B 審查（fixed range `0187664...3c44b01`，`pass`，post-merge checks 681 backend／126 unit／build 綠），已 merge 至 main（`3c44b01`）。**2026-08-01 驗收修正**：Human Owner 上傳 `.txt`（依契約路由案卷＋#88 暫停）發現無事前警告，裁決加「存檔前警告」；已於 fix `16c1b34...efd0bc1`（Gate B round2 `pass`，post-merge checks 133 unit／build 綠）完成並 merge（`efd0bc1`）。狀態 `implemented / awaiting acceptance`，**正在重新驗收**。附件（binary，AI 看不見）與案卷（text，AI 看得見）路由、可下載、附件永久不刪除皆依 #96。**2026-08-02 驗收修正（第二輪）**：Human Owner 上傳 `.md` 發現聊天室材料卡顯示「證物」（`[證物N]`）；根因為錨點 token 後端硬編碼法庭用語。已裁決非法院模式改「附件」（`[附件N]`），採輕量疊代（設計經 Reviewer Gate A 角色 `pass`，2 Minor 事實修正）。核心決策：儲存層典範 `[證物N]` 不變，輸出面（prompt／UI／AI 驗證／前端新建預覽）依 mode 本地化；parser 與 mock adapter 寛容接受 `證物|附件`（法院模式非法院 token 由 `case_profiles` validator 攔截）。Fix `6813798...ac6671c`（5 commits／8 檔）Gate B 獨立 Reviewer `pass`，post-merge checks 715 backend（基線 681＋34）／137 unit（＋4）／build 綠。狀態 `implemented / awaiting acceptance`，**重新驗收中**。**2026-08-02 驗收修正（第三輪：拆分上傳與管理）**：Human Owner 要求 LINE 風格拆分：`＋` 只上傳（快速選單）、管理移至右側側欄「資料」頁（法院「案卷」）、二進位上傳進度列在資料頁頂部。設計（`.scratch/96-upload-management-split.md`）Gate A 兩輪 `pass`（round 1 `needs-fixes` 1 Blocking＋3 Major＋6 Minor＋2 Nit 全數修入）。實作 `ce458e7...04817ce`（10 commits／14 檔）：`MaterialsQuickMenu`＋`MaterialsPanel`＋`useMaterialUploads` 新元件，`CaseMaterialsModal` 移除；`ChatroomComposer` 新增 `uploadDisabled` 只鎖上傳（運行中 composer 不整組停用）。Gate B round 1 `needs-fixes`（運行鎖/附件清單兩項 e2e 缺漏、composer 鎖定過度）→ 修正（`78a456f`/`d95d9cb`/`413af4a`/`04817ce`）→ round 2 `pass`。post-merge checks 146 unit（＋9）／build 綠／chatroom e2e 33 pass。狀態 `implemented / awaiting acceptance`，**重新驗收中**。**2026-08-02 驗收修正（第四輪：主題樣式）**：Human Owner 指出「＋ 白底／管理附件白底」，根因為新元件 scoped style 用未定義 `var(--bg, #fff)`／`var(--border, #eee)` 等 fallback 蓋過 styles.css 深色 token。Fix `39e41d1`（1 commit／2 檔）：`MaterialsQuickMenu.vue`＋`MaterialsPanel.vue` 全換 `--color-*` 深色 token（unit 146／build 綠／chatroom e2e 33 pass），已 FF merge 至 main `39e41d1`。狀態 `implemented / awaiting acceptance`，**重新驗收中**。**2026-08-02 驗收修正（第五輪：側欄佈局）**：Human Owner 指出資料頁與紀錄混合、側欄需橫向滾動、並質疑上傳是否顯示於聊天視窗。DOM 實測確診：上傳→聊天氣泡正常（AttachmentBubble 在 feed）；紀錄混合根因為 `v-else`（改 `v-else-if="activeContextTab === 'records'"`）；橫向滾動根因為長檔名缺 `min-width:0` 鏈把內容撐到 844px（ellipsis 永不觸發），補 `min-width:0` 後 panel scrollWidth 856→299。Fix `be8da43`（1 commit／2 檔），unit 146／build 綠／chatroom e2e 33 pass／control-flow 受影響 7 用例全過，已 FF merge 至 main `be8da43`。狀態 `implemented / awaiting acceptance`，**重新驗收中**。**2026-08-02 驗收修正（第六輪：LINE 式上傳）**：Human Owner 裁決「＋」直接開原生檔案選取器（不要快速選單兩選項、不要 modal、移除側欄備註／表單／版本管理），且聊天室停用 impact 閘門（round 1 起既有 409 卡死死結：聊天室 AI 回應受 `pending_impact` 阻擋但無重開審議 UI）。設計（`.scratch/96-line-style-upload-round6.md`）Gate A 兩輪（round 1 `needs-fixes` 3 Major＋1 Minor＋2 Nit；round 2 Approve with conditions 4 條件：`.txt/.md` 接受僅限 chatroom、讀側 `require_case_materials_ready` 新增 `ignore_pending_impact` 治癒舊會議、summary() 措辭、e2e selector 遷移）全數納入。實作 `9850e34...f0a6f73`（13 commits／12 檔 +546/−72）：`＋`（`chatroom-attachment-button`）直開 file picker、`.txt/.md` 聊天室一魚兩吃（mirror evidence＋`attachment-added` event、`attachment-text` 卡片點開 reader 見全文）、`MaterialsPanel` simple、`materialCountFor` 防 N+1、`perform_material_mutation` chatroom→impact=None、讀側 ignore_pending_impact（僅 chatroom）。Gate B round 1 `pass`（2 Minor＋1 Nit）→ 修正（`f77530b`/`8fc34ee`/`f0a6f73`）→ 聚焦複審 `pass`。post-merge checks 720 backend（＋5）／147 unit（＋1）／build 綠／chatroom e2e 35 pass（＋2）。已 FF merge 至 main `f0a6f73`。狀態 `implemented / awaiting acceptance`，**重新驗收中**。**2026-08-02 驗收修正（第七輪：聊天室附件修正）**：Human Owner 裁決三事：①聊天室證據卡「使用中／已停用」狀態無按鈕是假功能（改 simple 只顯示標題）；②補「刪除附件」（所有模式皆有；`.txt/.md` 刪除連動移除 mirror evidence；聊天串氣泡保留標「已刪除」不可點開，LINE 回收式）；③聊天室舊會議殘留 `pending_impact` banner 改投影抑制（chatroom `project_case_materials` effective_impact 恆 None，不遷移資料）。設計（`.scratch/96-chatroom-attachment-fixes-round7.md`）Gate A `pass`（含 WS trade-off：其他 WS client 的已刪氣泡 refresh/reconnect 自癒、不實作重發）。實作 `.worktrees/96-chatroom-attachment-fixes-round7`（`96444e1...cee96c1`，8 commits）：`attachment-removed` tombstone（append-only，不重寫 attachment-added）＋blob 刪除＋download 404＋quota 釋放；`DELETE /meetings/{id}/attachments/{file_id}`（evidence 移除先於 tombstone；legacy 無 `evidence_id` 用 title fallback 0→跳過/恰1→移除/>1→400）；`project_events` 過濾 tombstone＋已刪標註 `removed:true`；runner/chatroom_context/transcript 排除 tombstone；前端 `deleteAttachment`＋刪除按鈕＋中性 confirm＋removed 氣泡＋`materialCountFor` 跳過 removed；`cee96c1` 修刪除後 stale 證據卡（reload materials）。Gate B 獨立 Reviewer `pass`（1 Minor docs 併入、1 Nit `AttachmentBubble.vue:247` `--border` fallback 待小修）。post-merge checks 743 backend（唯一 failure 為 pre-existing timing flake `test_startup_health_check_does_not_block_app_creation`，load avg 121-152 機器擁塞）／149 unit／build 綠／chatroom e2e 40 pass／control-flow relay delete 1 pass。已 FF merge 至 main `cee96c1`。狀態 `implemented / awaiting acceptance`，**重新驗收中**。
7. **AIDLC bootstrap 已上線（2026-07-31，backlog #97）**：所有新 session 依 `docs/agents/workflow-bindings.md` §0 載入中央工作流；後續開發流程（含 #96 的 proposal → Gate A → 實作 → Gate B → closeout）應依綁定檔 §3-§4 執行。

**目前下一步（2026-08-05）**：先完成本 handoff 的目前狀態同步，再依 TDD → Executor → Reviewer 流程處理 #94⑮，通過 Gate B 後交由 Human Owner 驗收；不需 `grill-with-docs`。

**歷史候選（2026-07-31；僅保留作為追蹤紀錄，不代表目前狀態）**：backlog #94 遺留 Minor（②③④⑤⑥⑦⑨⑩⑭⑮，其中 ⑧⑪⑫⑬ 已於 2026-07-30 修畢、⑭⑮ 為 2026-07-31 Gate B 審查新增，勿重做）、#95 遺留的 `MeetingsModal.vue` `@keyup.enter` 中文選字提早觸發，以及 backlog #96（LINE 式聊天附件，需先開 OpenSpec proposal）。尚未建立 OpenSpec change，須先登錄 `spec.md` §15 再提 proposal。#96 是否與 #94/#95 同批或獨立批次由 Human Owner 裁定。

**Human Owner follow-up**：新角色立繪由使用者自行產圖，不屬於 agent 開發佇列或產品執行批次。

### #96 closeout（2026-08-04）

Human Owner 已明確確認 #96 驗收通過，狀態為 `accepted / done`。Exact implementation merge 是 `cee96c1`。Final contract 包含原始 binary/text attachment 能力、round-6 的 LINE 式 `+` 直接開原生 file picker、chatroom `.txt/.md` mirror 成 AI 可讀 evidence、text attachment reader、chatroom `pending_impact` 寫入與讀取投影抑制，以及 round-7 的全模式刪除、append-only `attachment-removed` tombstone、blob 刪除／download 404／quota 釋放、mirror evidence removal、已刪除不可互動氣泡與刪除後 materials reload。

驗收證據：focused `frontend/tests/e2e/chatroom.spec.ts` **12/12**、`frontend npm run test:unit` **162/162**、`npm run build` 綠。既有 post-merge evidence：backend **743 passed**（一個 pre-existing timing flake）、frontend unit **149**、chatroom E2E **40**、relay binary-delete control-flow **1**。本次未重跑 full backend suite 與 full Chromium E2E。已知非阻塞 Nit：`AttachmentBubble.vue:247` 的 `--border` hover fallback 未定義，深色主題 hover 可能短暫呈現淺色。

## 3. 架構關鍵事實（改動前必讀）

- **模式是設定不是程式碼**：`config/modes.yaml`（六模式）→ `backend/ai_council/meetings/modes.py`（`ModeCatalogRepository` + `relay_plan()`/`parallel_plan()`）。relay step_id 慣例 = template 名把 `_` 換 `-`；parallel fanout step_id = `fanout-{round}-member-{k}`，base_step_id = `member-{k}`，synthesis step_id = `synthesis-{round}`。role sequence 仍使用角色原 phase template；單一 directed response 改用共用 `directed_role_response` prompt，step_id 保持 `directed-N-{role}-response`。
- **相容鐵則**：events.jsonl 既有 step_id（`blue-propose`、`round-N-*`、`directed-N-*`、`sequence-N-*`）不可變；無 `mode_id` 的舊會議投影為 red-blue；共用 output schema（spec §8）不變。守門測試：`backend/tests/test_mode_catalog.py::test_repo_modes_yaml_is_loadable`。
- **Runner**：relay 公開方法收 `plan: RelayPlan` + `inputs`（API 層用 `meeting_mode()` → `relay_plan(mode)` 解析）。relay round 計數 = `plan.steps[-1].step_id` 完成次數。parallel 走 `MeetingRunner.start_parallel()` / `retry_failed_parallel_step()` + `ParallelPlan`；fanout 啟動前凍結同一 active transcript，adapter calls 併發，runner 以實際完成順序逐組 append，member failure 投影 `waiting`，retry 成功且全員完成後觸發 synthesis。`ParallelPlan.anonymize_synthesis_inputs` 開啟時，synthesis prompt 的 `prior_transcript` 會清空，僅透過匿名化 `fanout_outputs` 讀成員結果。所有 event append/read 共用 repository per-meeting RLock；completed model output 必須用 `append_event_if()` 在同一 critical section 判斷 terminal 並發布。
- **Meeting workspace presentation**：非 courtroom mode 使用同一 Conversation workspace，保存順序就是顯示順序；relay queue 只有目前角色 thinking，parallel running snapshot 則依 current round events 推導所有未完成成員。Courtroom 使用 Court Hearing presentation，frontend 只依 backend issues／phase／`available_actions` 分組與顯示，不自建法院 state machine。原場景只保留為次要可收合狀態視圖。
- **模型寫入紀律**（§17 實作）：所有 models.yaml 寫入走 `model_write_lock`（存在性檢查+寫入+health clear 同鎖）；health store 有 generation token——**generation 取值必須在讀 model config 之前**（先取 gen → 讀 config → 檢查 → record(gen)，過期即丟棄）；`_write_config` 是 temp+rename 原子寫。
- **422 契約**：/models 寫入路徑的驗證錯誤（含 pydantic 層）統一 `[{"field", "message"}]`，前端 `ApiError.detail` 依 field 對應表單欄位。
- **Meeting model assignment**：participant metadata 是新 meeting 的唯一 assignment SoT；`PUT /meetings/{id}/participant-models` 完整替換 roster。Runner 的 start/respond/sequence/retry 只讀後端 resolved snapshot；legacy request `models` 不具權威。舊 meeting 的 event/default recovery 與 deleted-model fallback 只在 read time 投影，不寫 metadata/events。
- **Meeting identity / objective**：新 metadata 的識別與 AI 任務 SoT 分別是 `title`、`goal`；title 不進角色 prompt。legacy `topic` 只投影為待確認 title，goal 為空且所有 AI 執行入口回 409；只有 `PUT /meetings/{id}/details` 會明示遷移單場 metadata 並移除 topic，歷史 events 不改。
- **定向角色追問**：`POST /meetings/{id}/roles/{role}/respond` 必填 instruction；先保存 `human-directed-message`（target role），再保存 linked directed response。失敗／timeout／interrupted retry 以 `in_response_to_event_id` 重用原 instruction 與 generic prompt，不新增第二筆 Human event。Transcript interaction labels 必須 event-local，不得用共用 base step map 覆寫較早事件。
- **Courtroom docket SoT**：`metadata.courtroom_docket` 保存 revision、confirmed roster 與穩定 issue ids；issue phases/rulings/final verdict 只 append events。Frontend 只消費 backend `courtroom.available_actions`，不自建 state machine。confirmed 後 goal 唯讀；legacy courtroom 不改歷史，但下次執行前同樣必須建立並確認 docket。
- **審議輪次**：raw `events.jsonl` 永遠保存完整 append-only 歷史；`DeliberationEpochs` 統一投影 active/workflow/all-history views。runner prompt、retry、parallel synthesis、WebSocket live snapshot 與預設 transcript 只讀 active view；legacy marker 前 events read-time 視為第一輪，不回填。
- **案卷 SoT 與 grounding**：`case_files.json` 是版本化 evidence／case-note 的唯一內容 SoT；每個 revision 保存不複製 content 的 immutable manifest。meeting list 只能使用 lightweight summary。Civil final 的證物與金額 grounding 只信任 runner 內部、按角色過濾的 structured evidence envelope；該 envelope 不得進 prompt 或 events，缺失時含引用／金額的輸出必須 fail closed。
- **Courtroom case profile**：meeting-level `civil|criminal` 決定顯示角色、三段 workflow、prompt/schema 與結果呈現，internal role IDs 保持穩定。新 events 保存 case/role/phase snapshot；舊 event 無 snapshot 時維持原 catalog label，不可 retroactive relabel。
- **原子 meeting settings**：title、goal、case type、scene 與完整 participant models 走單一 revisioned settings transition；goal audit、case-type epoch marker 與 metadata publish 使用可恢復 pending protocol。legacy details/case-type/participant-models endpoints 必須委派同一 transition 並 bump `settings_revision`。
- **Meeting transition coordinator**：每個 meeting 的 metadata/event mutation 與 AI job reservation 必須先通過同一 per-meeting coordinator；model call 不長時間持 lock。running job 期間 details/assignment/message/delete/reopen 不得與 snapshot 競態；close/cancel 後須等 job 真正結束才能 reopen，避免 stale output 寫回。
- **Provider 與 adapter 分離**：Provider 是前端產品概念，舊 `models.yaml` 仍保存 adapter schema，不需 migration。新 config discovery 走 `POST /models/available-models` preview，既有 config 沿用 `GET /models/{id}/available-models`；兩路都只接受 credential 環境變數名稱。
- **Provider discovery / CLI preset**：OpenAI-compatible、Anthropic、Gemini 皆經同一 discovery route interface，adapter 內處理 headers、pagination、normalization 與 credential-safe errors。CLI exact argv 固定為 Claude `claude --model <id> -p {prompt}`、Codex `codex exec --model <id> {prompt}`、AGY `agy --model <id> -p {prompt}`；每個 preset 自有 builder/parser，未知 legacy command 走 Custom 且不 migration。
- **Model health ordering**：每次 check 先以 `ModelHealthCheckStore.begin(model_id)` 取得新 token；只有最新 token 可 `record`。前端 `refreshModels(shouldCommit)` 也必須以 request generation guard shared store commit，避免 late HTTP result 恢復舊狀態。
- **前端 active mode**：`useCouncil.ts` 的 `activeModeSource`（module ref）跟著 `selectedMeeting.mode_id` 走（watchEffect，catalog splice 會重解析）；場景 override 是 keyed watch（`meeting_id::defaultScene` 字串）——**不要 watch 整顆 meeting 物件**（串流事件會整物件替換）。catalog 來源 = `GET /modes`，`modes.ts` 本地常數只是後端不可達時的 fallback。
- **前端測試**：Provider/discovery pure modules 使用 Node 內建 test runner（`npm run test:unit`）；使用者流程使用 Playwright e2e（`frontend/tests/e2e/control-flow.spec.ts`）。

## 4. 開發環境

- 後端測試：`cd backend && .venv/bin/python -m pytest tests/ -q`（venv 在主 repo `backend/.venv`；worktree 沒有 venv——pytest `pythonpath=["."]` 會 import 執行目錄的程式碼，所以**在 worktree 的 backend 目錄下用主 repo 的 venv 跑**即測 worktree 的碼）。`backend/conftest.py` 會把 pytest／Python tempfile 固定在目前 checkout 的 `.scratch/pytest-runtime/`；明示的 workspace 外 `--basetemp` 會在 collection 前拒絕。這是 repository safety guard，不可移除或繞過。
- **已知 flake（backlog 76）**：已於 2026-07-13 將 `test_api.py` 的 `wait_for_activity` deadline 放寬到 5s；若全套仍有單一 activity timeout，先單獨重跑再判斷。
- e2e：`playwright.config.ts` 無 webServer，baseURL 吃 `E2E_BASE_URL`（預設 3009）。**主 repo 的 3009/5009 常被使用者的 dev server 佔用**——一律用空閒 port 自起：
  所有測試資料必須留在 workspace 內；不得使用 `mktemp -d`、`/tmp` 或其他 workspace 外路徑。每次以新的 repo-local 目錄執行，完成後只清理該目錄：
  ```bash
  DATA="$PWD/.scratch/e2e-runtime"
  mkdir -p "$DATA"
  cp config/models.yaml.example "$DATA/models.yaml"
  cd backend
  AI_COUNCIL_DATA_DIR="$DATA/data" AI_COUNCIL_MODEL_CONFIG_PATH="$DATA/models.yaml" \
    AI_COUNCIL_MODES_CONFIG_PATH="$PWD/../config/modes.yaml" AI_COUNCIL_PROMPT_DIR="$PWD/../prompts" \
    <主repo>/backend/.venv/bin/python -c 'import os; from pathlib import Path; import uvicorn; from ai_council.api import create_app; app=create_app(data_dir=Path(os.environ["AI_COUNCIL_DATA_DIR"]), model_config_path=Path(os.environ["AI_COUNCIL_MODEL_CONFIG_PATH"]), modes_config_path=Path(os.environ["AI_COUNCIL_MODES_CONFIG_PATH"]), prompt_dir=Path(os.environ["AI_COUNCIL_PROMPT_DIR"]), start_model_health_checks=False); uvicorn.run(app, host="127.0.0.1", port=8123)' &
  cd ../frontend
  VITE_API_BASE_URL=http://127.0.0.1:8123 npx vite --port 3123 &
  E2E_BASE_URL=http://127.0.0.1:3123 E2E_API_BASE_URL=http://127.0.0.1:8123 E2E_DATA_DIR="$DATA/data" \
    PLAYWRIGHT_BROWSERS_PATH=<主repo>/frontend/.cache/ms-playwright npx playwright test
  # 停止自起服務後，回到 repo root 清理：rm -rf .scratch/e2e-runtime
  ```
  `E2E_DATA_DIR` 是 Playwright fixture 明確使用的 backend data seam，必須與 backend 的 `AI_COUNCIL_DATA_DIR` 指向同一個 workspace-local `$DATA/data`。e2e 會寫入 models.yaml（模型管理測試），**絕不可指向 repo 的 config/**。跑完清理進程與暫存目錄。
- 環境變數：`AI_COUNCIL_DATA_DIR` / `AI_COUNCIL_MODEL_CONFIG_PATH` / `AI_COUNCIL_MODES_CONFIG_PATH` / `AI_COUNCIL_PROMPT_DIR`（見 `.env.example`）。

## 5. 工作規範（使用者的既定政策）

- **角色分工（2026-07-31 起，AIDLC bootstrap）**：先讀 `docs/agents/workflow-bindings.md` 依 §0 固定 revision 載入中央主規範與角色 prompt。三角色由 Human Owner 確認皆以 session runtime 模型（目前 `opencode/big-pickle`）擔任：Orchestrator 執行並可派遣 subagent 擔任 Executor（`.worktrees/<slice>` 實作）與獨立 Reviewer（唯讀、固定輸出）；Execution 與 review 必須不同 agent session。未指定角色時保持唯讀並詢問 Human Owner。完整規範見中央 workflow source 的 `docs/agents/multi-agent-development.md`。
- **OpenSpec（2026-07-20 起）**：新能力、跨模組架構、資料格式與 product-surface change 使用 OpenSpec proposal → specs → design → tasks；`spec.md` §15 仍是唯一 backlog SoR，既有 `.scratch/` 不搬移，小型 scoped fix 可繼續使用。OpenSpec apply-ready 不取代 Codex Gate A；Gate B ready 後才能 merge。Human Owner acceptance 後，在獨立 closeout worktree 完成 accepted/done → sync → archive → commit → Codex closeout review → exact-HEAD merge。CLI 一律透過 `scripts/openspec-local` 停用 telemetry 並限制 runtime 在 workspace。
- **一個 feature 一個 worktree**（前後端可共用），完成即 merge 回 main 並刪 worktree/branch。已由 Human Owner 核准的整批工作，可依 `docs/agents/multi-agent-development.md` 的規範自主、連續執行，不需逐項重新取得授權；只有 Human Owner 明確指定的純治理文件、拼字或不影響行為的 trivial 修改可直接 main。
- **TDD**：先寫 failing test、確認紅燈（且紅得有意義——參考兩份留檔計畫裡的紅燈驗證寫法）、再實作。
- 寫計畫：大 feature 先寫 `docs/plans/YYYY-MM-DD-<name>.md`（兩份現有計畫是格式範本），bite-sized tasks、完整程式碼、明確驗收線。
- 註解風格：解釋 why、不留實作史（不要寫「Task 5 加的」）；spec.md 與文件用繁體中文。
- 完成一項就在 `spec.md` §15 這份 canonical backlog 標記（已完成 YYYY-MM-DD）；HANDOFF 只同步當前狀態與已核准批次快照。
- Commit 訊息慣例照 git log；使用者信任「測試綠 + 真瀏覽器冒煙」為驗收，冒煙要真的開瀏覽器操作，不是只跑測試。

## 6. 交接時的未結事項

- Mode system slice A–D、§17、Backlog 75–78 均已完成並驗證。
- Evidence to Verdict 批次（backlog 80、63–65）已實作、雙軸 review 與完整驗收通過，等待 Human Owner acceptance。
- Backlog 81 已實作、雙軸 review 與完整驗收通過，等待 Human Owner acceptance。
- Backlog 82 已實作、雙軸 review 與完整驗收通過，等待 Human Owner acceptance。
- Backlog 83–84 已實作、雙軸 review 與完整驗收通過，等待 Human Owner acceptance。
- Backlog 85 已實作、雙軸 review、291 backend／12 unit／build／69 Chromium 與 direct browser smoke 通過，等待 Human Owner acceptance。
- Backlog 86 已實作、雙軸 review、305 backend／19 unit／build／71 Chromium 與 direct browser smoke 通過，等待 Human Owner acceptance。
- Backlog 87 已實作、雙軸 review、345 backend／35 unit／build／77 Chromium 與 direct browser smoke 通過，狀態為 `implemented / awaiting acceptance`。
- Backlog 88 acceptance 修補已實作並再次通過雙軸 review；Human Owner 於 2026-07-17 驗收通過，狀態為 `accepted / done`。
- Backlog 89 已實作、雙軸 review、597 backend／50 unit／build／90 Chromium、direct browser smoke 與 Human Owner 驗收通過，狀態為 `accepted / done`。
- Backlog 90 已實作、雙軸 review、605 backend／61 unit／build／94 Chromium 與 direct Chromium smoke 通過，Human Owner 於 2026-07-20 驗收通過，狀態為 `accepted / done`。
- Backlog 91 自由聊天室模式已實作、通過 650 backend／99 frontend unit／105 e2e 與 direct Chromium smoke；2026-07-23 Human Owner 驗收發現 9 項 UX 問題（見 backlog 92），視為原需求尚未完成，狀態為 `implemented / acceptance rejected — see #92`；2026-07-31 依 #92 驗收通過，狀態為 `accepted / done`。
- Backlog 92 聊天室工作區 UX 精修已實作，歷經 7 輪 Gate B review-fix 循環（詳見 spec.md §15 #92），最終通過 650 backend／116 frontend unit／118 e2e／build 全綠，已 fast-forward merge 至 main（`f7065a9`），並於 2026-07-31 完成 round-2 修正（`ebc49f2`）。Backlog 93（角色自訂）明確裁定不在本批次，記入 backlog。Backlog 94 記錄本批次 13 項 Gate B round 7 遺留 Minor（皆 non-blocker）。2026-07-31 Human Owner 驗收 #92 通過，狀態為 `accepted / done`；#91 與 #92 的 delta specs 已於同一次 closeout 一併 sync 至 `openspec/specs/` 並 archive（`openspec/changes/archive/2026-07-31-*`）；#91 不獨立 sync/archive。
- 使用者已裁定：個人版不做多人/帳號（backlog 有註記）；案卷 Phase 2/RAG 仍延後到 backlog 79。

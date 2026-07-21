# 交接文件（2026-07-18，Codex）

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

**目前驗收基線（任何改動後不得低於此）**：後端 `pytest` **650 passed**；frontend unit **99 passed**；前端 `npm run build` 綠；Chromium e2e **105/105 passed**。Backlog #90 已通過 Standards／Spec 雙軸獨立 review，並以 direct Chromium 實際完成建立會議 → 主席補充 → AI 回合 → 角色篩選 → 長文展開 → 案卷 drawer。Backlog #91（chatroom mode）已實作並包含在此基線中。

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

**Human Owner follow-up**：新角色立繪由使用者自行產圖，不屬於 agent 開發佇列或產品執行批次。

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

- **角色分工（2026-07-20 起）**：目前由 OpenCode 擔任 Implementer／Integrator，負責 artifacts、隔離 worktree、TDD、review 修正、完整 gates、merge 與清理；Codex 擔任 review-only Reviewer，執行 artifacts、implementation 與 acceptance closeout 三個獨立 checkpoint，不改檔、不補 patch、不 merge。`AGENTS.md` 只保存兩邊共用政策，不會自動指派角色；每個新 session 必須由 caller／Human Owner 明確套用 `docs/agent-prompts/` 內對應 prompt，未指定時保持唯讀並詢問。完整規範見 `docs/agents/multi-agent-development.md`。
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
- Backlog 91 自由聊天室模式已實作、通過 650 backend／99 frontend unit／105 e2e 與 direct Chromium smoke，狀態為 `implemented / awaiting acceptance`。
- 使用者已裁定：個人版不做多人/帳號（backlog 有註記）；案卷 Phase 2/RAG 仍延後到 backlog 79。

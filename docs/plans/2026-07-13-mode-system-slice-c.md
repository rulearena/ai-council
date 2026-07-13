# Mode System Slice C（parallel executor + brainstorm/six-hats/persona-testing）Implementation Plan

**Goal:** 實作 spec.md §16.3 的 `parallel` 執行器，讓 `brainstorm` 可建立與執行；`six-hats`、`persona-testing` 以設定與 prompt 補齊方式上線。保留 relay executor 的既有 step_id / retry / directed response 相容行為。

**Architecture:** `config/modes.yaml` 繼續作為模式 catalog。`ModeCatalogRepository` 驗證 parallel mode 必須有 `fanout` + `synthesis`；`parallel_plan(mode, participants)` 由 mode 的 fanout/synthesis 與 meeting metadata 的 participant instances 推導執行計畫。`MeetingRunner` 新增 parallel 公開方法，API 層依 `mode.category` dispatch 到 relay 或 parallel。parallel fanout 以 thread pool 併發同步 adapter calls，單一 member 失敗只記錄該 member failed event；全部成功後同一 run 觸發 synthesis。若任何 fanout failed，會議投影為 `waiting`，使用者 retry 該 `fanout-{round}-member-{k}` 後，若所有 fanout 都成功，才觸發 `synthesis-{round}`。

**Tech Stack:** FastAPI + pytest（backend）；Vue 3 + TypeScript + Playwright（frontend）。

**Worktree:** `.scratch/worktrees/mode-system-slice-c`（branch `mode-system-slice-c`）。

**Acceptance Baseline:**
- Backend: `cd backend && <main repo>/backend/.venv/bin/python -m pytest tests/ -q`，不得低於 **171 passed**，本 slice 預期會增加測試數。
- Frontend build: `cd frontend && npm run build`。
- E2E: 自起 backend/frontend 空閒 port，`PLAYWRIGHT_BROWSERS_PATH=<main repo>/frontend/.cache/ms-playwright npx playwright test`，不得低於 **27/27**，本 slice 預期增加 parallel 覆蓋。
- 真瀏覽器冒煙：用 Playwright 或實際 browser 操作建立 brainstorm、指派 mock 模型、開始、觀察 fanout/synthesis 完成。

## TDD Seams

- **Mode catalog seam:** `ModeCatalogRepository.list_modes()` / `parallel_plan()`；驗證 parallel 可用、設定完整、prompt 存在。
- **Runner seam:** `MeetingRunner.start_parallel()` / `retry_failed_parallel_step()` 透過 `MeetingRepository.read_events()` 觀察事件，不測私有方法。
- **API seam:** `POST /meetings`、`POST /meetings/{id}/start`、`POST /meetings/{id}/steps/{step_id}/retry`、`GET /meetings/{id}`；驗證建會、投影、執行、retry gating。
- **Frontend seam:** Playwright 從 New Case modal 建立 parallel 會議，透過 Settings 指派模型、Stage seats 與 Records/Transcript 觀察結果。

## Phase 1 — Backend Catalog and Prompts

### Task 1: Catalog red tests for parallel availability and validation

**Files:**
- Modify: `backend/tests/test_mode_catalog.py`

**Red tests:**
- `test_catalog_marks_parallel_modes_available_after_slice_c`：讀取 minimal parallel YAML，期待 `mode.available is True`。
- `test_parallel_plan_derives_fanout_and_synthesis_steps`：期待 member instances 對應 step_id `fanout-1-member-1` 等與 synthesis base step。
- `test_catalog_rejects_parallel_mode_without_fanout_or_synthesis`：parallel mode 缺任一設定要 fail。
- `test_repo_modes_yaml_parallel_prompts_exist`：repo 的三個 parallel mode 都有 fanout/synthesis，所有 template 檔存在。

**Expected red:** `available` 仍為 false、`parallel_plan` 尚不存在、`six-hats` 缺 fanout/synthesis、prompt 檔缺。

### Task 2: Implement catalog support

**Files:**
- Modify: `backend/ai_council/meetings/modes.py`
- Modify: `config/modes.yaml`
- Create: `prompts/brainstorm_member.md`
- Create: `prompts/brainstorm_synthesis.md`
- Create: `prompts/hat_white.md`
- Create: `prompts/hat_red.md`
- Create: `prompts/hat_black.md`
- Create: `prompts/hat_yellow.md`
- Create: `prompts/hat_green.md`
- Create: `prompts/hat_blue_synthesis.md`
- Create: `prompts/persona_member.md`
- Create: `prompts/persona_synthesis.md`

**Implementation:**
- `ModeDefinition.available` 改為 `True`。
- 新增 `ParallelMemberStep` / `ParallelPlan` dataclass。`parallel_plan(mode, participants)` 接受已投影的 participants list；從 `kind == member` 取扇出成員，`kind == synthesizer` 取 synthesis 角色。
- `config/modes.yaml` 補齊：
  - `six-hats`: fanout role/template 可用固定 member roles；synthesis role `HatBlue`、template `hat_blue_synthesis`。
  - `persona-testing`: 已有 fanout/synthesis，保留 instance_prompt。
- Prompt 結構沿用既有 prompt：包含 `{{ topic }}`、`{{ prior_transcript }}`、`{{ required_json_schema }}`；member prompt 加 `{{ instance_prompt }}`；synthesis prompt 加 `{{ fanout_outputs }}`。

**Green:** mode catalog 單檔測試通過。

## Phase 2 — Parallel Runner

### Task 3: Runner red tests for fanout/synthesis

**Files:**
- Modify: `backend/tests/test_meeting_runner.py`

**Red tests:**
- `test_parallel_runner_completes_fanout_then_synthesis`：三個 member event step_id 為 `fanout-1-member-1`...，最後 `synthesis-1`，synthesis prompt 含 member outputs。
- `test_parallel_runner_records_individual_failures_without_stopping_other_members`：一個 adapter failure 仍保留其他 completed，沒有 synthesis event。
- `test_retry_failed_parallel_member_runs_only_that_member_then_synthesizes`：retry failed fanout member 後只新增該 member attempt 2，接著 synthesis。
- `test_parallel_runner_starts_next_round_after_synthesis_complete`：第二次 start 產生 `fanout-2-member-1` / `synthesis-2`。

**Expected red:** `MeetingRunner` 沒有 parallel API。

### Task 4: Implement runner

**Files:**
- Modify: `backend/ai_council/meetings/runner.py`

**Implementation:**
- 新增 `ParallelPlan` / `ParallelMemberStep` dataclass（放 runner.py，modes.py import，避免 runner import modes.py）。
- 新增 `start_parallel(...)`：
  - round = completed synthesis base step count + 1。
  - 跳過已 completed fanout；同 round 有 failed fanout 時不自動重跑，等待 explicit retry。
  - 用 `ThreadPoolExecutor` fanout member steps，event step_id 固定 `fanout-{round}-member-{k}`。
  - 全部 fanout latest status completed 才跑 synthesis `synthesis-{round}`。
- 新增 `retry_failed_parallel_step(...)`：
  - 只接受 base/step id 是 fanout member failed event。
  - retry 該 member attempt + 1。
  - retry 後若同 round 全部 member completed，立即跑 synthesis。
- 抽出 `_run_step` 可重用現有 prompt/render/parse/event 寫入；`inputs` 合併 `instance_prompt` / `fanout_outputs`。
- 匿名化 hook 以 helper `build_synthesis_inputs(..., anonymize=False)` 預留，預設關閉。

**Green:** runner 單檔測試通過，relay runner 測試維持綠。

## Phase 3 — API and Projection

### Task 5: API red tests

**Files:**
- Modify: `backend/tests/test_api.py`

**Red tests:**
- `test_modes_endpoint_marks_parallel_modes_available`。
- `test_create_brainstorm_meeting_accepts_member_instances`：participants 可為 `Member-1` / `Member-2` / `Moderator`，投影出 member instances。
- `test_create_brainstorm_rejects_member_count_outside_fanout_range`。
- `test_start_brainstorm_meeting_runs_parallel_steps`。
- `test_parallel_failure_projects_waiting_and_retry_synthesizes`。

**Expected red:** create still rejects parallel、project_participants 不展開 instances、start uses `relay_plan()`。

### Task 6: Implement API dispatch and participant projection

**Files:**
- Modify: `backend/ai_council/api.py`
- Modify: `backend/tests/test_api.py` prompt fixture template list

**Implementation:**
- `POST /meetings` 對 relay 沿用 role_ids 驗證；對 parallel：
  - 若 request participants 空，為 fanout `min_instances` 產生 `Member-1..N` 加 synthesizer。
  - 驗證 fanout instance id pattern、min/max、duplicate、model_config_id 存在。
  - 固定 roster 模式（six-hats）使用 mode.roles 中 `kind: member` 的固定成員；prototype 模式（brainstorm/persona-testing）使用 request instances。
- `project_participants()` 對 parallel 優先回 metadata participants，補齊 name/color/kind/portrait；fanout prototype instance 顯示名用 request `display_name` 或 `委員 1`/`Persona 1`。
- `POST /start`、`POST /steps/{step_id}/retry` 依 mode.category dispatch：relay 用既有方法，parallel 用新方法。
- `project_activity_status()`：latest event failed 且同 round 還缺 synthesis 時 parallel 顯示 `waiting`；一般 relay failed 仍顯示 `failed`。
- directed role response / sequence 暫維持 relay-only，parallel 回 400（前端 parallel 不顯示 sequence presets）。

**Green:** API tests 通過。

## Phase 4 — Frontend Parallel Creation

### Task 7: Frontend e2e red test

**Files:**
- Modify: `frontend/tests/e2e/control-flow.spec.ts`

**Red test:**
- `user can create and run a brainstorm meeting`：
  - New Case 選 `brainstorm`。
  - participant setup 可調整 member count 至 3，填 member display/persona。
  - 建立後 stage 有 `member-1` / `member-2` / `member-3` / `moderator` seats。
  - Settings 能為四個角色選 mock 模型。
  - start 後 fanout/synthesis 完成，Records 含 `fanout-1-member-1` 與 `synthesis-1`。

**Expected red:** UI 還不渲染 parallel 成員控制，`createMeeting()` 不送 participants。

### Task 8: Implement NewCaseModal parallel participants

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/components/NewCaseModal.vue`
- Modify: `frontend/src/composables/useCouncil.ts`
- Modify as needed: `frontend/src/modes.ts`, `frontend/src/components/*`

**Implementation:**
- `createMeeting()` options 支援 `participants`。
- NewCaseModal 對 `mode.category === 'parallel' && mode.fanout` 顯示 member count 控制（min/max）、每位 instance display_name + instance_prompt（若允許）。
- 建立 payload 包含 `Member-1..N` 與 synthesis role；six-hats/persona-testing 用同一生成策略。
- `startSelectedMeeting()` 對 parallel pending queue 使用 active participants 的 member roles 加 synthesizer；`currentStepProgress` 對 parallel 顯示簡短 fanout/synthesis 進度，不影響執行。
- `sequencePresets` 對 parallel 回空；role drawer 的 directed response button 在 parallel 可先不顯示或沿現有 guard 讓 API 拒絕。

**Green:** `npm run build` 與新增 e2e 通過。

## Phase 5 — Verification, Docs, Merge

### Task 9: Full verification

- Backend full: `cd backend && <main repo>/backend/.venv/bin/python -m pytest tests/ -q`。
- Frontend build: `cd frontend && npm run build`。
- E2E full with isolated data dir and free ports.
- 真瀏覽器冒煙：建立 brainstorm、三 member、mock-slow、start、觀察 completed。

### Task 10: Docs and merge

**Files:**
- Modify: `spec.md`：標記 Slice C 完成（2026-07-13）。
- Optional modify: `docs/HANDOFF.md`：更新 queue 狀態與新驗收基線。

**Git:**
- Commit branch with conventional message.
- Merge `mode-system-slice-c` back to `main`.
- Delete `.scratch/worktrees/mode-system-slice-c` worktree and branch after merge.

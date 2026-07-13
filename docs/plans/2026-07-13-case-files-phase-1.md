# Case Files Phase 1 Implementation Plan

**Goal:** 實作 spec.md backlog 78：建立會議時可附多份純文字/Markdown 案卷，每份指定可見角色；執行 prompt 時以 `{{ case_files }}` 注入該角色可見案卷。Phase 1 不做 RAG、不建索引。

**Architecture:** 案卷內容存放在 meeting data dir：`data/meetings/{meeting_id}/case_files.json`。`metadata.json` 保留 `case_files` manifest（id/title/visible_roles/size），避免列表 API 帶出全文。`GET /meetings/{id}` 回傳全文，供前端重新開啟/檢視。API 建立會議時驗證大小上限與 role 可見性；runner 啟動/重試/定向回應前，依 role 將可見案卷格式化成 `inputs["case_files"]`，沿用現有 `PromptRenderer.render(inputs=...)`。所有 prompt 模板補 `{{ case_files }}` 區塊。

**Acceptance Baseline:**
- Backend: `cd backend && <main repo>/backend/.venv/bin/python -m pytest tests/ -q`，不得低於 183 passed。
- Frontend build: `cd frontend && npm run build`。
- E2E: 隔離 backend/frontend + `PLAYWRIGHT_BROWSERS_PATH=<main repo>/frontend/.cache/ms-playwright npx playwright test`，不得低於 30/30，預期新增案卷測試。

## TDD Seams

- **Repository seam:** `MeetingRepository.save_case_files/read_case_files`，觀察 meeting data dir 內 JSON，而不是手動拼 path。
- **API seam:** `POST /meetings` / `GET /meetings/{id}` / `POST /meetings/{id}/start`，驗證 validation、投影、prompt 注入。
- **Runner seam:** 透過 completed event 的 `prompt_messages[0].content` 觀察每個 role 只收到可見案卷。
- **Frontend seam:** Playwright 透過 New Case modal 新增案卷、指定可見角色、建立會議後執行，後端 prompt 內容由 API/e2e 行為驗證。

## Task 1 — Backend Storage and API Contract

1. Red tests:
   - `test_create_meeting_stores_and_returns_case_files`
   - `test_create_meeting_rejects_case_files_for_unknown_roles`
   - `test_create_meeting_rejects_oversized_case_files`
2. Implementation:
   - Add `CaseFileRequest` / projection schema in `api.py`.
   - Add repository methods for `case_files.json`.
   - Add size constants, ids, manifest projection.
3. Green targeted backend API tests.

## Task 2 — Role-Scoped Prompt Injection

1. Red tests:
   - relay mode: Prosecutor sees prosecution evidence; Defense does not.
   - Judge sees files visible to Judge.
   - parallel member instances receive only matching instance/global visible files.
2. Implementation:
   - `case_files_input_for_role(case_files, role_id)` helper.
   - API builds role-specific inputs for `start_runner_for_mode`, directed role response, sequence, retry.
   - Prompt templates include a short `Case files visible to you:` section with `{{ case_files }}`.
3. Green targeted API/runner tests.

## Task 3 — Frontend Creation Flow

1. Red e2e:
   - New Case adds one案卷, selects role visibility, creates meeting, and the created meeting retains案卷 data.
2. Implementation:
   - `frontend/src/api.ts` types and `createMeeting` payload.
   - `NewCaseModal.vue` case file editor: title/content/visible role checkboxes/add/remove.
   - Responsive CSS under existing participant setup section.
3. Green build + targeted e2e.

## Task 4 — Final Verification and Docs

1. Mark backlog 78 complete in `spec.md`.
2. Update `docs/HANDOFF.md` queue to Slice D.
3. Run backend full pytest, frontend build, full e2e.
4. Merge and clean worktree.

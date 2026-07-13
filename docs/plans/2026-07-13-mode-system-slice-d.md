# Mode System Slice D Implementation Plan

**Goal:** 實作 spec.md §16.3 / §16.7 的 parallel synthesis anonymization hook。平行模式可由 `modes.yaml` per-mode 啟用彙整輸入匿名化；開啟後，synthesis prompt 只看到「委員A/B/C...」代稱與輸出摘要，不看到原始 role id、display name，並做字串層自我指認過濾。預設關閉。

**Architecture:** 將匿名化設定放在 `synthesis.anonymize_inputs`，由 `ModeSynthesis` 讀取並在 `parallel_plan()` 帶到 `ParallelPlan`。`MeetingRunner` 在 synthesis input 組裝點使用 `build_synthesis_inputs()`，依 `plan.anonymize_synthesis_inputs` 決定使用原本 fanout output 格式或匿名化格式。匿名化僅影響 synthesis prompt，不修改 fanout events 或 transcript。

**Acceptance Baseline:**
- Backend: `cd backend && <main repo>/backend/.venv/bin/python -m pytest tests/ -q`，不得低於 **188 passed**。
- Frontend build: `cd frontend && npm run build`。
- E2E: 隔離 backend/frontend + `PLAYWRIGHT_BROWSERS_PATH=<main repo>/frontend/.cache/ms-playwright npx playwright test`，不得低於 **31 passed**。

## TDD Seams

- **Catalog seam:** `ModeCatalogRepository` 讀取 `synthesis.anonymize_inputs`，`parallel_plan()` 轉成 runner plan。
- **Runner seam:** `MeetingRunner.start_parallel()` 完成後，檢查 synthesis completed event 的 `prompt_messages[0].content`。
- **API seam:** `GET /modes` 回傳 `synthesis.anonymize_inputs`，repo `config/modes.yaml` 對平行模式啟用。

## Tasks

1. Add red tests:
   - catalog reads `synthesis.anonymize_inputs` and exposes it through `ParallelPlan`.
   - runner anonymizes synthesis `fanout_outputs` when plan flag is enabled.
   - `/modes` exposes the flag.
2. Implement catalog/model/API:
   - add `ModeSynthesis.anonymize_inputs: bool = False`.
   - add `ParallelPlan.anonymize_synthesis_inputs: bool = False`.
   - parse/serialize `synthesis.anonymize_inputs`.
   - enable for repo parallel modes in `config/modes.yaml`.
3. Implement runner hook:
   - `build_synthesis_inputs()` merges caller inputs and `fanout_outputs`.
   - `_fanout_outputs(..., anonymize=False)`.
   - anonymous labels are deterministic by member order: 委員A, 委員B, ...
   - strip common self-identification phrases such as `身為 ChatGPT` / `As ChatGPT`.
4. Verification and docs:
   - targeted backend tests, full backend, frontend build, full e2e.
   - mark spec Slice D complete and update `docs/HANDOFF.md`.

# #94③ red evidence

- Base: `ff11542`
- Temporary mutation: `frontend/src/components/ConversationWorkspace.vue` changed the Chairman ℹ button to call `selectRole('Chairman')` before emitting `role-click`.
- Public seam: Chromium E2E through rendered role-seat buttons and real keyboard activation (`Enter` for a general role, `Space` for Chairman).
- Command:
  `E2E_BASE_URL=http://127.0.0.1:3133 E2E_API_BASE_URL=http://127.0.0.1:8133 E2E_DATA_DIR=.scratch/e2e-runtime-94-03-red/data PLAYWRIGHT_BROWSERS_PATH=frontend/.cache/ms-playwright npx playwright test tests/e2e/control-flow.spec.ts -g 'keyboard info activation' --project=chromium`
- Result: **red**, 1 failed.
- Failure: after Chairman ℹ Space activation, the filtered general-role seat had `aria-pressed="false"` instead of the expected `"true"`.
- This mutation is only for TDD red evidence and must not remain in the final product diff.

## Green evidence

- Restored the original Chairman ℹ handler; no product source change remains.
- The same command passed: **1 passed** in Chromium.
- The regression now verifies both the existing general-role Enter path and the Chairman Space path, including the public `aria-pressed` filter state and role drawer visibility.

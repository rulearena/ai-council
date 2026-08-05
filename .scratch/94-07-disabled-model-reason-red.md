# #94⑦ Gate B correction red evidence

## Reviewed baseline

- Base: `02f3b96`
- Test: `frontend/tests/e2e/control-flow.spec.ts` — `running meeting explains why the model select is disabled`
- Seam: real public user flow — create a meeting with `Blue: mock-slow`, click the real start button, observe the real `/start` 202 response, verify the running state, then wait for natural completion.
- No `page.evaluate`, `__vueParentComponent`, private Vue state, direct DOM attribute mutation, or WebSocket timing mock is used.

## Command

```text
E2E_BASE_URL=http://localhost:3137 \
E2E_API_BASE_URL=http://127.0.0.1:8137 \
E2E_DATA_DIR=.scratch/94-07-disabled-model-reason/e2e-runtime/data \
PLAYWRIGHT_BROWSERS_PATH=frontend/.cache/ms-playwright \
npx playwright test tests/e2e/control-flow.spec.ts \
  -g 'running meeting explains why the model select is disabled' --project=chromium
```

## Result

The test reaches the running state through the real start flow. These assertions pass before the red assertion:

```text
POST /meetings/{meeting_id}/start -> 202
select -> disabled
title -> 會議執行中無法更換模型
aria-label -> 會議執行中無法更換模型
meeting -> naturally completed
select -> enabled
```

Red is reproduced at the idle accessibility contract:

```text
Expected: title="目前模型：Mock · mock-slow（點擊更換）"
Received: title is absent
```

The idle `aria-label` already has the normal model-selection wording; the missing idle `title` is the only failure.

# #94⑦ red evidence

## Reviewed baseline

- Base: `e38a06a6bde573fcee0fbe82c5a36f4011180c33`
- Test: `frontend/tests/e2e/control-flow.spec.ts` — `running meeting explains why the model select is disabled`
- Seam: public `seat-model-select-blue` DOM attributes; the test preserves and asserts the disabled state before checking the accessibility explanation.

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

Red is reproduced at the product contract assertion:

```text
Expected: title="會議執行中無法更換模型"
Received: title is absent
DOM: <select disabled ... data-testid="seat-model-select-blue">
```

The following assertion passed before the failure, proving the tested control is disabled:

```text
await expect(select).toBeDisabled()
```

## Scope note

The test holds the public select in its disabled state at the DOM seam because this worktree's isolated Playwright fixture did not reliably inject the running activity snapshot through the WebSocket route. It does not inspect Vue private state. The production fix must add the reason to the disabled select itself and apply the same contract to `ConversationWorkspace` and `CourtroomDocketPanel`.

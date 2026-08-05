# #94⑥ red evidence

- Base: `5f25b71`
- Test: `frontend/tests/e2e/control-flow.spec.ts -g 'In-rail model switch rolls back' --project=chromium`
- Environment: isolated backend `8146`, frontend `3146`, Chromium
- Result: failed as expected on the new public DOM contract

The rejected assignment route returned the backend detail `Assignment save failed`.
The rendered `[data-testid="assignment-update-error"]` contained the same English
detail, while the regression expected the user-facing Traditional Chinese message
`模型指派儲存失敗`. This demonstrates that the backend diagnostic is currently
exposed directly to users.

Failure excerpt:

```text
Expected substring: "模型指派儲存失敗"
Received string:    "Assignment save failed"
```

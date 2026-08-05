# #94④ red evidence

- Base: `e86a2fc` (#94⑤ merged)
- Test command: `E2E_BASE_URL=http://127.0.0.1:3135 E2E_API_BASE_URL=http://127.0.0.1:8135 E2E_DATA_DIR=.scratch/e2e-runtime-94-04/data PLAYWRIGHT_BROWSERS_PATH=frontend/.cache/ms-playwright frontend/node_modules/.bin/playwright test tests/e2e/control-flow.spec.ts -g 'empty model registry fallback warning' --project=chromium`
- Public seam: the rendered `assignment-fallback-warning` DOM text in both conversation and courtroom workspaces.
- Injected backend diagnostic: `no models are configured`.
- Expected behavior: clear Traditional Chinese warning and no raw English diagnostic.
- Actual base behavior: conversation warning rendered `藍軍：no models are configured`; the expected Chinese assertion failed.
- Result: red reproduced. The focused run was stopped after the first reproducible failure, so the courtroom case did not run in this interrupted invocation.

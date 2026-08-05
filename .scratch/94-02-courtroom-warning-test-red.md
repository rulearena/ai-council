# #94② mutation red evidence

- Base: `cbc21e1`
- Public test: `frontend/tests/e2e/control-flow.spec.ts` — `courtroom fallback warning keeps courtroom role names`
- Mutation: in `CourtroomDocketPanel.vue`, temporarily changed the courtroom warning role projection for `Defense` from the mode display name to `藍軍`.
- Product mutation was not committed and was restored before the green commit.
- Command:

  ```text
  E2E_BASE_URL=http://127.0.0.1:3142 E2E_API_BASE_URL=http://127.0.0.1:8142 E2E_DATA_DIR=.scratch/e2e-runtime-94-02-red/data PLAYWRIGHT_BROWSERS_PATH=frontend/.cache/ms-playwright npx playwright test frontend/tests/e2e/control-flow.spec.ts -g 'courtroom fallback warning keeps courtroom role names' --project=chromium
  ```

- Result: **red as intended**. The public DOM assertion expected `辯護律師：...` but observed `藍軍：...`; the test failed at the role-specific warning assertion.
- This demonstrates that a future courtroom-to-red/blue role-name regression is observable through the rendered warning, without private Vue state or direct DOM mutation in the test.

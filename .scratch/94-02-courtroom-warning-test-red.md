# #94② mutation red evidence

- Base: `cbc21e1`
- Public test: `frontend/tests/e2e/control-flow.spec.ts` — `courtroom fallback warning keeps courtroom role names`
- Mutation: in `CourtroomDocketPanel.vue`, temporarily changed the courtroom warning role projection for `Defense` to `藍軍` and `Prosecutor` to `紅軍` instead of using each courtroom role's display name.
- Product mutation was not committed and was restored before the green commit.
- Command:

  ```text
  E2E_BASE_URL=http://127.0.0.1:3142 E2E_API_BASE_URL=http://127.0.0.1:8142 E2E_DATA_DIR=.scratch/e2e-runtime-94-02-review-fix/data PLAYWRIGHT_BROWSERS_PATH=frontend/.cache/ms-playwright npx playwright test frontend/tests/e2e/control-flow.spec.ts -g 'courtroom fallback warning keeps courtroom role names' --project=chromium
  ```

- Result: **red as intended**. The same public DOM contained `紅軍：...` and `藍軍：...`; assertions for the independent courtroom display names `檢察官：...` and `辯護人：...` failed. Both roles were injected in one criminal courtroom meeting.
- This demonstrates that a future courtroom-to-red/blue role-name regression is observable for both courtroom roles through the rendered warning, without private Vue state or direct DOM mutation in the test.

## Green verification

- Restored the unmutated base product code; no product source file was changed for this scoped coverage fix.
- The same public test passed with the courtroom profile display names `辯護人` and `檢察官` (criminal case profile); both warnings exclude `Blue`/`Red` and raw `Defense`/`Prosecutor` ids. The prior implementation verification's fallback-warning regression set passed **4/4** in Chromium.

## Reviewer-fix verification

- The pure courtroom focused set (`courtroom fallback warning keeps courtroom role names` plus the existing courtroom empty-registry warning) passed **2/2** in Chromium after restoring the product code.

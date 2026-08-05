# #94⑨ TDD red evidence

- Base: `4811fc1`
- Red change: add `frontend/tests/unit/assignmentWarnings.test.ts` before the helper exists.
- Command: `node --experimental-strip-types --test tests/unit/assignmentWarnings.test.ts`
- Result: expected failure with `ERR_MODULE_NOT_FOUND` for `frontend/src/assignmentWarnings.ts`.
- Contract covered by the red test: warning filtering, Chinese localization, saved/default fallback labels, assigned/recovered fallback labels, unknown warning preservation, participant order, and role-id fallback.

## Mutation red evidence

- Temporary mutation: changed the `no models are configured` branch to return the raw warning.
- Command: `node --experimental-strip-types --test tests/unit/assignmentWarnings.test.ts`
- Result: **1 failed, 1 passed**; the expected Chinese warning differed from the raw English warning.
- The mutation was restored before the final green commit.

## Reviewer follow-up contract

- The existing `missing-model` case intentionally remains as an unknown model-id fallback and must render `已自動使用「missing-model」`.
- Added a separate no-fallback case: `No saved model assignment was found.` must render `顧問：未指派模型。`.

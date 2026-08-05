# #94⑨ TDD red evidence

- Base: `4811fc1`
- Red change: add `frontend/tests/unit/assignmentWarnings.test.ts` before the helper exists.
- Command: `node --experimental-strip-types --test tests/unit/assignmentWarnings.test.ts`
- Result: expected failure with `ERR_MODULE_NOT_FOUND` for `frontend/src/assignmentWarnings.ts`.
- Contract covered by the red test: warning filtering, Chinese localization, saved/default fallback labels, assigned/recovered fallback labels, unknown warning preservation, participant order, and role-id fallback.

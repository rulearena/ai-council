# #94⑤ red evidence

- Base: `24497f1`
- Test: `frontend/tests/e2e/control-flow.spec.ts -g 'narrow role rail keeps fallback' --project=chromium`
- Environment: local backend/frontend, Chromium, viewport `375x812` for the fallback warning path
- Result: failed as expected before the product fix
- Failure: `assignment-fallback-warning` was attached, but its bounding box ended at `x + width = 406.1875`, exceeding the viewport width `375`. The warning was therefore clipped by the horizontal role rail. The earlier visibility assertion also showed the same warning could be compressed to zero size at this breakpoint.
- Scope: public DOM geometry only; no private Vue state or implementation detail is asserted.

The same regression test includes the assignment-update-error path at `640px`; it will be re-run after the layout fix to verify both warning paths.

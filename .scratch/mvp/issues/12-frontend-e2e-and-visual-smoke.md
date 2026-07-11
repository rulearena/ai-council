# 12 - Frontend E2E And Visual Smoke

Status: resolved
Type: task

## What to build

Add a real browser E2E/DOM smoke test for the Vue control/debug UI before continuing broader second-version work.

## Blocked by

09 - Vue Control And Debug UI
11 - Human Chair Message Slice

## Acceptance Criteria

- [x] E2E test uses stable `data-testid` selectors.
- [x] E2E creates a meeting through the UI.
- [x] E2E selects `mock-fast` for Blue/Red/Judge.
- [x] E2E starts a mock run and verifies timeline/debug/transcript updates.
- [x] E2E sends a chair message and verifies timeline/debug/transcript updates.
- [x] Visual smoke screenshot is generated and inspected.

## Resolution Notes

- Added Playwright test runner and `npm run test:e2e`.
- Added `frontend/tests/e2e/control-flow.spec.ts`.
- Installed Chromium under `frontend/.cache/ms-playwright` to keep browser artifacts inside the project boundary.
- Generated and inspected `.scratch/e2e-visual-smoke.png`.
- Added root `.gitignore` for local build/test/runtime artifacts.

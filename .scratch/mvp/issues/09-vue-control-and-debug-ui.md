# 09 - Vue Control And Debug UI

Status: resolved
Type: task

## What to build

Create a Vue 3 control/debug UI for creating meetings, selecting models, starting/cancelling runs, viewing timeline/debug output, and previewing transcripts.

## Blocked by

07 - FastAPI Meeting And Model API
08 - WebSocket Event Feed

## Acceptance Criteria

- [x] Meeting list and create flow work.
- [x] Blue/Red/Judge model selectors work.
- [x] Timeline reflects step status.
- [x] Debug panel shows raw/parsed/error details.
- [x] Transcript preview and download are available.
- [x] Required `data-testid` contract is present.

## Test Strategy

Use TypeScript build as the first validation gate. Keep UI code API-driven and include stable `data-testid` attributes for future E2E tests.

## Resolution Notes

- Added a Vue 3 + Vite frontend under `frontend/`.
- Added the control/debug surface with meeting creation/listing, role model selectors, start/cancel controls, event timeline, raw debug panel, and transcript preview/download.
- Added the required stable `data-testid` attributes for future E2E tests.
- Added local CORS support in the FastAPI app for Vite dev origins.
- Verified with `npm run build` and backend API tests.

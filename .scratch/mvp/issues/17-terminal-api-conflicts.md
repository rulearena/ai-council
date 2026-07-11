# 17 - Terminal API Conflicts

Status: resolved
Type: task

## What to build

Return clear API conflicts when a closed/cancelled meeting receives event-creating requests.

## Blocked by

16 - Terminal State Enforcement

## Acceptance Criteria

- [x] `POST /meetings/{meeting_id}/start` returns `409` when terminal.
- [x] `POST /meetings/{meeting_id}/messages` returns `409` when terminal.
- [x] `POST /meetings/{meeting_id}/roles/{role}/respond` returns `409` when terminal.
- [x] `POST /meetings/{meeting_id}/steps/{step_id}/retry` returns `409` when terminal.
- [x] Rejected terminal calls do not append events.

## Resolution Notes

- Added API-level `reject_terminal_meeting()` guard.
- The guard reports `Meeting is terminal: closed` or `Meeting is terminal: cancelled`.
- Frontend E2E still passes because terminal controls are disabled before these calls are possible from the UI.

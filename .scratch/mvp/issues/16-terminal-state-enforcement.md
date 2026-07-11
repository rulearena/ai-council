# 16 - Terminal State Enforcement

Status: resolved
Type: task

## What to build

Make closed/cancelled meetings behave as terminal states across backend and frontend.

## Blocked by

15 - Chair Close Meeting

## Acceptance Criteria

- [x] Closing/cancelling a meeting is idempotent.
- [x] Closed meetings cannot append future full-round AI events.
- [x] Closed meetings cannot append future directed role response events.
- [x] Frontend disables start/cancel/close once a meeting is terminal.
- [x] Frontend disables chair message input and role response buttons once terminal.
- [x] E2E verifies terminal controls are disabled after closure.

## Resolution Notes

- `MeetingRunner.cancel()` and `MeetingRunner.close()` now no-op when the meeting is already terminal.
- Frontend infers terminal state from `closed` / `cancelled` events.
- `canRun` now excludes terminal meetings.
- E2E verifies closure appears in transcript and disables all event-creating controls.

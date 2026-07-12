# 40 - Interrupted Execution Recovery State

Status: resolved
Type: task

## What to build

Persist the currently running model step so backend startup can detect interrupted executions and hand them back to manual retry.

## Blocked by

06 - MeetingRunner Red/Blue/Judge Flow; 25 - Meeting Activity Projection; 30 - Background Meeting Progress

## Acceptance Criteria

- [x] Runner writes `execution.json` before calling a model adapter.
- [x] Runner clears `execution.json` after normal completion or handled failure.
- [x] Backend startup scans leftover execution state.
- [x] Leftover execution state appends a failed event for the interrupted step.
- [x] Recovered failures project meeting `activity_status: failed`.
- [x] Recovery does not automatically resend model requests.

## Resolution Notes

- Added a per-meeting execution state file for the active model call.
- Startup recovery converts stale active state into a failed event so the existing retry flow can handle it.
- The implementation intentionally does not retry or resend model calls automatically.

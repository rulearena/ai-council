# 15 - Chair Close Meeting

Status: resolved
Type: task

## What to build

Allow the chair to close a meeting and prevent future AI steps from being appended after closure.

## Blocked by

11 - Human Chair Message Slice
14 - Chair Directed Role Response

## Acceptance Criteria

- [x] API can close a meeting.
- [x] Closing writes a System `closed` event.
- [x] Transcript projection shows the closed status.
- [x] Runner does not start full rounds after closure.
- [x] Runner does not run directed role responses after closure.
- [x] Frontend exposes a close meeting button.
- [x] E2E verifies closed status appears in timeline/transcript.

## Resolution Notes

- Added `MeetingRunner.close()`.
- Added `POST /meetings/{meeting_id}/close`.
- Added `closeMeeting()` frontend API helper and `close-meeting-button`.
- Treats both `cancelled` and `closed` as terminal states for future AI execution.
- Extended Playwright E2E to close the meeting at the end of the flow.

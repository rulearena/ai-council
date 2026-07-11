# 13 - Follow-Up Round Event Naming

Status: resolved
Type: task

## What to build

Make follow-up discussion rounds distinguishable after the chair adds feedback and continues the meeting.

## Blocked by

11 - Human Chair Message Slice
12 - Frontend E2E And Visual Smoke

## Acceptance Criteria

- [x] First AI round keeps existing MVP step ids.
- [x] Second and later AI rounds use `round-N-*` step ids.
- [x] Events record `round` and `base_step_id`.
- [x] Event ids are unique across rounds.
- [x] Follow-up prompts include the human chair feedback in prior transcript.
- [x] E2E verifies `round-2-*` steps appear in the UI after continuing.

## Resolution Notes

- Updated `MeetingRunner.start()` to compute the next round from completed judge events.
- Preserved first-round step ids for backward compatibility.
- Added `round` and `base_step_id` fields to AI events.
- Updated generated event ids to include the actual round-aware step id.
- Extended Playwright E2E to click continue after chair feedback and verify round 2 appears.

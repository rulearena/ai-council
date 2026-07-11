# 11 - Human Chair Message Slice

Status: resolved
Type: task

## What to build

Allow the user to add chairperson feedback inside an existing meeting, not only define the initial topic.

## Blocked by

09 - Vue Control And Debug UI

## Acceptance Criteria

- [x] API can append a human chair message to a meeting.
- [x] Human chair messages are persisted as JSONL events.
- [x] Transcript projection renders human chair messages as plain meeting turns.
- [x] Future AI prompts include human chair messages through `prior_transcript`.
- [x] Frontend exposes a chair message input and submit action.
- [x] Stable `data-testid` contract exists for the new controls.

## Resolution Notes

- Added `POST /meetings/{meeting_id}/messages`.
- Added `Human` / `human-message` events with `content`.
- Updated `TranscriptProjector` to render human messages directly.
- Added Vue controls with `chair-message-input` and `send-chair-message-button`.
- Verified with targeted red/green tests, full backend/local-executor test run, and frontend build.

# 06 - MeetingRunner Red/Blue/Judge Flow

Status: resolved
Type: task

## What to build

Create the core meeting runner that executes the fixed Blue propose -> Red critique -> Blue revise -> Judge decide flow using event log persistence.

## Blocked by

02 - Transcript Projection
05 - ModelAdapter Contract With Mock And OpenAI-Compatible HTTP

## Acceptance Criteria

- [x] Runner creates ordered step events.
- [x] Successful mock run completes all four steps.
- [x] Parse/adapter failure marks the step failed.
- [x] Failed step retry creates a new attempt and can continue the meeting.
- [x] Cancel stops unstarted steps and records cancellation.

## Test Strategy

Use TDD at the `MeetingRunner` public interface seam with fake adapters and repository temp dirs. Keep FastAPI/WebSocket out of this ticket.

## Answer

Implemented synchronous `MeetingRunner` for the fixed Blue propose -> Red critique -> Blue revise -> Judge decide flow.

Independent review note: an advisory reviewer suggested an automatic retry loop, but this was not adopted because MVP retry is explicitly user/manual retry of failed steps. Added tests for parse failure and invalid/non-failed retry boundaries instead.

Validation:

```bash
cd backend && /Users/chrischiu/.pyenv/versions/3.11.9/bin/python -m pytest tests/test_meeting_runner.py
```

Result: 7 passed.

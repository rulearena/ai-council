# 01 - Backend MeetingRepository Canary

Status: ready-for-agent
Type: task

## Goal

Create the backend skeleton and implement `MeetingRepository` append/read behavior using TDD.

## Scope

Allowed scope:

- Backend project skeleton only
- `MeetingRepository`
- Event append/read for JSONL files
- Minimal pytest setup needed for this repository behavior
- Minimal package/config files required to run the backend tests

Do not implement:

- FastAPI routes
- WebSocket
- frontend
- model adapters
- prompt rendering
- transcript projection
- retry/cancel runner logic
- Docker

## Product Context

Read `spec.md`, especially:

- Section 4: Architecture
- Section 9: Data Model And Persistence
- Section 13: Testing Strategy

The event log is the source of truth:

```text
data/
  meetings/
    <meeting_id>/
      events.jsonl
      transcript.md
      metadata.json
```

`MeetingRepository` should support appending events and reading them back in order.

## Expected Behavior

Implement enough behavior to support:

- Create meeting storage directory when appending the first event.
- Append a JSON object event to `data/meetings/<meeting_id>/events.jsonl`.
- Read all events for a meeting in append order.
- Return an empty list for a meeting with no event log.
- Preserve event fields exactly enough for round-trip tests.

## TDD Requirement

Write failing pytest tests first, then implement the minimal code to pass.

Required tests:

- append creates the meeting directory and `events.jsonl`
- appended events can be read back in order
- reading a missing event log returns an empty list
- appending multiple events preserves event order

## Suggested Shape

Use simple Python types for the canary. Avoid premature abstractions.

Possible structure:

```text
backend/
  ai_council/
    __init__.py
    meetings/
      __init__.py
      repository.py
  tests/
    test_meeting_repository.py
```

The exact structure may differ if the executor chooses a cleaner minimal backend layout, but scope must stay narrow.

## Validation Command

The executor must report the exact command used and the exact output.

Suggested:

```bash
cd backend
pytest
```

## Executor Rules

- Do not commit.
- Do not push.
- Do not modify files outside the assigned worktree/sandbox.
- Do not read files outside this repository.
- Do not expand scope beyond this ticket.
- If a dependency is needed, keep it minimal and justify it.

## Completion Report

Report:

- Files changed
- Test command and exact output
- Any deviations from this ticket
- Any unresolved issues

# 01 - Backend Skeleton And MeetingRepository

Status: resolved
Type: task

## What to build

Create a testable backend package with a file-backed `MeetingRepository` that appends and replays JSONL meeting events. This is the first source-of-truth persistence slice for the MVP.

## Blocked by

None - can start immediately.

## Acceptance Criteria

- [x] Backend package and pytest setup exist.
- [x] `MeetingRepository` appends events under `data/meetings/<meeting_id>/events.jsonl`.
- [x] Reading missing meeting events returns an empty list.
- [x] Appended events round-trip in order.
- [x] Data directory can be injected for tests/local runs.
- [x] Related tests pass.

## Test Strategy

Use TDD at the `MeetingRepository` public interface seam. Write pytest tests first for append/read/missing-log/order behavior, then implement the minimal repository.

## Answer

Implemented backend pytest setup and `MeetingRepository` with append/read JSONL event behavior.

Validation:

```bash
cd backend && /Users/chrischiu/.pyenv/versions/3.11.9/bin/python -m pytest tests/test_meeting_repository.py
```

Result: 4 passed.

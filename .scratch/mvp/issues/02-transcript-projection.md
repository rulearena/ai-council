# 02 - Transcript Projection

Status: resolved
Type: task

## What to build

Create a `TranscriptProjector` that turns meeting events into a deterministic Markdown transcript. JSONL events remain the source of truth; Markdown is only a read model.

## Blocked by

01 - Backend Skeleton And MeetingRepository

## Acceptance Criteria

- [x] Transcript output is derived from events.
- [x] Blue/Red/Judge completed outputs render clearly.
- [x] Failed/cancelled steps render as status entries.
- [x] Projection is deterministic and covered by tests.

## Test Strategy

Use TDD at the `TranscriptProjector` public interface seam. Tests should pass event dictionaries and assert exact Markdown for completed, failed, and cancelled steps.

## Answer

Implemented `TranscriptProjector` for deterministic Markdown rendering from event dictionaries.

Validation:

```bash
cd backend && /Users/chrischiu/.pyenv/versions/3.11.9/bin/python -m pytest tests/test_transcript_projector.py
```

Result: 3 passed.

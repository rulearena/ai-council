# 19 - Round Scoped Retry

Status: resolved
Type: task

## What to build

Allow failed steps from later rounds, such as `round-2-red-critique`, to be retried correctly.

## Blocked by

13 - Follow-Up Round Event Naming

## Acceptance Criteria

- [x] Retry accepts a round-scoped failed `step_id`.
- [x] Retry uses `base_step_id` to map back to the fixed step sequence.
- [x] Retry keeps the failed event's round number.
- [x] Retry emits round-scoped completed step ids after success.
- [x] Retry continues from the failed step through the rest of that round.

## Resolution Notes

- `MeetingRunner.retry_failed_step()` now resolves the step sequence position from `base_step_id` when available.
- Added coverage for retrying `round-2-red-critique`.

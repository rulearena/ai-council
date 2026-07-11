# Local Executor Canary Scorecard

Use this scorecard to compare `qwen27` and `ornith` on the same ticket.

Ticket: `issues/01-backend-meeting-repository.md`

## Executor Metadata

| Field | qwen27 | ornith |
| --- | --- | --- |
| Harness | `scripts/local_executor.py` | `scripts/local_executor.py` |
| Worktree / sandbox path | `.scratch/local-executor-canary/sandboxes/qwen27` | `.scratch/local-executor-canary/sandboxes/ornith` |
| Start time | 2026-07-10 | 2026-07-10 |
| End time | 2026-07-10 | 2026-07-10 |
| Final status | Passed with JSON file protocol on second attempt | Passed with JSON file protocol on second attempt |

## Scores

Score each category from 0 to 5.

| Category | qwen27 | ornith | Notes |
| --- | ---: | ---: | --- |
| Spec alignment | 4 | 4 | Both targeted repository/tests and passed with JSON protocol |
| TDD discipline | 3 | 3 | Both produced tests and implementation together; harness cannot prove true red-first timing |
| Test quality | 3 | 4 | Ornith tests are slightly cleaner and assert full list equality |
| Test result credibility | 4 | 4 | Both passed actual harness-run pytest on second JSON attempt |
| Change quality | 3 | 4 | Ornith file output is cleaner; qwen has unused imports and less polished tests |
| Scope discipline | 4 | 4 | Both stayed near assigned backend scope |
| Error handling | 3 | 3 | Both implemented missing-log behavior and basic JSONL read skipping blanks |
| Maintainability | 3 | 4 | Ornith code is a bit simpler and more idiomatic |
| Documentation/backlog sync | 1 | 1 | No meaningful sync expected for this canary |
| Autonomy | 4 | 4 | Both corrected after first failure and passed on attempt 2 |

## Review Notes

### qwen27

- Unified diff protocol was unstable: first run produced partial files/import failure, second patch was malformed.
- Thinking-plan + JSON file protocol succeeded on the second attempt.
- Attempt 1 JSON output omitted `import os` in tests, causing actual pytest failure.
- Attempt 2 used test failure feedback, fixed the test file, and passed `cd backend && pytest` with 4 tests.
- Self-reported validation is still not trusted; harness-run pytest output is the source of truth.
- Current best mode: qwen27 as patch/file executor using `--planning --protocol json-files`.

### ornith

- Unified diff protocol failed in the earlier run.
- Thinking-plan + JSON file protocol succeeded on the second attempt.
- Attempt 1 JSON output was machine-readable but wrapped in a markdown fence; the harness extracted JSON and applied it, then pytest failure feedback triggered attempt 2.
- Attempt 2 passed `cd backend && pytest` with 4 tests.
- Output quality was slightly cleaner than qwen27 for this canary.

## Decision

Preferred result:

```text
Both qwen27 and ornith are viable local executor candidates when using JSON file protocol. Ornith slightly wins this canary on code/test cleanliness; qwen27 remains viable and may benefit more from thinking on harder reasoning tasks.
```

Reason:

```text
Both models produced scoped repository/test changes and successfully reacted to real pytest feedback when the harness used JSON file protocol. Unified diff was the wrong protocol for both.
```

Follow-up actions:

- Prefer `--protocol json-files` over unified diff for local models.
- Keep `--planning` optional; it improves planning quality but increases latency.
- Use a larger second canary to compare qwen27 and ornith beyond simple file I/O.
- Do not adopt either sandbox result into the main workspace.

## Agent skills

### Issue tracker

Issues and PRDs are tracked as local markdown files under `.scratch/`; external PRs are not a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels

The repo uses the default mattpocock/skills triage label vocabulary. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repo: use root `CONTEXT.md` and `docs/adr/` when present. See `docs/agents/domain.md`.

### Handoff

Continuing development? Read `docs/HANDOFF.md` first — current state, task queue with priorities, architecture invariants, dev-environment recipes, and the user's working policies.

### Development workflow

Before planning or implementing product work, read `docs/agents/multi-agent-development.md`. It defines the Human Owner, Orchestrator, Executor, and Reviewer responsibilities; grilling and approval gates; worktree isolation; TDD and independent review requirements; autonomous batch execution; acceptance states; and completion rules.

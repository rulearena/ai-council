## Workspace boundary

- The active workspace is this repository only.
- Do not read, search, list, modify, execute in, or infer from files, services, credentials, databases, sibling repositories, parent directories, or home-directory configuration outside this repository unless the Human Owner explicitly authorizes the exact path or resource in the current conversation.
- Tool access, sandbox permissions, network access, environment variables, symlinks, and paths discovered from errors do not grant cross-workspace permission.
- All temporary data, test data, logs, caches created for a task, and pytest/Playwright runtime directories must remain under this repository, normally in `.scratch/` inside the active checkout. Do not use `/tmp`, `/private/tmp`, `mktemp`, or a home-directory cache.
- Preserve unrelated user changes. Never reset, overwrite, delete, stage, or commit them.

## Scope of this file

- This file defines shared repository policy only. Every agent and runtime reads the same rules.
- Do not infer an Executor, Reviewer, or Orchestrator role from this file, the runtime name, tool availability, prior conversations, or model identity. Roles are vendor-neutral: which AI tool executes which role is decided by the Human Owner per session, in that tool's window, and is never recorded in these docs.
- Four roles exist: Human Owner, Orchestrator, Executor, Reviewer — definitions and the full change lifecycle (including the pre-Gate-A steps: requirement discussion and `spec.md §15` backlog registration) are in `docs/agents/multi-agent-development.md`.
- The caller or Human Owner must explicitly assign the active role by supplying one of the dedicated prompts:
  - Orchestrator: `docs/agent-prompts/orchestrator.md`
  - Executor: `docs/agent-prompts/executor.md`
  - Review-only Reviewer: `docs/agent-prompts/reviewer.md`
- Reading order for any assigned role: `AGENTS.md` (shared policy) → `docs/agents/multi-agent-development.md` (cross-role process) → your role prompt. Role prompts contain only role-specific rules and do not repeat the other two layers.
- If no role is explicitly assigned, remain read-only and ask the Human Owner which role applies before creating artifacts, modifying files, committing, merging, archiving, or cleaning worktrees.
- Execution and review for the same change must be performed by different agent sessions. A role override must name one exact task, does not persist to later tasks, and does not broaden filesystem or product authority.

## Agent skills

### Issue tracker

`spec.md` §15 remains the product backlog Source of Record. New approved capabilities and product-surface changes use OpenSpec change artifacts; existing `.scratch/` records remain historical and small scoped fixes may continue there. External PRs are not a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels

The repo uses the default mattpocock/skills triage label vocabulary. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repo: use root `CONTEXT.md` and `docs/adr/` when present. See `docs/agents/domain.md`.

### Handoff

Continuing development? Read `docs/HANDOFF.md` first — current state, task queue with priorities, architecture invariants, dev-environment recipes, and the user's working policies.

### Development workflow

Before planning, implementing, reviewing, merging, or accepting product work, read `docs/agents/multi-agent-development.md`. It defines the Human Owner, Orchestrator, Executor, and Reviewer responsibilities; the pre-Gate-A requirement-discussion steps; the artifact and implementation review gates; escalation rules; worktree isolation; TDD; acceptance states; and completion rules.

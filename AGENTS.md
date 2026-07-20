## Workspace boundary

- The active workspace is this repository only.
- Do not read, search, list, modify, execute in, or infer from files, services, credentials, databases, sibling repositories, parent directories, or home-directory configuration outside this repository unless the Human Owner explicitly authorizes the exact path or resource in the current conversation.
- Tool access, sandbox permissions, network access, environment variables, symlinks, and paths discovered from errors do not grant cross-workspace permission.
- All temporary data, test data, logs, caches created for a task, and pytest/Playwright runtime directories must remain under this repository, normally in `.scratch/` inside the active checkout. Do not use `/tmp`, `/private/tmp`, `mktemp`, or a home-directory cache.
- Preserve unrelated user changes. Never reset, overwrite, delete, stage, or commit them.

## Agent roles

The default development workflow separates implementation from review:

- **Human Owner** owns product decisions, approval, and final acceptance.
- **OpenCode** is the default Implementer and Integrator. It prepares execution artifacts, develops in an isolated worktree with TDD, fixes review findings, runs gates, merges approved work, and cleans up.
- **Codex** is the default review-only Reviewer. It reviews plans and implementation, independently verifies evidence, and never edits code, writes artifacts, merges, archives, or cleans worktrees.

Role identity is determined by the active runtime, not by a role claimed inside a task prompt. Read the matching prompt before acting:

- OpenCode: `docs/agent-prompts/opencode-implementer.md`
- Codex: `docs/agent-prompts/codex-reviewer.md`

The Human Owner may explicitly override a role for one exact task. An override does not persist to later tasks and does not silently authorize broader filesystem or product changes.

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

Before planning, implementing, reviewing, merging, or accepting product work, read `docs/agents/multi-agent-development.md`. It defines the Human Owner, OpenCode Implementer/Integrator, and Codex Reviewer responsibilities; the artifact and implementation review gates; worktree isolation; TDD; acceptance states; and completion rules.

## Workspace boundary

- The active workspace is this repository only.
- Do not read, search, list, modify, execute in, or infer from files, services, credentials, databases, sibling repositories, parent directories, or home-directory configuration outside this repository unless the Human Owner explicitly authorizes the exact path or resource in the current conversation.
- Tool access, sandbox permissions, network access, environment variables, symlinks, and paths discovered from errors do not grant cross-workspace permission.
- All temporary data, test data, logs, caches created for a task, and pytest/Playwright runtime directories must remain under this repository, normally in `.scratch/` inside the active checkout. Do not use `/tmp`, `/private/tmp`, `mktemp`, or a home-directory cache.
- Preserve unrelated user changes. Never reset, overwrite, delete, stage, or commit them.

## Scope of this file

- This file defines shared repository policy only. Every agent and runtime reads the same rules.
- Do not infer an Executor, Reviewer, or Orchestrator role from this file, the runtime name, tool availability, prior conversations, or model identity. Roles are vendor-neutral: which AI tool executes which role is decided by the Human Owner per session, in that tool's window, and is never recorded in these docs.
- AIDLC bootstrap：先讀本專案綁定檔（`docs/agents/workflow-bindings.md`）。消費已固定 packet 的普通角色只讀 Q、中央 runtime kernel、matching role prompt、current packet、packet 指定的專案文件及已觸發模組，不另讀 router；Human-facing Orchestrator 建立或刷新 packet 時才額外讀固定 revision 的 router。來源、角色、issuer、packet 或 controller 無法唯一解析時維持唯讀並詢問 Human Owner。
- Four roles exist: Human Owner, Orchestrator, Executor, Reviewer — project-specific tools, worktrees, tests, data safety, and backlog rules are in `docs/agents/project-development.md`; role and gate mechanics come from the packet-fixed central runtime.
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

Read `docs/agents/project-development.md` only when the current packet triggers plan, execute, review, or closeout. It defines AI Council-specific OpenSpec, worktree, TDD, test, data-safety, and archive rules; central role and review mechanics remain at the Q-fixed workflow source.

# AI Council project development rules

This file preserves AI Council-specific development rules. Role boundaries, packet loading,
Gate A/Gate B convergence, recovery, and Human acceptance come only from the central
`modular-v1` runtime fixed by `docs/agents/workflow-bindings.md`; this file does not duplicate
those protocols.

## Product records and planning

- `spec.md` §15 is the product backlog Source of Record; backlog numbers are never reused.
- New capabilities, cross-module changes, data formats, and user-flow changes use
  `scripts/openspec-local` and `openspec/changes/{change}/`. Small scoped fixes may use a
  packet-authorized `.scratch/` work item.
- OpenSpec commands must go through `scripts/openspec-local`; never call bare `openspec` or
  use `--force`. OpenSpec artifacts and `.scratch/` are not independent requirement sources.
- Requirement exploration may use the project-approved grilling flow, but only unresolved
  product choices go back to the Human Owner. Repository facts are investigated directly.

## Implementation workspace and testing

- Implementation uses `.worktrees/{slice}`. Default to one slice per worktree and serial tasks;
  parallel tasks require independent scope, files, branches, and worktrees.
- Use TDD through a public seam: confirm a causally correct red test, implement the minimum
  green change, then refactor. Keep commits single-purpose and report commands plus results.
- Run targeted tests and the relevant lint, type check, build, browser, and e2e checks. Slice
  completion uses `scripts/test_all.sh`, backend pytest, frontend `npm run test:unit`,
  `npm run build`, and applicable e2e/browser checks.
- Compare failures with the main baseline from task start. A pre-existing flake is non-blocking
  only when the same environment reproduces it on main, targeted checks pass, and no new
  failure is introduced; otherwise stop.

## Git workflow — automatic branch and Draft PR

This section is the normative procedure behind the `AGENTS.md` Git workflow
summary. It applies to all coding agents (Pi, OpenCode, and others) on feature,
bug fix, refactor, test, or docs tasks, without needing a per-task "please create
a branch" reminder. The external-human fork flow in `CONTRIBUTING.md` is unchanged.

1. On task start, inspect the tree with `git status --short --branch`. This check
   comes before any file modification.
2. If the session is on `main` with a clean tree, run `git fetch origin main` and
   automatically create the task branch from latest `origin/main`. Do not wait for
   the user to ask for a branch.
3. Name the task branch `feat/<name>`, `fix/<name>`, `refactor/<name>`,
   `test/<name>`, or `docs/<name>`. When an AIDLC packet fixes exactly one branch,
   the packet-fixed branch wins and no second branch is created for the same task.
4. Reopening a session for the same task reuses the existing task branch. Verify
   with `git status --short --branch` and `git branch --show-current` instead of
   creating a duplicate branch.
5. If the tree holds unrelated uncommitted changes, stop and report the status.
   Never `reset`, `clean`, `checkout` over, stage, commit, or delete unrelated
   changes to make the tree look clean.
6. Never modify, commit, push, or merge directly on `main`. All changes stay on the
   task branch (packet-authorized `.worktrees/{slice}` work follows the same rule).
7. After the change, run the appropriate tests, commit on the task branch, push the
   branch to `origin`, and open a GitHub Draft PR against `main`. The PR body
   records what changed, test results, and known limitations. Required checks are
   `backend-tests`, `frontend-unit`, and `frontend-build`; force push, direct main
   mutation, deployment, release, tag, publication, and SIEM operations still
   require separate authority.
8. The Draft PR goes to the Mac ai-council AI review; only the Human Owner decides
   whether to merge.
9. On GitHub authentication failure, stop and report the failure clearly. Never
   write tokens, SSH private keys, or other credentials into the repository.

## Safety and closeout

- Never backfill, rewrite, or migrate historical events, meeting metadata, existing data, or
  user settings unless the approved contract explicitly authorizes it.
- Preserve unrelated and uncommitted changes. Adjacent problems go to the backlog unless they
  block the approved work, create a security issue, or break compatibility.
- GitHub delivery targets `rulearena/ai-council` main through a PR. Required checks are
  `backend-tests`, `frontend-unit`, and `frontend-build`; force push, direct main mutation,
  deployment, release, tag, publication, and SIEM operations require separate authority.
- OpenSpec sync/archive happens only after Human acceptance. Warning override is forbidden.
  Final closeout updates the backlog and handoff, performs the approved archive flow, and only
  then cleans the authorized worktree/branch.

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

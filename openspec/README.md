# AI Council OpenSpec policy

OpenSpec stores execution contracts for newly approved capabilities and product-surface changes. It does not replace the product backlog.

- Canonical backlog Source of Record: `spec.md` §15
- Active changes: `openspec/changes/<change-name>/`
- Accepted capability contracts: `openspec/specs/<capability>/spec.md`
- Historical accepted changes: `openspec/changes/archive/`
- CLI wrapper: `scripts/openspec-local`

Lifecycle:

1. Human Owner approves scope in `spec.md` §15.
2. OpenCode creates proposal, delta specs, design, and tasks.
3. Codex Gate A must return `ready` before apply.
4. OpenCode implements in an isolated worktree with TDD.
5. Codex Gate B must return `ready` before merge.
6. Human Owner accepts the merged behavior.
7. OpenCode creates a dedicated latest-main acceptance-closeout worktree and commits accepted/done, main-spec sync, and archive together.
8. A different Codex session reviews the fixed closeout diff; only `ready` permits an exact-HEAD fast-forward merge and cleanup.

Existing `.scratch/` artifacts remain historical and are not migrated.

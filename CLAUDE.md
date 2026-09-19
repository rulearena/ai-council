## Agent workflow

AIDLC bootstrap：先讀本專案綁定檔（`docs/agents/workflow-bindings.md`）。消費已固定 packet 的普通角色只讀 Q、中央 runtime kernel、matching role prompt、current packet、packet 指定的專案文件及已觸發模組，不另讀 router；Human-facing Orchestrator 建立或刷新 packet 時才額外讀固定 revision 的 router。來源、角色、issuer、packet 或 controller 無法唯一解析時維持唯讀並詢問 Human Owner。

## Agent skills

### Issue tracker

Issues and PRDs are tracked in `spec.md` §15 (backlog Source of Record); new approved capabilities use OpenSpec change artifacts under `openspec/changes/`. See `docs/agents/issue-tracker.md`.

### Triage labels

The repo uses the default mattpocock/skills triage label vocabulary. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repo: use root `CONTEXT.md` and `docs/adr/` when present. See `docs/agents/domain.md`.

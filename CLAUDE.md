## Agent workflow

AIDLC bootstrap：先讀取本專案綁定檔（`docs/agents/workflow-bindings.md`）；依其 §0 的固定 workflow source 載入中央主規範與目前角色 prompt。來源、綁定或目前角色缺漏時維持唯讀並詢問 Human Owner。

## Agent skills

### Issue tracker

Issues and PRDs are tracked in `spec.md` §15 (backlog Source of Record); new approved capabilities use OpenSpec change artifacts under `openspec/changes/`. See `docs/agents/issue-tracker.md`.

### Triage labels

The repo uses the default mattpocock/skills triage label vocabulary. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repo: use root `CONTEXT.md` and `docs/adr/` when present. See `docs/agents/domain.md`.

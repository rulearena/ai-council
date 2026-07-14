# 主席操作與逐一爭點法院流程實作計畫

Canonical backlog: `spec.md` §15 #87  
PRD: `.scratch/chairman-courtroom-flow/PRD.md`

## 基線與限制

- Base: `ddd162e`
- Backend: 305 passed
- Frontend unit: 19 passed
- Frontend build: pass
- Chromium e2e: 71 passed
- main 的 `config/models.yaml.example` 是 Human Owner 未提交變更，不得修改、stash、覆寫或納入本批次。
- runtime 只使用 worktree `.scratch/`，不得使用 `/tmp`。

## 模組設計

### CourtroomWorkflow module

外部 interface 是 meeting HTTP lifecycle；它隱藏 metadata draft/confirmed roster、event-derived progress、合法 transition與 prompt orchestration。Frontend 只消費 projection並送 action，不重作 state machine。Workflow service 是 app-scoped singleton，使用 per-meeting lock 在每個 transition 內重讀 metadata/events 後再驗證與 reserve；generic `/start`、`/sequences`、round counter 與 retry 不得承擔 courtroom issue semantics。

### ChairmanAction module

外部 interface 是 `{kind, targetRole?, content}` 與 projected next action；UI 由同一個 module 決定選項、placeholder、submit label與呼叫路徑，避免一般發言與指定追問再次分裂。

### Persistence

- metadata：可編修 issue definitions、confirmed marker。
- append-only events：goal change audit、issue phases/rulings/final。
- derived projection：current issue、per-issue status、available actions、final readiness。
- courtroom docket 使用 optimistic revision；確認後 roster 與 goal 均唯讀，title 仍可在 idle 修改。

## 執行順序

1. Ticket 01：先用 HTTP/runner failing tests 固定 state machine與events，再完成 backend domain。
2. Ticket 02：先用 frontend pure tests/API tests 固定 chairman/edit/workflow labels，再完成 unified controls。
3. Ticket 03：以 Playwright tracer bullets串接 issue workspace，完成 reload/race/error UX。
4. 執行 Standards/Spec 雙軸獨立 review；Blocking/Major/選定 Minor 退回原 Executor。
5. 完整 backend/unit/build/Chromium/direct browser smoke，更新 spec/HANDOFF，merge main，清理 worktree。

## Gate

- 不得降低既有 305/19/71 基線。
- 每張 ticket 必須先有原因正確的 RED 證據，再 GREEN。
- final verdict 前必須有所有 confirmed issue completed ruling 的後端證據。
- 所有 user-visible state 必須可在 reload 後從 backend 恢復。

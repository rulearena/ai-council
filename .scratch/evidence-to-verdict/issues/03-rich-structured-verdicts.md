# 豐富結構化裁決

Status: ready-for-agent
Blocked by: 01, 02

## Goal

完成 backlog 65。adjudicator 類角色使用 `structured-verdict/v1`，產生帶裁決結果、證據引用、條件與未決問題的結構化輸出；其他角色及舊事件維持現況。

## Behavior contract

- registry 增加 `structured-verdict/v1`，欄位至少包含：
  - `summary: string`
  - `decision: approve | approve-with-conditions | reject | insufficient-evidence`
  - `findings: [{title, detail, evidence_refs: string[]}]`
  - `risks: [{title, detail, evidence_refs: string[]}]`
  - `recommendation: string`
  - `conditions: string[]`
  - `unresolved_questions: string[]`
- parser 嚴格驗證 container、string、decision enum 與每個 evidence ref；ref 必須符合 `[證物…]` 形狀，但不在本 slice 以 LLM 或全文比對判定語意真偽。
- `config/modes.yaml` 中所有 `kind: adjudicator` role 使用 rich schema；member、synthesizer 保持 v1。
- prompt 除 required schema 外，要求 findings/risks 對案卷主張附既有 anchor；無充分證據可選 `insufficient-evidence`，不可捏造引用。
- event/API 保存新 schema ID 與 parsed output。
- transcript 與 Role Drawer 顯示 decision、findings/evidence refs、risks/evidence refs、conditions、unresolved questions；舊 v1 UI 不變。
- parse failure 保持既有一次自動 retry、再 failed 的語意。

## Files likely involved

- schema registry/parser module
- `config/modes.yaml`
- adjudicator prompt templates
- `backend/ai_council/meetings/transcript.py`
- runner/API tests
- `frontend/src/api.ts`
- `frontend/src/components/RoleDrawer.vue`
- `frontend/tests/e2e/control-flow.spec.ts`

## Forbidden

- 不修改 step ids、role ids 或 mode topology。
- 不讓 non-adjudicator 改用 rich schema。
- 不把 evidence ref 驗證擴張成 RAG 或外部服務。
- 不刪除或回填舊 parsed output。

## TDD cases

1. rich schema parser 接受已知 literal，拒絕未知 decision、錯型別及非法 evidence ref。
2. red-blue/courtroom/debate adjudicator completed event 使用 rich schema；普通 member event 仍為 v1。
3. invalid rich output 第一次失敗後自動 retry；第二次有效時 completed，兩次皆使用相同 rich schema metadata。
4. transcript 同時渲染 legacy v1 與 rich verdict fixture。
5. Playwright 執行至少一個 adjudicator step，Role Drawer 顯示裁決、證據 refs、條件與未決問題。

## Acceptance

- targeted backend/frontend verification green。
- backend full pytest、frontend build、完整 e2e green。
- 真瀏覽器 smoke 驗證新舊輸出。
- Reviewer verdict pass。

## Comments

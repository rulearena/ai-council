# 01 — Courtroom issue domain、HTTP 與 Runner

Status: implemented / awaiting acceptance

Blocked by: none

## 目標

建立可持久化、可投影、可重整恢復的 issue-driven courtroom lifecycle，所有 gate 由後端決定。

## 行為契約

- 僅 `mode_id=courtroom` 可使用 courtroom issue endpoints。
- AI draft 是顯式付費動作，使用 Judge assignment、goal、Judge 可見案卷與既有逐字稿；結果只保存為未確認草稿。
- 主席可在未確認前整批替換 issue roster（含新增、修改、刪除、排序）；issue id 穩定且輸入需驗證非空與唯一。
- metadata docket 使用 schema version、optimistic revision 與 server-issued monotonically increasing issue ids；重排不改 id、刪除後不重用 id。
- confirm 後 roster 不得被一般 update 偷改；existing courtroom meetings 沒有 confirmed issues 時，所有舊 start/sequence/final paths 必須 409。
- current issue 只允許 confirmed 且尚未 ruled 的 issue；開始後依 charge → defense → rebuttal 執行並停止。
- 送交 ruling 僅在該 issue 攻防完成後允許；保存 `courtroom-ruling/v1` outcome、理由、evidence_refs、unresolved_questions。
- next issue 只能由主席顯式選擇/開始，不自動串接。
- final verdict 僅在 roster 全部都有 completed issue ruling 時允許；prompt 必須包含各 issue/ruling 並回答 meeting goal。
- retry 保留 issue id/phase與原 interaction linkage；不能跨 issue 污染。
- 舊 events 不改寫，非 courtroom runner 不變。
- app-scoped `CourtroomWorkflowService` 以 per-meeting lock 包住「重讀 metadata/events → validate transition → reserve/append」；AI operation 開始前先留下 reservation/start event。metadata mutation、details、assignment、message 在該 meeting job 執行中需拒絕，避免 TOCTOU 與 prompt 看不到途中補充。
- final readiness 必須逐一比對 confirmed revision 的 issue ids 與各自 latest completed ruling；舊 verdict、directed Judge reply、不同 revision、failed/discarded attempt 都不得計入。final failed 時只允許 retry linked final，不得新增第二條 final 流程。

## 建議 interface

- `POST /meetings/{id}/courtroom/issues/draft`
- `PUT /meetings/{id}/courtroom/issues`
- `POST /meetings/{id}/courtroom/issues/confirm`
- `POST /meetings/{id}/courtroom/issues/{issue_id}/arguments`
- `POST /meetings/{id}/courtroom/issues/{issue_id}/ruling`
- `POST /meetings/{id}/courtroom/final-verdict`

所有 read projection 併入既有 meeting response 的 `courtroom` 欄位，frontend 不自行重建 state machine。

## TDD tracer bullets

1. Draft → edit/reorder → confirm 經 HTTP round-trip 且 reload 保留。
2. 未確認、錯誤 mode、running/terminal、unknown/duplicate issue 的 transition 被拒絕且不追加 AI event。
3. Start 單一 issue 只產生三個 issue-scoped role events，prompt 只聚焦 current issue，沒有 Judge final。
4. Rule 產生具 issue id 的 structured ruling；裁定後不自動開始下一 issue。
5. Final 在缺 ruling 時拒絕；全部完成後只產生一次 final verdict。
6. Legacy courtroom 有舊 events 但無 confirmed roster 時被 gate，既有 bytes/events 不變。
7. `/start`、`/sequences` 與 generic role flow 無法繞過 courtroom docket；concurrent/stale revision 被拒絕。
8. Concurrent double submit 只接受一次 transition；background exception 會留下可投影 failure，不會靜默卡住。

## 相關檔案

- `backend/ai_council/api.py`
- `backend/ai_council/meetings/runner.py`
- 新增 `backend/ai_council/meetings/courtroom.py` 深模組，generic relay 不承擔 docket state machine
- `backend/ai_council/meetings/execution_state.py`
- `backend/ai_council/prompting/`
- `prompts/courtroom_*.md`
- `backend/tests/test_api.py`
- `backend/tests/test_meeting_runner.py`
- `backend/tests/test_prompting.py`
- 新增 `backend/tests/test_courtroom_workflow.py`

## 驗收

- targeted backend tests 全綠並 commit。

# 01 — Deterministic courtroom settlement

Type: task
Status: implemented / awaiting acceptance
Blocked by: none

## 目標

以 deterministic timing harness 重現並修復 completed courtroom events、job release、WebSocket/HTTP refresh 之間的競態，讓 UI 不需 reload 即取得正確下一步。

## 相關檔案

- `backend/ai_council/api.py`
- `backend/ai_council/meetings/courtroom.py`
- `backend/tests/test_api.py`
- `backend/tests/test_websocket.py`
- `frontend/src/composables/useCouncil.ts`
- frontend public store seam tests（若現有 seam 不足，僅抽出最小可測 domain helper）
- `frontend/tests/e2e/control-flow.spec.ts`

## 診斷順序

1. 建立一個快、deterministic、agent-runnable 的紅燈，能控制 completed event 可見與 job release 的先後。
2. 依證據逐一排除：stale frontend overwrite、過早 settled、backend intermediate projection。
3. 只在已證實的責任邊界修復。

## TDD 案例

- job 仍 running 且 completed event 已可見：frontend 必須繼續等待，不得 commit 空 action projection。
- 較舊 refresh 晚回來：不得覆蓋較新的 settled courtroom projection。
- job release 後：arguments／ruling／final 各自投影正確 action/final state。
- 使用者連續推進兩個爭點：每一步 CTA 不 reload 即更新。

## 禁止事項

- 不把 polling timeout 調大當作修復。
- 不加入任意 sleep 作 production ordering。
- 不重寫 events、不改 event identity、不改 courtroom state machine。
- 不修改使用者的 `config/models.yaml.example`。

## 完成條件

- 保留最小 regression test 並記錄紅／綠指令與輸出。
- targeted gates 綠並提交小步 commit。
- 回報 root cause、commit SHA、測試與未驗證範圍。

## Comments

- Root cause：`GET /meetings/{id}` 與 WebSocket loop 原先先讀 events、再讀
  `jobs.is_running()`；job 若在兩者之間寫完並 release，同一 response 會混合
  「部分 courtroom events」與 `activity_status=completed`。Frontend 因而合理地
  停止 polling，留下 `arguments-in-progress`／空 action，reload 才取得完整 events。
- Red：
  `python -m pytest tests/test_api.py::test_courtroom_get_does_not_report_settled_from_an_incomplete_event_snapshot -q`
  連續三次穩定失敗，實際為 `activity_status=completed` 但 issue status
  `arguments-in-progress`，預期 `awaiting-ruling`。
- Green：相同 deterministic regression 連續五次通過；courtroom API 9 passed；
  WebSocket 4 passed；backend full 590 passed；frontend unit 48 passed；build 通過；
  雙爭點 courtroom Chromium 首次 1 passed、壓力 10/10 passed、完整 Chromium
  90/90 passed。
- Fix：GET 與 WebSocket 共用 `live_meeting_snapshot()`。若 job 在 events read 期間
  從 running 轉為 released，先重讀完整 events 才發布 non-running projection。
  沒有增加 timeout、production sleep、coordinator 長鎖、event schema 或 courtroom
  state machine 變更。
- 初次修復未修改 frontend production；Spec review 後補上最小 settlement coordinator，
  只負責 running／settled 與 request generation freshness，不推導 courtroom action。
- Commit：`eaa059ff51b950a43f368edcc5561205b9aef8ef`；另以 follow-up test commit
  將 harness 的 polling wait 改為 job completion callback。
- 執行環境揭露：工具無模型 selector，使用 assigned runtime 以 Executor 身分完成。
- 測試環境違規：最初數次 pytest 未明示 `TMPDIR`，pytest 自動在 workspace 外建立
  暫存目錄；Executor 未讀取、列出或清理外部內容。發現後所有 pytest gate 改用
  worktree `.scratch/courtroom-async-settlement/pytest-*` 的明示 `TMPDIR`，並在完成後
  精確清理 repo-local artifacts。
- Review fix：雙 boolean snapshot 仍可能漏掉 `false → start/finish → false` 的 ABA。
  `MeetingJobManager.lifecycle_state()` 現在在同一 lock 回傳 running 與每場成功 start
  才遞增的 revision；non-running 且 revision 改變時必須重讀 events。Regression 以
  completion callback 控制整個 job 在單次 read 內完成，舊版穩定得到 `events=[]`、
  `reads=1`，修復後取得 completed event、`reads=2`。
- Spec seams：新增 controlled WebSocket test，禁止 completed frame 只含部分 arguments；
  新增 arguments／ruling／final 三次 job release 後 public action/final projection test；
  frontend `waitForSettledProjection()` 以 injected wait/load/isCurrent 驗證 running 會繼續、
  late older refresh 不得發布，並由 `useCouncil` 的 settlement generation 使用。
- Review-fix targeted：backend settlement 4 passed；job lifecycle／既有 WebSocket 7 passed；
  frontend unit 50 passed；build 通過；雙爭點與刑事 courtroom Chromium 2 passed，
  另一次雙爭點 Chromium 1 passed。
- Second review fix：補讀期間仍可能完整跑完下一個 job。Back-to-back regression 舊版
  將只含第一個 completed event 的補讀誤標 `completed`；現在補讀後再驗一次 lifecycle
  state。若仍 running 或 revision 再變，有限次補讀立即以 `activity_status=running`
  發布，交給 frontend 下一輪 polling，不使用 loop、sleep 或長鎖。直接 manager contract
  tests 同時固定 accepted start 才增 revision、running rejected start 不增、done callback
  不得移除較新的 job，以及 exception finish 保留 revision。相關 targeted 8 passed。
- 最終獨立 review：Standards PASS、Spec PASS；工具無 Terra selector，兩位 Reviewer
  均使用 assigned runtime，與 Executor 分離。
- Post-review gates：backend 597 passed；frontend unit 50 passed；build 通過；完整
  Chromium 90/90；direct Chromium 由 UI 實際完成 arguments → ruling → final，輸出
  `DIRECT_SMOKE_OK arguments->ruling->final without reload`。所有 repo-local runtime、
  pytest、Playwright、build artifacts 與 node_modules symlink 已精確清理。

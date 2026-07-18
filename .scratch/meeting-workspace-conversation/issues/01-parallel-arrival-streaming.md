# 01 — Parallel arrival-order streaming

Type: task
Status: resolved
Blocked by: none

## 目標

讓 parallel 成員以同一份 round-start context 同時執行，完成時立即依 arrival order append，並在全員成功後才 synthesis。

## 相關檔案

- `backend/ai_council/meetings/runner.py`
- `backend/tests/test_meeting_runner.py`
- 必要時 `backend/tests/test_api.py`、`backend/tests/test_websocket.py`

## TDD 案例

- 以 threading primitives 控制 member 3 → 1 → 2 完成，events 立即按 3 → 1 → 2 可見且 reload 順序不變。
- 所有 member prompt 的 prior transcript 完全相同，不含同輪已完成 member output。
- 慢 member 未完成時，HTTP／WebSocket live snapshot 已含快 member event且 activity 仍 running。
- synthesis 不可在任一 member 未完成或失敗時開始；retry 成功後才可執行。
- cancel／terminal 後的 in-flight result 保留既有 discarded/interrupted 語意。

## 禁止事項

- 不使用 timing sleep 作 deterministic test。
- 不在 worker thread 併發寫 repository。
- 不改 event identity、failure/retry contract 或匿名化 synthesis。

## 完成條件

- 紅／綠證據、targeted tests 與小步 commit。

## Comments

- 2026-07-18 Executor：先加入受控 `threading.Event` 測試，固定 Member-3 → Member-1 → Member-2 完成。紅燈證實舊 runner 會等所有 futures 結束，Member-3 完成時仍無 partial event，並在等待 Member-1 可見時失敗。
- 2026-07-18 Executor：fanout 前凍結 active round-start transcript，worker 僅產生 event group；runner thread 以 completion order 立即 append。terminal discarded diagnostics 仍依 member index 收斂，保留取消契約。
- 2026-07-18 Executor：新增 HTTP／WebSocket partial snapshot 測試，確認快成員可見時 activity 仍為 running，且 synthesis 尚未開始；並讓 parallel activity projection 以本輪每位 member 的最新 attempt 判斷 unresolved failure，避免 arrival order 掩蓋 waiting 狀態。
- 紅燈：`python -m pytest tests/test_meeting_runner.py::test_parallel_runner_publishes_members_in_arrival_order_from_one_round_start_context -q` → `1 failed`（快成員未即時 append）。
- 綠燈：同測試 → `1 passed`；`pytest tests/test_meeting_runner.py -q -k parallel` → `15 passed`；`pytest tests/test_api.py tests/test_websocket.py -q -k 'parallel or brainstorm'` → `9 passed`；backend full → `602 passed`。
- Runtime disclosure：工具無模型 selector，本 ticket 使用 assigned runtime，未能明示選擇 `gpt-5.6-luna`。

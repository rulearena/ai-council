# 01 — Parallel arrival-order streaming

Type: task
Status: ready
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

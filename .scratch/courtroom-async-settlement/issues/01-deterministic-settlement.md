# 01 — Deterministic courtroom settlement

Type: task
Status: open
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

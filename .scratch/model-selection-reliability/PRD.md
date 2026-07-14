# 模型選擇可靠性

Status: implemented / awaiting acceptance

Human Owner 於 2026-07-14 核准 spec backlog 83、84 合併批次。產品 backlog 仍以 `spec.md` §15 為唯一 Source of Record；本目錄只保存已核准工作的執行資料。

## Goal

讓每場 meeting 的角色模型指派成為可持久化、可恢復且由後端統一執行的 Source of Truth，同時把模型管理改成 Provider 導引、exact model ID 可 discovery 或手動輸入的流程。

## Fixed decisions

- Meeting participant metadata 是新 meeting assignment 的 Source of Truth；events 只用於舊 meeting read-time recovery。
- `start`、`respond`、`sequence`、`retry` 一律由後端解析同一份 meeting assignment，run request 不得覆蓋。
- 新增完整 roster replacement interface：`PUT /meetings/{meeting_id}/participant-models`。
- Recovery/fallback 不寫回 metadata、不新增或修改歷史 events；只有使用者明確改選才持久化。
- Provider 是使用者產品概念，adapter 是內部傳輸協定；不新增必填 YAML provider 欄位。
- 「型號」指 Provider 的 exact model ID/version，不新增 family/variant 第二層。
- 新 config discovery 使用不保存的 preview interface；既有 config 使用既有 `GET /models/{id}/available-models`。
- API key 明文不得進前端、response、models.yaml 或 meeting/event 資料；UI/API 只處理環境變數名稱。

## Acceptance

- Backlog 83、84 所列 API 與 Playwright 情境全部覆蓋。
- Backend full、frontend build、full Chromium 與真瀏覽器 smoke test 通過，且不低於 262 / 39 的核准基線。
- Standards 與 Spec 由獨立 Reviewer 雙軸審查並 pass。
- 完成後更新 `spec.md` §15、`docs/HANDOFF.md`，merge main 並清理 worktree/branch。

## Comments

- 2026-07-14：Human Owner 核准完整批次；開始自主實作流程。
- 2026-07-14：完成 backlog 83–84；Spec review pass、Standards review pass（僅 Provider transport Repeated Switches Minor deferred）。最終 gates：backend 280 passed、frontend unit 8 passed、build 綠、Chromium 53 passed、直接 Chromium smoke 通過。

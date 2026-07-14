# Provider 與模型設定 UX 強化實作計畫

**Goal:** 完成 spec backlog 85：provider-specific discovery、Subscription CLI 導引式 presets，以及模型測試的 loading/slow/stale-response UX。

**Architecture:** discovery 建立 provider strategy seam，讓 API route 只傳入 model config 並接收 normalized IDs；Subscription CLI 在 frontend provider domain module 提供 preset projection/payload，保存格式維持既有 adapter schema；模型測試以 request generation 管理只允許最新結果提交 UI。

## 執行順序

1. Ticket 01：Anthropic/Gemini discovery red→green，先固定公開 HTTP 行為。
2. Ticket 02：CLI preset domain red→green，再接 Model Manager 與 legacy compatibility。
3. Ticket 04：把 Anthropic/Gemini discovery 接入 Provider UI 與 manual fallback。
4. Ticket 03：test feedback/race red→green，最後統一視覺與可存取狀態。
5. Ticket 05：backend health result ordering，阻止舊檢查 late-write 覆蓋新結果。
6. Orchestrator 執行 full backend/unit/build/e2e 與真瀏覽器 smoke。
7. Standards/Spec 兩位獨立 Reviewer 平行審查；Blocking/Major 回原 Executor 修復後複驗。
8. 通過後更新 spec/HANDOFF/tickets，merge main，清理 worktree/branch/runtime。

## TDD seams

- Backend public discovery endpoints。
- Frontend provider/CLI pure domain interface。
- Existing model health endpoint + user-visible list state。
- Playwright 真瀏覽器 user journey；不存取 Vue 私有 state。

## 完整 gates

- Backend ≥ 280 passed；frontend unit ≥ 8 passed；新增測試全綠。
- Frontend build、完整 Chromium e2e、真瀏覽器 smoke、`git diff --check`。
- 測試資料只在 worktree `.scratch/e2e-runtime/`；禁止 `/tmp`、`mktemp` 與 workspace 外路徑。

# 設定化案卷限制與建立前提示

Status: implemented / awaiting acceptance
Blocked by: none

## Goal

依 `docs/plans/2026-07-13-configurable-case-file-limits.md` 完成 backlog 81。

## Required behavior

- Backend limits、env validation、public limits endpoint、POST validation 使用同一 immutable config value，不得各自硬編碼。
- Frontend 使用 endpoint 實值；載入中或 endpoint 不可達時 fail closed、不得送出 POST，並提供重試。舊 request 不得覆寫重新開啟 modal 後的新 limits 狀態。
- 每份案卷顯示字元數/上限；總量沿用 `case-file-cost-note` 並加入上限、token 粗估與風險提示。
- 任一 per-file 或 total overflow 時 inline error + submit disabled，且 Playwright 證明沒有 POST。
- `ApiError.detail` 為 string 時在 New Case modal 顯示，不只顯示 generic status；失敗不關 modal、不清 topic/case files。
- 更新 `.env.example` 說明兩個 env 與 defaults。

## Forbidden

- 不做 RAG、摘要、文件切片、tokenizer dependency、模型 context metadata。
- 不把 token 粗估當 server validation。
- 不讀寫 workspace 外設定或資料。
- 不改 `events.jsonl`、output schema、prompt 或 runner。

## TDD and verification

- 每個 behavior 使用 API/Playwright public seam 逐輪 red→green。
- targeted backend/API、frontend build、targeted Chromium；最後 backend full + full Chromium。
- 提交小步 commits，回報 red/green、驗證、未驗證與模型 runtime。

## Comments

- 2026-07-13：完成於 `2c3f069`–`b51052a`；Standards 與 Spec review 均 pass。最終驗證：backend 249 passed、frontend build 綠、Chromium 37 passed。

# Meeting assignment 前端建立、恢復與設定

Status: implemented / awaiting review
Blocked by: 01

## Goal

讓 New Case、meeting hydration 與 Settings 全部使用每場 meeting 自己的 persisted assignment。

## Required behavior

- New Case 對 relay 與 parallel 全部 participant 顯示模型選擇並送出 model id。
- New Case draft 是 modal-local state；開啟、換 mode、增減 parallel member 時 deterministic 初始化，不讀取目前 meeting 的 selectedModels。
- 沒有可用模型或任何 participant 未選時禁止建立並提示。
- open/reload/switch meeting 時只從 meeting participants hydration；A/B meeting 不互相污染。
- Settings 選擇變更後呼叫完整 replacement endpoint；儲存失敗 rollback 並顯示錯誤。
- deleted/missing model 使用後端 effective fallback，顯示 warning，不自動持久化 fallback。
- start/respond/sequence/retry 前端不再傳 models map。

## Forbidden

- 不以 event history 在前端重新實作 recovery。
- 不以全域 selectedModels 作為新 meeting 預設。
- 不在 websocket event replacement 時反覆覆寫使用者已儲存的選擇。

## TDD seams

- Playwright：create→reload、settings→reload、meeting A/B switch、parallel roster、legacy recovery、deleted fallback。
- HTTP request assertions只驗證公開 payload/response，不讀 Vue 私有 state。

## Acceptance

- Targeted Chromium 與 frontend build 綠；既有模型選擇 e2e 更新為 persisted contract。

## Comments

- 2026-07-14：Executor 以 Playwright public seams 逐項完成 relay/parallel 建立、meeting hydration/switch isolation、Settings full replacement/rollback、legacy/deleted fallback，以及四種 run request 移除 models map。Assignment PUT 回傳 summary 不含 events，前端採合併 projection 並保留既有 events/case_files，避免設定更新後遺失 retry UI。
- 2026-07-14：工具沒有 gpt-5.6-luna selector，使用 assigned runtime。Frontend build、完整 Chromium 45/45、assignment backend targeted 9/9 與 `git diff --check` 通過；新增 legacy projection Playwright targeted 1/1 於完整 suite 後另行通過。
- 2026-07-14（review fix 1）：fixed parallel roster 改以 catalog 是否已有 member roles 判定；six-hats New Case 現保存 `HatWhite`、`HatRed`、`HatBlack`、`HatYellow`、`HatGreen`、`HatBlue` 全 roster assignment，dynamic brainstorm/persona 仍採 prototype-N。Playwright 紅燈為仍顯示 dynamic member editor，修正後建立→API response→reload targeted 綠。
- 2026-07-14（review fix 1）：assignment PUT 加入 captured meeting id 與 request generation guard。延遲的 A success 僅可更新 A 的 meetings summary，只有 A 仍為 active meeting 才更新 selected state；延遲 rejection 同樣不得 rollback 或顯示錯誤到 B。Playwright 紅燈重現 A response 把 B 切回 A，修正後 success/rejection 情境綠；相關 targeted Chromium 8/8、frontend build 與 `git diff --check` 通過。

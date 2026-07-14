# Meeting assignment 前端建立、恢復與設定

Status: ready-for-agent
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

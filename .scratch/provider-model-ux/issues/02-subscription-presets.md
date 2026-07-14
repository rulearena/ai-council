# Subscription CLI guided presets

Type: task
Status: open
Blocked by: 01

## 目標

以深 module 將 CLI provider/preset/argv/legacy projection 隱藏在小 interface 後，前端提供 Claude CLI、Codex CLI、AGY、Custom CLI 導引式設定。

## TDD

- Pure module tests：每個 preset 預設 argv、進階 model argv、legacy command 辨識與 custom round-trip。
- API/repository tests：generated payload 通過既有驗證且 YAML schema 不變。
- Playwright：使用 preset 不需手打 `{prompt}`；legacy custom command 仍可編輯保存。

## 相容性

- CLI 預設模型為推薦預設；不硬性要求 provider model catalog。
- 舊 command 不 migration、不靜默重寫。

## 驗收

- Frontend unit、targeted backend/e2e 與 build 綠；單一目的 commit。

# Subscription CLI guided presets

Type: task
Status: resolved
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

## Resolution

- Claude CLI、Codex CLI、AGY preset 由 pure domain module 產生固定 argv，預設交由 CLI 自動選擇模型。
- Model Manager 一般路徑顯示 CLI Provider 與「使用 CLI 預設模型／指定 exact model ID」；exact 模式由各 preset 依 canonical contract 產生 argv（Claude `claude --model <id> -p {prompt}`、Codex `codex exec --model <id> {prompt}`、AGY `agy --model <id> -p {prompt}`），Custom CLI 才顯示逐參數 command 編輯。
- 可辨識的 default/exact preset 投影回導引式選項；未知 legacy command 投影為 Custom 並原樣 round-trip，不 migration。
- 未帶 `extra_body.cli_provider` 的既有 preset 若未變更即原樣保存；新建或切換 preset 才產生 provider marker。

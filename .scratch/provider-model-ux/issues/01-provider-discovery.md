# Provider-specific model discovery

Type: task
Status: open
Blocked by:

## 目標

讓 Anthropic、Gemini 經既有 discovery HTTP interface 回傳 normalized exact model IDs，並保持 OpenAI-compatible 行為與 secret safety。

## TDD

- 先以 API tests 證明 Anthropic/Gemini preview 與 existing discovery 目前為紅燈。
- 覆蓋 provider headers/query、base URL composition、排序去重、空清單、upstream error、缺 credential env。
- 測試不得連真 provider 或讀 workspace 外環境設定。

## 禁止事項

- 不發 completion、不保存 config、不記錄 API key。
- 不改 meeting/events。

## 驗收

- Targeted backend tests 綠並有 red→green 證據；單一目的 commit。

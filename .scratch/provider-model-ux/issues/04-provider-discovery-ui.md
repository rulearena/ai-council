# Provider discovery UI

Type: task
Status: resolved
Blocked by: 01, 02

## 目標

將 Anthropic、Gemini 已完成的 backend discovery 接入 Model Manager，提供與 OpenAI 一致的載入／重新整理、exact model ID 下拉與 manual fallback。

## TDD

- Provider domain unit：Anthropic/Gemini 宣告為 provider-specific discovery，不再顯示 unsupported。
- Playwright：兩個 Provider 的成功、空清單與失敗情境；成功可從下拉保存 exact ID。
- 確認 credential 仍只傳 env var 名稱，切換 Provider/manual edit 會淘汰 late discovery。

## 驗收

- Frontend unit、targeted e2e 與 build 綠；單一目的 commit。

## 完成

- Anthropic 與 Gemini 已標示為 provider-specific discovery，Model Manager 可載入及重新整理 exact model ID。
- 成功可由下拉儲存；空清單或錯誤保留 manual exact ID；credential payload 僅包含環境變數名稱。
- Provider 切換或 manual model edit 會淘汰進行中的 discovery 回應。

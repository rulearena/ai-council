# Provider 導引式模型管理 UI

Status: ready-for-agent
Blocked by: 02, 03

## Goal

以 Provider → connection → exact model ID 的流程取代 adapter-first 技術表單。

## Required behavior

- 模型管理先選人類可理解的 Provider，不把 adapter select 當主要 UI。
- 依 Provider 顯示連線欄位、credential 環境變數名稱與安全說明。
- OpenAI-compatible 支援載入／重新整理模型；新 config 走 preview，既有 config 走既有 GET endpoint。
- 成功時可從下拉選 exact model ID；失敗、空清單、unsupported 或新型號未列出時可手動輸入。
- Anthropic、Gemini、CLI 顯示明確 manual/unsupported UX。
- 模型列表、Settings 角色下拉、New Case 下拉與 stage nameplate 使用 Provider + exact model ID；CLI 無 model 時誠實顯示由 command 決定及 config id。
- 編輯舊 config 保留 extra_body/pricing/command 等 round-trip fidelity。

## TDD seams

- Playwright：provider selection、existing edit、discovery success/failure/empty/manual、legacy config、role labels。

## Acceptance

- Targeted Chromium、frontend build、backend full、full Chromium 綠；真瀏覽器 smoke 完成。

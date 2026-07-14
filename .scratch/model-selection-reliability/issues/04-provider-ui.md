# Provider 導引式模型管理 UI

Status: implemented / awaiting acceptance
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

## Comments

- 2026-07-14：Executor 完成 Provider-first Model Manager。Create 使用 preview discovery，edit 使用既有 saved-config discovery；成功可選 exact model ID，失敗、空清單、unsupported 皆保留 manual entry。Anthropic、Gemini、Subscription CLI 與 Mock 明示不支援自動 discovery；credential 欄位只接受環境變數名稱並顯示安全說明。
- 2026-07-14：模型列表、Settings、New Case、stage 共用 Provider label；CLI 無 model 時顯示「由 command 決定（config id）」。Provider payload mapping 保留 legacy base URL、extra_body、pricing 與 CLI command round-trip。
- 2026-07-14：TDD red 證據包括 adapter select 仍存在、CLI label 未誠實表達 command、CLI 缺少 unsupported discovery 提示、discovery failure detail 被泛化；均已轉綠。Frontend unit 5 passed、build 通過、backend discovery targeted 10 passed；targeted Chromium 通過。完整 Chromium 首輪 50 passed / 1 test-race timeout，加入等待前一個 save 完成後該情境 targeted 綠；乾淨 fixture 完整重跑 51 passed。
- 2026-07-14：工具沒有 gpt-5.6-luna selector，Executor 使用 assigned runtime。
- 2026-07-14 review fix：Discovery 改由公開的 latest-request coordinator 管理 generation 與 captured form/provider identity。Provider／connection 切換、close/reopen、新 request 都會淘汰舊 generation；stale success、empty、error 不再能更新 model options、form model 或 discovery 狀態。可控 Promise unit tests 覆蓋 invalidation 與 overlapping requests。
- 2026-07-14：Standards Minor「transport kind 重複判斷」不阻擋本次安全修復；ProviderDefinition kind schema 調整延後，避免在 race fix 中擴大 catalog public contract。
- 2026-07-14 review round 2：manual exact model 與 discovered select 修改都會 invalidate pending discovery；late success/empty/error 不得覆蓋新選擇。Standards 複驗 pass。Final unit 8 passed、build 綠、Chromium 53 passed、直接 browser smoke 通過。
- 2026-07-14 review round 2：Manual exact model input 與 refresh 中的 discovered select 改選都會淘汰 in-flight discovery；輸入保持可用，不以 disabled 規避 race。Late success、empty、error 的可控 Promise regression test 證明使用者的新 model ID 不會被舊 response 覆寫或隱藏。

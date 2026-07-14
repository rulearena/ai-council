# Provider 與 discovery foundation

Status: implemented / awaiting acceptance
Blocked by: 01

## Goal

建立 Provider 產品概念與不保存的新 config discovery preview，同時保留舊 models.yaml 相容性。

## Required behavior

- Provider catalog：OpenAI、Anthropic、Gemini、Custom OpenAI-compatible、Subscription CLI、Mock。
- Provider 到既有 adapter/base URL/env-name preset 的 mapping 集中在單一前端 module。
- 舊 config 依 adapter 與已知官方 base URL deterministic 投影 Provider；不要求 YAML migration。
- 新增 preview discovery interface，只接受 transport 設定與 credential 環境變數名稱，不保存 config。
- Preview 僅支援 OpenAI-compatible；unsupported、adapter failure、empty list 可區分。
- 既有 `GET /models/{id}/available-models` 保持相容並供編輯流程使用。
- Response 與錯誤不得包含 API key 值。

## Forbidden

- 不新增必填 provider YAML 欄位。
- 不替 Anthropic/Gemini/CLI 假造 discovery。
- 不把 adapter 名稱當作主要使用者文案。

## TDD seams

- Backend HTTP discovery interface，外部 provider request 可 mock。
- Frontend provider module pure public functions：projection、payload mapping、display label。

## Acceptance

- Discovery success/failure/empty/unsupported 與 secret safety tests 綠。

## Comments

- 2026-07-14：完成六 Provider domain mapping、preview/existing discovery、strict payload 與 secret error redaction；backend 與 Provider pure tests 納入 final gates。

- 2026-07-14：Executor 完成集中式 frontend Provider domain module、legacy config deterministic projection、provider payload/label public functions，以及未保存的 `POST /models/available-models` preview。Preview 僅接受 transport 設定與 credential 環境變數名稱；extra 欄位會以不回顯輸入值的 422 拒絕，provider error 也會遮罩實際環境變數內容。既有 GET discovery 保持相容並共用 error redaction。
- 2026-07-14：TDD 證據包含 preview route 405→200、provider credential echo failure→redaction、明文 `api_key` 被接受→strict safe 422、legacy proxy base URL 被 preset 覆寫→round-trip 保留。Backend `test_api.py` 111 passed；frontend provider unit 5 passed；frontend build 與 `git diff --check` 通過。Node 22.17.0 以內建 TypeScript stripping test runner 執行，未新增 dependency 或 lockfile 變動。
- 2026-07-14：工具沒有 gpt-5.6-luna selector，使用 assigned runtime。完整 ModelManager Provider UI 與 Playwright 流程保留給 issue 04。

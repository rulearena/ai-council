# Provider 與 discovery foundation

Status: ready-for-agent
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

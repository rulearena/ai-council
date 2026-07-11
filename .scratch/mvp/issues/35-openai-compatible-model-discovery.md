# 35 - OpenAI-Compatible Model Discovery

Status: resolved
Type: task

## What to build

Allow OpenAI-compatible HTTP configs to list available model ids from their endpoint.

## Blocked by

05 - Model Adapter Contract With Mock And OpenAI-Compatible HTTP

## Acceptance Criteria

- [x] OpenAI-compatible adapter can call `GET /models`.
- [x] API exposes `GET /models/{model_config_id}/available-models`.
- [x] Discovery returns available model ids.
- [x] Unsupported adapters return a clear error instead of pretending discovery works.

## Resolution Notes

- Added `OpenAICompatibleHTTPAdapter.discover_models()`.
- Added `GET /models/{model_config_id}/available-models`.
- Unsupported adapters return `400`.


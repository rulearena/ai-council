# 20 - Model Connection Test

Status: resolved
Type: task

## What to build

Make model connection testing actually exercise configured adapters and expose the result in the frontend.

## Blocked by

07 - FastAPI Meeting And Model API
09 - Vue Control And Debug UI

## Acceptance Criteria

- [x] Mock model test returns `available`.
- [x] OpenAI-compatible HTTP model test calls the adapter.
- [x] HTTP adapter success returns `available`.
- [x] HTTP adapter failure returns `unavailable` with an error message.
- [x] Frontend exposes model test buttons for Blue/Red/Judge selections.
- [x] Frontend displays model test status.
- [x] E2E verifies `mock-fast` reports available.

## Resolution Notes

- `POST /models/{model_config_id}/test` now calls the configured adapter instead of returning `unknown` for HTTP models.
- Added frontend `testModel()` API helper.
- Added `test-blue-model-button`, `test-red-model-button`, `test-judge-model-button`, and `model-test-status`.
- Extended E2E to verify Blue mock model test status.

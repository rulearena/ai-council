# 41 - Background Model Health Checks

Status: resolved
Type: task

## What to build

Run a backend startup health check for configured models and expose the latest health result through the existing model list API.

## Blocked by

20 - Model Connection Test; 25 - Meeting Activity Projection

## Acceptance Criteria

- [x] Backend startup schedules model health checks without blocking app creation.
- [x] Successful checks mark models `available`.
- [x] Adapter failures mark models `unavailable` with an error string.
- [x] `GET /models` includes health check timestamp and error metadata.
- [x] Health status stays in memory and does not rewrite `config/models.yaml`.

## Resolution Notes

- Added an in-memory startup model health checker that reuses the same adapter test helper as `POST /models/{model_config_id}/test`.
- `GET /models` now reports `health_checked_at` and `health_error` alongside the projected `status`.
- API tests disable background checks by default and opt in for health-check coverage to avoid background-thread races in unrelated tests.

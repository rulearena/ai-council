# 34 - Backend Credential Readiness Projection

Status: resolved
Type: task

## What to build

Let the backend report whether an API-backed model's configured environment variable exists without exposing the secret value.

## Blocked by

33 - Backend Model Config Management API

## Acceptance Criteria

- [x] `GET /models` includes credential readiness for `api_key_env` configs.
- [x] Credential readiness object returns env var name and configured boolean only.
- [x] Credential readiness never returns secret values.
- [x] Existing `api_key_env` config metadata remains visible because it is an env var name, not a secret value.
- [x] Local/no-key models return no credential requirement.

## Resolution Notes

- Added a `credential` projection to model list and model upsert responses.
- The projection reports `type`, `env_var`, and `configured`.
- The actual environment variable value is never returned.


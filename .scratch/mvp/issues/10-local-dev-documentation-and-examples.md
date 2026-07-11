# 10 - Local Dev Documentation And Examples

Status: resolved
Type: task

## What to build

Add local setup docs and examples so the MVP can be run and tested consistently.

## Blocked by

07 - FastAPI Meeting And Model API
09 - Vue Control And Debug UI

## Acceptance Criteria

- [x] README documents backend and frontend dev commands.
- [x] `.env.example` documents data/config variables.
- [x] `config/models.yaml.example` stays aligned with implemented config schema.
- [x] Prompt templates are documented or discoverable.

## Test Strategy

Run backend tests and frontend build after documentation/example changes. Import the backend app entrypoint to confirm local dev commands target a real app object.

## Resolution Notes

- Added root `README.md` with backend/frontend setup, run, and validation commands.
- Added `.env.example` for local data/config/prompt/API variables.
- Added `ai_council.main:app` so the documented `uvicorn` command points to a real FastAPI app.
- Added default prompt templates under `prompts/`.
- Added `uvicorn` to backend runtime dependencies.
- Verified app import, backend/local-executor tests, and frontend build.

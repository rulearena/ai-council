# 37 - Token Usage Metadata Tracking

Status: resolved
Type: task

## What to build

Preserve provider token usage metadata in completed events and expose meeting-level totals.

## Blocked by

05 - Model Adapter Contract With Mock And OpenAI-Compatible HTTP; 18 - Meeting Status Projection

## Acceptance Criteria

- [x] OpenAI-compatible responses map `usage` into normalized token usage.
- [x] Anthropic responses map `usage.input_tokens` / `usage.output_tokens`.
- [x] Gemini responses map `usageMetadata`.
- [x] Runner persists `token_usage` on completed model events when available.
- [x] Meeting read models include cumulative `token_usage` totals.
- [x] Frontend API types include the new `token_usage` fields.

## Resolution Notes

- Added optional `token_usage` to `ModelResponse`.
- Added provider-specific token usage extraction for OpenAI-compatible, Anthropic, and Gemini adapters.
- Persisted usage on completed events and projected meeting totals.


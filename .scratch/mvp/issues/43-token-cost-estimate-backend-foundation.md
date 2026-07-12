# 43 - Token Cost Estimate Backend Foundation

Status: resolved
Type: task

## What to build

Add backend-only token cost estimate support using optional model pricing metadata and existing token usage totals.

## Blocked by

37 - Token Usage Metadata Tracking; 33 - Backend Model Config Management API

## Acceptance Criteria

- [x] Model configs can declare optional `pricing` metadata with `currency`, `input_per_1m_tokens`, and `output_per_1m_tokens`.
- [x] Model config repository preserves pricing metadata when loading and saving YAML.
- [x] Meeting read models include `estimated_cost` as `{currency, amount}` when all token-usage events can be priced.
- [x] Meeting read models return `estimated_cost: null` when pricing metadata is unavailable.
- [x] `GET /meetings` and `GET /meetings/{meeting_id}` return consistent `estimated_cost` values.
- [x] Frontend API types include the new optional model pricing and meeting estimated cost fields without adding UI.

## Resolution Notes

- Added top-level `pricing` metadata on model configs instead of using `extra_body`, so pricing is not sent to provider request payloads.
- Meeting summaries now project `estimated_cost` from persisted event `token_usage` and current model pricing metadata.
- Cost estimates return `null` unless all token-usage events can be priced in one currency.

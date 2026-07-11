# 39 - Token Streaming Backend Foundation

Status: resolved
Type: task

## What to build

Let model adapters emit non-persistent token deltas during a running step and expose them through the existing meeting WebSocket.

## Blocked by

08 - WebSocket Event Feed; 30 - Background Meeting Progress

## Acceptance Criteria

- [x] `ModelRequest` can carry an optional token-delta callback.
- [x] Mock model configs can emit deterministic `mock_stream_chunks` for tests.
- [x] Runner converts token deltas into step-scoped stream events.
- [x] WebSocket snapshot/update payloads include `stream_events`.
- [x] Token delta stream events are not persisted to `events.jsonl`.
- [x] Frontend API types include token-delta stream event payloads.

## Resolution Notes

- Added a non-persistent meeting stream bus for ephemeral token delta events.
- Kept `events.jsonl` as the durable source of truth for completed/failed meeting events only.
- Real provider streaming and visible frontend rendering remain follow-up work.

## Why

Human Owner asked whether chatroom `@all` runs in parallel; backend events prove it does (`fanout_chatroom_all` uses `ThreadPoolExecutor(max_workers=len)`, all roles start the same millisecond with overlapping durations). But the frontend makes it *look* sequential: responses are appended one-by-one in completion order (`as_completed`), and the thinking indicator only ever shows the first queued role as "thinking" (`projectRoles` marks only `queueIndex === 0` as thinking for non-parallel modes). The owner accepted a batch-group presentation so a single `@all` round reads as one parallel round instead of a relay sequence.

## What Changes

- **Batch-group rendering of one `@all` fanout round**: message bubbles whose `in_response_to_event_id` points at the same human-message event are rendered as a visual group (a "N 位角色回應中" header and a grouped container), filling in members in arrival order as they complete. Each role's bubble remains a distinct message (feed count and per-role selectors are unchanged).
- **Simultaneous thinking indicators**: during a fanout round, every mentioned role shows a thinking indicator at the same time (not just the first queued role). The group header shows live progress (e.g. "2/4 已回應").
- **No backend or event-schema change**: fanout execution already parallel; grouping is a frontend projection concern keyed off existing `in_response_to_event_id` + `chat-fanout-{ts}-{role}` step_ids. No historical events are rewritten.
- **Legacy robustness**: fanout events without a resolvable `in_response_to_event_id` (old/pre-existing data) fall back to the current sequential display rather than mis-grouping.

## Capabilities

### New Capabilities
- `fanout-round-display`: groups one chatroom `@all`/multi-mention fanout round into a single visual batch with simultaneous thinking indicators and live round progress, keyed on `in_response_to_event_id` + `chat-fanout-{ts}-*` step_id prefix, with safe fallback when the grouping key is absent.

### Modified Capabilities
- `conversation-workspace`: the "Chatroom message display" requirement's fanout scenarios change — `@all` responses render as a grouped round (not just a flat arrival-ordered feed), and the thinking-indicator scenario now expects every mentioned role to indicate thinking simultaneously.

## Impact

- `frontend/src/meetingWorkspace.ts`: projection changes — derive fanout rounds from `in_response_to_event_id`; adjust `projectRoles` so a chatroom fanout round marks all mentioned roles thinking (not only queue position 0); surface round metadata on `WorkspaceMessage`.
- `frontend/src/components/ConversationWorkspace.vue`: render fanout round groups (group header, member bubbles, thinking placeholders, live progress) while keeping per-message markup/selectors intact.
- `frontend/src/composables/useCouncil.ts`: chatroom mention send already queues every mentioned role via `pendingRoles`; capture that queued list as the round's expected member set, and adjust the chatroom-fanout failure path so a failed member clears only its own slot instead of collapsing the whole round (relay/parallel/courtroom failure behavior unchanged). This file is in scope despite the "projection files only" shorthand in backlog #98 — the change remains a pure frontend change.
- Tests: frontend unit (round grouping, simultaneous thinking, progress, legacy fallback) and Playwright e2e (existing `chatroom.spec.ts` 13.4/13.7/13.22 selectors stay green; new assertions for group header and simultaneous thinking).
- No backend changes. No `events.jsonl`/`models.yaml`/`modes.yaml` changes. No historical data migration.

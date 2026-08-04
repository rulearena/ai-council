## Context

Backend `fanout_chatroom_all` already invokes all assigned roles concurrently and appends each response as it completes. Every response event carries `in_response_to_event_id` for the triggering human message. The frontend currently derives thinking state from a flat `pendingRoles` queue and only creates message DOM nodes for persisted events, so there is no group container during the interval between the request and the first response.

The chat mention endpoint starts the fanout asynchronously and returns `202`; it does not return the human event ID. The frontend therefore needs a small, session-local correlation record. The event log remains append-only and is the source of truth. This change is frontend-only and must preserve the existing event schema and all non-chatroom/formal flows.

## Goals / Non-Goals

**Goals:**

- Show a real `@all` round container before any member response exists, with a `0/N` header and all expected roles represented as pending placeholders.
- Correlate that provisional round to the human event and keep the same container while responses arrive in backend append order.
- Show arrived member bubbles first and pending placeholders at the bottom; failed members settle independently.
- Define deterministic terminal behavior for request failure, WebSocket disconnect/reconnect, and an expected role that emits no event.
- Keep each arrived response a distinct `workspace-message`, preserve existing role filtering/quoting selectors, and leave non-`@all` behavior unchanged.

**Non-Goals:**

- No backend or event-schema changes, no mention parser changes, and no history migration.
- No grouping for directed single-role or existing multi-role mentions.
- No changes to relay, parallel, courtroom, formal output, or backend fanout execution/order.

## Decisions

### D1. Group arrived events by the verified human-event reference

An arrived event is eligible for a round only when its `step_id` starts with `chat-fanout-` and its `in_response_to_event_id` resolves to a `human-message` event in the same meeting. The resolved human event ID is the durable round key. An event with a missing or unresolvable key stays a flat message in arrival order, preventing legacy data from being mis-grouped.

### D2. Use a public round/feed-item projection, not a message-only wrapper

`projectMeetingWorkspace` will expose a `fanoutRounds`/feed-item seam that can represent a round independently of `WorkspaceMessage[]`. A round contains its stable ID, optional human event ID, expected role IDs, arrived member messages in event order, per-role state (`pending`, `completed`, `failed`, or `unknown`), response/failure counts, and a terminal status. The conversation feed projection emits a `fanout-round` item even when `members` is empty; ordinary messages remain message items.

This is necessary because wrapping the first arrived message cannot render the required pre-event `0/N` state. Once the human event is observed, the provisional item is reconciled to its durable event key without losing its position or expected-role set. Each arrived member remains a distinct `workspace-message` inside the round; the round header and placeholders are presentational and are not messages.

### D3. Capture → human event correlation is explicit and session-local

Before calling `sendChatMention`, `sendChatroomMention` creates a provisional capture containing: meeting ID, exact instruction text, expected participant role IDs, capture time, and the event IDs already known for that meeting. It immediately feeds that capture to the workspace projection, so placeholders render before the `202` request completes.

The WebSocket handler binds the oldest unresolved capture for the meeting when a new `human-message` event arrives whose content matches the captured instruction and whose ID was not in the pre-send set. The backend rejects a second running chatroom job, so two captures with the same meeting/instruction cannot be active concurrently; if matching remains ambiguous, the capture is not rebound and the event-derived fallback is used. After binding, only response events whose `in_response_to_event_id` equals that human event ID can enter the round. A failed HTTP request removes the capture and restores the prior pending state.

### D4. Expected roles are captured from the `@all` participant roster

The capture is created only when the mention set contains `all`. Its expected set is the selected meeting's participant role IDs, in participant order, filtered to stable non-empty role IDs; no role inferred from an arrived event or from a directed/multi-role mention is added to a provisional round. This is the same roster the existing chatroom UI queues for `@all` and is bounded to roles the meeting exposes to the backend. Arrived participant roles are merged for robustness, but the denominator is fixed once the capture is created and does not grow with completion order.

After reload or a disconnect that loses the capture, the projection uses only roles observed in durable events for that round and labels the result as degraded; it never invents missing members or over-counts. This is an intentional frontend-only trade-off because persisting the mention set would change the backend event contract.

### D5. Render three round phases with an observable settlement rule

1. **Pre-event:** the provisional capture renders at the bottom of the feed with a round header (`0/N` or equivalent) and one pending placeholder for every expected role.
2. **In-stream:** after correlation, arrived completed/failed events render in append order. Completed or failed roles leave the pending placeholder; remaining expected roles stay pending at the bottom. The header uses the fixed N.
3. **Terminal:** the WebSocket `activity_status` transition away from `running` after the correlated human event is the observable settlement signal. Any expected role without a completed/failed event is marked `unknown`, its thinking indicator is removed, and the header shows a partial/unknown terminal label rather than claiming all roles responded. A failed member counts toward settlement but not the completed-response count.

If the connection closes, clear provisional capture/pending UI state. On reconnect, rebuild from durable events; a round with a lost capture degrades to arrived members only. An unbound provisional capture is discarded when the request's activity settles without a correlating human event, so it cannot remain pending forever.

### D6. Failure handling is scoped to chatroom `@all`

When a new failed event belongs to a resolved chatroom `chat-fanout-*` round, remove only that role's pending slot and keep all other roles pending. The existing full-clear behavior remains for relay sequences, parallel action queues, courtroom actions, and unrelated failures. This keeps failure-first arrival from collapsing the visual round.

### D7. Scope is exactly `@all`

Only `@all` creates the provisional capture and grouped round. Directed single-role and existing multi-role mentions continue to render as individual messages; fanout-looking legacy events with no resolvable human key also remain flat.

## Risks / Trade-offs

- [The asynchronous endpoint does not return a human event ID] → Capture before send, match the first unseen same-content human event for the single active chat job, and use durable `in_response_to_event_id` after binding.
- [A duplicate instruction or event arrives during correlation] → Use the pre-send event-ID set, capture order, and the backend's one-running-job guard; if ambiguity remains, refuse to group rather than mis-bind.
- [The first response arrives before the human event is observed] → Keep the provisional capture alive and merge the response after the human event binds; if the key cannot be resolved, retain flat fallback instead of guessing.
- [An expected role never emits an event] → Use the post-run `activity_status !== running` signal to mark it unknown and clear its thinking state; never claim a full completion label.
- [Reconnect loses the expected set] → Rebuild from durable events and show only known members; no over-counting or permanent pending placeholder.
- [Existing selectors break inside a new wrapper] → Keep every arrived bubble's `workspace-message`, event ID, role attribute, quote control, and filter behavior unchanged; add public round test IDs.

## Migration Plan

1. Add pure round/feed-item projection helpers and unit tests first.
2. Add send-time capture/correlation and failure handling, then render the pre-event and in-stream group.
3. Run focused frontend tests, build, and chatroom Playwright tests; no backend or data migration is run.
4. Rollback is code-only. Existing events remain valid and fall back to flat arrival-order rendering when the grouping key or session capture is unavailable.

## Open Questions

- None for Gate A. The `@all` expected roster and terminal settlement rules are fixed above; multi-role grouping is explicitly out of scope.

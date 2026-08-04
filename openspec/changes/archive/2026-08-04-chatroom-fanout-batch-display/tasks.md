## 1. Projection contract and round derivation

- [x] 1.1 Add `in_response_to_event_id?: string` and explicit round/feed-item types to the workspace projection, including stable/provisional IDs, expected roles, member state, progress, and terminal status.
- [x] 1.2 Implement a pure helper that groups only resolvable `chat-fanout-*` events for the same human event, preserves append order, and leaves unknown-key events flat.
- [x] 1.3 Add a projection path for a pending `@all` round with zero response messages, all expected roles, `0/N` progress, and bottom-of-feed placement; keep arrived bubbles as distinct `workspace-message` items.
- [x] 1.4 Implement fixed expected-set progress, failure/unknown/terminal states, reconnect degradation, and the capture-to-human-event reconciliation seam in unit-testable helpers.

## 2. @all capture and pending-state lifecycle

- [x] 2.1 Add a session-local `@all` capture before `sendChatMention` runs, storing meeting ID, exact instruction, pre-send event IDs, capture time, and the participant-role expected set; expose it to `projectMeetingWorkspace` immediately.
- [x] 2.2 In the WebSocket event handler, bind the oldest unresolved capture to the first unseen matching `human-message` event and then use that event ID as the only durable grouping key; discard the capture and restore the queue when the request fails.
- [x] 2.3 On WebSocket disconnect/reconnect, clear provisional capture state and rebuild from durable events with arrived-members-only degradation; ensure no client-only placeholder remains pending forever.
- [x] 2.4 When activity status settles away from `running`, mark expected roles without completed/failed events as `unknown`, remove their thinking indicators, and show a partial/unknown terminal label.

## 3. Simultaneous thinking and failure semantics

- [x] 3.1 Update chatroom role projection so every unresolved expected `@all` member is `thinking` simultaneously in the pre-event and in-stream phases; relay/parallel/courtroom queue behavior remains unchanged.
- [x] 3.2 Update `applyPendingRoleUpdates` so a failed event belonging to a chatroom `chat-fanout-*` round removes only that role's pending slot; retain the current full-clear behavior for other modes/actions.
- [x] 3.3 Verify completed, failed, and unknown roles settle independently and that failure-first arrival cannot extinguish other members' thinking state.

## 4. Conversation rendering

- [x] 4.1 Render a public `fanout-round` container even when it has no arrived messages, with a `fanout-round-header` and one placeholder per expected role.
- [x] 4.2 Fill arrived member bubbles in append order before unresolved placeholders; preserve each bubble's existing avatar/name/time, role filter, quote control, `workspace-message` test ID, and event identity.
- [x] 4.3 Render live `0/N` and `x/N` progress plus completion/partial/unknown terminal labels; add stable test IDs for the round and header.
- [x] 4.4 Keep single-role, multi-role, ordinary chat, relay, parallel, courtroom, and attachment rendering unchanged.

## 5. Tests and verification

- [x] 5.1 Add frontend unit tests for zero-event pre-render, capture correlation, fixed denominator, arrival order, unresolved key fallback, single/multi mention flat behavior, and per-member identity.
- [x] 5.2 Add deterministic transition tests for pre-event `0/N` → in-stream `x/N` → terminal, including failure-first, missing-member unknown settlement, request failure rollback, and reconnect degradation.
- [x] 5.3 Extend Playwright chatroom coverage to assert the fanout round/header and simultaneous pending placeholders are visible before the first response, then verify arrival-order fill and existing 13.4/13.7/13.22 selectors.
- [x] 5.4 Run `npm run test:unit`, `npm run build`, and the relevant chatroom Playwright suite; confirm no backend or event-log files changed.

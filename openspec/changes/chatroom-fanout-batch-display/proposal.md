## Why

Human Owner validation showed that chatroom `@all` responses are executed in parallel, but the frontend presents only one active thinking bubble and only creates a visual grouping after response events arrive. The first completed response therefore looks like a sequential relay, and the remaining roles do not appear to be working concurrently.

## What Changes

- Render one chatroom `@all` request as a visual fanout round with a group header, all expected-role placeholders visible before the first AI event, and member bubbles that fill in as responses arrive.
- Keep completed members in event arrival order, with pending placeholders below the arrived responses; each member remains an independent message for quoting, filtering, and selectors.
- Capture the client-side expected member set before the asynchronous request, correlate it to the later human event, and define reconnect, request-failure, and terminal-settlement behavior without changing the backend event schema.
- Clear only the failed member's pending state so other `@all` roles continue to display thinking until their own terminal event.
- Scope the new grouping to `@all`; directed single-role and existing multi-role mentions remain flat, as do relay, parallel, courtroom, and historical fallback presentations.

## Capabilities

### New Capabilities

- `fanout-round-display`: Groups one chatroom `@all` fanout into a pre-event and in-stream visual round with simultaneous thinking indicators, live progress, arrival-order member bubbles, and safe terminal/reconnect behavior.

### Modified Capabilities

- `conversation-workspace`: the "Chatroom message display" requirement changes to include a pending `@all` round container and its in-stream member presentation while preserving flat non-`@all` chat.

## Impact

- `frontend/src/meetingWorkspace.ts`: expose a public fanout-round/feed-item projection that can represent a round with zero response messages, correlate arrived events, and derive progress/status.
- `frontend/src/composables/useCouncil.ts`: capture `@all` expected roles before sending, bind the capture to the later human event, expose pending-round state, and clear only a failed fanout member.
- `frontend/src/components/ConversationWorkspace.vue`: render the pending and in-stream round container, placeholders, header, and member bubbles while preserving existing message selectors.
- Frontend unit and Playwright coverage for pre-event, arrival, failure-first, terminal unknown, reconnect degradation, and non-`@all` fallback.
- No backend, `events.jsonl`, `models.yaml`, or `modes.yaml` changes; no historical migration.

# fanout-round-display Specification

## Purpose
When a chatroom Human sends `@all`, the backend invokes the participant roles in parallel but appends response events in completion order. This capability presents that request as one visual round from the pre-event waiting state through terminal settlement, while preserving arrival order and individual message identity.
## Requirements
### Requirement: @all fanout round grouping

A chatroom `@all` request SHALL project as one visual fanout round. Arrived members SHALL be selected only from events whose `step_id` begins with `chat-fanout-` and whose `in_response_to_event_id` resolves to the triggering `human-message` event in the same meeting. Events without a resolvable grouping key SHALL render as individual messages in arrival order. Directed single-role and existing multi-role mentions SHALL remain flat.

#### Scenario: @all responses group into one round

- **WHEN** the Human sends `@all 大家覺得呢？` and four participant roles respond
- **THEN** the feed shows one fanout round containing four distinct response bubbles
- **AND** the member bubbles appear in the order their events were appended

#### Scenario: Legacy fanout event without grouping key stays flat

- **WHEN** a fanout event has no `in_response_to_event_id` or its reference cannot be resolved
- **THEN** that message renders as an individual message in arrival order
- **AND** it is not placed in a guessed or provisional group

#### Scenario: Non-@all mention stays flat

- **WHEN** the Human sends a directed single-role or existing multi-role mention
- **THEN** each resulting response renders as an individual message
- **AND** no `@all` fanout group is created

### Requirement: Pre-event pending round is independently renderable

Immediately after an `@all` request is accepted, before any `chat-fanout-*` response event exists, the conversation projection SHALL expose a pending fanout round item independent of `WorkspaceMessage` count. The item SHALL contain the captured expected participant set, a live `0/N` header, and one pending placeholder for every expected role, and SHALL be rendered at the bottom of the feed. The placeholders SHALL not be counted as persisted messages.

#### Scenario: All roles appear before the first response

- **WHEN** an `@all` request for four participant roles has been sent and zero AI response events have arrived
- **THEN** the feed contains one fanout round container with a `0/4`-style pending header
- **AND** all four roles have visible pending/thinking placeholders inside that container

#### Scenario: Pre-event round does not fabricate messages

- **WHEN** the pending round has no response events yet
- **THEN** the persisted workspace message count remains unchanged
- **AND** the round header/placeholders are presentational items only

### Requirement: Capture is correlated to the durable human event

The frontend SHALL capture the `@all` expected role set before sending the asynchronous request, then bind the provisional round to the first unseen matching human-message event for that request. Once bound, only response events whose `in_response_to_event_id` equals that human event ID SHALL fill the round. A failed request SHALL discard the provisional round and restore the prior pending state. A lost session capture SHALL degrade to the durable arrived-event projection rather than guessing a human-event association.

#### Scenario: Human event binds the pending round

- **WHEN** the request's WebSocket stream emits a new human-message event after the client captured the `@all` instruction
- **THEN** the provisional round keeps its expected role set and adopts that human event ID as its durable key
- **AND** later matching fanout events fill the same round

#### Scenario: Failed request does not leave an orphan round

- **WHEN** the asynchronous `@all` request fails before a human event is observed
- **THEN** the provisional round and its placeholders are removed
- **AND** the pending role state returns to its pre-send value

### Requirement: Header progress uses a fixed expected set

Each `@all` round SHALL display a header showing responded count versus its expected participant count (`0/N`, `2/N`, and a terminal label). N SHALL be captured before response arrival and SHALL NOT grow as members complete. A completed member increments the responded count; a failed member advances settlement but is not counted as a completed response. If the capture is lost, N SHALL degrade to the roles observed in durable events and SHALL NOT over-count.

#### Scenario: In-stream header keeps its denominator

- **WHEN** two of four expected roles have completed
- **THEN** the header shows `2/4` (or equivalent)
- **AND** a later response does not change the denominator to the number already observed

#### Scenario: Failed role advances partial settlement

- **WHEN** one expected role fails and the remaining roles complete
- **THEN** the round reaches a terminal partial state
- **AND** the failed role is not counted as a completed response

### Requirement: Simultaneous placeholders and independent role settlement

During a pending `@all` round, every expected role without its own completed or failed event SHALL show a thinking placeholder simultaneously. Arrived completed response bubbles SHALL be rendered before still-pending placeholders, in arrival order. A role's placeholder SHALL clear only when that role's own completed/failed event arrives, or when the round receives its terminal activity-status settlement signal and that role is marked `unknown`. A failed role SHALL not clear other roles' placeholders.

#### Scenario: All pending roles think at once

- **WHEN** `@all` is sent and no role has responded yet
- **THEN** every expected role shows a thinking placeholder inside the same fanout round

#### Scenario: Completed role stops independently

- **WHEN** role A completes while roles B and C are still pending
- **THEN** A's response bubble appears first in the round's arrived section
- **AND** B and C continue showing thinking placeholders below it

#### Scenario: Failure-first does not collapse the round

- **WHEN** role A fails before roles B and C respond
- **THEN** A is shown as failed and no longer thinking
- **AND** B and C continue showing thinking placeholders until their own events or terminal settlement

### Requirement: Terminal settlement clears unknown placeholders

When the meeting event stream reports an activity status other than `running` after the correlated `@all` human event, the round SHALL settle. Any expected role without a completed/failed event SHALL be marked `unknown`, SHALL stop showing a thinking placeholder, and SHALL prevent the UI from claiming that all expected roles responded. A disconnected/reloaded client SHALL rebuild only from durable events and SHALL not leave a client-only placeholder pending forever.

#### Scenario: Missing member becomes unknown at settlement

- **WHEN** the fanout job settles and one expected role emitted no terminal event
- **THEN** that role is marked unknown and its thinking placeholder is removed
- **AND** the header shows a partial/unknown terminal label rather than full completion

#### Scenario: Reconnect degrades safely

- **WHEN** the WebSocket disconnects before the capture is bound and reconnect later reloads durable events
- **THEN** only durable arrived members are projected
- **AND** no missing member is invented or kept pending indefinitely

### Requirement: Member bubbles preserve per-message identity

Grouping SHALL NOT alter an arrived member's identity or message count. Each response bubble inside a round SHALL retain its own `event_id`, `workspace-message` test ID, role attribute, quote control, and role-filter behavior. The group header and placeholders SHALL not count as workspace messages.

#### Scenario: Message count unchanged by grouping

- **WHEN** one `@all` round has one human message and four response events
- **THEN** the feed still contains five `workspace-message` elements
- **AND** the fanout wrapper/header/placeholders add no persisted message elements

#### Scenario: Per-role selectors remain available

- **WHEN** a response is rendered inside a fanout round
- **THEN** its role-specific selector and quote action work exactly as before

### Requirement: Sequential-mode compatibility

The grouping SHALL apply only to chatroom `@all` rounds with a matching human event. Ordinary human messages, directed single-role and multi-role responses, relay/parallel messages, courtroom messages, and attachment events SHALL render exactly as they do today.

#### Scenario: Directed response is not grouped

- **WHEN** the Human sends `@Advisor 你覺得呢？`
- **THEN** Advisor's response renders as an individual message
- **AND** no fanout round header appears

#### Scenario: Non-chatroom modes are unaffected

- **WHEN** a relay or parallel meeting renders its feed
- **THEN** no chatroom fanout round appears
- **AND** the existing presentation remains unchanged

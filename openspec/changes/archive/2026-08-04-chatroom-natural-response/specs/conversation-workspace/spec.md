# conversation-workspace Delta Specification

## MODIFIED Requirements

### Requirement: Chatroom message display

Chatroom messages SHALL be displayed in the same time-ordered feed as other conversation modes. Human messages, AI responses, and system messages use the same visual format. A new chatroom AI response using `chat-message/v1` SHALL display its parsed `message` directly, without synthesizing formal report sections from parsed fields. Historical chatroom events without the new schema SHALL remain readable through deterministic read-time fallback, with no event rewrite. A chatroom `@all` request SHALL render one fanout round before the first response, with all expected-role placeholders and a fixed denominator shown as `0/N`; each arrived member SHALL remain a distinct bubble appended inside that round in events append/arrival order, while unresolved placeholders remain below arrived members. Pending roles SHALL think simultaneously. Failure, unknown, terminal settlement, and disconnect/reconnect degradation SHALL preserve the round's defined partial-state behavior. Directed single-role and existing multi-role mentions SHALL remain flat individual messages without a fanout wrapper. Formal schemas and non-chatroom modes SHALL remain unchanged.

#### Scenario: Natural chat response displays directly

- **WHEN** a chatroom AI event has `output_schema_id: "chat-message/v1"` and a parsed `message`
- **THEN** the message feed displays that message text directly
- **AND** the bubble does not display generated 摘要、論點、風險、或建議處置 headings

#### Scenario: Legacy chatroom response remains readable

- **WHEN** a historical chatroom AI event has no `chat-message/v1` message field
- **THEN** the feed uses the existing deterministic fallback for that event
- **AND** no historical event is rewritten

#### Scenario: Pending @all round is visible before responses

- **WHEN** `@all` is sent and no AI response event has arrived
- **THEN** the feed shows one fanout round and all expected roles' thinking placeholders together
- **AND** the header shows `0/N` using the fixed expected-role denominator

#### Scenario: Fanout messages display in arrival order

- **WHEN** `@all` is sent and responses arrive in order B, A, C
- **THEN** the message feed shows B's response first, then A, then C inside the same round
- **AND** each arrived response remains a distinct member bubble
- **AND** roles still pending appear below the arrived responses

#### Scenario: Thinking indicator for pending fanout

- **WHEN** `@all` is sent and only A has responded
- **THEN** B and every other unresolved expected role show thinking indicators simultaneously inside the fanout round
- **AND** the natural-message projection does not remove or suppress those pending indicators

#### Scenario: Failure-first fanout keeps other roles pending

- **WHEN** role A fails before roles B and C respond
- **THEN** A is shown as failed and no longer thinking
- **AND** B and C continue showing thinking placeholders until their own events or terminal settlement

#### Scenario: Terminal settlement marks missing members unknown

- **WHEN** the fanout job settles and an expected role emitted no completed or failed event
- **THEN** that role is marked unknown and its thinking placeholder is removed
- **AND** the header shows a partial/unknown terminal label rather than claiming all expected roles responded

#### Scenario: Reconnect degrades to durable fanout members

- **WHEN** the WebSocket disconnects before the round capture is bound and reconnect later reloads durable events
- **THEN** only durable arrived members are projected
- **AND** no missing member is invented or kept pending indefinitely

#### Scenario: Non-@all chat remains flat

- **WHEN** a directed single-role or existing multi-role mention is sent
- **THEN** its response renders as an individual message without a fanout round wrapper

#### Scenario: Formal contracts remain unchanged

- **WHEN** a relay, parallel, brainstorm, courtroom, or formal response is rendered
- **THEN** its existing schema and presentation are preserved

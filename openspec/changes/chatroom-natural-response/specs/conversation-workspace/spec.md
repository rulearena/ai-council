# conversation-workspace Delta Specification

## MODIFIED Requirements

### Requirement: Chatroom message display

Chatroom messages SHALL be displayed in the same time-ordered feed as other conversation modes. Human messages, AI responses, and system messages use the same visual format. A new chatroom AI response using `chat-message/v1` SHALL display its parsed `message` directly, without synthesizing formal report sections from parsed fields. Historical chatroom events without the new schema SHALL remain readable through the existing fallback. AI responses from `@all` fanout SHALL be displayed in arrival order (the order they were appended to events.jsonl), not in participant list order.

#### Scenario: Natural chat response displays directly

- **WHEN** a chatroom AI event has `output_schema_id: "chat-message/v1"` and a parsed `message`
- **THEN** the message feed displays that message text directly
- **AND** the bubble does not display generated 摘要、論點、風險、或建議處置 headings

#### Scenario: Legacy chatroom response remains readable

- **WHEN** a historical chatroom AI event has no `chat-message/v1` message field
- **THEN** the feed uses the existing deterministic fallback for that event
- **AND** no historical event is rewritten

#### Scenario: Fanout messages display in arrival order

- **WHEN** `@all` is sent and responses arrive in order B, A, C
- **THEN** the message feed shows B's response first, then A, then C

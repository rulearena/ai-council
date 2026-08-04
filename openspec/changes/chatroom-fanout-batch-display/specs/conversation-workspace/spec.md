# conversation-workspace Delta Spec

## MODIFIED Requirements

### Requirement: Chatroom message display

Chatroom messages SHALL be displayed in the same time-ordered feed as other conversation modes. Human messages, AI responses, and system messages use the same visual format. A chatroom `@all` request SHALL render a single fanout round item that exists before the first response, shows all expected-role thinking placeholders, and fills arrived member bubbles in the order they were appended to events.jsonl. Each arrived AI response remains a distinct message. Directed single-role and existing multi-role responses SHALL remain individual messages, not grouped.

#### Scenario: Pending @all round is visible before responses

- **WHEN** `@all` is sent and no AI response event has arrived
- **THEN** the feed shows one fanout round header and all expected roles' thinking placeholders together

#### Scenario: Fanout messages display in arrival order

- **WHEN** `@all` is sent and responses arrive in order B, A, C
- **THEN** the message feed shows B's response first, then A's, then C's inside the same round
- **AND** roles still pending appear below the arrived responses

#### Scenario: Thinking indicator for pending fanout

- **WHEN** `@all` is sent and only A has responded
- **THEN** B and every other unresolved expected role show thinking indicators simultaneously inside the fanout round

#### Scenario: Non-@all chat remains flat

- **WHEN** a directed single-role or existing multi-role mention is sent
- **THEN** its response renders as an individual message without a fanout round wrapper

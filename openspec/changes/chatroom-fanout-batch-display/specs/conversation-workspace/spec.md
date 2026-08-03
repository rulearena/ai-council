# conversation-workspace Delta Spec

## MODIFIED Requirements

### Requirement: Chatroom message display
Chatroom messages SHALL be displayed in the same time-ordered feed as other conversation modes. Human messages, AI responses, and system messages use the same visual format. AI responses from @all fanout SHALL be displayed in arrival order (the order they were appended to events.jsonl), not in participant list order, and SHALL be rendered as a single grouped fanout round per the `fanout-round-display` capability (round header with live progress, simultaneous thinking indicators, member bubbles filling in as each completes).

#### Scenario: Fanout messages display in arrival order
- **WHEN** @all is sent and responses arrive in order B, A, C
- **THEN** the message feed shows B's response first, then A's, then C's, all inside the same fanout round group

#### Scenario: Thinking indicator for pending fanout
- **WHEN** @all is sent and only A has responded
- **THEN** every role that has not yet responded shows a thinking indicator at the same time, and the round header shows live progress

# chatroom-mode Delta Specification

## MODIFIED Requirements

### Requirement: Concise response policy

Chatroom mode responses SHALL default to concise, conversational length and SHALL use the dedicated `chat-message/v1` output contract for directed and `@all` responses. The `message` field SHALL contain the complete natural reply rather than a formal report envelope. This SHALL be controlled by the `chatroom_response` prompt template, which instructs the role to respond briefly and naturally while preserving visible evidence anchors when relevant. The system SHALL NOT truncate already-generated text; length control happens at the prompt level, not post-generation.

#### Scenario: Prompt instructs concise natural response

- **WHEN** a role is invoked in chatroom mode
- **THEN** the rendered prompt includes the `chatroom_response` template and the `chat-message/v1` schema
- **AND** it instructs a brief conversational reply without formal report headings

#### Scenario: Chatroom response uses message field

- **WHEN** a role completes a directed or `@all` chatroom response
- **THEN** the parsed output contains the complete reply in `message`
- **AND** the response is not required to contain `summary`, `arguments`, `risks`, or `recommendation`

#### Scenario: No post-generation truncation

- **WHEN** a role generates a longer-than-expected response
- **THEN** the full `message` text is saved to events.jsonl and displayed without truncation

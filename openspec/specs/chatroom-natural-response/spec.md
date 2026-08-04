# chatroom-natural-response Specification

## Purpose
TBD - created by archiving change chatroom-natural-response. Update Purpose after archive.
## Requirements
### Requirement: Dedicated chat message output contract

Every newly generated directed or `@all` fanout response in chatroom mode SHALL use the registered `chat-message/v1` output schema. The parsed output SHALL contain a non-blank string field named `message`, which is the complete user-facing reply. The chat-message schema SHALL NOT require report sections such as `summary`, `arguments`, `risks`, or `recommendation`.

#### Scenario: Directed response uses the chat message schema

- **WHEN** a Human sends a valid single-role mention in a chatroom
- **THEN** the resulting completed AI event has `output_schema_id: "chat-message/v1"`
- **AND** its `parsed_output.message` is a non-blank string

#### Scenario: Fanout response uses the chat message schema

- **WHEN** a Human sends `@all` in a chatroom and a role completes
- **THEN** that role's completed event has `output_schema_id: "chat-message/v1"`
- **AND** its parsed output does not require formal report fields

#### Scenario: Invalid chat message is rejected

- **WHEN** the model returns a non-object, omits `message`, or returns a blank `message`
- **THEN** the existing parse-error/retry/failure path records the raw output and failure diagnostics
- **AND** no completed chatroom response with an invalid parsed message is appended

### Requirement: Natural conversational generation

The chatroom response prompt SHALL instruct the role to answer in the meeting's language with a few concise, natural sentences, without formal report headings or a report-shaped structure. When the response refers to visible case materials, the prompt SHALL allow the role to preserve the existing citation anchor text such as `[附件一]`. The system SHALL NOT truncate a generated message after the model responds.

#### Scenario: Prompt requests an ordinary chat reply

- **WHEN** a directed or `@all` chatroom response is rendered
- **THEN** the prompt identifies `message` as the complete reply
- **AND** it instructs the role not to produce 摘要、論點、風險、建議處置 headings or a lengthy formal report

#### Scenario: Evidence anchor remains in message text

- **WHEN** a role refers to a visible attachment using `[附件一]`
- **THEN** the parsed `message` and displayed chat bubble retain `[附件一]`

### Requirement: Chatroom event preserves diagnostics

A chatroom response event SHALL preserve the raw model output, parsed output when parsing succeeds, `output_schema_id`, `output_schema_hash`, prompt messages and template metadata, and the existing model, timing, token-usage, and failure diagnostics. The user-facing message projection SHALL NOT discard or overwrite those audit fields.

#### Scenario: Completed event retains audit fields

- **WHEN** a chatroom role response completes successfully
- **THEN** the event contains `raw_output`, `parsed_output`, `output_schema_id`, `output_schema_hash`, and prompt metadata
- **AND** the display text is derived from `parsed_output.message`

#### Scenario: Failed event retains raw failure evidence

- **WHEN** a chatroom response fails parsing or model execution
- **THEN** the failed event retains its raw output when available, prompt metadata, failure kind, error, and retry state
- **AND** no formal report-shaped placeholder is synthesized for the failed response

### Requirement: Historical chatroom events remain read-compatible

The system SHALL read historical chatroom events without rewriting or backfilling their JSONL records. For a new `chat-message/v1` event, the conversation projection SHALL display `parsed_output.message` directly. For a legacy event without that contract, the projection SHALL retain the existing deterministic fallback using `content`, legacy parsed fields, or raw output. Formal-mode events SHALL continue to use their existing structured projections.

#### Scenario: Existing event log is not migrated

- **WHEN** the application starts after this change with historical chatroom events
- **THEN** the historical event lines remain byte-for-byte unchanged
- **AND** the events remain available in the meeting records

#### Scenario: Legacy structured chatroom event can still render

- **WHEN** a historical chatroom AI event has `role-output/v1` parsed fields but no `message` field
- **THEN** the conversation projection renders it through the legacy fallback
- **AND** opening a formal meeting continues to render its existing structured output

#### Scenario: New message event renders without report formatting

- **WHEN** a chatroom event has `output_schema_id: "chat-message/v1"` and `parsed_output.message: "我會先驗證市場需求。"`
- **THEN** the chat bubble displays `我會先驗證市場需求。`
- **AND** it does not synthesize 摘要、論點、風險、或建議處置 sections

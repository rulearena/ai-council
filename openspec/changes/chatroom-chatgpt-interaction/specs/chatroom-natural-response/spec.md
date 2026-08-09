## ADDED Requirements

### Requirement: Chatroom prompt uses layered messages
Every chatroom `ModelRequest` SHALL contain exactly three canonical pre-transport messages in this order: `system` for fixed role identity/backend Persona/language/hard rules; `developer` for product routing, context, and output-contract rules; and `user` for the current instruction plus the context available in that implementation slice. Its compatibility `prompt` SHALL be the deterministic labeled flattening `SYSTEM\n{system}\n\nDEVELOPER\n{developer}\n\nUSER\n{user}`. Slice 2 user/context SHALL contain only current instruction, quote, and recent transcript; Slice 3 MAY add the frozen selected-source excerpts; Slice 4 MAY add shared summary. User-authored Persona is out of scope and SHALL NOT enter system/developer through this change.

Adapter capability SHALL be owned only by adapter code. `supports_developer_role` SHALL default to false and SHALL NOT appear in `ModelConfig`, meetings, or user settings. OpenAI-compatible true mode sends system/developer/user natively; false mode sends a deterministic system+developer merge followed by user. Anthropic sends the same merge in top-level `system` and one user message. Gemini's code-owned `supports_system_instruction` defaults true and sends `{systemInstruction:{parts:[{text:merge}]},contents:[{role:"user",parts:[{text:user}]}]}`; false sends `{contents:[{role:"user",parts:[{text:flattened_prompt}]}]}` without `systemInstruction`. CLI consumes only the labeled flattening; mock exposes both forms for tests. When canonical messages are absent, all adapters SHALL preserve their existing legacy single-prompt payload.

Every chatroom attempt event that carries prompt diagnostics SHALL persist `prompt_messages` as the exact canonical three-message list before provider mapping, including completed, adapter-failure, parse/schema-failure, and automatic-retry events. Provider merges SHALL NOT change that audit. Non-chatroom events SHALL retain their existing single `user` audit message.

#### Scenario: System layer carries role identity
- **WHEN** Critic is invoked in chatroom mode
- **THEN** the request has a system-level role identity and Critic Persona
- **AND** the user's message is not used to redefine the hard Persona rules

#### Scenario: User layer carries selected material
- **WHEN** a user sends a message with a quote and one `#` source token
- **THEN** the user/context layer contains the current instruction, quote, and bounded selected attachment excerpts
- **AND** no unselected attachment body is included

#### Scenario: Single-prompt adapter remains deterministic
- **WHEN** a model adapter does not support separated message roles
- **THEN** the layers are flattened in a documented stable order
- **AND** the same layer content and output schema remain available to the model

#### Scenario: Audit is provider-independent
- **WHEN** the same frozen chatroom request is sent through native and fallback adapters
- **THEN** both attempt events record byte-identical ordered `prompt_messages` with roles system, developer, user
- **AND** their provider-specific payload mapping is not substituted into the audit

#### Scenario: Non-chatroom adapter path is unchanged
- **WHEN** a relay, parallel, courtroom, or other non-chatroom call is made
- **THEN** canonical messages are absent and its provider payload retains the legacy single-prompt form
- **AND** its event audit remains one synthetic `user` message

### Requirement: Chatroom responses expose structured source citations
Slice 2 SHALL keep registered `chat-message/v1` limited to the required non-blank string `message`. Slice 3 SHALL then add the optional `attachment_refs` array together with the selected-source snapshot that authorizes it. If the response uses a concrete fact from a selected source, the Slice-3 prompt/output contract SHALL require `attachment_refs`; every item SHALL be exactly `{source_ref: string, label: string, segment_refs: string[]}`, with values validated only against the frozen invocation snapshot. Generic chat MAY omit the array. A wrong label, unknown segment, or source absent from the snapshot SHALL follow existing output parse/semantic failure behavior; deletion after the snapshot is frozen does not replace or retroactively invalidate it. The natural message SHALL not be required to contain fixed citation anchor text.

#### Scenario: Slice 2 remains message-only
- **WHEN** layered prompting is implemented before selected-source retrieval
- **THEN** `chat-message/v1` still requires only a non-blank `message`
- **AND** no attachment citation validation depends on an unavailable source allow-list

#### Scenario: Response with source citation validates
- **WHEN** a model returns a message and an `attachment_refs` entry for a selected `.md` file
- **THEN** the output passes chat-message validation with `{source_ref, label, segment_refs}`
- **AND** the event preserves the structured reference beside the message

#### Scenario: Invalid source citation fails validation
- **WHEN** a model returns an `attachment_refs` entry for an unselected or deleted file
- **THEN** the output is rejected or sanitized according to the existing parse-failure path
- **AND** no completed event claims the invalid source

#### Scenario: Free-form message does not need legacy anchors
- **WHEN** a role gives a natural response based on selected material
- **THEN** the message can remain ordinary prose without `[附件一]`
- **AND** the source relationship is represented by `attachment_refs` when applicable

## MODIFIED Requirements

### Requirement: Natural conversational generation
The chatroom response prompt SHALL instruct the role to answer in the meeting's language with a natural, adaptive reply. Simple questions SHALL receive a direct brief answer; complex questions SHALL receive enough explanation to be useful. The prompt SHALL permit Markdown lists, emphasis, short headings, or code blocks when they improve clarity, SHALL prohibit fixed report-shaped headings such as 摘要、論點、風險、建議處置 unless the user explicitly asks for that format, and SHALL not force a fixed sentence count. Attachment source relationships SHALL use structured `attachment_refs` rather than mandatory `[附件一]` text. The system SHALL NOT truncate a generated message after the model responds.

#### Scenario: Prompt requests an ordinary chat reply
- **WHEN** a directed or `@all` chatroom response is rendered
- **THEN** the prompt identifies `message` as the complete reply
- **AND** it asks for a direct natural response without a fixed report template

#### Scenario: Complex answer can use useful Markdown
- **WHEN** a role receives a multi-part design or decision question
- **THEN** the role can organize the answer with concise Markdown
- **AND** the response remains a chat message rather than a mandatory formal report

#### Scenario: Evidence citation is not a text anchor requirement
- **WHEN** a role uses a concrete fact from a selected source
- **THEN** the prompt requires a structured allow-listed attachment reference
- **AND** the parsed message is not required to contain `[附件一]`

#### Scenario: No post-generation truncation
- **WHEN** a role generates a longer valid response
- **THEN** the full `message` text is saved and displayed
- **AND** no fixed character or sentence truncation is applied

## ADDED Requirements

### Requirement: Chatroom prompt uses layered messages
The chatroom model request SHALL represent prompt layers separately: a system layer for role identity, Persona, language, and hard safety/format rules; a developer layer for chatroom routing, context-budget, citation, and output-contract instructions; and a user/context layer for the current human instruction, shared summary, quoted event, recent transcript, and explicitly selected attachment excerpts. The transport SHALL preserve these layers for providers that support system/developer messages and SHALL use a deterministic compatibility flattening for providers that accept only one prompt string.

#### Scenario: System layer carries role identity
- **WHEN** Critic is invoked in chatroom mode
- **THEN** the request has a system-level role identity and Critic Persona
- **AND** the user's message is not used to redefine the hard Persona rules

#### Scenario: User layer carries selected material
- **WHEN** a user sends a message with a quote and one `#` attachment reference
- **THEN** the user/context layer contains the current instruction, quote, and bounded selected attachment excerpts
- **AND** no unselected attachment body is included

#### Scenario: Single-prompt adapter remains deterministic
- **WHEN** a model adapter does not support separated message roles
- **THEN** the layers are flattened in a documented stable order
- **AND** the same layer content and output schema remain available to the model

### Requirement: Chatroom responses expose structured attachment references
The registered `chat-message/v1` contract SHALL retain a non-blank string `message` and SHALL support an optional `attachment_refs` array. If the response uses a concrete fact from a selected source, the prompt and output contract SHALL require `attachment_refs`; every item SHALL be exactly `{source_ref: string, label: string, segment_refs: string[]}`, with `source_ref` in the current selected allow-list, `label` exactly equal to the server projection label, and every `segment_ref` in the request's retrieved `available_segment_refs`; at least one valid segment ref SHALL be present. Generic chat MAY omit the array. Unknown label/segment/deleted source SHALL fail existing output parse/semantic validation. The natural message SHALL not be required to contain fixed citation anchor text.

#### Scenario: Response with attachment references validates
- **WHEN** a model returns a message and an `attachment_refs` entry for a selected `.md` file
- **THEN** the output passes chat-message validation with `{source_ref, label, segment_refs}`
- **AND** the event preserves the structured reference beside the message

#### Scenario: Invalid attachment reference fails validation
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

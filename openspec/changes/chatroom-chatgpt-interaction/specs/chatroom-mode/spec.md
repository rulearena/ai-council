## ADDED Requirements

### Requirement: Chatroom has a fixed Host role
The chatroom mode SHALL expose one fixed role with stable internal ID `host` and display name 「主持 AI」. The Host SHALL be available in the active chatroom participant projection, SHALL have a model assignment through the existing meeting model mechanism, and SHALL be included when the `all` role chip is resolved. The Host SHALL be a chatroom role only; other modes SHALL not gain this role through this change.

#### Scenario: Chatroom participant projection includes Host
- **WHEN** the chatroom mode catalog or an open chatroom meeting is projected
- **THEN** one participant has `role_id: "host"` and display name 「主持 AI」
- **AND** its model assignment is resolved like other chatroom roles

#### Scenario: all chip includes Host
- **WHEN** a human sends the `all` role chip in a chatroom
- **THEN** the Host is one of the expected fanout roles
- **AND** the Host receives the same frozen pre-send context as the other targeted roles

### Requirement: Chatroom roles use explicit Personas
Each chatroom role SHALL have a stable Persona containing its working perspective and hard behavioral rules. The Host Persona SHALL direct, clarify, and organize; Advisor SHALL offer practical options; Critic SHALL challenge assumptions and surface risks; Strategist SHALL prioritize trade-offs and next steps; Analyst SHALL distinguish evidence, data, and uncertainty. Persona instructions SHALL not require the role to announce its role or use a fixed report template.

#### Scenario: Persona changes working perspective
- **WHEN** the same user question is sent to Critic and Strategist
- **THEN** each prompt contains its corresponding Persona
- **AND** the response contract does not require identical report sections

#### Scenario: Persona is not a visible role announcement
- **WHEN** a role generates a chat response
- **THEN** the role may answer in its natural voice
- **AND** the prompt does not require a prefix such as "我是評論者"

## MODIFIED Requirements

### Requirement: Chatroom mode definition
The system SHALL define a `chatroom` mode category in `config/modes.yaml` alongside existing `relay` and `parallel` categories. The chatroom mode SHALL declare the fixed `host` role and its configurable member roles, SHALL NOT declare `steps`, `fanout`, or `synthesis` sections, and SHALL include `id: chatroom`, display name, tagline, when_to_use guidance, and `default_scene: meeting-room`.

#### Scenario: Mode catalog loads chatroom with Host
- **WHEN** `GET /modes` is called
- **THEN** the response includes a mode with `id: "chatroom"` and `category: "chatroom"`
- **AND** its role definitions include stable role ID `host`

#### Scenario: Mode catalog validates chatroom structure
- **WHEN** `modes.yaml` is parsed by `ModeCatalogRepository`
- **THEN** the chatroom mode validates successfully with the Host and member roles
- **AND** it has no steps, fanout, or synthesis sections

### Requirement: Human-message-only semantics
A human message sent to a chatroom meeting without any role chip SHALL be saved as a human event and SHALL invoke the fixed Host role with the same instruction. A message containing a hand-typed role-like token or stale role chip SHALL be rejected before any AI invocation; the composer input and references SHALL remain available for correction. The `all` chip SHALL take precedence over other chips and SHALL be resolved independently of unrelated invalid role-like tokens.

#### Scenario: Plain text routes to Host
- **WHEN** a human sends "大家覺得怎麼樣？" to a chatroom meeting with no @mention
- **THEN** a human event is appended to `events.jsonl`
- **AND** exactly the Host role is invoked

#### Scenario: Mention-only message still activates
- **WHEN** a human sends an Advisor chip with no additional instruction
- **THEN** a human event is saved
- **AND** Advisor is invoked with the empty-after-mention instruction and may ask a clarifying question

#### Scenario: Invalid normal mention blocks execution
- **WHEN** a human sends `@NonExistent 請回答` and `NonExistent` is not an active role ID
- **THEN** the request returns a validation error before any AI job starts
- **AND** no AI response event is appended
- **AND** the composer content and invalid mention remain available for correction

#### Scenario: all chip has routing precedence
- **WHEN** a human sends the `all` chip plus a hand-typed `@NonExistent` token
- **THEN** the request resolves to all active chatroom roles once each
- **AND** the invalid token does not cause a second invocation or a Host fallback

### Requirement: Directed single-role response
When a human message contains one or more valid role chips other than the `all` chip, the system SHALL invoke exactly the selected role set through the chatroom-specific response contract. One role SHALL use the directed path; two or more roles SHALL use parallel fanout semantics. The chip SHALL resolve to a stable `role_id` from the active meeting participant projection, including `host`, and SHALL NOT use free-text display-name matching.

#### Scenario: Host chip triggers Host only
- **WHEN** a human sends an `@主持 AI` chip with `請整理目前共識`
- **THEN** only the Host responds
- **AND** the response uses the chatroom-specific `chat-message/v1` contract

#### Scenario: Two explicit roles receive one request each
- **WHEN** a human sends Advisor and Critic display-name chips with `請比較這個方案`
- **THEN** Advisor and Critic are invoked in parallel
- **AND** no other role, including Host, is invoked

#### Scenario: Display name is not a route
- **WHEN** a human sends `@顧問 請回答` while the stable role ID is `Advisor`
- **THEN** the mention is invalid
- **AND** no AI role is invoked

### Requirement: @all parallel frozen-context fanout
When a human message contains the `all` role chip, the system SHALL invoke every active chatroom role, including Host, exactly once in parallel. Each role SHALL receive the same pre-send transcript, shared-summary, quoted-message, and selected-source snapshot. Roles SHALL NOT read each other's outputs from the same fanout round. Responses SHALL persist and display in arrival order, with existing pending, partial-success, failure, and terminal-settlement behavior preserved.

#### Scenario: all chip triggers Host and active roles
- **WHEN** a human sends the `all` chip with `大家覺得呢？` to a chatroom with Host and 3 member roles
- **THEN** all 4 roles are invoked concurrently
- **AND** each role receives the same frozen context snapshot

#### Scenario: Arrival-order persistence remains stable
- **WHEN** roles finish in order Critic, Host, Advisor, then Analyst
- **THEN** completed events are appended and displayed in that arrival order
- **AND** the pending placeholders remain for roles that have not completed

#### Scenario: Duplicate mentions are invoked once
- **WHEN** a human sends the `all` chip plus duplicate Advisor chips with `請回答`
- **THEN** Advisor is invoked once as part of the all-role set
- **AND** no duplicate response event is scheduled for Advisor

### Requirement: Chatroom mode has no auto-start or step sequence
The chatroom mode SHALL NOT have an auto-start behavior. Pressing "start meeting" in chatroom mode SHALL NOT trigger an automated AI sequence. After a meeting is idle, a plain human message SHALL invoke Host, while explicit role chips and the `all` chip SHALL invoke only their resolved target set.

#### Scenario: Start chatroom meeting does not invoke AI
- **WHEN** the user starts a chatroom meeting
- **THEN** no AI roles are invoked
- **AND** the meeting enters idle state immediately

#### Scenario: Plain message is the default turn
- **WHEN** the user sends ordinary text after the meeting is idle
- **THEN** the message is persisted
- **AND** Host is invoked without requiring a separate start action

### Requirement: Deterministic context/token-budget policy
Each AI call in chatroom mode SHALL assemble context in this order: system and developer instructions; the current human message; the current shared-summary revision when available; a quoted message identified by event ID; recent published transcript events; and content retrieved only from explicitly selected readable attachments. The context SHALL use a deterministic token budget configurable per meeting (default from `AI_COUNCIL_CHATROOM_CONTEXT_TOKEN_BUDGET`, default 4096), SHALL remain within one meeting, and SHALL preserve required current/quote/summary blocks by evicting older transcript material first. Attachment retrieval SHALL be bounded by the remaining budget and SHALL NOT silently claim that omitted content was read.

#### Scenario: Context includes current and quoted messages
- **WHEN** a role responds to a message that quotes an earlier message
- **THEN** the prompt includes the current message and the quoted message when the quoted event belongs to the meeting
- **AND** the quoted block is not replaced by an unrelated attachment

#### Scenario: Context includes shared summary when present
- **WHEN** a current summary revision exists and the token budget is constrained
- **THEN** the prompt includes that summary revision before older transcript events
- **AND** older transcript events are evicted before the current message or summary

#### Scenario: No attachment is read without #
- **WHEN** a chatroom message contains no source token
- **THEN** no attachment body is retrieved or injected into the prompt
- **AND** the prompt does not infer an attachment from natural-language wording

#### Scenario: Context does not cross meeting boundaries
- **WHEN** a chatroom meeting is open
- **THEN** the context for any AI call contains only events, summary, quotes, and attachments belonging to that meeting

### Requirement: Concise response policy
Chatroom responses SHALL use the dedicated `chat-message/v1` output contract and SHALL adapt their length to the user's request and the complexity of the question. Simple questions SHALL be answered briefly; complex questions SHALL receive enough explanation to be useful. The response MAY use Markdown lists, emphasis, short headings, or code blocks when they improve clarity, but SHALL NOT be forced into 摘要、論點、風險、建議處置 or another fixed report template. The system SHALL NOT truncate already-generated text; length control happens in the prompt and model settings.

#### Scenario: Simple question receives a direct reply
- **WHEN** a role receives a simple factual or conversational question
- **THEN** the generated message is direct and brief
- **AND** it does not contain fixed report headings

#### Scenario: Complex question receives sufficient explanation
- **WHEN** a role receives a multi-part decision question
- **THEN** the generated message can use adaptive detail and useful Markdown
- **AND** the complete `message` text is persisted and displayed

#### Scenario: No post-generation truncation
- **WHEN** a role generates a response longer than the default conversational length
- **THEN** the full valid `message` is saved to `events.jsonl`
- **AND** the system does not cut it to a fixed sentence or character count

### Requirement: Case files remain compatible
Chatroom meetings SHALL retain the existing case-material storage, deletion, download, reader, and historical event contracts. Case-material body content SHALL NOT be injected into a chatroom prompt merely because it is attached to the meeting. Only explicitly selected, active, AI-readable attachments SHALL contribute bounded content through the `#` reference contract. Binary and unsupported material SHALL remain available for its existing UI behavior but SHALL remain absent from prompt body content.

#### Scenario: Existing case material remains stored
- **WHEN** a chatroom meeting is created with case files or receives an upload
- **THEN** the files remain represented by the existing versioned storage and attachment events
- **AND** the material can still be managed and downloaded through the existing UI

#### Scenario: Unselected case material is not injected
- **WHEN** a chatroom meeting has active `.txt` and `.md` attachments but the message contains no `#` reference
- **THEN** neither attachment body is included in the AI prompt
- **AND** the role is not told that it read those attachments

#### Scenario: Unsupported selected file is not read
- **WHEN** a user attempts to select a PDF or image with `#`
- **THEN** the file remains downloadable/previewable according to the existing attachment UI
- **AND** the AI request is blocked because the file is not prompt-readable

### Requirement: Chatroom context panel omits formal process indicators
The chatroom right context panel SHALL continue to omit relay, parallel, and courtroom process indicators. The shared-summary content, status, update, and feed-separation contract is defined by the `conversation-workspace` and `chatroom-memory` capabilities.

#### Scenario: Chatroom panel has no formal progress
- **WHEN** a chatroom meeting is open
- **THEN** the workspace does not display step progress, synthesis progress, or courtroom actions
- **AND** the dedicated memory/workspace projection owns summary presentation

#### Scenario: Summary panel does not create a message
- **WHEN** a new summary revision is published
- **THEN** the dedicated memory/workspace projection updates summary presentation
- **AND** the time-ordered message feed does not gain a synthetic AI bubble

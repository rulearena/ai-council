# chatroom-mode Specification

## Purpose

The `chatroom` mode is a third execution category alongside `relay` and `parallel`: a free-form meeting type with no fixed rounds, no mandatory AI goal, and no process progress indicators. AI roles respond only when explicitly mentioned via `@role` or `@all`. The mode is defined in `config/modes.yaml` and rendered in the mode picker as the first option.
## Requirements
### Requirement: Chatroom mode definition
The system SHALL define a `chatroom` mode category in `config/modes.yaml` alongside existing `relay` and `parallel` categories. The chatroom mode SHALL declare roles with `kind: member`, SHALL NOT declare `steps`, `fanout`, or `synthesis` sections. The mode definition SHALL include `id: chatroom`, display name, tagline, when_to_use guidance, and a `default_scene: meeting-room`.

#### Scenario: Mode catalog loads chatroom
- **WHEN** `GET /modes` is called
- **THEN** the response includes a mode with `id: "chatroom"` and `category: "chatroom"`

#### Scenario: Mode catalog validates chatroom structure
- **WHEN** `modes.yaml` is parsed by `ModeCatalogRepository`
- **THEN** the chatroom mode validates successfully with roles but no steps/fanout/synthesis

### Requirement: ModeCatalogRepository accepts chatroom category
`ModeCatalogRepository` SHALL accept `"chatroom"` as a valid `category` value alongside `"relay"` and `"parallel"`. The `VALID_CATEGORIES` set in `modes.py` SHALL include `"chatroom"`.

#### Scenario: Validation passes for chatroom category
- **WHEN** a mode definition has `category: chatroom`
- **THEN** `ModeCatalogRepository.list_modes()` includes it without error

### Requirement: Chatroom meeting creation requires only title
`POST /meetings` with `mode_id: "chatroom"` SHALL require only `title` (non-empty string). The `goal` field SHALL be optional; when omitted, the meeting is created with an empty goal. The endpoint SHALL NOT return 409 or any error for goal-less chatroom meetings.

#### Scenario: Create chatroom with title only
- **WHEN** `POST /meetings` is called with `mode_id: "chatroom"`, `title: "產品討論"`, no `goal`, and valid participants
- **THEN** a meeting is created with `goal: ""` and the response includes the meeting ID

#### Scenario: Create chatroom with optional goal
- **WHEN** `POST /meetings` is called with `mode_id: "chatroom"`, `title: "產品討論"`, `goal: "討論新功能設計"`, and valid participants
- **THEN** the meeting is created with the provided goal

#### Scenario: Create chatroom with empty title rejected
- **WHEN** `POST /meetings` is called with `mode_id: "chatroom"` and `title: ""`
- **THEN** the response is 422 with a validation error on the `title` field

### Requirement: Meeting metadata stores chatroom goal as optional
The meeting metadata `goal` field SHALL remain present in the JSON structure for backward compatibility. For chatroom meetings where no goal is provided, `goal` SHALL be stored as an empty string `""`. This empty goal SHALL NOT be injected into role prompts.

#### Scenario: Goal empty string not injected
- **WHEN** a chatroom meeting has `goal: ""`
- **THEN** the rendered prompt for any role SHALL NOT contain an empty goal string

### Requirement: Human-message-only semantics
A human message sent to a chatroom meeting without a valid mention SHALL be saved as a `human-message` event only. The system SHALL NOT invoke any AI role for messages that contain no `@role` or `@all` mention.

#### Scenario: Plain text message saves without AI
- **WHEN** a human sends "大家覺得怎麼樣？" to a chatroom meeting with no @mention
- **THEN** a `human-message` event is appended to `events.jsonl`
- **AND** no AI role is invoked

#### Scenario: Message with only whitespace mention saves without AI
- **WHEN** a human sends "@ " (at sign followed by space) to a chatroom meeting
- **THEN** a `human-message` event is appended
- **AND** no AI role is invoked

### Requirement: Directed single-role response
When a human message contains a valid `@role` mention (single role), the system SHALL invoke that specific role to respond. The invocation SHALL use the existing `respond_as_role()` backend contract with the `directed_role_response` template. The mention SHALL be resolved to a stable `role_id` from the meeting's participant list, not by free-text name matching.

#### Scenario: @role triggers single AI response
- **WHEN** a human sends "@藍軍 你覺得這個方案怎麼樣？" to a chatroom meeting
- **THEN** a `human-directed-message` event is appended with the instruction text
- **AND** the Blue role responds using the `directed_role_response` template
- **AND** the step_id follows the pattern `chat-directed-{seq}-blue-response`

#### Scenario: Unknown @role saves as human message only
- **WHEN** a human sends "@未知角色 你好" and "未知角色" does not match any participant role_id
- **THEN** a `human-message` event is appended
- **AND** no AI role is invoked

### Requirement: @all parallel frozen-context fanout
When a human message contains `@all`, the system SHALL invoke all participant roles in parallel. Each role SHALL receive the same pre-send transcript snapshot (frozen context). Roles SHALL NOT read each other's outputs from the same fanout round.

#### Scenario: @all triggers all roles in parallel
- **WHEN** a human sends "@all 大家覺得呢？" to a chatroom with 3 roles
- **THEN** all 3 roles are invoked concurrently
- **AND** each role receives the same transcript snapshot from before the message was sent

#### Scenario: Arrival-order persistence
- **WHEN** 3 roles respond to @all and role B finishes first, then role A, then role C
- **THEN** events are appended in the order: B's response, A's response, C's response
- **AND** the display order matches the append order

#### Scenario: Partial success
- **WHEN** @all is sent and role A succeeds, role B fails, role C succeeds
- **THEN** role A and role C responses are appended and displayed
- **AND** role B's failure is recorded as a failed event
- **AND** the user sees role B as failed, not hidden

#### Scenario: Single-role failure does not block others
- **WHEN** @all is sent and role A completes first, role B is still pending
- **THEN** role A's response is immediately visible and persisted
- **AND** role B's status shows as "thinking" until it completes or fails

### Requirement: Chatroom mode has no auto-start or step sequence
The chatroom mode SHALL NOT have an auto-start behavior. Pressing "start meeting" in chatroom mode SHALL NOT trigger any automated AI sequence. The system SHALL only respond when explicitly mentioned via `@role` or `@all`.

#### Scenario: Start chatroom meeting does not invoke AI
- **WHEN** the user starts a chatroom meeting
- **THEN** no AI roles are invoked
- **AND** the meeting enters idle state immediately

### Requirement: Deterministic context/token-budget policy
Each AI call in chatroom mode SHALL assemble context according to a deterministic policy:
1. The current human message (the one triggering the response)
2. Any quoted/referenced message identified by event_id
3. System and role-specific prompt instructions
4. Recent history: most recent N messages that fit within the token budget, selected by reverse chronological order from the transcript

The token budget SHALL be configurable per chatroom meeting (default from environment variable `AI_COUNCIL_CHATROOM_CONTEXT_TOKEN_BUDGET`, default 4096). When the budget is exceeded, the system SHALL silently drop oldest messages that don't fall into categories 1-3. The system SHALL NOT mix context from different meetings.

#### Scenario: Context includes current and quoted messages
- **WHEN** role responds to a message that quotes an earlier message
- **THEN** the prompt includes the current message and the quoted message

#### Scenario: Context respects token budget
- **WHEN** the transcript has 50 messages but the budget fits only the 10 most recent
- **THEN** the prompt includes the current message, the quoted message (if any), system instructions, and the 10 most recent messages

#### Scenario: Context does not cross meeting boundaries
- **WHEN** a chatroom meeting is open
- **THEN** the context for any AI call contains only events from that meeting

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

### Requirement: Chatroom mode does not display process indicators
The frontend SHALL NOT display court CTA buttons, 正式流程按鈕, "開始新回合" buttons, step progress indicators, or synthesis status for chatroom meetings. The right context panel SHALL omit goal display when goal is empty, and SHALL NOT show parallel progress or relay step progress.

#### Scenario: No step progress bar in chatroom
- **WHEN** a chatroom meeting is open
- **THEN** the workspace does not display "第 N 步 / 共 M 步" or equivalent

#### Scenario: No court CTA in chatroom
- **WHEN** a chatroom meeting is open
- **THEN** no courtroom action buttons are visible

### Requirement: Chatroom event schema
Chatroom mode events SHALL use the existing `events.jsonl` schema. Human messages use `type: "human-message"`. Directed responses use `type: "ai-response"` with step_id `chat-directed-{seq}-{role}-response`. @all fanout responses use `type: "ai-response"` with step_id `chat-fanout-{timestamp_ms}-{role}`. Failed responses use `type: "ai-response"` with `status: "failed"`. All events SHALL include the standard `meeting_id`, `role`, `created_at`, `status`, and `content` fields.

#### Scenario: Directed response event structure
- **WHEN** a role responds to a @role mention
- **THEN** the event has `step_id: "chat-directed-1-blue-response"` (or incremented seq)
- **AND** the event has `role: "Blue"`, `status: "completed"`, `content` with the response

#### Scenario: Fanout response event structure
- **WHEN** a role responds to @all
- **THEN** the event has `step_id: "chat-fanout-{timestamp_ms}-{role_id}"`
- **AND** the event has the correct `role` and `status`

### Requirement: Case files remain compatible
Chatroom meetings MAY have case files attached using the existing versioned case-file contract. The `POST /meetings` case_files field and the existing case_files.json storage SHALL work unchanged for chatroom mode. Case file content SHALL be injected into role prompts via the `{{ case_files }}` template variable, same as other modes.

#### Scenario: Attach case files to chatroom
- **WHEN** a chatroom meeting is created with case_files
- **THEN** the case files are stored in case_files.json
- **AND** subsequent role responses include case file content in their prompt

### Requirement: No historical data mutation
Creating, operating, or deleting chatroom meetings SHALL NOT modify, rewrite, or backfill events, metadata, or data of any existing meeting of any mode type.

#### Scenario: Existing meetings unaffected
- **WHEN** a new chatroom meeting is created
- **THEN** all existing meetings' events.jsonl, metadata, and case_files.json remain byte-identical

### Requirement: No API key in frontend
The chatroom mode frontend SHALL NOT store, transmit, or log API keys. All model configuration is resolved server-side. The frontend only displays model config IDs and display names.

#### Scenario: API key never reaches frontend
- **WHEN** a chatroom meeting invokes AI roles
- **THEN** no API key value appears in any HTTP response body, WebSocket message, or frontend state

### Requirement: Chatroom mode is presented first in the mode picker
The new-meeting mode picker SHALL present the `chatroom` mode as its first option, ahead of `red-blue`, `courtroom`, `debate`, `brainstorm`, `six-hats`, and `persona-testing`.

#### Scenario: Chatroom listed first
- **WHEN** the new-meeting mode picker is opened
- **THEN** `chatroom` is the first mode shown in the list

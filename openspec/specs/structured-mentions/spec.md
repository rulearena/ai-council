# structured-mentions Specification

## Purpose

Structured mentions are the interaction contract that lets a chatroom Human drive the conversation: `@role_id` and `@all` syntax parsed from message text, an autocomplete menu in the chatroom composer, resolution to stable participant role IDs (never free-text name matching), quote-inline referencing by event_id, and the integration contract with the backend directed-response and parallel-fanout paths.

## Requirements

### Requirement: Mention syntax definition
The system SHALL recognize two mention syntaxes in human messages:
- `@role_id` — a single-role mention where `role_id` matches a stable participant role identifier (e.g., `@Blue`, `@Judge`)
- `@all` — a special keyword that mentions all participant roles simultaneously

Mentions SHALL be parsed from the message text at send time. The `@` symbol followed by a valid role_id or `all` constitutes a mention; `@` in other contexts (e.g., email addresses) SHALL NOT be treated as a mention.

#### Scenario: Single role mention parsed
- **WHEN** a message contains "@Blue 你怎麼看？"
- **THEN** the system identifies a mention of role_id "Blue"

#### Scenario: @all keyword parsed
- **WHEN** a message contains "@all 大家覺得呢？"
- **THEN** the system identifies an @all mention

#### Scenario: @ at email not treated as mention
- **WHEN** a message contains "contact@example.com"
- **THEN** no mention is identified

#### Scenario: @ with invalid role saved as human message
- **WHEN** a message contains "@NonExistent 觀點"
- **AND** "NonExistent" does not match any participant role_id
- **THEN** the message is saved as a `human-message` event without AI invocation

### Requirement: Mention autocomplete in composer
The frontend composer SHALL provide an autocomplete/selection menu when the user types `@` followed by characters. The menu SHALL list all participant roles from the current meeting's participant list, showing each role's display name and role_id. Selection SHALL insert the stable `role_id` into the message text, not the display name. The menu SHALL also include an `@all` option.

#### Scenario: Autocomplete shows participants
- **WHEN** the user types "@B" in the chatroom composer
- **THEN** the autocomplete menu shows "Blue" (matching role_id "Blue")

#### Scenario: Autocomplete inserts stable role_id
- **WHEN** the user selects "Blue" from the autocomplete menu
- **THEN** the composer text contains "@Blue " (with trailing space)

#### Scenario: @all appears in autocomplete
- **WHEN** the user types "@" in the chatroom composer
- **THEN** the autocomplete menu includes "@all — 邀請所有角色" as an option

#### Scenario: No autocomplete in non-chatroom modes
- **WHEN** the current meeting mode is not "chatroom"
- **THEN** the composer does not show mention autocomplete

### Requirement: Mention resolution to stable role_id
Mentions in the message text SHALL be resolved to stable role identifiers from the meeting's `participants` array. Resolution SHALL NOT rely on display name fuzzy matching or free-text role name interpretation. If the mentioned string does not exactly match a `role_id` in the participants list, it SHALL be treated as plain text (no AI invocation).

#### Scenario: Exact role_id match resolves
- **WHEN** the message contains "@Blue" and the meeting has a participant with `role_id: "Blue"`
- **THEN** the mention resolves to role "Blue"

#### Scenario: Case-sensitive resolution
- **WHEN** the message contains "@blue" and the meeting has a participant with `role_id: "Blue"`
- **THEN** the mention does NOT resolve (role_id matching is case-sensitive)

#### Scenario: Display name does not resolve
- **WHEN** the message contains "@藍軍" and the meeting has a participant with `role_id: "Blue"` and `display_name: "藍軍"`
- **THEN** the mention does NOT resolve as a valid mention (must use role_id "Blue")

### Requirement: Quote-inline referencing
The frontend SHALL support referencing an existing message by its event_id. When a user quotes a message, the resulting human message SHALL include a `quoted_event_id` field. The backend SHALL include the content of the quoted message in the context for any AI role responding to that message.

#### Scenario: Quote includes referenced message in context
- **WHEN** a human quotes message event_id "abc123" and asks a role to comment
- **THEN** the role's prompt context includes the content of event "abc123"

#### Scenario: Quote of non-existent event ignored gracefully
- **WHEN** a human quotes an event_id that does not exist in the meeting's events
- **THEN** the message is saved without the quote reference
- **AND** no error is returned

### Requirement: Composer mode adaptation for chatroom
The chatroom composer SHALL replace the current relay/parallel action dropdown (note/all/role-select) with a simpler interface:
- A text input area with mention autocomplete support
- A send button that always sends the typed message
- The mention parsing determines behavior: no mention = human message only; @role = directed response; @all = parallel fanout
- There SHALL NOT be a separate "記錄補充" / "請全體回應" / "請角色回答" dropdown

#### Scenario: Composer without action dropdown
- **WHEN** the meeting mode is "chatroom"
- **THEN** the composer does not show the chairman action dropdown

#### Scenario: Send without mention saves as human
- **WHEN** the user types "Hello" and clicks send in chatroom mode
- **THEN** a `human-message` event is appended

#### Scenario: Send with @role triggers directed response
- **WHEN** the user types "@Blue 看看這個" and clicks send
- **THEN** a directed response is triggered for the Blue role

### Requirement: Multiple mentions in single message
A single message MAY contain multiple `@role` mentions. When multiple roles are mentioned, each mentioned role SHALL be invoked independently (parallel fanout). The message SHALL be saved once as a human message, and each mentioned role SHALL receive a separate AI invocation with the same frozen context.

#### Scenario: Two roles mentioned
- **WHEN** a message contains "@Blue @Red 你們覺得呢？"
- **THEN** both Blue and Red are invoked in parallel
- **AND** each receives the same pre-send transcript snapshot

#### Scenario: Mix of @role and @all
- **WHEN** a message contains "@all @Blue 重點問你"
- **THEN** @all takes precedence (all roles including Blue are invoked once)

### Requirement: Mention autocomplete keyboard interaction
The mention autocomplete menu SHALL support keyboard navigation (arrow up/down to move, Enter/Tab to select, Escape to dismiss). Typing continues normally while the menu is open. Selecting an item inserts the role_id and closes the menu.

#### Scenario: Keyboard selection inserts role_id
- **WHEN** the autocomplete menu is open and the user presses ArrowDown then Enter
- **THEN** the selected role_id is inserted into the composer text

#### Scenario: Escape dismisses menu
- **WHEN** the autocomplete menu is open and the user presses Escape
- **THEN** the menu closes without inserting anything

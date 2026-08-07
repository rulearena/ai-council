## ADDED Requirements

### Requirement: Chatroom mention API has an explicit validation contract
`POST /meetings/{meeting_id}/chat/mention` SHALL accept `content: string`, `mentions: string[]`, ordered `source_refs: string[]`, and the existing optional `quote_event_id`. `mentions` SHALL contain normalized stable role IDs or the `all` sentinel; the backend SHALL re-parse `content` and reject stale or inconsistent normal-role metadata. `source_refs` SHALL be the only source authorization and SHALL use stable source IDs, never display labels. A successful request SHALL return HTTP `202` with `meeting_id`, `human_event_id`, `job_ids`, `target_role_ids`, `source_refs`, `warnings`, and `status: "accepted"`. Normal invalid mentions, invalid source references, or payload inconsistencies SHALL return HTTP `400` with a stable error code and field details, without creating a human event or AI job. A missing meeting SHALL return `404`, and a meeting that cannot accept chat input SHALL return `409`. `@all` with invalid extra role-like tokens SHALL still return `202` and include those ignored tokens in `warnings`.

#### Scenario: Direct API accepts a valid request
- **WHEN** the API receives valid `content`, stable `mentions`, and ordered valid `source_refs`
- **THEN** it returns `202` with the human event ID, target roles, jobs, sources, warnings, and accepted status
- **AND** the human event and AI jobs are created exactly once

#### Scenario: Invalid request has no side effects
- **WHEN** the API receives an invalid normal role or inaccessible source reference
- **THEN** it returns `400` with field-level validation details
- **AND** it creates neither a human event nor an AI job

#### Scenario: @all warning is observable
- **WHEN** the API receives `@all @NotARealRole` with a valid source list
- **THEN** it returns `202` for the all-role fanout
- **AND** the response warning list identifies `@NotARealRole` as ignored

### Requirement: Composer source chips are distinct from ordinary hashtags
The composer SHALL represent an attachment or evidence selection as a reference chip carrying its stable `source_ref` and display label. The backend SHALL use the ordered `source_refs` payload for authorization and SHALL not parse ordinary hashtags or infer a source from a filename/display label. Sources with identical display labels SHALL remain independently selectable and distinguishable by stable ID.

#### Scenario: Same-label sources remain unambiguous
- **WHEN** two sources are both labelled `需求說明.md`
- **THEN** the composer shows enough metadata to distinguish their chips
- **AND** the API receives the selected stable source ID rather than a filename

#### Scenario: Ordinary hashtag is not a source
- **WHEN** a user writes `#待確認` without selecting a source chip
- **THEN** it remains ordinary message text
- **AND** no source body is retrieved

### Requirement: Plain chatroom input defaults to Host
In chatroom mode, a human message with no valid `@role` or `@all` mention SHALL route to the fixed role ID `host`. The message SHALL still be persisted as a human event before the Host response job is started. This default SHALL apply only to chatroom mode.

#### Scenario: Ordinary text invokes Host
- **WHEN** the user sends `請幫我整理一下目前討論` without an @mention in chatroom mode
- **THEN** the human message is persisted
- **AND** exactly the `host` role is scheduled

#### Scenario: Non-chatroom plain text is unchanged
- **WHEN** the user sends text without a mention in a relay or parallel meeting
- **THEN** the existing non-chatroom composer behavior is used
- **AND** the chatroom Host routing rule is not applied

### Requirement: Mention routing and attachment references are independent
The composer and backend SHALL parse `@` role directives and `#` attachment references as separate token classes. `@` SHALL select responders; `#` SHALL select allowable attachment sources. A message SHALL be able to contain zero, one, or many tokens of either class without one class implicitly changing the other.

#### Scenario: Explicit role with selected attachment
- **WHEN** a user sends `@Critic 請檢查 #需求說明`
- **THEN** only Critic is selected as responder
- **AND** only the selected attachment is eligible as prompt material

#### Scenario: Attachment reference does not target a role
- **WHEN** a user sends `#需求說明 請摘要` without an @mention
- **THEN** Host is selected by the default routing rule
- **AND** the attachment reference is passed as source scope, not as a responder

#### Scenario: Role mention does not read attachments
- **WHEN** a user sends `@Critic 請回答` without a # reference
- **THEN** Critic is selected
- **AND** no attachment body is retrieved

### Requirement: Attachment reference autocomplete uses stable IDs
In chatroom mode, typing `#` followed by characters SHALL open an attachment autocomplete menu containing active attachments available in the current meeting. Each option SHALL show a human-readable display label and SHALL carry the stable attachment/file ID for submission. Selection SHALL insert a reference token associated with that stable ID, not an inferred filename lookup. Deleted, unavailable, and unsupported non-readable attachments SHALL be visibly marked and SHALL not be selectable as AI-readable sources.

#### Scenario: Attachment autocomplete shows readable material
- **WHEN** the user types `#需` in a chatroom composer
- **THEN** the menu shows matching active readable attachment labels
- **AND** each option has a stable attachment/file ID

#### Scenario: Selection keeps display label and stable ID
- **WHEN** the user selects an attachment named `需求說明.md`
- **THEN** the composer shows a readable `#` reference chip or token
- **AND** the send payload contains the selected stable attachment ID

#### Scenario: Unsupported attachment cannot be selected for AI
- **WHEN** the attachment menu contains a PDF or image
- **THEN** the item indicates that it is not AI-readable
- **AND** selecting it as an AI source is disabled

### Requirement: Multiple attachment references preserve selection order and deduplicate
A single chatroom message SHALL support multiple `#` attachment references. The frontend SHALL preserve first-selection order, and the backend SHALL deduplicate repeated stable IDs before retrieval. The same attachment SHALL contribute at most one source block to a request.

#### Scenario: Compare two selected attachments
- **WHEN** the user selects `#需求說明` and then `#競品分析`
- **THEN** both references are included in the send payload in that order
- **AND** the AI request can retrieve both sources

#### Scenario: Repeated attachment is sent once
- **WHEN** the user selects the same attachment twice
- **THEN** the UI may show one consolidated chip
- **AND** the backend sends at most one source block for that attachment ID

### Requirement: Composer teaches both routing controls
The chatroom composer SHALL provide visible, concise affordances that explain `@` role routing and `#` attachment selection. The empty or idle composer placeholder SHALL include the equivalent of `@指定 AI` and `#選取附件`, and the UI SHALL state that leaving out `@` sends to the Host. The affordance SHALL not appear as an instruction in the AI prompt.

#### Scenario: Idle composer displays controls
- **WHEN** a chatroom meeting is idle and the composer is empty
- **THEN** the composer shows guidance for `@` and `#`
- **AND** it explains that no @mention uses 主持 AI

#### Scenario: Guidance is not sent as user content
- **WHEN** the user sends a message after reading the composer hint
- **THEN** only the user's message and selected references are sent
- **AND** the hint text is not persisted as a human event

### Requirement: Invalid normal mentions fail before AI execution
At send time, every normal `@role` token SHALL resolve exactly to an active stable role ID or the request SHALL be rejected before any AI job starts. The backend SHALL not silently fall back to Host, ignore an invalid normal mention, or substitute a display-name match. `@all` SHALL be resolved first and SHALL take precedence over other role tokens; unrelated invalid role-like tokens in an `@all` message SHALL be ignored with a user-visible warning rather than creating extra jobs.

#### Scenario: Typo does not fall back to Host
- **WHEN** the user sends `@Adviser 請回答` and only `Advisor` is active
- **THEN** the send is rejected with a validation message
- **AND** neither Adviser nor Host is invoked

#### Scenario: Mixed valid and invalid normal roles are all rejected
- **WHEN** the user sends `@Advisor @Adviser 請比較`
- **THEN** the request is rejected before Advisor is invoked
- **AND** the composer retains the text for correction

#### Scenario: @all takes precedence with warning
- **WHEN** the user sends `@all @Adviser 請大家回答`
- **THEN** all active chatroom roles are invoked once
- **AND** the UI reports that the invalid extra token was ignored

### Requirement: Mention-only messages activate a response
A message containing only valid `@role` or `@all` tokens and no remaining instruction SHALL still activate the resolved role set. The role prompt SHALL receive an empty user instruction and may respond with a clarifying question. The system SHALL not treat a valid mention-only message as a human-only note.

#### Scenario: Mention-only directed request
- **WHEN** the user sends `@Advisor`
- **THEN** Advisor is invoked
- **AND** Advisor can ask what the user wants to discuss

#### Scenario: Mention-only all request
- **WHEN** the user sends `@all`
- **THEN** Host and all active member roles are invoked once
- **AND** the request is displayed as one fanout round under the existing fanout projection

## MODIFIED Requirements

### Requirement: Mention syntax definition
The system SHALL recognize two mention syntaxes in chatroom human messages:
- `@role_id` — a single-role mention where `role_id` matches a stable active participant role identifier, including `host`
- `@all` — a special keyword that mentions all active chatroom roles simultaneously

Mentions SHALL be parsed from message text at send time. The `@` symbol followed by a valid role_id or `all` constitutes a mention; `@` in other contexts such as email addresses SHALL NOT be treated as a mention. A normal role-like token that is not a valid active role ID SHALL be a send-time validation error rather than a silent human-only message. `@all` SHALL be resolved before normal role validation and SHALL take precedence over other role-like tokens.

#### Scenario: Single role mention parsed
- **WHEN** a message contains `@Advisor 你怎麼看？`
- **THEN** the system identifies a mention of stable role ID `Advisor`

#### Scenario: Host mention parsed
- **WHEN** a message contains `@host 請整理`
- **THEN** the system identifies a mention of stable role ID `host`

#### Scenario: @all keyword parsed
- **WHEN** a message contains `@all 大家覺得呢？`
- **THEN** the system identifies an @all mention

#### Scenario: @ at email is not treated as a mention
- **WHEN** a message contains `contact@example.com`
- **THEN** no mention is identified

#### Scenario: Invalid normal role blocks send
- **WHEN** a message contains `@NonExistent 觀點` and `NonExistent` is not an active role ID
- **THEN** the send is rejected before AI invocation
- **AND** the composer retains the message for correction

### Requirement: Mention resolution to stable role_id
Mentions in the message text SHALL be resolved to stable role identifiers from the active meeting participant projection. Resolution SHALL NOT rely on display-name fuzzy matching or free-text role-name interpretation. If a normal mentioned string does not exactly match a stable active `role_id`, the request SHALL fail validation before any AI invocation. The fixed Host role SHALL resolve through `role_id: "host"` when explicitly mentioned.

#### Scenario: Exact role_id match resolves
- **WHEN** the message contains `@Advisor` and the meeting has a participant with `role_id: "Advisor"`
- **THEN** the mention resolves to role `Advisor`

#### Scenario: Host stable ID resolves
- **WHEN** the message contains `@host` and the chatroom exposes the fixed Host role
- **THEN** the mention resolves to role `host`

#### Scenario: Case-sensitive resolution
- **WHEN** the message contains `@advisor` and the meeting has a participant with `role_id: "Advisor"`
- **THEN** the request fails validation
- **AND** no AI role is invoked

#### Scenario: Display name does not resolve
- **WHEN** the message contains `@顧問` and the meeting has `role_id: "Advisor"` with display name `顧問`
- **THEN** the request fails validation
- **AND** no AI role is invoked

### Requirement: Composer mode adaptation for chatroom
The chatroom composer SHALL replace the current relay/parallel action dropdown (note/all/role-select) with a simpler interface:
- A text input area with `@` role autocomplete and `#` attachment autocomplete
- A send button that always sends the typed message
- No `@` mention routes to Host; one valid `@role` routes to that role; multiple valid roles route in parallel; `@all` routes to all active roles including Host
- Invalid normal role mentions block the request before AI execution; `@all` takes precedence and reports ignored invalid extras
- There SHALL NOT be a separate "記錄補充" / "請全體回應" / "請角色回答" dropdown

#### Scenario: Composer without action dropdown
- **WHEN** the meeting mode is `chatroom`
- **THEN** the composer does not show the chairman action dropdown
- **AND** it shows `@` and `#` routing guidance

#### Scenario: Send without mention uses Host
- **WHEN** the user types `Hello` and clicks send in chatroom mode
- **THEN** a human event is appended
- **AND** a Host response is triggered

#### Scenario: Send with one role mention triggers directed response
- **WHEN** the user types `@Advisor 看看這個` and clicks send
- **THEN** only the Advisor response is triggered

#### Scenario: Invalid mention prevents execution
- **WHEN** the user types `@Unknown 看看這個` and clicks send
- **THEN** the request is rejected before an AI job starts
- **AND** the input remains editable

### Requirement: Multiple mentions in single message
A single message MAY contain multiple valid `@role` mentions. When multiple valid roles are mentioned, each mentioned role SHALL be invoked independently in parallel. The message SHALL be saved once as a human event, and each mentioned role SHALL receive a separate AI invocation with the same frozen context. `@all` SHALL take precedence over all valid role mentions and SHALL include Host exactly once.

#### Scenario: Two roles mentioned
- **WHEN** a message contains `@Advisor @Critic 你們覺得呢？`
- **THEN** both Advisor and Critic are invoked in parallel
- **AND** each receives the same pre-send transcript and summary snapshot

#### Scenario: Mix of @role and @all
- **WHEN** a message contains `@all @Advisor 重點問你`
- **THEN** Host and every active role are invoked once
- **AND** Advisor is not invoked a second time

#### Scenario: Duplicate role mentions are deduplicated
- **WHEN** a message contains `@Advisor @Advisor 請回答`
- **THEN** Advisor is invoked once
- **AND** the human message is persisted once

### Requirement: Mention autocomplete in composer
The frontend composer SHALL provide an autocomplete/selection menu when the user types `@` followed by characters. The menu SHALL list all active chatroom roles, including Host, showing each role's display name and stable role_id. Selection SHALL insert the stable role_id into the message text, not the display name. The menu SHALL also include an `@all` option. The same composer SHALL provide the separate `#` attachment autocomplete defined by this change.

#### Scenario: Autocomplete shows Host and participants
- **WHEN** the user types `@` in a chatroom composer
- **THEN** the autocomplete menu shows 「主持 AI」 with role_id `host` and the active member roles

#### Scenario: Host selection inserts stable ID
- **WHEN** the user selects 「主持 AI」 from autocomplete
- **THEN** the composer text contains `@host ` with a trailing space

#### Scenario: @all appears in autocomplete
- **WHEN** the user types `@` in a chatroom composer
- **THEN** the autocomplete menu includes `@all`

#### Scenario: No autocomplete in non-chatroom modes
- **WHEN** the current meeting mode is not `chatroom`
- **THEN** the composer does not show chatroom role or attachment autocomplete

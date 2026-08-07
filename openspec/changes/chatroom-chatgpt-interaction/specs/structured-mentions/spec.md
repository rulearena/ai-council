## ADDED Requirements

### Requirement: Chatroom mention API has an explicit validation contract
`POST /meetings/{meeting_id}/chat/mention` SHALL accept exactly `content:string`, `mentions:Array<{token_id:string,role_id:string,display_text:string,start:int,end:int}>`, `source_tokens:Array<{token_id:string,source_ref:string,display_text:string,start:int,end:int}>`, `source_refs:string[]`, and `quoted_event_id:string|null`. Offsets SHALL be Python/Unicode code-point half-open offsets; token IDs SHALL be unique within the request. For every token, the backend SHALL require bounds, non-overlap, the correct `@`/`#` prefix, and `content[start:end]` exactly equal to `display_text`. `role_id`/`source_ref` SHALL authorize; display text SHALL only provide integrity/display. `source_refs` SHALL equal first-appearance, deduplicated `source_tokens[].source_ref` values or fail `STALE_SOURCE_PAYLOAD`. Role chips SHALL display `@顧問`, `@主持 AI`, and `@全部角色`; stable IDs SHALL be hidden. A hand-typed uncovered role-like token SHALL be `INVALID_MENTION_TOKEN`; email and ordinary `@` text SHALL not be tokens. A successful request SHALL return exactly HTTP `202` body `{status:"accepted",meeting_id:string,target_role_ids:string[],source_refs:string[],warnings:Array<{code:"IGNORED_INVALID_MENTION",display_text:string}>}` and SHALL not promise job IDs. All other JSON/schema/field/type/unknown-field/blank-content/span/quote/source/role validation SHALL return exactly HTTP `400` `{status:"rejected",error:{code,field:string|null,details:Array<Detail>}}`. Codes SHALL include `INVALID_REQUEST_SCHEMA`, `INVALID_MENTION_TOKEN`, `STALE_MENTION_PAYLOAD`, `MENTION_TOKEN_MISMATCH`, `INVALID_SOURCE_REF`, `STALE_SOURCE_PAYLOAD`, `SOURCE_TOKEN_MISMATCH`, `SOURCE_NOT_VISIBLE_TO_TARGET`, and `SOURCE_NOT_READABLE`; each Detail SHALL contain only optional `token_id`, `role_id`, `display_text`, `source_ref`, `start`, and `end`. Unknown/malformed `quoted_event_id` SHALL be `INVALID_REQUEST_SCHEMA`; a well-typed missing quote event SHALL preserve graceful quote-ignore. Missing meeting SHALL return exactly HTTP `404` `{status:"rejected",error:{code:"MEETING_NOT_FOUND",field:null,details:[]}}`; a non-accepting meeting SHALL return exactly HTTP `409` `{status:"rejected",error:{code:"CHATROOM_NOT_ACCEPTING_INPUT",field:null,details:[]}}`. Every rejection SHALL happen before a human event or AI job exists.

Before offsets are generated, composer and backend SHALL NFC-normalize canonical content. If submitted content is not NFC (`content != NFC(content)`), the request SHALL return `400 INVALID_REQUEST_SCHEMA` with field `content`; the composer SHALL normalize first. All spans SHALL use Unicode code-point half-open `[start,end)` offsets, SHALL be in bounds and non-overlapping, and chip `display_text` SHALL exactly equal the content slice. An uncovered raw role-like candidate SHALL satisfy: `@` at start or preceded by neither Unicode `XID_Continue` nor `@`, `.`, `+`, `-`; followed by 1–64 Unicode `XID_Continue` code points (CJK letters, combining marks, decimal digits, underscore included); and followed by end or a non-`XID_Continue`/non-`-` code point. Hyphen is chip-only. Email-like local/domain patterns are ordinary text: a preceding local run of XID/`.`/`+`/`-` containing local text, or candidate followed by `.` plus an XID domain. Raw scanning SHALL skip verified chip spans, including display text with spaces such as `@主持 AI`. Uncovered `#` SHALL always remain ordinary hashtag/text and SHALL never authorize or invalidate a request.

The 400 union SHALL be closed and mapped exactly as follows:

| Input failure | Code | Field |
|---|---|---|
| missing/wrong/unknown field or type, blank/non-NFC content, malformed quote | `INVALID_REQUEST_SCHEMA` | `content`, `mentions`, `source_tokens`, `source_refs`, `quoted_event_id`, or `null` |
| duplicate mention token ID, mention span out of range/overlap/content mismatch, missing/invalid `@` prefix | `MENTION_TOKEN_MISMATCH` | `mentions` |
| inactive role or display text no longer matches active projection | `STALE_MENTION_PAYLOAD` | `mentions` |
| uncovered raw role-like candidate | `INVALID_MENTION_TOKEN` | `content` |
| duplicate source token ID, source span out of range/overlap/content mismatch, missing `#` prefix | `SOURCE_TOKEN_MISMATCH` | `source_tokens` |
| source refs differ from first-occurrence deduped source-token projection | `STALE_SOURCE_PAYLOAD` | `source_refs` |
| invalid source namespace/format/meeting membership/active state | `INVALID_SOURCE_REF` | `source_refs` |
| source not visible to target | `SOURCE_NOT_VISIBLE_TO_TARGET` | `source_refs` |
| source unsupported or unreadable | `SOURCE_NOT_READABLE` | `source_refs` |

Every 400 response SHALL be exactly `{status:"rejected",error:{code:one-of-table,field:string|null,details:Detail[]}}`; `Detail` SHALL contain only optional `token_id?:string`, `role_id?:string`, `display_text?:string`, `source_ref?:string`, `start?:integer`, and `end?:integer`, omitting non-applicable keys. No new 400 code is permitted without updating this table and its direct full-body tests.

#### Scenario: Direct API accepts a valid request
- **WHEN** the API receives valid content, non-overlapping chip spans, ordered source tokens, matching deduplicated source refs, and a well-typed quote ID
- **THEN** it returns exactly the accepted status, meeting ID, target roles, deduplicated source refs, and warnings
- **AND** the human event and AI jobs are created exactly once

#### Scenario: Invalid request has no side effects
- **WHEN** the API receives a missing/wrong field, blank content, unknown field, malformed quote, invalid span, stale payload, invalid role, or inaccessible source reference
- **THEN** it returns `400` with the exact rejected error envelope and field-level details
- **AND** it creates neither a human event nor an AI job

#### Scenario: all-chip warning is observable
- **WHEN** the API receives an `@全部角色` chip and an uncovered `@NotARealRole` token with valid source tokens
- **THEN** it returns `202` for the all-role fanout
- **AND** the response warning list contains exactly `{code: "IGNORED_INVALID_MENTION", display_text: "@NotARealRole"}`

### Requirement: Composer token spans are distinct from ordinary text
The composer SHALL represent each role/source selection as a chip with a unique `token_id`, display text, code-point `start`/`end` span, and hidden stable `role_id` or `source_ref`. The backend SHALL use role IDs/source refs for authorization and SHALL not infer them from display labels. Sources with identical labels SHALL remain independently selectable by token ID and hidden source ref. A hand-typed token with identical display text is not a chip and has no authorization.

#### Scenario: Same-label sources remain unambiguous
- **WHEN** two sources are both labelled `需求說明.md`
- **THEN** the composer shows enough metadata to distinguish their chips
- **AND** the API receives the selected stable `source_ref` rather than a filename

#### Scenario: Ordinary hashtag is not a source
- **WHEN** a user writes `#待確認` without selecting a source chip
- **THEN** it remains ordinary message text
- **AND** no source body is retrieved

### Requirement: Plain chatroom input defaults to Host
In chatroom mode, a human message with no role chip SHALL route to the fixed role ID `host`. The message SHALL still be persisted as a human event before the Host response job is started. This default SHALL apply only to chatroom mode.

#### Scenario: Ordinary text invokes Host
- **WHEN** the user sends `請幫我整理一下目前討論` without an @mention in chatroom mode
- **THEN** the human message is persisted
- **AND** exactly the `host` role is scheduled

#### Scenario: Non-chatroom plain text is unchanged
- **WHEN** the user sends text without a mention in a relay or parallel meeting
- **THEN** the existing non-chatroom composer behavior is used
- **AND** the chatroom Host routing rule is not applied

### Requirement: Role and source chips are independent
The composer and backend SHALL preserve role chips and `source_tokens` as separate token classes. Role chips SHALL select responders; source tokens SHALL select allowable sources. A message SHALL be able to contain zero, one, or many tokens of either class without one class implicitly changing the other.

#### Scenario: Explicit role with selected attachment
- **WHEN** a user sends a Critic chip (`{role_id: "Critic", display_text: "@評論者"}`) followed by `#需求說明`
- **THEN** only Critic is selected as responder
- **AND** only the selected attachment is eligible as prompt material

#### Scenario: Attachment reference does not target a role
- **WHEN** a user sends `#需求說明 請摘要` without an @mention
- **THEN** Host is selected by the default routing rule
- **AND** the source token is passed as source scope, not as a responder

#### Scenario: Role mention does not read attachments
- **WHEN** a user sends a Critic chip without a # reference
- **THEN** Critic is selected
- **AND** no attachment body is retrieved

### Requirement: Source autocomplete uses authoritative source refs
In chatroom mode, typing `#` followed by characters SHALL open a source autocomplete menu containing active chat-upload attachments and active evidence with non-empty string content available in the current meeting, excluding notes. Each option SHALL show a human-readable display label and SHALL carry its authoritative `source_ref` for submission. Selection SHALL insert a source token with a unique token ID and code-point span, not an inferred filename lookup. Deleted, unavailable, and unsupported non-readable sources SHALL be visibly marked and SHALL not be selectable as AI-readable sources; attachment readability remains limited to active `.txt`/`.md` blobs, while evidence has no extension requirement.

#### Scenario: Attachment autocomplete shows readable material
- **WHEN** the user types `#需` in a chatroom composer
- **THEN** the menu shows matching active readable attachment labels
- **AND** each option has a stable `source_ref`

#### Scenario: Selection keeps display label and stable ID
- **WHEN** the user selects an attachment named `需求說明.md`
- **THEN** the composer shows a readable `#` reference chip or token
- **AND** the send payload contains the selected stable `source_ref`

#### Scenario: Unsupported attachment cannot be selected for AI
- **WHEN** the attachment menu contains a PDF or image
- **THEN** the item indicates that it is not AI-readable
- **AND** selecting it as an AI source is disabled

### Requirement: Multiple source tokens preserve selection order and deduplicate
A single chatroom message SHALL support multiple `#` source chips. The frontend SHALL preserve first-selection order, and the backend SHALL deduplicate repeated `source_ref` values before retrieval. The same source SHALL contribute at most one source block to a request.

#### Scenario: Compare two selected attachments
- **WHEN** the user selects `#需求說明` and then `#競品分析`
- **THEN** both references are included in the send payload in that order
- **AND** the AI request can retrieve both sources

#### Scenario: Repeated attachment is sent once
- **WHEN** the user selects the same attachment twice
- **THEN** the UI may show one consolidated chip
- **AND** the backend sends at most one source block for that `source_ref`

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
At send time, every normal role chip SHALL resolve exactly to an active stable role ID or the request SHALL be rejected before any AI job starts. A hand-typed role-like token without a chip SHALL return `INVALID_MENTION_TOKEN`. The backend SHALL not silently fall back to Host, ignore an invalid normal chip, or substitute a display-name match. The `all` chip SHALL be resolved first and SHALL take precedence over other role chips; unrelated invalid role-like tokens in an `all` message SHALL be ignored with a user-visible warning rather than creating extra jobs.

#### Scenario: Typo does not fall back to Host
- **WHEN** the user sends `@Adviser 請回答` and only `Advisor` is active
- **THEN** the send is rejected with a validation message
- **AND** neither Adviser nor Host is invoked

#### Scenario: Mixed valid and invalid normal roles are all rejected
- **WHEN** the user sends valid Advisor and invalid hand-typed `@Adviser` tokens with `請比較`
- **THEN** the request is rejected before Advisor is invoked
- **AND** the composer retains the text for correction

#### Scenario: @all takes precedence with warning
- **WHEN** the user sends the `all` chip plus an invalid hand-typed `@Adviser` token
- **THEN** all active chatroom roles are invoked once
- **AND** the UI reports that the invalid extra token was ignored

### Requirement: Mention-only messages activate a response
A message containing only valid role chips and no remaining instruction SHALL still activate the resolved role set. The role prompt SHALL receive an empty user instruction and may respond with a clarifying question. The system SHALL not treat a valid chip-only message as a human-only note.

#### Scenario: Mention-only directed request
- **WHEN** the user sends a chip `{role_id: "Advisor", display_text: "@顧問"}`
- **THEN** Advisor is invoked
- **AND** Advisor can ask what the user wants to discuss

#### Scenario: Mention-only all request
- **WHEN** the user sends the `all` chip `{role_id: "all", display_text: "@全部角色"}`
- **THEN** Host and all active member roles are invoked once
- **AND** the request is displayed as one fanout round under the existing fanout projection

## MODIFIED Requirements

### Requirement: Mention syntax definition
The system SHALL recognize role reference chips in chatroom human messages. A chip SHALL carry a stable `role_id` for one active role, including `host`, or the `all` sentinel, and a display-only `display_text` such as `@顧問`, `@主持 AI`, or `@全部角色`. The user-visible content SHALL contain display text, never the stable IDs `@Advisor` or `@host`.

The backend SHALL validate the structured chip payload against the active projection. A hand-typed role-like `@` token without a corresponding chip SHALL return `INVALID_MENTION_TOKEN`; `@` in email addresses and ordinary non-role text SHALL not be treated as mentions. `all` SHALL be resolved before normal chip validation and SHALL take precedence over other role chips.

#### Scenario: Single role chip parsed
- **WHEN** a message contains an `@顧問` chip with hidden `role_id: "Advisor"` followed by `你怎麼看？`
- **THEN** the system identifies a chip for stable role ID `Advisor`

#### Scenario: Host chip parsed
- **WHEN** a message contains an `@主持 AI` chip with hidden `role_id: "host"` followed by `請整理`
- **THEN** the system identifies a chip for stable role ID `host`

#### Scenario: all chip parsed
- **WHEN** a message contains an `@全部角色` chip with hidden `role_id: "all"` followed by `大家覺得呢？`
- **THEN** the system identifies the all chip

#### Scenario: @ at email is not treated as a mention
- **WHEN** a message contains `contact@example.com`
- **THEN** no mention is identified

#### Scenario: Invalid normal role blocks send
- **WHEN** a message contains `@NonExistent 觀點` and `NonExistent` is not an active role ID
- **THEN** the send is rejected before AI invocation
- **AND** the composer retains the message for correction

### Requirement: Mention chip resolution to stable role_id
Mention chips SHALL be resolved to stable role identifiers from the active meeting participant projection. Resolution SHALL use only the hidden `role_id`; display text SHALL be checked for consistency but SHALL never authorize a different role. Display-name fuzzy matching and free-text role-name interpretation SHALL NOT be used. A stale role ID or inconsistent display text SHALL fail validation before any AI invocation. The fixed Host role SHALL resolve through `role_id: "host"` when explicitly selected.

#### Scenario: Exact role_id match resolves
- **WHEN** the message contains a chip with `role_id: "Advisor"` and display text `@顧問`
- **THEN** the mention resolves to role `Advisor`

#### Scenario: Host stable ID resolves
- **WHEN** the message contains a chip with `role_id: "host"` and display text `@主持 AI`
- **THEN** the mention resolves to role `host`

#### Scenario: Case-sensitive resolution
- **WHEN** the message contains a chip with stale `role_id: "advisor"` while only `Advisor` is active
- **THEN** the request fails validation
- **AND** no AI role is invoked

#### Scenario: Display name does not resolve
- **WHEN** the message contains a chip with `role_id: "Advisor"` but mismatched display text `@評論者`
- **THEN** the request fails validation
- **AND** no AI role is invoked

### Requirement: Composer mode adaptation for chatroom
The chatroom composer SHALL replace the current relay/parallel action dropdown (note/all/role-select) with a simpler interface:
- A text input area with display-name role-chip autocomplete and `#` source autocomplete
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
- **WHEN** the user selects an Advisor chip and types `看看這個`
- **THEN** only the Advisor response is triggered

#### Scenario: Invalid mention prevents execution
- **WHEN** the user types `@Unknown 看看這個` and clicks send
- **THEN** the request is rejected before an AI job starts
- **AND** the input remains editable

### Requirement: Multiple mentions in single message
A single message MAY contain multiple valid role chips. When multiple roles are selected, each role SHALL be invoked independently in parallel. The message SHALL be saved once as a human event, and each role SHALL receive a separate AI invocation with the same frozen context. The `all` chip SHALL take precedence over all valid role chips and SHALL include Host exactly once.

#### Scenario: Two roles mentioned
- **WHEN** a message contains Advisor and Critic display chips followed by `你們覺得呢？`
- **THEN** both Advisor and Critic are invoked in parallel
- **AND** each receives the same pre-send transcript and summary snapshot

#### Scenario: Mix of @role and @all
- **WHEN** a message contains the `all` chip plus an Advisor chip
- **THEN** Host and every active role are invoked once
- **AND** Advisor is not invoked a second time

#### Scenario: Duplicate role mentions are deduplicated
- **WHEN** a message contains the same Advisor chip twice followed by `請回答`
- **THEN** Advisor is invoked once
- **AND** the human message is persisted once

### Requirement: Mention autocomplete in composer
The frontend composer SHALL provide an autocomplete/selection menu when the user types `@` followed by characters. The menu SHALL list all active chatroom roles, including Host, and selection SHALL insert a display-name role chip with a hidden stable `role_id`. The menu SHALL include an `@全部角色` chip whose hidden ID is `all`. The composer SHALL never insert `@Advisor` or `@host` as user-visible text. The same composer SHALL provide the separate `#` source autocomplete defined by this change.

#### Scenario: Autocomplete shows Host and participants
- **WHEN** the user types `@` in a chatroom composer
- **THEN** the autocomplete menu shows 「主持 AI」 with role_id `host` and the active member roles

#### Scenario: Host selection inserts a display chip
- **WHEN** the user selects 「主持 AI」 from autocomplete
- **THEN** the composer shows an `@主持 AI` chip with hidden `role_id: "host"`
- **AND** the request mentions array contains `{role_id: "host", display_text: "@主持 AI"}`

#### Scenario: @all appears as a display chip
- **WHEN** the user types `@` in a chatroom composer
- **THEN** the autocomplete menu includes `@全部角色`
- **AND** selecting it creates a chip with hidden `role_id: "all"`

#### Scenario: No autocomplete in non-chatroom modes
- **WHEN** the current meeting mode is not `chatroom`
- **THEN** the composer does not show chatroom role or attachment autocomplete

## ADDED Requirements

### Requirement: Chatroom composer exposes @ and # controls
The chatroom composer SHALL visibly explain that `@` selects responding AI roles and `#` selects attachment sources. The idle placeholder or nearby helper text SHALL indicate that omitting `@` routes to 「主持 AI」. Typing `@` SHALL open role autocomplete and typing `#` SHALL open attachment autocomplete without changing the existing direct-upload `+` behavior.

#### Scenario: User can discover routing syntax
- **WHEN** a chatroom composer is opened with no draft
- **THEN** the UI shows guidance equivalent to `@指定 AI` and `#選取附件`
- **AND** it states that no @mention uses Host

#### Scenario: Role and attachment menus coexist
- **WHEN** the user selects an `@顧問` role chip and a `#需求說明` source chip in the same draft
- **THEN** the draft retains both reference classes
- **AND** the send payload contains structured role chips and `source_ref` tokens separately

#### Scenario: Existing upload entry point remains available
- **WHEN** the user clicks the composer `+` button
- **THEN** the resident file picker still opens immediately
- **AND** upload progress continues to appear in the materials tab

### Requirement: Attachment citations render as clickable chips
When a new chatroom response contains valid structured `attachment_refs`, the conversation feed SHALL render each reference as a compact citation chip associated with the AI bubble. Clicking a readable active `.txt` or `.md` citation SHALL open the existing reader selected by its `source_ref`/`reader_ref`, whether it is an attachment or evidence source. A deleted or unavailable citation SHALL render an unavailable state without breaking the message bubble. The chip SHALL not expand the full attachment body inside the bubble.

#### Scenario: Citation chip opens reader
- **WHEN** an AI message references an active selected `需求.md`
- **THEN** the bubble shows a citation chip for `需求.md`
- **AND** clicking the chip opens the existing text reader

#### Scenario: Deleted citation is non-blocking
- **WHEN** a previously cited attachment has been deleted
- **THEN** its chip shows an unavailable state
- **AND** the surrounding AI message remains readable

#### Scenario: No structured reference means no chip
- **WHEN** a chatroom message has no `attachment_refs`
- **THEN** the feed does not invent an attachment chip or `[附件一]` anchor

### Requirement: Shared summary has a separate context-panel section
The chatroom right context panel SHALL include a shared-summary section separate from the chronological feed. The meeting projection SHALL expose `chatroom_memory` with `summary`, `revision`, `updated_at`, `status`, `stale`, and optional error metadata. The section SHALL show the current summary content, version, and update time when available, an explicit empty/unavailable state before the first successful summary, and an explicit stale/update-failed state when the prior summary was retained. A `chatroom_memory_updated` websocket/projection event SHALL update the section without a feed event; after reconnect or a missed notification, the client SHALL refetch `GET /meetings/{meeting_id}`. Updating the section SHALL not create a message bubble or alter feed ordering.

#### Scenario: Summary appears outside feed
- **WHEN** a new shared summary revision is available
- **THEN** the context panel displays its content, version, and update time
- **AND** the feed contains only durable human, AI, attachment, and existing system projections

#### Scenario: Summary empty state is understandable
- **WHEN** no summary revision exists
- **THEN** the context panel states that shared summary is not available yet
- **AND** it does not display 「尚未有會議發言」 as if the summary were a message

#### Scenario: Summary failure is visible but non-blocking
- **WHEN** summary generation fails after a prior revision exists
- **THEN** the panel keeps the prior content and shows stale/update-failed state
- **AND** chat feed rendering and new chat requests remain available

#### Scenario: Memory notification and reconnect are deterministic
- **WHEN** a new revision is committed or the client reconnects after missing a notification
- **THEN** the panel either consumes `chatroom_memory_updated` or refetches `GET /meetings/{meeting_id}`
- **AND** no summary event is inserted into the chronological feed

#### Scenario: Summary survives feed filtering
- **WHEN** the user filters the message feed to one role
- **THEN** the shared summary section remains available in the context panel
- **AND** summary visibility is not treated as a role message

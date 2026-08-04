# conversation-workspace Specification

## Purpose

The Conversation workspace is the shared time-ordered message-feed presentation used by relay, parallel, and chatroom modes. This capability covers the chatroom-specific projection (hide process indicators, chatroom composer, quote-inline state, context-panel adaptations) and the workspace UX contract shared by chatroom and courtroom meetings: unified seat click behavior, symmetric role filtering, message avatars, in-rail model switching, scene enlargement, records access within the context panel, consolidated workspace controls, and a feed that stays scrollable.
## Requirements
### Requirement: Chatroom workspace projection
The Conversation workspace SHALL project chatroom meetings using the same time-ordered message feed, collapsible left role rail, and collapsible right context panel as relay/parallel modes. The workspace family for chatroom SHALL be `'conversation'`, reusing the existing `ConversationWorkspace.vue` component.

#### Scenario: Chatroom uses conversation workspace
- **WHEN** a chatroom meeting is opened
- **THEN** the `ConversationWorkspace` component renders with time-ordered messages

#### Scenario: Role rail shows chatroom participants
- **WHEN** a chatroom meeting with 4 roles is open
- **THEN** the left role rail shows all 4 roles with their status indicators

### Requirement: Chatroom context panel omits process indicators
For chatroom meetings, the right context panel SHALL omit the following:
- Goal display (when goal is empty)
- Parallel progress bar (fanout/synthesis status)
- Relay step progress ("第 N 步 / 共 M 步")
- Court CTA buttons and available_actions
- "開始新回合" or equivalent buttons

The context panel SHALL show: meeting title, participant count, case file count (if any), and a mode badge indicating "聊天室".

#### Scenario: Context panel shows title and participants
- **WHEN** a chatroom meeting is open
- **THEN** the right panel shows the meeting title and "4 位角色"

#### Scenario: No step progress in chatroom
- **WHEN** a chatroom meeting has ongoing AI responses
- **THEN** the right panel does not show step progress or round progress

### Requirement: Chatroom message display

Chatroom messages SHALL be displayed in the same time-ordered feed as other conversation modes. Human messages, AI responses, and system messages use the same visual format. A new chatroom AI response using `chat-message/v1` SHALL display its parsed `message` directly, without synthesizing formal report sections from parsed fields. Historical chatroom events without the new schema SHALL remain readable through the existing fallback. AI responses from `@all` fanout SHALL be displayed in arrival order (the order they were appended to events.jsonl), not in participant list order.

#### Scenario: Natural chat response displays directly

- **WHEN** a chatroom AI event has `output_schema_id: "chat-message/v1"` and a parsed `message`
- **THEN** the message feed displays that message text directly
- **AND** the bubble does not display generated 摘要、論點、風險、或建議處置 headings

#### Scenario: Legacy chatroom response remains readable

- **WHEN** a historical chatroom AI event has no `chat-message/v1` message field
- **THEN** the feed uses the existing deterministic fallback for that event
- **AND** no historical event is rewritten

#### Scenario: Fanout messages display in arrival order

- **WHEN** `@all` is sent and responses arrive in order B, A, C
- **THEN** the message feed shows B's response first, then A, then C

#### Scenario: Thinking indicator for pending fanout

- **WHEN** `@all` is sent and only A has responded
- **THEN** the remaining roles show a thinking/animated indicator in the feed
- **AND** the natural-message projection does not remove or suppress those pending indicators

### Requirement: Chatroom long message collapse
AI responses longer than 240 characters or 3 lines in chatroom mode SHALL be collapsed by default with an expand/collapse toggle, same as other conversation modes.

#### Scenario: Long AI response collapsed
- **WHEN** an AI role responds with 500 characters in chatroom mode
- **THEN** the response is displayed collapsed with an expand toggle

### Requirement: Role filtering in chatroom
Clicking a seat (Chairman or any role) in the left rail SHALL toggle a message-feed filter to that seat's messages: a single click on an unfiltered or differently-filtered seat filters the feed to that seat; a single click on the currently active (filtered) seat clears the filter and scrolls to the latest message. The currently filtered seat SHALL display a visible filtering indicator. A "顯示全部發言" button SHALL remain available in the conversation header as a secondary way to clear the filter and scroll to the latest message.

#### Scenario: Filter by role in chatroom
- **WHEN** the user clicks "Blue" in the role rail
- **THEN** only Blue's messages are visible in the feed
- **AND** the Blue seat shows a filtering indicator

#### Scenario: Clicking the active seat clears the filter
- **WHEN** the Blue seat is currently filtering the feed and the user clicks the Blue seat again
- **THEN** the filter is cleared, all messages are visible, and the feed scrolls to the latest message
- **AND** the Blue seat no longer shows a filtering indicator

#### Scenario: Header button still clears the filter
- **WHEN** a seat filter is active
- **THEN** clicking "顯示全部發言" in the conversation header clears the filter and scrolls to the latest message

### Requirement: Quote-inline UI in composer
The chatroom composer SHALL support an inline quote indicator. When the user selects "quote" on an existing message, the composer SHALL show a visual indicator of the quoted message (content preview or event_id reference) above the text input. The quoted event_id SHALL be sent with the message to the backend.

#### Scenario: Quote indicator visible in composer
- **WHEN** the user clicks "quote" on a message
- **THEN** the composer shows a quote preview bar above the text input

#### Scenario: Quote cleared on send
- **WHEN** the user sends a quoted message
- **THEN** the quote indicator is cleared from the composer

### Requirement: Case file entry point in chatroom composer
The chatroom composer SHALL include a `+` button that directly opens the native file picker through a resident input. It SHALL not open a modal or quick-menu. Upload progress and attachment management SHALL be available in the context panel’s materials/data tab, with courtroom wording localized to 案卷/證物. `.txt` and `.md` files SHALL follow the chatroom text-mirroring contract; other files SHALL be binary attachments. The count SHALL exclude removed attachments.

#### Scenario: Direct LINE-style upload
- **WHEN** the user clicks `+` and selects a file
- **THEN** the file uploads immediately without an intermediate menu or modal
- **AND** progress is visible in the materials tab

#### Scenario: Materials management
- **WHEN** the user opens the context panel materials/data tab
- **THEN** active attachments, upload progress, and the accepted simple chatroom text projection are visible
- **AND** chatroom does not expose the old notes/form/version-management flow

### Requirement: Unified seat click behavior
Every seat in the left role rail, including the Chairman seat, SHALL respond to its primary click with the same action: filtering the message feed to that seat (per the Role filtering requirement). Opening a seat's detail view (persona/description) SHALL be a secondary action available via a distinct control within the seat (not the seat's primary click), and SHALL work identically for the Chairman seat and every role seat.

#### Scenario: Chairman seat filters like a role seat
- **WHEN** the user clicks the Chairman seat
- **THEN** the message feed filters to Chairman's messages, the same way clicking a role seat filters to that role

#### Scenario: Detail view reachable from any seat
- **WHEN** the user activates the secondary detail control on the Chairman seat or on any role seat
- **THEN** the corresponding detail drawer opens, without changing the current message filter

### Requirement: Message avatars in feed
Each message card in the conversation feed SHALL display the speaking role's avatar (the same portrait/silhouette resolution used in the role rail) alongside its name in the message header.

#### Scenario: AI message shows avatar
- **WHEN** an AI role's message is rendered in the feed
- **THEN** the message header shows that role's avatar image (or silhouette fallback) next to its name

### Requirement: In-rail model switching
Each role seat in the left rail SHALL provide a control to view and change that role's assigned model, without requiring the user to open meeting settings. Changing the model from the seat SHALL use the same update path as the existing meeting-settings model change.

#### Scenario: Change model from the role rail
- **WHEN** the user activates a role seat's model control and selects a different model
- **THEN** that role's assigned model is updated for the meeting
- **AND** the seat's model label reflects the new selection

### Requirement: Scene enlargement
The role scene image shown in the context panel SHALL be enlargeable on click into a full-size view.

#### Scenario: Enlarge scene image
- **WHEN** the user clicks the scene image in the context panel
- **THEN** the scene is displayed enlarged in a modal overlay

### Requirement: Context panel includes meeting records
The right context panel SHALL provide access to the meeting's records (proceedings/log) without requiring a separate top-level navigation entry. The records view and the existing context body (goal/status/parallel progress/scene) SHALL both be reachable from within the same panel.

#### Scenario: View records from the context panel
- **WHEN** the user switches the context panel to its records view
- **THEN** the meeting's records are displayed within the panel

### Requirement: Consolidated meeting workspace controls
For an open meeting, the workspace SHALL NOT present a dedicated top-level subnav row duplicating entry points available elsewhere. Meeting settings SHALL be reachable via a control adjacent to the meeting title. Case materials SHALL be reachable via the composer's existing entry point. Records SHALL be reachable via the context panel (per the Context panel includes meeting records requirement).

#### Scenario: Open meeting settings from the title area
- **WHEN** the user activates the settings control beside the meeting title
- **THEN** the meeting settings view opens

#### Scenario: No redundant subnav row
- **WHEN** a meeting is open
- **THEN** the workspace does not show a separate row of 會議設定／案卷與證據／議事紀錄 buttons

### Requirement: Message feed remains scrollable
The conversation message feed SHALL remain scrollable via mouse wheel and trackpad input at all times, including while messages are actively streaming in.

#### Scenario: Wheel scroll works during active meeting
- **WHEN** the user scrolls the mouse wheel over the message feed
- **THEN** the feed scrolls in response, regardless of whether AI responses are currently streaming

### Requirement: Attachment bubbles in chat feed
Binary attachment metadata SHALL render as feed bubbles: images as thumbnail/lightbox, PDFs and generic binaries as filename/size/download cards. Chatroom text attachments SHALL render as a card with an on-demand reader, not full text. Removed attachments SHALL remain as non-clickable “已刪除” cards. Downloads SHALL use `file_id`.

#### Scenario: Render active and removed attachments
- **WHEN** the feed contains an image, PDF, generic binary, text, and removed attachment
- **THEN** each active type uses its corresponding card/reader presentation
- **AND** the removed card cannot be opened or downloaded

### Requirement: Attachment deletion in feed
Each active attachment bubble SHALL expose a delete control. The control SHALL use neutral irreversible confirmation. After deletion the bubble SHALL remain visible as a non-interactive removed card and the management list/count SHALL refresh.

#### Scenario: Delete from feed
- **WHEN** the user confirms deletion from an active attachment bubble
- **THEN** the bubble becomes a non-interactive removed card
- **AND** the materials list and count refresh

### Requirement: Attachment bubble downloadability for all participants
Every participant SHALL see active binary attachment bubbles and be able to download them independent of role or visibility settings.

#### Scenario: Shared binary download
- **WHEN** any participant activates a binary attachment download control
- **THEN** the file is served by its `file_id`

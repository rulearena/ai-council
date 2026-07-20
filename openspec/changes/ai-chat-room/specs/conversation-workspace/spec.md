## ADDED Requirements

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
Chatroom messages SHALL be displayed in the same time-ordered feed as other conversation modes. Human messages, AI responses, and system messages use the same visual format. AI responses from @all fanout SHALL be displayed in arrival order (the order they were appended to events.jsonl), not in participant list order.

#### Scenario: Fanout messages display in arrival order
- **WHEN** @all is sent and responses arrive in order B, A, C
- **THEN** the message feed shows B's response first, then A's, then C's

#### Scenario: Thinking indicator for pending fanout
- **WHEN** @all is sent and only A has responded
- **THEN** the remaining roles show a thinking/animated indicator in the feed

### Requirement: Chatroom long message collapse
AI responses longer than 240 characters or 3 lines in chatroom mode SHALL be collapsed by default with an expand/collapse toggle, same as other conversation modes.

#### Scenario: Long AI response collapsed
- **WHEN** an AI role responds with 500 characters in chatroom mode
- **THEN** the response is displayed collapsed with an expand toggle

### Requirement: Role filtering in chatroom
Clicking a role in the left rail SHALL filter the message feed to show only messages from that role. A "顯示全部發言" button SHALL clear the filter and scroll to the latest message.

#### Scenario: Filter by role in chatroom
- **WHEN** the user clicks "Blue" in the role rail
- **THEN** only Blue's messages are visible in the feed

### Requirement: Quote-inline UI in composer
The chatroom composer SHALL support an inline quote indicator. When the user selects "quote" on an existing message, the composer SHALL show a visual indicator of the quoted message (content preview or event_id reference) above the text input. The quoted event_id SHALL be sent with the message to the backend.

#### Scenario: Quote indicator visible in composer
- **WHEN** the user clicks "quote" on a message
- **THEN** the composer shows a quote preview bar above the text input

#### Scenario: Quote cleared on send
- **WHEN** the user sends a quoted message
- **THEN** the quote indicator is cleared from the composer

### Requirement: Case file entry point in chatroom composer
The chatroom composer SHALL include a "+" button or equivalent that opens the existing versioned case-files upload/management flow. This entry point SHALL work identically to the existing case-files flow in relay/parallel modes. No new attachment format is created.

#### Scenario: Case files accessible from chatroom
- **WHEN** the user clicks the case file entry point in chatroom mode
- **THEN** the existing case files management interface opens

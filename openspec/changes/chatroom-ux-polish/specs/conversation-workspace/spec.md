## MODIFIED Requirements

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

## ADDED Requirements

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

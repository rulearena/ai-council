## ADDED Requirements

### Requirement: Summary regeneration has an explicit API contract
`POST /meetings/{meeting_id}/chat/memory/regenerate` SHALL be available when the meeting is idle and able to accept chat input. Success SHALL return HTTP `202` with exactly `{status: "accepted", meeting_id: string, memory_status: "generating"}`. A running or terminal meeting SHALL return HTTP `409` with exactly `{status: "rejected", error: {code: "CHATROOM_MEMORY_REGENERATION_NOT_ALLOWED"}}`. The request SHALL not create a human event, AI chat event, or feed bubble.

#### Scenario: User requests regeneration while idle
- **WHEN** an idle chatroom receives a valid regeneration request
- **THEN** it returns the exact `202` accepted body
- **AND** the memory task enters `generating` without creating a feed event

#### Scenario: Regeneration is rejected while unavailable
- **WHEN** a running or terminal meeting receives a regeneration request
- **THEN** it returns the exact `409` rejected body
- **AND** no memory task or feed event is created


### Requirement: Shared transcript is the canonical chatroom memory
The complete append-only event transcript for a chatroom meeting SHALL remain the canonical shared memory for every chatroom role. Human messages, completed AI responses, failed AI events, and durable attachment metadata SHALL be eligible for later read-time projection according to the existing event contract. No role SHALL receive a private long-term memory store as part of this change.

#### Scenario: Later role sees published earlier response
- **WHEN** an Advisor response has completed and a later human message targets the Critic
- **THEN** the Critic's context includes the published Advisor event when it fits the context policy
- **AND** the system does not use a Critic-only memory source

#### Scenario: Same fanout round does not leak in-flight output
- **WHEN** `@all` invokes several roles concurrently
- **THEN** every role receives the same frozen pre-send transcript snapshot
- **AND** no role receives another role's not-yet-published output from that round

### Requirement: Shared meeting summary is derived and reconstructable
The system SHALL maintain a derived shared summary for chatroom meetings that records durable facts, decisions, unresolved questions, and next steps. The full transcript SHALL remain authoritative. The meeting read model SHALL expose `summary`, `revision`, `updated_at`, `status`, `stale`, and optional `error_code`/`error_message` metadata, plus the source event boundary. The summary SHALL carry a version and update timestamp, SHALL be replaceable by a newer revision, and SHALL be regenerable from the transcript without requiring historical event mutation.

#### Scenario: Summary contains shared meeting state
- **WHEN** a summary revision is generated successfully
- **THEN** it contains facts, decisions, unresolved questions, and next steps in a stable schema
- **AND** it identifies its version and update time

#### Scenario: Missing summary is recoverable
- **WHEN** an old meeting has no summary record
- **THEN** the context builder uses the recent transcript until a summary is generated
- **AND** no historical event or meeting JSONL line is rewritten

#### Scenario: Summary can be regenerated
- **WHEN** the user or an administrative task requests summary regeneration
- **THEN** the system derives a new revision from the canonical transcript
- **AND** the previous transcript remains unchanged

### Requirement: Summary updates at stable round boundaries
The summary task SHALL run only after the context threshold is reached and the current response round is terminal. A round is terminal when every targeted role has completed, failed, or been cancelled; for `@all`, the task SHALL wait for all expected role outcomes. The summary task SHALL NOT create a user-visible chat bubble or a fake AI response event.

#### Scenario: Summary waits for fanout settlement
- **WHEN** an `@all` fanout has one completed role and one still-thinking role
- **THEN** no new shared summary revision is published yet
- **AND** the pending role remains eligible for the current chatroom context

#### Scenario: Summary starts after terminal fanout
- **WHEN** every expected `@all` role has completed, failed, or been cancelled and the threshold is reached
- **THEN** one summary task is scheduled for the settled round
- **AND** the task is not rendered as a chat bubble

### Requirement: Summary failure does not block chat
If summary generation fails, the system SHALL retain the last successful summary revision, set the read-model status to `stale` with `stale: true` and `error_code: "SUMMARY_UPDATE_FAILED"`, and continue chatroom requests using the recent transcript plus the retained summary when available. If no prior revision exists, the status SHALL be `empty` with `error_code: "SUMMARY_UPDATE_FAILED"` and the bounded recent transcript fallback. The context panel SHALL visibly indicate stale/update-failed state, but a summary failure SHALL NOT fail or cancel the triggering chatroom response.

#### Scenario: Failed summary keeps prior revision
- **WHEN** a summary task fails after a previous revision exists
- **THEN** the previous revision remains the current summary
- **AND** the next chatroom response can proceed
- **AND** the context panel shows that the retained summary is stale or its update failed

#### Scenario: First summary failure falls back to transcript
- **WHEN** the first summary task fails and no previous revision exists
- **THEN** the next chatroom response uses the bounded recent transcript
- **AND** the user does not receive a synthetic summary message

### Requirement: Summary projection updates without a feed event
When a summary revision or summary status changes, the meeting read model SHALL update its `chatroom_memory` projection and the backend SHALL emit one dedicated `chatroom_memory_updated` websocket/projection event containing the meeting ID and revision/status. The update SHALL not append to the chronological feed. After reconnect or a missed notification, the client SHALL fetch `GET /meetings/{meeting_id}` and use its current memory state.

#### Scenario: Summary completion refreshes the panel
- **WHEN** a new summary revision is committed
- **THEN** the client receives `chatroom_memory_updated` and updates the summary panel
- **AND** no human, AI, or system feed event is created

#### Scenario: Reconnect recovers current summary
- **WHEN** the client reconnects after missing a memory update notification
- **THEN** it fetches `GET /meetings/{meeting_id}`
- **AND** it displays the returned current revision and status

### Requirement: Summary is visible in the context panel
The current shared summary SHALL be visible in the chatroom right context panel with its content, version, and update time. The summary SHALL be visually distinct from the chronological message feed and SHALL NOT be projected as a role message. The panel SHALL indicate when no summary exists yet.

#### Scenario: Current summary is inspectable
- **WHEN** a chatroom meeting has a current summary revision
- **THEN** the context panel shows the summary content, version, and update time
- **AND** the conversation feed contains no additional summary bubble

#### Scenario: Empty summary state is clear
- **WHEN** a chatroom meeting has not generated a summary
- **THEN** the context panel shows that shared summary is not available yet
- **AND** it does not imply that a role has spoken

### Requirement: All roles share one summary projection
Every chatroom role request in the same meeting SHALL use the same current summary revision and summary schema. The summary generator SHALL use the default host model assignment but SHALL use a dedicated summary prompt without the Host chat Persona. Summary content SHALL not be role-personalized.

#### Scenario: Roles receive identical summary
- **WHEN** Advisor and Analyst are invoked in separate turns while the same summary revision is current
- **THEN** both prompt contexts contain the same summary revision content
- **AND** neither receives a role-specific private summary

#### Scenario: Summary generator has no chat Persona
- **WHEN** the summary task invokes the default host model
- **THEN** its prompt uses the dedicated summary schema and instructions
- **AND** it does not address the user as the Host chat Persona would

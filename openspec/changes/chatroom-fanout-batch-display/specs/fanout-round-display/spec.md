# fanout-round-display Specification

## Purpose

When a chatroom Human sends `@all` or a multi-role mention, the backend fans out to every mentioned role in parallel (`fanout_chatroom_all` via `ThreadPoolExecutor`), but events are appended in completion order, so the flat feed made the round look sequential. This capability groups one fanout round into a single visual batch: a round header with live progress, simultaneous thinking indicators for every mentioned role, and member bubbles that fill in as each role completes.

## ADDED Requirements

### Requirement: Fanout round grouping
A chatroom message that triggers a fanout SHALL project all resulting AI response messages as one visual round group. Membership SHALL be determined by `in_response_to_event_id`: every fanout event whose `in_response_to_event_id` matches the same human-message event belongs to that round. Events whose `step_id` begins with `chat-fanout-` but have no resolvable `in_response_to_event_id` SHALL NOT be grouped and SHALL render as individual messages in arrival order.

#### Scenario: @all responses group into one round
- **WHEN** the Human sends "@all 大家覺得呢？" and the four mentioned roles respond
- **THEN** the feed shows one round group containing all four response bubbles

#### Scenario: Multi-mention groups into one round
- **WHEN** the Human sends "@Advisor @Critic 你們覺得呢？" and both roles respond
- **THEN** the feed shows one round group containing both response bubbles

#### Scenario: Legacy fanout event without grouping key stays flat
- **WHEN** a fanout event has no `in_response_to_event_id` (or it cannot be resolved)
- **THEN** that message renders as an individual message in arrival order, not inside a round group

### Requirement: Round header with live progress
Each fanout round group SHALL display a header showing how many members have responded versus the round's expected size ("N 位角色回應中" while pending, e.g. "2/4 已回應", and a completion label once all members are done). The expected size N SHALL be the round's full member set (the roles the mention addressed, aligned to the roles the backend can actually fan out to), not the count of responses that have arrived so far, so the denominator does not grow as members complete. The header SHALL reflect the round's current state and update as members complete. If the frontend's knowledge of the full member set was lost (e.g. after a reconnect/reload mid-round), the header SHALL degrade to showing only the members known to the frontend and SHALL NOT over-count. An expected member that never emits an event SHALL NOT block the round from reaching its terminal state once all other expected members are done.

#### Scenario: Pending round shows count
- **WHEN** a fanout round is running and two of four members have completed
- **THEN** the round header shows a live progress label (e.g. "2/4 已回應")

#### Scenario: Completed round shows completion
- **WHEN** all members of a fanout round have responded
- **THEN** the round header shows a completion label rather than a pending count

### Requirement: Simultaneous thinking indicators
During a fanout round, every mentioned role that has not yet responded SHALL show a thinking indicator at the same time. A role's thinking indicator SHALL clear only when that role's own completion (or failure) event is appended. A failed member SHALL not block other members' indicators or the round's progress.

#### Scenario: All pending roles think at once
- **WHEN** @all is sent and no role has responded yet
- **THEN** every mentioned role shows a thinking indicator simultaneously

#### Scenario: Completed role stops thinking independently
- **WHEN** role A completes while B and C are still pending
- **THEN** A's thinking indicator clears while B and C continue to show theirs

#### Scenario: Failed member does not stall the round
- **WHEN** one role of a fanout round fails while others complete
- **THEN** the failed member is marked failed, the remaining members' indicators clear on completion, and the round reaches a terminal state

### Requirement: Member bubbles preserve per-message identity
Grouping SHALL NOT alter each member's message identity or count. Each response bubble inside a round SHALL remain a distinct message (own `event_id`, own testid `workspace-message`), so message count, per-role selectors, quoting, and role filtering continue to work unchanged.

#### Scenario: Message count unchanged by grouping
- **WHEN** a single @all round with four responses is rendered
- **THEN** the feed still contains five message elements (1 human + 4 AI) regardless of grouping

#### Scenario: Per-role bubble selectors unchanged
- **WHEN** a role's response is rendered inside a fanout round group
- **THEN** the bubble retains its role-specific testid/attribute selectors and can be quoted and filtered as before

### Requirement: Sequential-mode compatibility
The grouping SHALL apply only to fanout rounds (`chat-fanout-*` step_ids with a matching human `in_response_to_event_id`). Ordinary human messages, directed single-role responses, relay/parallel mode messages, and courtroom messages SHALL render exactly as they do today.

#### Scenario: Directed single-role response not grouped
- **WHEN** the Human sends "@Advisor 你覺得呢？" (single mention)
- **THEN** Advisor's response renders as an individual message, not inside a round group

#### Scenario: Non-chatroom modes unaffected
- **WHEN** a relay or parallel meeting renders its feed
- **THEN** no fanout round groups appear and the existing presentation is unchanged

## Context

Backend `fanout_chatroom_all` (runner.py:475) already runs @all in parallel (`ThreadPoolExecutor(max_workers=len)`), and each member's completed event carries `in_response_to_event_id` pointing at the triggering human-message. But the frontend presented results as a flat arrival-ordered feed, and the thinking indicator only ever lit the first queued role (`projectRoles` marks only `queueIndex === 0` as `thinking` for `mode.category !== 'parallel'`), so one parallel @all round looked like a relay sequence. The Human Owner accepted batch-group presentation.

This is a pure frontend projection/render change. No backend, event-schema, or history changes.

## Goals / Non-Goals

**Goals:**
- Render one fanout round as a single visual batch: round header with live progress, simultaneous thinking indicators for every pending member, member bubbles filling in on completion.
- Keep every member bubble a distinct message (counts, per-role selectors, quoting, role filtering, tests 13.4/13.7/13.22 stay green).
- Safe fallback when a fanout event lacks a resolvable grouping key.

**Non-Goals:**
- No backend changes; no changes to fanout execution order or `as_completed` append semantics.
- No changes to relay/parallel/courtroom presentations.
- No changes to `@all` execution, token budget, or mention parsing.
- No history migration.

## Decisions

### D1. Round grouping key = `in_response_to_event_id`
Every `chat-fanout-{ts}-{role}` completed/failed event carries `in_response_to_event_id` = the human-message event_id that triggered the round (verified in real data). Group members = events whose `step_id` starts with `chat-fanout-` AND whose `in_response_to_event_id` resolves to a human-message event in the same meeting's events.

- Why over a step_id timestamp prefix (`chat-fanout-{ts}`): the ts is shared by the round but is a bare milliseconds number; `in_response_to_event_id` is an explicit, verifiable event reference already present and already used for quote/linkage.
- Fallback: a `chat-fanout-*` event with a missing/unresolvable `in_response_to_event_id` renders flat (single message, no group). This protects pre-existing data.

### D2. Round metadata added to `WorkspaceMessage` projection
Extend `WorkspaceMessage` with optional round fields (e.g. `fanoutRoundId?: string`, `fanoutMemberCount?: number`, `isFanoutRoundStart?: boolean`, `isFanoutRoundEnd?: boolean`, and per-member status). `projectMessages` derives a round map in one pass over events:
1. Build `humanEventIds = Set(events where step_id === 'human-message' and role === 'Human')`.
2. For each event with `step_id.startsWith('chat-fanout-')`, group key = `in_response_to_event_id` if present in `humanEventIds`, else null.
3. Round members keep arrival order (events order), so existing feed order is untouched.
4. Attach `fanoutRoundId` etc. to the projected `WorkspaceMessage`.

The component (ConversationWorkspace) renders a group wrapper when a message's `fanoutRoundId` changes: opens a round group with header on first member, closes on last member, but each bubble keeps its own `article.workspace-message` markup and testids.

### D3. Simultaneous thinking for fanout members
In `projectRoles`, when the active meeting is chatroom (`mode.category === 'chatroom'`) and the latest fanout round is still pending (some members have not completed/failed), mark every pending round member as `thinking` simultaneously — not just `queueIndex === 0`.

Implementation approach: compute the pending round from events (rounds where member count > completed/failed count and `activity_status === 'running'`), and in the non-parallel branch treat round members as thinking. `pendingRoles` still drives the transient pre-event window (before the first completion lands); once events exist, round-derived state is authoritative. The failed-member rule from `parallelRoundState` (failure marks that member failed without blocking others) applies by analogy.

- Why: the one-at-a-time `queueIndex === 0` rule was correct for relay sequences (which genuinely serialize) but wrong for fanout (which genuinely parallelizes). Chatroom is the only mode that fans out without `mode.category === 'parallel'` (parallel category modes already mark all members thinking via the `parallelRoundState` branch).
- Alternatives considered: reusing `parallelRoundState` for chatroom — rejected because chatroom rounds are keyed differently (`chat-fanout-*` vs `fanout-{round}-member-{k}`) and have no synthesis step, so a dedicated chatroom round derivation is clearer.

### D4. Round header + progress
The round group header renders:
- While pending: `N 位角色回應中` with a live `x/N 已回應` progress derived from the round's member events.
- When all members completed: completion label (e.g. `全部 N 位已回應`).
- When a member failed: that member's bubble shows the failed state; progress counts only completed members; the header shows a mixed/partial label and does not stall waiting for the failed member.

Header is a presentational element only; it carries no backend meaning and is not a message.

### D5. Grouping applies to fanout only; single-mention stays flat
Single-role mentions (`@Advisor`) go through `chat_respond_as_role` producing `chat-directed-N-{role}-response` step_ids (not `chat-fanout-*`), so they never group. Ordinary human messages, relay/parallel/courtroom feeds, and attachment events are untouched. Grouping is gated on `step_id.startsWith('chat-fanout-')`.

## Risks / Trade-offs

- **Existing e2e rely on flat per-message selectors** → Grouping adds a wrapper but keeps each `article.workspace-message` with its existing testids/attributes; tests 13.4 (count = 1 human + 4 AI) and 13.22 (thinking indicator visible/clears) must remain green and will be extended, not rewritten.
- **Thinking state source of truth split** (`pendingRoles` for pre-event window vs event-derived for round) → Keep the chatroom fanout thinking derived from events when round events exist; `pendingRoles` only covers the brief window before the first completion. Add a unit test for the transition.
- **Legacy/unknown `in_response_to_event_id`** → Flat fallback; no mis-grouping.
- **Failed member could stall the round header** → Progress counts completed members only; a failed member terminates that slot and the header reaches a terminal label once all slots are completed or failed.

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

### D3. Expected member set = send-time queuedRoles ∪ arrived members (the round's N)

Backend fanout events are appended only on member completion/failure (`as_completed`, runner.py:600), so **arrived events alone cannot reveal the expected member count**: before the first completion lands there are zero member events, and during the stream the count grows 1→2→3→4, never reaching a stable N. The `human-message` event does not persist the mention set. Therefore the round's expected member set must come from the client at send time:

- **Source**: `sendChatroomMention` (useCouncil.ts:1114-1127) already expands `@all`/multi-mention into the full queued role list it pushes into `pendingRoles`. Capture that same list as the round's expected member set when the mention is sent.
- **Merge**: expected set = captured queuedRoles ∪ roles seen arriving via `chat-fanout-*` events for the same round (union covers reconnect/reload where the capture was lost). Round N = `|expected set|`, and it is fixed once known — it never grows with arrivals.
- **Lifecycle**: the captured expected set lives as long as the round is pending (keyed by the round's `in_response_to_event_id` once known, transiently keyed by send order before that). On WS disconnect/reconnect `pendingRoles` is cleared (useCouncil.ts:776), so the captured set is also cleared and the round degrades to "arrived members only" for the remainder — progress then shows `x/x` until the round completes, never over-counting.
- **Why not server-persisted mentions**: would require a backend/event-schema change, which is out of scope (backlog #98: pure frontend projection change; historical events are never rewritten).

### D4. Three-phase round behavior (simultaneous thinking + progress)

The round presents in three deterministic phases; the projection derives state from the union of the send-time expected set and arrived events:

1. **Pre-event** (after send, before the first member completes): every role in the expected set shows a thinking indicator simultaneously; header shows `0/N 已回應`. This is exactly the window where the old code lit only `queueIndex === 0`.
2. **In-stream** (some members arrived): each arrived member that completed renders its bubble and stops thinking; roles still in the expected set without an arrived event keep thinking; header shows `x/N 已回應` where x = completed members (failed slots are excluded from x and marked failed on their bubble). N is the fixed expected count from D3, not the arrival count.
3. **Terminal** (every expected member completed or failed): header shows a completion label (`全部 N 位已回應`) or a partial label if any slot failed; no slot remains thinking.

In `projectRoles`, when the active meeting is chatroom (`mode.category === 'chatroom'`) and a fanout round is pending per D3/D4, mark every pending expected member as `thinking` simultaneously — not just `queueIndex === 0`. The one-at-a-time `queueIndex === 0` rule was correct for relay sequences (which genuinely serialize) but wrong for fanout (which genuinely parallelizes). Chatroom is the only mode that fans out without `mode.category === 'parallel'` (parallel category modes already mark all members thinking via the `parallelRoundState` branch).

- Alternatives considered: reusing `parallelRoundState` for chatroom — rejected because chatroom rounds are keyed differently (`chat-fanout-*` vs `fanout-{round}-member-{k}`) and have no synthesis step, so a dedicated chatroom round derivation is clearer.

### D5. Chatroom fanout failure semantics (must not collapse the round)

`applyPendingRoleUpdates` currently clears the entire `pendingRoles` on any member failure (useCouncil.ts:787-790). That rule is correct for serial relay/parallel batches (backend halts remaining steps after the first failure) but **wrong for fanout**: a failed fanout member does not stall the others — they run independently and must keep thinking. For chatroom fanout rounds, failure handling must change so a failed member:
- clears only that member's pending slot (not the whole array),
- shows `failed` on its bubble (e2e 13.7 relies on `role-seat-advisor data-status=failed`),
- does not block the remaining expected members from thinking,
- is excluded from the header's completed count but still counts toward the round reaching terminal.

Guard this on "the event belongs to a chatroom fanout round" so relay/parallel/courtroom failure behavior is untouched.

### D6. Grouping applies to fanout only; single-mention stays flat
Single-role mentions (`@Advisor`) go through `chat_respond_as_role` producing `chat-directed-N-{role}-response` step_ids (not `chat-fanout-*`), so they never group. Ordinary human messages, relay/parallel/courtroom feeds, and attachment events are untouched. Grouping is gated on `step_id.startsWith('chat-fanout-')`.

## Risks / Trade-offs

- **Existing e2e rely on flat per-message selectors** → Grouping adds a wrapper but keeps each `article.workspace-message` with its existing testids/attributes; tests 13.4 (count = 1 human + 4 AI), 13.7 (per-role `data-status=failed`), and 13.22 (thinking indicator visible/clears) must remain green and will be extended, not rewritten.
- **Expected member set is client-send-time state, not persisted** → Within a session the round N is exact (D3). Across a WS disconnect/reload the captured set is lost and the round degrades to arrived-members-only (`x/x`), never over-counting. This is an accepted trade-off because persisting the mention set would require a backend/event-schema change (out of scope, backlog #98 = pure frontend).
- **Thinking state source of truth split** (`pendingRoles` pre-event vs round-derived in-stream) → Both derive from the same expected member set (D3), so the pre-event `0/N` window and the in-stream `x/N` window compose without a discontinuity. Add a unit test for the transition.
- **Legacy/unknown `in_response_to_event_id`** → Flat fallback; no mis-grouping.
- **Failed member collapsing the round** → D5 guards chatroom-fanout failure to clear only that member's slot; relay/parallel/courtroom failure behavior is untouched. Add a failure-first ordering unit test so a failed member arriving before its peers does not extinguish their thinking.

## Context

AI Council currently supports 6 meeting modes in two execution categories: `relay` (sequential step-by-step) and `parallel` (fanout + synthesis). Backlog #90 delivered a unified Conversation workspace for both. All modes impose fixed AI execution sequences triggered automatically by the system.

Users need a mode for casual multi-role conversation where the Human drives the dialogue, invokes specific AI roles on demand, and receives concise responses — without process overhead, fixed rounds, or mandatory goals.

Key existing architecture:
- `config/modes.yaml` defines mode schemas; `ModeCatalogRepository` validates them
- `MeetingRunner` executes relay (`start()`) or parallel (`start_parallel()`) plans
- `respond_as_role()` in runner.py handles directed single-role responses via `directed_role_response` prompt template
- `POST /meetings` creates meetings with required `title` + `goal`; `POST /meetings/{id}/messages` appends human-only notes; `POST /meetings/{id}/roles/{role}/respond` triggers directed AI
- Frontend `ConversationWorkspace.vue` renders time-ordered messages with role rail and context panel
- `chairmanActions.ts` dispatches note/all/role-select actions from `ActionBar.vue` dropdown
- No mention/@ autocomplete system exists; directed responses use a dropdown selector

## Goals / Non-Goals

**Goals:**
- Add a `chatroom` meeting mode where Human drives conversation via @mentions
- Support `@role` (single directed response) and `@all` (parallel frozen-context fanout)
- Implement structured mention autocomplete in the frontend composer
- Make `goal` optional for chatroom meetings
- Reuse the existing Conversation workspace with chatroom-specific adaptations
- Maintain full backward compatibility with all existing modes, events, and data

**Non-Goals:**
- Multi-user accounts or authentication
- External messaging integration (Line, Slack, etc.)
- Message deletion or permanent purge
- Cross-meeting memory or context sharing
- New attachment format (reuse existing case files)
- Post-generation text truncation (length control via prompt only)
- Modifying historical events or meetings of any mode

## Decisions

### Decision 1: Third mode category `chatroom` (not a special relay)

**Choice:** Add `category: chatroom` as a third valid category alongside `relay` and `parallel`.

**Alternatives considered:**
- *Use relay with empty steps:* Would inherit relay's step-progress UI, auto-start behavior, and round-counting. Requires many "if chatroom, skip" guards throughout the relay code path. Fragile.
- *Use parallel with min_instances=0:* Parallel's synthesis-phase logic has no meaning for chatroom. Would require bypassing synthesis checks, member counting, and arrival-order synthesis gating. Worse semantic fit.

**Rationale:** Chatroom has fundamentally different execution semantics — no steps, no fanout, no synthesis, human-driven. A distinct category makes the code path clean: runner.py checks `category == "chatroom"` and takes a dedicated path, just as it does for relay vs parallel. The mode catalog validation becomes straightforward.

### Decision 2: Reuse `respond_as_role()` for @role mentions

**Choice:** @role mentions invoke the existing `respond_as_role()` backend contract. A new chatroom-specific prompt template (`chatroom_response`) wraps the `directed_role_response` template's injection pattern.

**Alternatives considered:**
- *New endpoint per chatroom role response:* Adds API surface without benefit; the existing `/roles/{role}/respond` endpoint already handles directed responses cleanly.
- *Inline runner execution:* Bypassing the runner would lose event recording, retry, and diagnostic infrastructure.

**Rationale:** `respond_as_role()` already handles: event recording (`human-directed-message` + AI response), model resolution, failure recording, and diagnostic attempts. Reusing it means chatroom @role gets all this infrastructure for free. The only addition is a chatroom-specific prompt template.

### Decision 3: @all as parallel fanout with frozen context

**Choice:** @all triggers a new `fanout_chatroom()` method on MeetingRunner that:
1. Takes a frozen transcript snapshot before the message
2. Invokes all roles in parallel (ThreadPoolExecutor, same as existing parallel)
3. Persists responses in arrival order (same pattern as `_run_parallel_members()`)
4. No synthesis phase — each response is standalone

**Alternatives considered:**
- *Sequential @all:* Invoke roles one by one. Simpler but slower; contradicts the "all respond" expectation. Each role could see earlier responses, breaking the frozen-context requirement.
- *Reuse parallel executor directly:* The existing parallel executor requires `ParallelPlan` with fanout/synthesis config. Chatroom has none of this. Would need to construct a synthetic ParallelPlan, polluting the abstraction.

**Rationale:** The frozen-context + arrival-order pattern is already proven in `_run_parallel_members()`. The chatroom version is simpler (no synthesis, no member retry, no anonymization). A dedicated method keeps the semantics explicit.

### Decision 4: Deterministic token-budget context selection

**Choice:** Context assembly for each AI call follows a strict priority order:
1. Current message (always included)
2. Quoted message by event_id (if present, always included)
3. System + role prompt instructions (always included)
4. Recent history: most recent messages in reverse chronological order until token budget is filled

The token budget defaults to `AI_COUNCIL_CHATROOM_CONTEXT_TOKEN_BUDGET` environment variable (default: 4096 tokens). Selection is deterministic — same events + same budget = same context, regardless of timing.

**Alternatives considered:**
- *Summarization-based context:* Too expensive, non-deterministic, and requires an additional LLM call.
- *Sliding window by message count:* Doesn't account for variable message lengths; may under- or over-use the budget.
- *Include all messages:* Unbounded context grows with conversation length; risks token limits.

**Rationale:** Deterministic selection is testable, predictable, and avoids silent context mixing. The priority order ensures the most relevant content (current + quoted) is always present. Oldest messages are dropped first when budget is exceeded.

### Decision 5: Mention autocomplete as a composable component

**Choice:** Build `MentionAutocomplete.vue` as a standalone component used by a chatroom-specific `ChatroomComposer.vue`. The component:
- Watches the textarea input for `@` trigger characters
- Queries the meeting's participant list for matching role_ids
- Renders a positioned dropdown menu with keyboard navigation
- On selection, inserts `@role_id ` into the textarea

**Alternatives considered:**
- *Extend ActionBar.vue:* The existing ActionBar has deeply coupled action-dropdown + button logic. Adding mention autocomplete would entangle two different interaction models.
- *ContentEditable div:* More flexible for rich text but significantly more complex, harder to test, and inconsistent with existing textarea patterns.

**Rationale:** A standalone component is testable in isolation, doesn't modify existing ActionBar behavior, and can be conditionally rendered only for chatroom mode. The textarea-based approach is consistent with the existing composer pattern.

### Decision 6: Prompt template `chatroom_response`

**Choice:** Create `prompts/chatroom_response.md` that instructs roles to respond concisely and conversationally. The template uses the same `{{ goal }}`, `{{ prior_transcript }}`, `{{ instruction }}`, and `{{ role_display_name }}` slots as `directed_role_response`, but adds a system-level instruction for brief, natural tone. For @all fanout, each role uses a variant that includes `{{ instruction }}` from the human's @all message.

**Alternatives considered:**
- *Reuse `directed_role_response` with a flag:* Would require modifying the existing template to conditionally change tone, adding complexity without clarity.
- *Per-role chatroom templates:* Unnecessary — the chatroom tone instruction applies uniformly; role-specific behavior comes from the role's own character definition.

**Rationale:** A dedicated template keeps the chatroom tone contract explicit and testable. It doesn't modify any existing template, preserving backward compatibility.

### Decision 7: step_id naming convention for chatroom events

**Choice:**
- Directed response: `chat-directed-{seq}-{role_id}-response` (seq = per-meeting directed-response counter)
- @all fanout: `chat-fanout-{timestamp_ms}-{role_id}` (timestamp_ms = message send time, unique per @all invocation)
- Human message: `human-message` (existing, no change)

**Rationale:** `chat-directed-*` extends the existing `directed-N-*` pattern with a `chat-` prefix to distinguish chatroom events in the same events.jsonl. `chat-fanout-*` uses timestamp to ensure uniqueness across multiple @all invocations. Both patterns are deterministic from the event data, supporting reproducible tests.

### Decision 7b: Multiple @role mentions (not @all) handled as parallel directed fanout

**Choice:** When a message contains multiple distinct `@role` mentions (e.g., `@Blue @Red`), the system SHALL invoke each mentioned role independently using the same frozen-context fanout as `@all`. Each role receives its own `chat-directed-{seq}-{role_id}-response` event with the same pre-send transcript snapshot. If `@all` also appears in the same message, `@all` takes precedence and the per-role mentions are deduplicated (all roles invoked once).

The `/chat/mention` endpoint processes this: the `mentions` array is resolved against participants; if `"all"` is present, all participant role_ids are used; otherwise only the explicitly listed role_ids are invoked. Each invocation follows the same `chat_respond_as_role()` path with per-role sequence counters.

**Alternatives considered:**
- *Sequential execution per mentioned role:* Slower, and each role could see earlier responses, breaking frozen context. Parallel fanout is simpler and consistent with @all.
- *Refuse multiple mentions:* Forces users to send separate messages, adding friction for a common conversational pattern.

**Rationale:** Multi-mention is a natural chat interaction ("@Blue @Red 你們覺得呢？"). Reusing the frozen-context fanout pattern keeps the semantics consistent with @all and avoids a new execution path. The dedup rule when @all co-occurs prevents double-invocation.

### Decision 8: Frontend mode-aware rendering

**Choice:** The `ConversationWorkspace.vue` and `useCouncil.ts` check `activeMode.category === 'chatroom'` to:
- Hide step progress bar
- Hide court CTA / available_actions
- Hide "開始新回合" button
- Show chatroom-specific composer (MentionAutocomplete + textarea + send button) instead of the chairman action dropdown
- Show mode badge "聊天室" in context panel

**Alternatives considered:**
- *New ChatroomWorkspace.vue component:* Would duplicate the message feed, role rail, and context panel rendering. Maintenance burden for minimal differentiation.
- *Full generic workspace:* Would require abstracting all mode-specific behaviors into a plugin system. Over-engineered for the current scope.

**Rationale:** The existing Conversation workspace already handles 90% of what chatroom needs. Conditional rendering for the 10% that differs is simpler and more maintainable than a new component or a full abstraction layer.

## Risks / Trade-offs

**[Risk] Token budget estimation inaccuracy** → Mitigation: Use a conservative tokenizer approximation (chars / 4 for English, chars / 2 for CJK) with a configurable buffer. The budget is a guide, not a hard limit; the system prioritizes recent messages and always includes current + quoted.

**[Risk] @all fanout partial failure leaves confusing state** → Mitigation: Each role's success/failure is independently recorded. The frontend shows per-role status (thinking/completed/failed) in the role rail and message feed. Failed roles can be retried individually.

**[Risk] Mention autocomplete conflicts with normal typing** → Mitigation: Only trigger autocomplete after `@` at word boundary (start of text or after whitespace). Dismiss on Escape, Space without selection, or clicking outside. Don't block normal typing.

**[Risk] Chatroom context budget may be too small for complex discussions** → Mitigation: Configurable via environment variable. Users can increase it. The deterministic selection ensures predictability regardless of budget size.

**[Trade-off] No synthesis for @all** → Accepted: Chatroom @all is explicitly not a structured deliberation. Each role's response is standalone. Users who need synthesis should use parallel mode.

**[Trade-off] Case-sensitive role_id in mentions** → Accepted: Matches the existing role_id contract (case-sensitive strings). Display names are for UI only; mention resolution uses stable identifiers.

**[Trade-off] No post-generation truncation** → Accepted: Length control is prompt-level. If a role generates unexpectedly long text, it's preserved. Truncation would lose information and create inconsistent state.

## Migration Plan

This is a purely additive change. No migration is needed:
- Existing modes continue to work unchanged
- Existing events are not modified
- The chatroom mode is a new entry in modes.yaml
- Frontend changes are conditional on `mode.category === 'chatroom'`
- The `goal` field remains required for relay/parallel; only chatroom allows empty goal

## Open Questions

1. **Chatroom-specific role character prompts**: Should chatroom roles have different character/personality prompts than their relay/parallel counterparts, or should the `chatroom_response` template alone handle the tone shift? Recommendation: the `chatroom_response` template handles tone; existing role character definitions remain unchanged.

2. **@all fanout retry**: Should users be able to retry a failed @all fanout role individually, or only re-send @all? Recommendation: individual retry via the existing `POST /meetings/{id}/steps/{step_id}/retry` endpoint, consistent with other modes.

## Why

Backlog #90 delivered a unified Conversation workspace for relay and parallel modes, but all existing modes impose fixed execution sequences: relay mandates a preset step order, parallel mandates fanout-then-synthesis. Users who simply want to chat with multiple AI roles — ask one, then another, quote someone, bring everyone in — have no mode that fits. The current workaround (using relay mode with manual directed responses) forces irrelevant progress bars, step labels, and a mandatory AI goal, creating friction for casual multi-role conversation.

The chatroom mode fills this gap: a free-form meeting type where the Human drives the conversation, invokes AI roles on demand, and receives concise natural-language responses — no fixed rounds, no mandatory goal, no process progress indicators.

## What Changes

- **New mode category `chatroom`**: A third execution category alongside `relay` and `parallel`. Chatroom has no `steps`, no `fanout`/`synthesis` config; AI roles respond only when explicitly mentioned.
- **Meeting creation contract change**: Chatroom meetings require only `title`; `goal` becomes optional. The `CreateMeetingRequest` must accept goal-less chatroom meetings without returning 409.
- **Structured mention system**: Frontend composer supports `@role` and `@all` mention syntax with autocomplete from the meeting's participant list, resolving to stable role IDs. Mention must not rely on free-text role names.
- **Directed single-role response**: `@RoleName` triggers a single AI response using that role, reusing the existing `respond_as_role()` backend contract with a chatroom-specific prompt template.
- **Parallel frozen-context fanout via `@all`**: `@all` triggers all roles responding in parallel, each reading the same pre-send transcript snapshot. Outputs are persisted in arrival order. Partial success is visible; single-role failure does not block others.
- **Human-message-only semantics**: Messages without valid mentions save as human conversation history only; no AI is invoked silently.
- **Deterministic context/token-budget policy**: Each AI call receives the current message, any referenced (quoted) message, system/role instructions, and a deterministic selection of recent history that fits the token budget. When the budget is exceeded, oldest messages are dropped silently — the selection is deterministic and reproducible.
- **Concise response policy**: Chatroom mode defaults to short, natural responses. Length is controlled by a chatroom-specific prompt template, not by post-generation truncation.
- **Conversation workspace projection**: Chatroom reuses the existing Conversation workspace (time-ordered message feed, collapsible role rail, collapsible context panel). The right panel omits court/flow progress; the step progress bar is hidden. Composer gains mention autocomplete, quote-inline state, and an existing case-files entry point.
- **No court CTA, no process progress, no "start new round"**: Chatroom meetings never display courtroom actions, 正式流程按鈕, or round progress indicators.
- **Legacy meeting isolation**: Existing relay/parallel meetings are unaffected. Chatroom mode does not alter event schema, existing step_id patterns, or historical data. The mode is purely additive.

## Capabilities

### New Capabilities

- `chatroom-mode`: The chatroom meeting mode — domain model, mode configuration, meeting creation contract, execution semantics (human-only, directed role, @all fanout), context/token budget, concise response policy, legacy isolation.
- `structured-mentions`: Frontend mention parsing, autocomplete/selection menu, stable role-ID resolution, quote-inline referencing, and the integration contract with backend directed-response and parallel-fanout APIs.

### Modified Capabilities

- `conversation-workspace`: The existing Conversation workspace gains chatroom-specific projections — hidden step progress, chatroom composer with mention autocomplete, quote-inline state, and context panel adaptations. No behavior change for relay/parallel modes.

## Impact

- **Backend**: `modes.yaml` gains a chatroom mode definition; `ModeCatalogRepository` validates the new category; `MeetingRunner` adds a chatroom-specific path (no step execution, only on-demand responses); `CreateMeetingRequest` relaxes goal requirement for chatroom mode; new prompt template for chatroom responses; new endpoint or event contract for @all fanout.
- **Frontend**: New mention autocomplete component; composer modifications for @ syntax and quote-inline; Conversation workspace conditional rendering for chatroom (hide step bar, adjust context panel); mode-aware routing in `useCouncil.ts`.
- **Events**: New event types for chatroom fanout (`chat-fanout-{timestamp}-{role}` step_id pattern) and human-only messages. Existing event schema unchanged.
- **API**: `POST /meetings` accepts goal-less chatroom creation; possible new `POST /meetings/{id}/chat/fanout` or extension of existing `requestAll` for chatroom @all semantics.
- **Prompt**: New `chatroom_response` prompt template emphasizing concise, conversational tone.

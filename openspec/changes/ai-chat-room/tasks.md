## 1. Backend Domain Model & Mode Configuration

- [ ] 1.1 Add `"chatroom"` to `VALID_CATEGORIES` in `backend/ai_council/meetings/modes.py` (existing `relay_plan()`/`parallel_plan()` already reject non-matching categories via generic check — no code change needed there)
- [ ] 1.2 Add chatroom mode definition to `config/modes.yaml` with `id: chatroom`, `category: chatroom`, roles ( Advisor, Critic, Strategist, Analyst — illustrative; actual role_ids to be confirmed during implementation ), no steps/fanout/synthesis
- [ ] 1.3 Add test: `test_mode_catalog.py::test_chatroom_mode_loads` — verifies chatroom mode parses with valid structure, no steps/fanout/synthesis fields
- [ ] 1.4 Add test: `test_mode_catalog.py::test_chatroom_relay_plan_rejected` — verifies `relay_plan()` raises `ModeConfigError` on chatroom category (regression confirmation: existing generic check already catches this)
- [ ] 1.5 Add test: `test_mode_catalog.py::test_chatroom_parallel_plan_rejected` — verifies `parallel_plan()` raises `ModeConfigError` on chatroom category (regression confirmation: existing generic check already catches this)

**Red light:** Test 1.3 passes (mode loads after VALID_CATEGORIES update). Tests 1.4–1.5 are regression confirmation tests that should pass immediately (the existing generic `category != "relay"` / `category != "parallel"` checks in `relay_plan()`/`parallel_plan()` already reject unknown categories). The purpose of 1.4–1.5 is to lock in this behavior, not to discover new failures.

## 2. Backend Meeting Creation Contract

- [ ] 2.1 Modify `CreateMeetingRequest` in `api.py`: make `goal` optional (default `""`) for chatroom mode; keep required for relay/parallel
- [ ] 2.2 Modify POST /meetings handler: skip goal validation when `mode_id == "chatroom"` and goal is absent/empty
- [ ] 2.3 Add test: `test_api.py::test_create_chatroom_meeting_without_goal` — POST /meetings with mode_id=chatroom, title present, no goal → 201, goal=""
- [ ] 2.4 Add test: `test_api.py::test_create_chatroom_meeting_with_goal` — POST with goal → 201, goal stored
- [ ] 2.5 Add test: `test_api.py::test_create_chatroom_empty_title_rejected` — POST with title="" → 422
- [ ] 2.6 Add test: `test_api.py::test_create_relay_meeting_without_goal_still_422` — verify relay mode still requires goal

**Red light:** Tests 2.3–2.4 fail (goal still required); test 2.6 passes (existing behavior preserved).

## 3. Backend Prompt Template

- [ ] 3.1 Create `prompts/chatroom_response.md` with `{{ goal }}`, `{{ prior_transcript }}`, `{{ instruction }}`, `{{ role_display_name }}` slots and concise/conversational tone instruction
- [ ] 3.2 Add test: `test_prompt_renderer.py::test_chatroom_response_template_renders` — verifies template renders with all slots filled, output contains role_display_name

**Red light:** Test 3.2 fails (template not found by renderer).

## 4. Backend Chatroom Runner — Directed Response (@role)

- [ ] 4.1 Add `chat_respond_as_role()` method to MeetingRunner: uses `chatroom_response` template, step_id = `chat-directed-{seq}-{role}-response`, appends `human-directed-message` + AI response events
- [ ] 4.2 Add test: `test_runner_chatroom.py::test_chat_directed_single_role_response` — send @Blue message → blue's response event appended with correct step_id
- [ ] 4.3 Add test: `test_runner_chatroom.py::test_chat_directed_increments_sequence` — two directed responses → seq increments (chat-directed-1-*, chat-directed-2-*)
- [ ] 4.4 Add test: `test_runner_chatroom.py::test_chat_directed_unknown_role_saves_human_only` — @Unknown → human-message event, no AI invocation

**Red light:** Tests 4.2–4.4 fail (method doesn't exist).

## 5. Backend Chatroom Runner — @all Fanout

- [ ] 5.1 Add `fanout_chatroom_all()` method to MeetingRunner: freezes transcript snapshot, invokes all roles via ThreadPoolExecutor, persists in arrival order, records partial failures
- [ ] 5.2 Add test: `test_runner_chatroom.py::test_chat_fanout_all_roles_invoked` — @all with 3 roles → 3 AI response events appended
- [ ] 5.3 Add test: `test_runner_chatroom.py::test_chat_fanout_frozen_context` — verify all roles receive same transcript snapshot (mock transcript_projector, assert same input)
- [ ] 5.4 Add test: `test_runner_chatroom.py::test_chat_fanout_arrival_order_persistence` — mock roles with different delays → events appended in completion order
- [ ] 5.5 Add test: `test_runner_chatroom.py::test_chat_fanout_partial_success` — mock one role failure → 2 success events + 1 failure event, no hidden failures
- [ ] 5.6 Add test: `test_runner_chatroom.py::test_chat_fanout_step_id_format` — step_ids match `chat-fanout-{timestamp_ms}-{role}` pattern

**Red light:** Tests 5.2–5.6 fail (method doesn't exist).

## 6. Backend API Endpoints for Chatroom

- [ ] 6.1 Add `POST /meetings/{id}/chat/mention` endpoint: accepts `{ content: str, mentions: list[str], quoted_event_id?: str }`, dispatches to `chat_respond_as_role()` for single mention, frozen-context parallel fanout for multiple mentions, or `fanout_chatroom_all()` for @all; deduplicates when @all co-occurs with individual role mentions
- [ ] 6.2 Add `POST /meetings/{id}/messages` extension: accept optional `quoted_event_id` field for quote-inline references
- [ ] 6.3 Add test: `test_api.py::test_chat_mention_single_role` — POST /chat/mention with mentions=["Blue"] → 200, blue responds
- [ ] 6.4 Add test: `test_api.py::test_chat_mention_all` — POST /chat/mention with mentions=["all"] → 200, all roles respond
- [ ] 6.5 Add test: `test_api.py::test_chat_mention_empty_saves_human` — POST with mentions=[] → 200, human-message event only
- [ ] 6.6 Add test: `test_api.py::test_chat_mention_invalid_role_400` — POST with mentions=["Unknown"] → 400
- [ ] 6.7 Add test: `test_api.py::test_chat_mention_rejects_non_chatroom` — POST to relay meeting → 409
- [ ] 6.8 Add test: `test_api.py::test_chat_mention_multiple_roles` — POST with mentions=["Blue", "Red"] → 200, both Blue and Red respond in parallel with frozen context
- [ ] 6.9 Add test: `test_api.py::test_chat_mention_all_deduplicates` — POST with mentions=["all", "Blue"] → 200, all roles invoked once (Blue not double-invoked)

**Red light:** Tests 6.3–6.9 fail (endpoint doesn't exist).

## 7. Backend Context Token Budget

- [ ] 7.1 Implement `ChatroomContextBuilder` class: deterministic context assembly with priority (current message → quoted message → system instructions → recent history by reverse chronological order within token budget)
- [ ] 7.2 Add env var `AI_COUNCIL_CHATROOM_CONTEXT_TOKEN_BUDGET` (default 4096), read by ChatroomContextBuilder
- [ ] 7.3 Add test: `test_chatroom_context.py::test_context_includes_current_and_quoted` — verify current + quoted messages always present
- [ ] 7.4 Add test: `test_chatroom_context.py::test_context_respects_token_budget` — 50 messages, budget fits 10 → most recent 10 included, oldest dropped
- [ ] 7.5 Add test: `test_chatroom_context.py::test_context_deterministic` — same inputs → same context output
- [ ] 7.6 Add test: `test_chatroom_context.py::test_context_no_cross_meeting_leak` — events from other meetings never included

**Red light:** Tests 7.3–7.6 fail (class doesn't exist).

## 8. Backend Human-Message-Only Semantics

- [ ] 8.1 Ensure POST /meetings/{id}/messages (existing endpoint) works unchanged for chatroom: saves `human-message` event, no AI invocation
- [ ] 8.2 Add test: `test_api.py::test_chatroom_human_message_no_ai` — POST /messages in chatroom → human-message event, no AI events follow

**Red light:** Test 8.2 should pass immediately (existing behavior), but add to confirm contract.

## 9. Frontend Mention Autocomplete Component

- [ ] 9.1 Create `MentionAutocomplete.vue`: watches textarea `@` trigger, queries participants, renders dropdown with keyboard navigation (ArrowUp/Down, Enter/Tab, Escape)
- [ ] 9.2 Create `useMentionAutocomplete.ts` composable: manages trigger detection, filtered participant list, active index, selection, and text insertion
- [ ] 9.3 Add unit test: `test_mention_autocomplete.ts::test_trigger_on_at` — typing "@" activates the menu
- [ ] 9.4 Add unit test: `test_mention_autocomplete.ts::test_filters_participants` — typing "@B" filters to roles matching "B"
- [ ] 9.5 Add unit test: `test_mention_autocomplete.ts::test_select_inserts_role_id` — selecting "Blue" inserts "@Blue " into text
- [ ] 9.6 Add unit test: `test_mention_autocomplete.ts::test_all_option_present` — "@all" option always in menu
- [ ] 9.7 Add unit test: `test_mention_autocomplete.ts::test_escape_dismisses` — Escape closes menu without insertion
- [ ] 9.8 Add unit test: `test_mention_autocomplete.ts::test_no_autocomplete_non_chatroom` — component not rendered when mode != chatroom

**Red light:** Tests 9.3–9.8 fail (component doesn't exist).

## 10. Frontend Chatroom Composer

- [ ] 10.1 Create `ChatroomComposer.vue`: textarea + MentionAutocomplete + send button + optional quote-inline indicator + case-file "+" entry point
- [ ] 10.2 Implement mention parsing in send flow: extract @role and @all from message text, build `mentions` array for API call
- [ ] 10.3 Implement quote-inline: selecting "quote" on a message sets `quoted_event_id` in composer state; visual indicator above textarea; cleared on send
- [ ] 10.4 Wire case-file "+" button to existing case-files management flow
- [ ] 10.5 Add unit test: `test_chatroom_composer.ts::test_send_without_mention` — dispatches human-message API call
- [ ] 10.6 Add unit test: `test_chatroom_composer.ts::test_send_with_mention` — dispatches /chat/mention API call with mentions array
- [ ] 10.7 Add unit test: `test_chatroom_composer.ts::test_send_with_quote` — dispatches with quoted_event_id

**Red light:** Tests 10.5–10.7 fail (component doesn't exist).

## 11. Frontend Conversation Workspace Chatroom Adaptation

- [ ] 11.1 Modify `ConversationWorkspace.vue`: conditionally hide step progress bar, court CTA, and "開始新回合" when `activeMode.category === 'chatroom'`
- [ ] 11.2 Modify context panel: show mode badge "聊天室", omit goal when empty, omit parallel/relay progress
- [ ] 11.3 Render `ChatroomComposer` instead of `ActionBar` when mode is chatroom
- [ ] 11.4 Ensure message feed renders fanout responses in arrival order (event order from backend)
- [ ] 11.5 Add unit test: `test_conversation_workspace.ts::test_chatroom_hides_step_progress` — verify step bar not rendered
- [ ] 11.6 Add unit test: `test_conversation_workspace.ts::test_chatroom_shows_mode_badge` — verify "聊天室" badge in context panel
- [ ] 11.7 Add unit test: `test_conversation_workspace.ts::test_chatroom_uses_chatroom_composer` — verify ChatroomComposer rendered, ActionBar not

**Red light:** Tests 11.5–11.7 fail (adaptations not implemented).

## 12. Frontend useCouncil Integration

- [ ] 12.1 Extend `useCouncil.ts`: resolve chatroom mode from meeting's `mode_id`, set `activeModeSource` for chatroom
- [ ] 12.2 Implement `sendChatMessage(content, mentions, quotedEventId)` function: dispatches to POST /meetings/{id}/chat/mention or POST /meetings/{id}/messages based on mentions
- [ ] 12.3 Disable auto-start behavior for chatroom: `startSelectedMeeting()` no-ops or shows message when mode is chatroom
- [ ] 12.4 Add unit test: `test_use_council.ts::test_chatroom_mode_resolves` — opening chatroom meeting sets activeMode correctly
- [ ] 12.5 Add unit test: `test_use_council.ts::test_chatroom_no_auto_start` — start action disabled/no-op for chatroom

**Red light:** Tests 12.4–12.5 fail (chatroom routing not implemented).

## 13. Playwright E2E Tests

- [ ] 13.1 E2E: Create chatroom meeting (title only, no goal) → verify meeting created and opens in conversation workspace
- [ ] 13.2 E2E: Send plain text message in chatroom → verify human-message appears, no AI response
- [ ] 13.3 E2E: Send "@Blue 看看這個" → verify Blue's AI response appears with thinking indicator then completion
- [ ] 13.4 E2E: Send "@all 大家覺得呢？" → verify all roles respond, display in arrival order
- [ ] 13.4b E2E: Send "@Blue @Red 你們覺得呢？" → verify both Blue and Red respond in parallel, display in arrival order
- [ ] 13.5 E2E: Quote an existing message → verify quoted message context included in AI response
- [ ] 13.6 E2E: Reload chatroom meeting → verify all messages persist in correct order
- [ ] 13.7 E2E: @all with one role failing → verify partial success visible (2 completed, 1 failed indicator)
- [ ] 13.8 E2E: 375px viewport → verify chatroom layout responsive (composer visible, messages readable)
- [ ] 13.9 E2E: Verify no court CTA, no step progress bar, no "開始新回合" in chatroom mode
- [ ] 13.10 E2E: Mention autocomplete — type "@", verify participant list appears, select role, verify insertion

**Red light:** All 13.x tests fail (features not implemented).

## 14. Full Gates

- [x] 14.1 Run full backend `pytest` — 650 passed (baseline 605 + 45 new chatroom)
- [x] 14.2 Run full frontend unit `npm run test:unit` — 99 passed, 0 fail (baseline 61 + 38 new chatroom)
- [x] 14.3 Run `npm run build` — succeeded
- [x] 14.4 Run full Chromium e2e — 105/105 passed (94 existing + 11 new chatroom), zero regressions
- [ ] 14.5 Direct Chromium smoke: create chatroom → send message → @role → @all → reload → verify

## 15. Spec & Documentation Updates

- [ ] 15.1 Update `spec.md` §15 #91: mark as `implemented / awaiting acceptance` with date
- [ ] 15.2 Update `docs/HANDOFF.md`: add chatroom mode to completed features table, update baseline numbers
- [ ] 15.3 Update OpenSpec tasks status to reflect completion

## 16. Gate B & Merge

- [ ] 16.1 Prepare Gate B review packet: base, HEAD, branch, worktree, commit list, diff, red/green evidence, gate results
- [ ] 16.2 Submit for Codex Gate B review
- [ ] 16.3 After Gate B `ready`: merge exact reviewed HEAD to main
- [ ] 16.4 Post-merge: run read-only checks (pytest, unit, build, e2e) to confirm no merge drift
- [ ] 16.5 Clean up worktree and branch
- [ ] 16.6 Present Human Owner acceptance checklist with verifiable features

## 17. Acceptance Closeout (after Human Owner acceptance)

- [ ] 17.1 Create independent acceptance-closeout worktree from latest main
- [ ] 17.2 Update `spec.md` §15 #91 to `accepted / done` with date
- [ ] 17.3 Run `/opsx-sync` to sync delta specs to main specs
- [ ] 17.4 Run `/opsx-archive` to archive the change
- [ ] 17.5 Commit closeout chain
- [ ] 17.6 Submit for Codex closeout review
- [ ] 17.7 After closeout `ready`: fast-forward merge exact reviewed HEAD
- [ ] 17.8 Post-merge read-only checks and cleanup

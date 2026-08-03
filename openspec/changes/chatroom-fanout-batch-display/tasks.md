## 1. Projection: fanout round derivation

- [ ] 1.1 Add `in_response_to_event_id?: string` to `WorkspaceEvent` type in `frontend/src/meetingWorkspace.ts` (mirror the existing field already present in `frontend/src/api.ts` `MeetingEvent`)
- [ ] 1.2 Add round metadata fields to `WorkspaceMessage`: `fanoutRoundId?: string`, `fanoutMemberCount?: number`, `fanoutRoundStart?: boolean`, `fanoutRoundEnd?: boolean`, `fanoutMemberCompleted?: boolean`, `fanoutMemberFailed?: boolean`
- [ ] 1.3 Implement a pure helper in `meetingWorkspace.ts` (e.g. `fanoutRoundsFor(events)`) that: collects human-message event_ids, groups `chat-fanout-*` events by resolvable `in_response_to_event_id`, keeps arrival order, and returns per-round membership (members, completed count, failed count, member status per role)
- [ ] 1.4 Wire the helper into `projectMessages` so each projected message carries its round metadata; messages with `chat-fanout-*` step_id but unresolvable key get no round metadata (flat fallback)
- [ ] 1.5 Add `fanoutRounds` summary (round id → live progress) to `ConversationWorkspaceProjection` for the round header

## 2. Projection: expected member set + simultaneous thinking

- [ ] 2.1 Capture the send-time expected member set: in `sendChatroomMention` (useCouncil.ts:1114-1127), record the full queued role list (the `@all`/multi-mention expansion) as the round's expected members, keyed to the round before/after its `in_response_to_event_id` is known
- [ ] 2.2 Merge with arrived members: round expected set = captured queuedRoles ∪ roles seen via `chat-fanout-*` events for that round, aligned to participant roles (backend drops mentioned roles without a model assignment); round N = `|expected set|`, fixed once known, never growing with arrivals (reconnect/reload degradation → arrived-members-only, never over-counting; an expected slot that never emits an event does not block terminal)
- [ ] 2.3 In `projectRoles`, when `mode.category === 'chatroom'` and a fanout round is pending (per D3/D4), mark every pending expected member as `thinking` simultaneously, overriding `queueIndex === 0` for those members; relay/parallel/courtroom behavior unchanged
- [ ] 2.4 Three-phase transition: pre-event (`0/N`, all expected members thinking) → in-stream (`x/N`, arrived members stop thinking, remaining keep thinking) → terminal (completion/partial label, no member thinking); verify the pre-event window uses the captured expected set and composes with the event-derived window without discontinuity
- [ ] 2.5 Ensure a failed member is marked `failed` and does not block other members' thinking indicators

## 3. Projection: chatroom fanout failure semantics

- [ ] 3.1 In `applyPendingRoleUpdates` (useCouncil.ts:781-798), guard failure handling on "the event belongs to a chatroom fanout round"; for those events a failed member clears only its own pending slot (not `pendingRoles.value = []`) and does not collapse the round
- [ ] 3.2 Verify relay/parallel/courtroom failure behavior is untouched (full clear on first failure remains for those modes)
- [ ] 3.3 Verify a failed member keeps `data-status=failed` on its bubble (e2e 13.7) and is excluded from the header's completed count while still advancing the round toward terminal

## 4. Render: fanout round group in ConversationWorkspace

- [ ] 4.1 In `ConversationWorkspace.vue`, render a round group wrapper when a message's `fanoutRoundId` is set: open group on `fanoutRoundStart`, close on `fanoutRoundEnd`; keep each `article.workspace-message` markup, testids, quote button, avatar/name/time, and role-filter behavior unchanged
- [ ] 4.2 Render the round header with live progress: `N 位角色回應中` while pending (with `x/N 已回應`), completion label when all members done, partial label when a member failed
- [ ] 4.3 Ensure per-message grouping (avatar/name shown once per run) still works inside a round group; group header is presentational only and is not a message
- [ ] 4.4 Add testids for the round group and header (e.g. `fanout-round`, `fanout-round-header`) for e2e

## 5. Tests

- [ ] 5.1 Frontend unit tests: round grouping from events (order preserved), unresolvable key falls back flat, expected member set from send-time capture (N fixed, not arrival count), member completion/failed counts, simultaneous thinking projection, single-mention not grouped
- [ ] 5.2 Frontend unit tests (deterministic event fixtures): three-phase behavior as events arrive one-by-one (pre-event 0/N → in-stream x/N → terminal), failure-first ordering (a failed member arriving before its peers must not extinguish their thinking), reconnect/reload degradation (arrived-members-only, no over-count)
- [ ] 5.3 Playwright e2e: existing `chatroom.spec.ts` 13.4 / 13.7 / 13.22 stay green unchanged; extend with assertions that @all responses appear inside a fanout round group with header, and that multiple roles show thinking indicators simultaneously during the pending window
- [ ] 5.4 Run full frontend suite (`npm run test:unit`, `npm run build`, `npm run test:e2e`) green; backend unchanged

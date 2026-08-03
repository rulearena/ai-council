## 1. Projection: fanout round derivation

- [ ] 1.1 Add `in_response_to_event_id?: string` to `WorkspaceEvent` type in `frontend/src/meetingWorkspace.ts` (mirror the existing field already present in `frontend/src/api.ts` `MeetingEvent`)
- [ ] 1.2 Add round metadata fields to `WorkspaceMessage`: `fanoutRoundId?: string`, `fanoutMemberCount?: number`, `fanoutRoundStart?: boolean`, `fanoutRoundEnd?: boolean`, `fanoutMemberCompleted?: boolean`, `fanoutMemberFailed?: boolean`
- [ ] 1.3 Implement a pure helper in `meetingWorkspace.ts` (e.g. `fanoutRoundsFor(events)`) that: collects human-message event_ids, groups `chat-fanout-*` events by resolvable `in_response_to_event_id`, keeps arrival order, and returns per-round membership (members, completed count, failed count, member status per role)
- [ ] 1.4 Wire the helper into `projectMessages` so each projected message carries its round metadata; messages with `chat-fanout-*` step_id but unresolvable key get no round metadata (flat fallback)
- [ ] 1.5 Add `fanoutRounds` summary (round id → live progress) to `ConversationWorkspaceProjection` for the round header

## 2. Projection: simultaneous thinking for fanout members

- [ ] 2.1 In `projectRoles`, detect an active pending chatroom fanout round (round where some member has not completed/failed and `activity_status === 'running'`)
- [ ] 2.2 When such a round is active and `mode.category === 'chatroom'`, mark every pending member as `thinking` simultaneously (overriding the `queueIndex === 0` single-thinking rule for those members); relay/parallel/courtroom behavior unchanged
- [ ] 2.3 Ensure a failed member is marked `failed` and does not block other members' thinking indicators
- [ ] 2.4 Verify the transition: before the first completion event arrives, `pendingRoles` still lights thinking; once round events exist, event-derived state is authoritative

## 3. Render: fanout round group in ConversationWorkspace

- [ ] 3.1 In `ConversationWorkspace.vue`, render a round group wrapper when a message's `fanoutRoundId` is set: open group on `fanoutRoundStart`, close on `fanoutRoundEnd`; keep each `article.workspace-message` markup, testids, quote button, avatar/name/time, and role-filter behavior unchanged
- [ ] 3.2 Render the round header with live progress: `N 位角色回應中` while pending (with `x/N 已回應`), completion label when all members done, partial label when a member failed
- [ ] 3.3 Ensure per-message grouping (avatar/name shown once per run) still works inside a round group; group header is presentational only and is not a message
- [ ] 3.4 Add testids for the round group and header (e.g. `fanout-round`, `fanout-round-header`) for e2e

## 4. Tests

- [ ] 4.1 Frontend unit tests: round grouping from events (order preserved), unresolvable key falls back flat, member completion/failed counts, simultaneous thinking projection, single-mention not grouped
- [ ] 4.2 Playwright e2e: existing `chatroom.spec.ts` 13.4 / 13.7 / 13.22 stay green unchanged; extend with assertions that @all responses appear inside a fanout round group with header, and that multiple roles show thinking indicators simultaneously during the pending window
- [ ] 4.3 Run full frontend suite (`npm run test:unit`, `npm run build`, `npm run test:e2e`) green; backend unchanged

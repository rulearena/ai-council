## 1. Seat interaction unification (Chairman + role seats)

- [ ] 1.1 In `ConversationWorkspace.vue`, add a secondary detail-control (small icon button) inside each seat — Chairman and every role — wired to the existing `role-click` emit / `App.vue`'s `openRole` (`RoleDrawer`)
- [ ] 1.2 Change each seat's primary click (Chairman + role seats) to uniformly call `selectRole(...)`, treating `'Chairman'` as a filterable seat id
- [ ] 1.3 Update `meetingWorkspace.ts` filter helpers (`nextWorkspaceRoleFilter`, `latestWorkspaceMessageTarget`, etc.) to support `'Chairman'` as a filter target and to toggle off when the currently active seat is clicked again
- [ ] 1.4 Add visible "filtering active" styling (class/badge) in `styles.css` for whichever seat currently drives the filter
- [ ] 1.5 Add test: `frontend/tests/unit/meetingWorkspace.test.ts` — clicking the already-active filtered seat clears the filter; clicking Chairman filters to Chairman's messages
- [ ] 1.6 Add/update test: `frontend/tests/e2e/chatroom.spec.ts` — seat click behavior is identical for Chairman and role seats (filter on first click, clear on second click of the same seat)

**Red light:** 1.5–1.6 fail before the change (Chairman seat opens the drawer instead of filtering; re-clicking a filtered role seat does not clear the filter).

## 2. Message avatars in feed

- [ ] 2.1 In `ConversationWorkspace.vue`, add an avatar element to the `workspace-message` header, reusing `roleIcon(message.roleId)` / `RoleSilhouette` fallback (same resolution already used in the role rail)
- [ ] 2.2 Add avatar sizing/layout styles in `styles.css` for the message header (small circular avatar, ~20px)
- [ ] 2.3 Add test: `frontend/tests/unit/meetingWorkspace.test.ts` or a component test — AI/synthesizer message headers render an avatar element
- [ ] 2.4 Add/update e2e assertion in `frontend/tests/e2e/chatroom.spec.ts` that a message card contains an avatar image or silhouette

**Red light:** 2.3–2.4 fail before the change (no avatar markup exists in the message header).

## 3. Chatroom listed first in the mode picker

- [ ] 3.1 Reorder `config/modes.yaml`: move the `chatroom` block to be the first entry (currently 7th/last)
- [ ] 3.2 Run the existing backend mode-catalog tests to confirm reordering does not break validation (order is not a validated field, but confirm no test hardcodes position)
- [ ] 3.3 Add/update a test asserting the mode list (backend `GET /modes` response or frontend `modeCatalog`/`NewCaseModal` render order) has `chatroom` first

**Red light:** 3.3 fails before the change (chatroom currently sorts last).

## 4. Scene enlargement (lightbox)

- [ ] 4.1 In `ConversationWorkspace.vue`, add a click handler on the scene image inside `workspace-scene-details` that opens the existing `Modal.vue` with the scene rendered larger
- [ ] 4.2 Add enlarged-scene styling in `styles.css`
- [ ] 4.3 Add test: clicking the scene image opens a modal containing the enlarged scene

**Red light:** 4.3 fails before the change (no click handler/modal exists for the scene image).

## 5. In-rail model switching

- [ ] 5.1 Add a per-seat model control to `workspace-role-button` in `ConversationWorkspace.vue`, reusing `selectedModels`, `models`, `updateSelectedModel`, `testSelectedModel` already exposed by `useCouncil.ts`; the existing `workspace-role-model` label becomes the trigger for a compact inline select
- [ ] 5.2 Remove the `participantModels` model-select section from `MeetingSettingsDrawer.vue` (title/goal/scene/case-type editing stay)
- [ ] 5.3 Add test: `frontend/tests/unit` — activating a seat's model control and selecting a different model calls `updateSelectedModel` and updates the seat's model label
- [ ] 5.4 Add/update e2e test: switch a role's model directly from the role rail, without opening meeting settings

**Red light:** 5.3–5.4 fail before the change (no model control exists on the seat; model change only reachable via `MeetingSettingsDrawer`).

## 6. Context panel records tab

- [ ] 6.1 Add a tab toggle (脈絡／紀錄) to the `workspace-context-panel` header in `ConversationWorkspace.vue`
- [ ] 6.2 Port `RecordsDrawer.vue`'s content/data source into a records-tab section rendered within the context panel
- [ ] 6.3 Retire `RecordsDrawer.vue` as a standalone top-level modal: remove its separate trigger from `TopBar.vue` and `App.vue`; refactor it into a records sub-component rendered inside the context panel's records tab (keep the component file as the tab's internal view rather than inlining its complex timeline/transcript/epoch logic)
- [ ] 6.4 Add test: selecting the records tab in the context panel displays the meeting's records

**Red light:** 6.4 fails before the change (records are only reachable via the separate `RecordsDrawer` modal).

## 7. TopBar subnav consolidation

- [ ] 7.1 Remove `case-materials-button` and `records-button` from `TopBar.vue`'s `meeting-subnav`
- [ ] 7.2 Add a pencil icon button beside `meeting-title-pill` in `top-bar-left`, wired to the existing `open-meeting-settings` emit; remove `meeting-settings-button` from `meeting-subnav`
- [ ] 7.3 Remove the now-empty `meeting-subnav` row and its styles once no buttons remain in it
- [ ] 7.4 Update e2e tests referencing the old subnav testids (`meeting-settings-button`, `case-materials-button`, `records-button`) to target their new locations
- [ ] 7.5 Add test asserting no `meeting-subnav` row renders when a meeting is open

**Red light:** 7.5 fails before the change (the subnav row currently always renders for an open meeting).

## 8. Message feed scroll fix

- [ ] 8.1 Reproduce the reported wheel-scroll failure live in-browser across relay/parallel/chatroom meetings; note the exact trigger condition (idle feed vs. actively streaming, specific viewport, input device)
- [ ] 8.2 Identify root cause (e.g. pointer-events overlap from an adjacent element, a missing height constraint somewhere in the ancestor chain despite the `min-height: 0` chain looking correct in `styles.css`, or a `scroll-behavior: smooth` interaction with rapid re-renders during streaming)
- [ ] 8.3 Implement the fix in `ConversationWorkspace.vue` / `styles.css` based on the 8.2 findings
- [ ] 8.4 Add a regression e2e test verifying the message feed scrolls via wheel/trackpad input, including while a response is actively streaming

**Red light:** 8.1 is a spike (no fixed red-light test until root cause is known); 8.4 must fail against the pre-fix build once written, to confirm it actually detects the reported bug.

## 9. Verification

- [ ] 9.1 Run the frontend unit test suite
- [ ] 9.2 Run the frontend e2e suite
- [ ] 9.3 Run the backend test suite (confirms the `config/modes.yaml` reorder doesn't break anything backend-side)
- [ ] 9.4 Manual smoke test walking through all eight fixed points (seat clicks, filter toggle, avatars, mode picker order, scene lightbox, in-rail model switch, context panel records tab, topbar consolidation); prepare the review packet for Gate B

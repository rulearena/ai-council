## Context

Backlog #91 (`ai-chat-room`) shipped the chatroom mode and is merged to main but not yet archived — the Human Owner's acceptance pass found nine UX problems in the shared `ConversationWorkspace.vue` chrome (role rail, message feed, top subnav, context panel) that block sign-off. All nine were verified against the current source:

- `ConversationWorkspace.vue`: Chairman seat (hardcoded button, opens `RoleDrawer`) vs. role seats (`selectRole()`, filters the feed) diverge in click behavior. The filter is cleared by a "顯示全部發言" button in the conversation header, physically far from the seat that set it.
- `workspace-message` article headers render `{{ message.roleName }}` only — no avatar, even though the role rail one column over already resolves `roleIcon()` per role.
- `config/modes.yaml` lists `chatroom` as its 7th (last) entry; `refreshModeCatalog()` replaces the whole `modeCatalog` array in file order, so the new-meeting mode picker shows chatroom last.
- The role scene (`CouncilStage`) only renders small, inside a collapsed `<details>` in the context panel, with no enlarge affordance.
- Model switching lives in `MeetingSettingsDrawer.vue` (`participantModels` selects), reached via the top-left "會議設定" button — not discoverable from the role rail where users look first.
- `TopBar.vue`'s `meeting-subnav` row has three buttons (會議設定／案卷與證據／議事紀錄) that duplicate functionality available elsewhere (composer "+" / `ActionBar` already open materials) or can be relocated to reclaim the row.
- `.workspace-message-feed` reportedly does not respond to mouse-wheel scrolling, despite `min-height: 0` / `overflow-y: auto` being present through the flex/grid ancestor chain in `styles.css` — root cause unconfirmed from static review.

## Goals / Non-Goals

**Goals:**
- Make seat interaction (Chairman + role seats) behave identically for the primary click.
- Make the message filter symmetric: the seat that opens a filter also closes it.
- Add avatars to feed messages, matching the role rail.
- Present `chatroom` first in the mode picker.
- Let the scene image be viewed enlarged.
- Move model switching into the role rail.
- Remove the `TopBar` subnav row by relocating its three entries.
- Find and fix the message-feed scroll failure.

**Non-Goals:**
- Per-meeting customizable role names/count/portraits (backlog'd per Owner decision; roles stay sourced from the fixed roster in `config/modes.yaml`).
- Any change to chatroom execution semantics (`@role`/`@all`, token budget, event schema) — this change is presentation-only.
- Any backend/API change.

## Decisions

**Seat click unification.** Both the Chairman seat and role seats keep their two existing actions (filter feed / open detail drawer) but expose them the same way: the seat's primary click now filters the feed for every seat type, including Chairman (filtering to Chairman's own record/announcement events). Each seat gains a small secondary "ⓘ" affordance (icon button inside the seat) that opens the existing detail view (`RoleDrawer`, already implemented for both roles and Chairman via `openRole` in `App.vue`). This reuses `RoleDrawer` unchanged and only touches which handler the seat's main click vs. its inner icon button call.
- *Alternative considered*: make Chairman non-filterable (Chairman has no feed messages in most modes) and instead make role seats also open the detail drawer on primary click, moving filtering to a secondary control. Rejected — filtering-by-click is the more frequent action per the Owner's report ("找了半天"), so it should stay the cheap, primary gesture.

**Symmetric filter toggle.** Clicking an already-active (filtered) seat clears the filter — same seat, same click, toggles. The seat also gets a visible `data-status`/class-driven "filtering" indicator (ring or badge) so it's clear which seat is currently isolating the feed. The existing "顯示全部發言" button in the conversation header stays as a secondary, always-visible escape hatch (useful once scrolled away from the rail) but is no longer the only way to clear a filter.

**Message avatars.** `workspace-message` header gains the same `roleIcon(message.roleId)` / `RoleSilhouette` fallback markup already used in the role rail, sized smaller (~20px) to fit the message header row. No new asset pipeline — reuses `ROLE_ICON_ASSETS`.

**Mode picker order.** Purely a `config/modes.yaml` entry reorder (move the `chatroom` block to be first). `refreshModeCatalog()` already does a full in-order `splice`, so no frontend code changes needed. Verified no code elsewhere depends on mode array index (search shows only `.find()` / `.filter()` by `id`).

**Scene lightbox.** Clicking the scene image inside `workspace-scene-details` opens the existing `Modal.vue` shell with the scene rendered at a larger size. No new modal component.

**Model switcher relocation.** The per-role model select currently in `MeetingSettingsDrawer.vue` moves to sit under each role seat in `workspace-role-rail` (reusing `selectedModels`, `models`, `updateSelectedModel`, `testSelectedModel` already exposed by `useCouncil.ts` — this is a template/markup move, not new state). `MeetingSettingsDrawer.vue` drops the `participantModels` section; meeting title/goal/scene/case-type editing stay there. The seat's existing small model-label text (`workspace-role-model`) becomes the click target that opens a compact inline select.
- *Risk*: seat real estate is already tight (92px rail column). Mitigate by keeping the control collapsed to the existing label text until clicked/focused, rather than always-on inline `<select>`.

**TopBar subnav removal.**
- 案卷與證據: removed from `TopBar`. Chatroom already has the composer "+" entry point (existing `ai-chat-room` requirement); relay/parallel modes already have it via `ActionBar embedded @open-materials`. The TopBar button was a redundant third entry point.
- 會議設定: removed from `TopBar` subnav; a pencil icon button is added beside `meeting-title-pill` in `top-bar-left`, wired to the same `open-meeting-settings` emit.
- 議事紀錄: removed from `TopBar` subnav; `RecordsDrawer`'s content is folded into `workspace-context-panel` as a second tab (脈絡／紀錄) alongside the existing context body, toggled by a small tab control in the panel header. `RecordsDrawer.vue` as a standalone modal is retired once its content is reachable from the panel.

**Scroll investigation.** Root cause not yet known — will be diagnosed live in-browser (mouse wheel / trackpad event path, possible pointer-events overlap, possible `scroll-behavior: smooth` + rapid re-render interaction from streaming AI messages) before writing the fix task in detail. Task list keeps this as a spike-then-fix pair rather than a pre-committed patch.

## Risks / Trade-offs

- [Risk] Folding 案卷與證據／議事紀錄 into existing panels could hide affordances users already learned in the merged (but not yet accepted) build. → Mitigation: keep icon/label text explicit (not icon-only) so the relocated entry points remain discoverable; this is acceptance feedback specifically asking for this consolidation, so the learned-affordance cost is accepted by the Owner.
- [Risk] Moving model switching into the cramped 92px role rail could feel crowded on smaller viewports. → Mitigation: reuse the existing collapsed-label pattern; only expand to a select on interaction.
- [Risk] `config/modes.yaml` reorder is low-risk but touches a config file also read by backend tests/fixtures. → Mitigation: run existing backend mode-catalog tests after reorder; order is not a validated field.
- [Risk] Scroll bug's root cause is unknown going in; the fix scope could grow once reproduced live. → Mitigation: task list treats repro as its own step before committing to a specific patch.

## Migration Plan

Frontend + config only; no data migration. Roll out as a normal merge to main once Gate B (manual smoke test) passes again, same process used for `ai-chat-room`. Rollback is a normal git revert (no persisted-state impact).

## Open Questions

- None blocking — all ambiguous points (records placement, model-switch location, custom-role scope) were resolved with the Owner before writing this design.

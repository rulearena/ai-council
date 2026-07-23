## Why

Human Owner acceptance testing of backlog #91 (chatroom mode, merged to main, change `ai-chat-room` still unarchived) surfaced nine concrete UX problems in the shipped Conversation workspace: inconsistent seat behavior, an asymmetric filter toggle, no message avatars, chatroom listed last in the mode picker, no scene enlargement, a buried model-switch entry point, a cluttered top subnav, a non-functional mouse-wheel scroll on the message feed, and non-enlargeable scene images. Eight of these are addressed in this change; the ninth (per-meeting customizable role names/count/portraits) is deferred to backlog #93 per the Owner's decision. All eight block acceptance sign-off and must be resolved before `ai-chat-room` can be archived.

## What Changes

- Unify seat click behavior: the Chairman seat and role seats in `workspace-role-rail` currently trigger different actions (detail drawer vs. message filter); make them consistent.
- Make the message filter toggle symmetric: clicking an active role seat again clears the filter, with a visible "filtering" state on the seat itself, instead of requiring a separate "顯示全部發言" button in a different screen region.
- Add role avatars to `workspace-message` cards (currently text-only headers), reusing the same portrait assets already shown in the role rail.
- Reorder `config/modes.yaml` so `chatroom` is the first entry, making it the default/first option in the new-meeting mode picker.
- Add a click-to-enlarge (lightbox) interaction for the role scene image currently shown only in a small collapsed panel in the context sidebar.
- Move the per-role model switcher from the `MeetingSettingsDrawer` into the role rail, as a control on/under each role seat.
- Consolidate the `TopBar` meeting subnav (會議設定／案卷與證據／議事紀錄): fold 案卷與證據 into the existing composer "+" materials entry point, move 會議設定 to a pencil icon beside the meeting title, and fold 議事紀錄 into the existing `workspace-context-panel` (會議脈絡) as an additional section/tab.
- Investigate and fix the reported mouse-wheel scroll failure on `workspace-message-feed` (root cause not yet confirmed from static CSS review; requires live browser repro).

Explicitly out of scope (deferred to backlog per Owner decision): making role names, role count, and portraits customizable per meeting. Roles remain sourced from the fixed roster defined per mode in `config/modes.yaml`.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `conversation-workspace`: seat interaction model (unified click behavior, symmetric filter toggle, in-rail model switching, message avatars), context panel gains a records section, scene view gains enlargement.
- `chatroom-mode`: mode catalog ordering (`chatroom` presented first in the mode picker) — presentation-only, no execution semantics change.

## Impact

- **Frontend**: `ConversationWorkspace.vue` (seat rendering, filter logic, message header markup), `TopBar.vue` (subnav removal), `MeetingSettingsDrawer.vue` (model switcher removed), `RoleDrawer.vue`/role rail (model switcher added), `RecordsDrawer.vue` (content moves into context panel), `CouncilStage.vue`/scene panel (lightbox), `styles.css` (new avatar, lightbox, in-rail model control, scroll fix styles).
- **Config**: `config/modes.yaml` entry order (`chatroom` moved to first position); no schema change.
- **No backend or API changes.**
- **No changes** to `structured-mentions` or chatroom execution semantics (fanout, directed response, token budget).

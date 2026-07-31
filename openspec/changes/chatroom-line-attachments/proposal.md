## Why

Human Owner acceptance of #92 (2026-07-31) revealed the chatroom's `+` button promises upload ability via an "附件（0）" label but only opens the text-only `CaseMaterialsModal`; the only binary file upload in the system is `NewCaseModal.vue` (`.txt/.md` read as text) with no binary attachment contract in the backend. The Human Owner ruled in favor of LINE-style chat attachments: files uploaded via `+` appear as downloadable message bubbles in the chat feed, with `.txt/.md` fed into the existing versioned case-files contract (AI-visible) and PDF/images stored as binary attachments (AI-invisible). This reverses spec.md #90's "no second message-attachment contract" decision and is an explicit scope expansion (registered as backlog #96).

## What Changes

- **New binary attachment store**: files are stored as blobs in a data-dir attachments directory (`<meeting_id>/attachments/`), keyed by `file_id`; metadata (filename, size, mime_type, file_id) is appended as events to `events.jsonl`. Downloads resolve the real path by `file_id`.
- **New upload/download endpoints**: an upload endpoint (multipart) appends the metadata event and stores the blob; a download endpoint serves the blob by `file_id`. No delete or deactivate in v1 (events are append-only history).
- **File-type routing and limits**: `.txt/.md/.markdown` follow the existing versioned case-files contract (per-file char limit, visible_roles, revision) and are AI-visible. PDF/PNG/JPG are binary attachments (10 MB/file, 50 MB/meeting, env-overridable) and are AI-invisible. Other types are rejected in v1.
- **Binary attachments are visible/downloadable to all participants**; text files keep the existing case-files `visible_roles`.
- **Unified `+` modal**: the existing `CaseMaterialsModal` gains an upload zone on top of the existing case-files list. "附件（N）" count = binary + text attachments total. Courtroom mode reuses the same modal with "證物" wording.
- **Chat feed presentation**: images render as inline thumbnails with a lightbox; PDFs render as cards (filename/size/download); text files only appear in the case-files modal, never as chat bubbles.
- **Upload timing**: files upload immediately on selection (no required accompanying text); upload state and inline errors are shown.
- **AI is fully unaware of binary attachments**: they are not injected into the prompt and not mentioned in context.

## Capabilities

### New Capabilities
- `chatroom-attachments`: binary attachment contract — blob storage, metadata events, upload/download endpoints, file-type routing, limits, and the append-only no-delete rule.

### Modified Capabilities
- `conversation-workspace`: reverses the "No new attachment format is created" requirement; adds the unified `+` attachment modal, chat-bubble attachment rendering (inline image + lightbox, PDF cards, text stays in the case-files modal), the "附件（N）" total count, and courtroom "證物" wording.

## Impact

- `backend/ai_council/meetings/`: new attachment store module (blob + events) analogous to `case_materials.py`; meeting routes gain upload/download endpoints; `events.jsonl` gains a new event kind; data-dir gains an attachments directory layout.
- `frontend/src/components/CaseMaterialsModal.vue`: adds upload zone, attachment count, and list integration.
- `frontend/src/components/ConversationWorkspace.vue` (and message card): renders attachment bubbles (image thumbnail + lightbox, PDF cards) and wires the download URL.
- `CONTEXT.md`: "附件" (binary) vs "案卷" (text) domain terms already recorded.
- No change to chatroom execution semantics (`@`/`@all`, token budget), no rewrite of historical events, no model-switching or meeting-settings changes.

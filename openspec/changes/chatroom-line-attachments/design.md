## Context

Chatroom UX acceptance (#92, 2026-07-31) surfaced that the `+` button and its "附件（N）" label promise uploads that do not exist: `CaseMaterialsModal.vue` only handles text case-files (`title + content + visible_roles`), and the only binary upload in the system is `NewCaseModal.vue`, which reads `.txt/.md` as text. The backend has no binary attachment contract: `case_materials.py` `MaterialVersion` is `title+content` only, and `repository.py` persists `case_files.json` plus an append-only `events.jsonl`. Backlog #96 (Human Owner approved scope expansion) mandates LINE-style attachments. This reverses spec.md #90's "no second message-attachment contract" decision.

Eight grilling decisions are locked (recorded in `CONTEXT.md`): blob storage + metadata events; `.txt/.md` → existing case-files contract, all other file types → binary attachments; binary visible to all participants; image thumbnail + lightbox, PDF card, text stays in modal only; unified `+` modal with total "附件（N）" count, courtroom "證物" wording; immediate upload on selection; no delete/deactivate; AI unaware of binary attachments.

## Goals / Non-Goals

**Goals:**
- Binary attachment contract: blob storage under data-dir, append-only metadata events, upload/download endpoints, per-file and per-meeting limits.
- LINE-style feed presentation: image bubbles (thumbnail + lightbox), PDF cards, download by `file_id`.
- Unified `+` entry: one modal with upload zone + existing case-files list; "附件（N）" = binary + text; courtroom "證物" wording.
- Deterministic backend tests for storage/limits/routing; frontend unit tests for projection; Playwright coverage.

**Non-Goals:**
- No delete/deactivate for attachments in v1 (append-only history).
- No AI knowledge of binary attachments (not in prompt, not in context).
- No new message/chat semantics, token-budget changes, or free-form chat mode.
- No rewriting, backfilling, or migration of historical events.
- No new external dependencies (no object storage, no DB — filesystem + JSONL only, matching existing architecture).

## Decisions

### D1: Blob storage layout mirrors the meeting directory
Store blobs under `data_dir/meetings/<meeting_id>/attachments/<file_id>`. This matches the existing `_meeting_dir` pattern in `repository.py:146` (which already validates `meeting_id` against `SAFE_MEETING_ID`). `file_id` is a new UUID hex (e.g. `attachment-{uuid4.hex}`) generated at upload; the blob filename on disk is the `file_id` (no user-supplied filename in the path → no path traversal). Meeting deletion (`repository.delete`) already `rmtree`s the meeting dir, so attachments are cleaned up with the meeting for free.
- *Alternative considered*: a flat global `attachments/` dir with `meeting_id` in the filename — rejected because it breaks the per-meeting directory invariant and the free cleanup.

### D2: Metadata lives in `events.jsonl` as a new event kind
Append an event of kind `attachment-added` via `repository.append_event` (`repository.py:31`), carrying `{file_id, filename, size, mime_type, extension, meeting_id, role: "Human", status: "completed"}` plus the standard `event_id`/`step_id` fields (mirroring the human-message shape in `api.py:1906`). Download resolves the real path by reading the event log and looking up `file_id`. The blob is written before the event is appended so a metadata event never points at a missing blob.
- *Alternative considered*: a separate `attachments.json` like `case_files.json` — rejected: violates the decision that metadata is append-only history, and would create a second source of truth not driven by events.

### D3: File-type routing and limits follow the case-file pattern
- `.txt/.md` → existing `CaseMaterials.add_evidence`/`add_note` path (per-file char limit, `visible_roles`, revisioning, `pending_impact`). The unified modal shows these in the existing case-files list, never as bubbles.
- All other file types → binary attachment. Defaults 10 MB/file and 50 MB/meeting, read from environment variables with the same `_positive_integer_environment` pattern (`api.py:130`). MIME is inferred from a fixed extension→MIME map (not trusted from client headers); unknown extensions fall back to `application/octet-stream`.
- *Alternative considered*: sniffing content via `python-magic` — rejected: adds a dependency; a fixed extension→MIME map is sufficient for a local single-user app.

### D4: Upload and download endpoints
- `POST /meetings/{meeting_id}/attachments` — multipart/form-data (one file per request, matching the immediate-per-file upload UX), gated by the same `meeting_transitions.synchronized` guard used by other meeting writes. Validates extension, size, aggregate quota, then writes blob + appends event. Returns the metadata event.
- `GET /meetings/{meeting_id}/attachments/{file_id}` — resolves path from events, serves with `Content-Type` from the metadata MIME and `Content-Disposition: attachment` (inline for images). Unknown `file_id` → 404.
- Quota accounting reads the meeting's existing attachment events (count of `attachment-added` events) rather than maintaining a separate counter file, keeping a single source of truth.
- *Alternative considered*: base64 JSON payload like case-files — rejected: wasteful for 10 MB files and misaligned with browser upload UX; multipart is standard for the frontend `input[type=file]`.

### D5: Frontend — unified modal and feed projection
- `CaseMaterialsModal.vue` gains an upload zone above the existing case-files list. File selection immediately POSTs (per decision #6); per-file status (uploading / done / error) renders inline with retry. The modal is reused across modes; courtroom labels binary attachments and case-files with "證物" wording (existing mode-aware terminology from #92 round 2).
- "附件（N）" count = binary attachment events + active case-files. The count source comes from the meeting payload: extend `GET /meetings/{meeting_id}` `case_materials_summary` (or add an `attachments_summary`) so the label stays truthful on reload.
- Message feed: events of kind `attachment-added` project to bubbles. Images render inline thumbnail; clicking opens a lightbox (reusing the existing modal/overlay pattern). PDFs render a card with filename/size + download link to the endpoint. Text case-files never render as bubbles.
- *Alternative considered*: separate attachment component file per type — rejected; keep a single `AttachmentBubble`-style render inside the message card with a small type switch.

### D6: Attach timing, errors, and append-only rule
- Immediate upload on selection; no accompanying text required; inline progress and error with retry (matches decision #6 and the existing inline-error style).
- No delete/deactivate UI and no removal endpoint in v1; attachments are append-only history (decision #7). A future `attachment-deleted` marker event remains a backward-compatible addition.

### D7: AI unawareness enforced at the boundary
Binary attachment events are excluded from every prompt-assembly path (`runner.py`, `chatroom_context.py`) and from the context projection (`chatroom_context.py`). The AI prompt and context contain no attachment metadata. Text case-files continue through the existing case-file injection contract unchanged. A test asserts the assembled prompt/context contains no `attachment` fields.

## Risks / Trade-offs

- [Mistaken upload is permanent] → No delete in v1 by design (append-only); mitigate with a confirm step before upload in the modal; future marker-event option documented.
- [Attachment blobs leak on meeting delete] → Blobs live under the meeting dir, so `repository.delete` cleans them; add a test asserting attachment cleanup on meeting deletion.
- [Aggregate quota drifts if events are hand-edited] → Quota is projected from `attachment-added` events; events are the single source of truth and are append-only, so drift requires manual tampering (accepted for a local single-user app).
- [AI unawareness regresses if a new prompt path is added] → Boundary test on prompt/context assembly guards it; document in `CONTEXT.md` (already records 附件 vs 案卷 terms).
- [Uploaded filename collides or contains unsafe characters] → Disk name is always `file_id`; original filename is metadata only, so no filesystem risk.

## Migration Plan

No migration. This is a purely additive capability: new endpoints, a new event kind, new modal zone, and feed projection. Existing meetings with only case-files are unaffected; `CaseMaterialsModal` gains the upload zone for all modes. No historical events are rewritten.

## Open Questions

None blocking. Implementer may choose the exact `attachment-added` event field names as long as they match the download/projection contract in the delta specs.

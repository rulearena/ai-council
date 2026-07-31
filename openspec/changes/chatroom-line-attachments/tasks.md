## 1. Backend: attachment storage layer

- [ ] 1.1 Add `backend/ai_council/meetings/attachments.py` with `AttachmentLimits` dataclass (per_file_bytes, per_meeting_bytes) and an environment-driven `from_environment()` mirroring `_positive_integer_environment`; default 10 MB / 50 MB
- [ ] 1.2 Add extension → category routing (`text` for .txt/.md/.markdown, `binary` for .pdf/.png/.jpg/.jpeg, else rejected) and a fixed extension → MIME map
- [ ] 1.3 Implement blob write: `save_blob(meeting_id, file_id, stream) -> Path` writing under `data_dir/meetings/<meeting_id>/attachments/<file_id>`
- [ ] 1.4 Implement metadata event append: `record_attachment(meeting_id, file_id, filename, size, mime_type)` via `repository.append_event` with kind `attachment-added` and standard `event_id`/`step_id`/`role: "Human"` fields
- [ ] 1.5 Implement aggregate quota projection from `attachment-added` events (no separate counter file)
- [ ] 1.6 Implement download path resolution by `file_id` (read events, find `attachment-added` event, resolve real path; unknown id → None)
- [ ] 1.7 Ensure `repository.delete` cleans the attachments subdirectory with the meeting dir (verify existing `rmtree` covers it; add test)

## 2. Backend: upload/download endpoints

- [ ] 2.1 Add `POST /meetings/{meeting_id}/attachments` (multipart, one file) with `meeting_transitions.synchronized` guard; validate meeting exists/not terminal; reject running meeting like `add_meeting_message`
- [ ] 2.2 Enforce extension whitelist, per-file size limit, and per-meeting aggregate quota; return 400 with clear error message on rejection (no blob/event written)
- [ ] 2.3 Write blob then append metadata event; return the metadata event JSON
- [ ] 2.4 Add `GET /meetings/{meeting_id}/attachments/{file_id}` serving the blob with metadata MIME, `Content-Disposition: attachment` (inline for images), 404 for unknown file_id
- [ ] 2.5 Wire `attachments_summary` (count + total bytes) into `GET /meetings/{meeting_id}` and `GET /meetings` list payload so the frontend count stays truthful on reload

## 3. Backend: AI unawareness boundary

- [ ] 3.1 Exclude `attachment-added` events from all prompt-assembly paths (`runner.py`, `chatroom_context.py`) and from the context projection
- [ ] 3.2 Add a regression test asserting the assembled prompt/context contains no attachment metadata for a meeting that has binary attachments

## 4. Backend: deterministic tests

- [ ] 4.1 Tests: blob written before event; event carries file_id/filename/size/mime_type
- [ ] 4.2 Tests: extension routing (.txt/.md → text contract path; .pdf/.png/.jpg → binary; .zip → rejected with no blob/event)
- [ ] 4.3 Tests: per-file and per-meeting size limits enforced (default and env-overridden)
- [ ] 4.4 Tests: download by file_id resolves real path, returns correct content-type, 404 for unknown id
- [ ] 4.5 Tests: unknown file_id rejected; meeting deletion removes attachment blobs
- [ ] 4.6 Tests: `attachments_summary` counts and bytes correct in meeting payloads

## 5. Frontend: unified `+` modal with upload zone

- [ ] 5.1 Extend `CaseMaterialsModal.vue` with an upload zone above the existing case-files list; mode-aware "證物" wording for binary attachments in courtroom
- [ ] 5.2 Wire file selection to immediate `POST /attachments` (per file); render uploading / done / error states inline with retry
- [ ] 5.3 Update "附件（N）" count to total binary attachments + active case-files; refresh from meeting payload
- [ ] 5.4 Update `frontend/src/api.ts` with `uploadAttachment` (multipart) and `attachmentDownloadUrl(fileId)` helpers
- [ ] 5.5 Frontend unit tests for upload state machine (uploading/done/error/retry) and count computation

## 6. Frontend: attachment bubbles in feed

- [ ] 6.1 Project `attachment-added` events to message-feed bubbles in `ConversationWorkspace.vue` message card (image thumbnail + lightbox; PDF card with filename/size/download)
- [ ] 6.2 Ensure text case-files never render as chat bubbles (existing modal-only behavior preserved)
- [ ] 6.3 Frontend unit tests for bubble projection (image vs PDF vs text-not-a-bubble) and lightbox behavior
- [ ] 6.4 Playwright e2e: upload an image through `+`, assert bubble + thumbnail + download; upload a PDF, assert card; upload unsupported type, assert inline error

## 7. Docs and wiring

- [ ] 7.1 Sync `CONTEXT.md` if domain terms need extension (附件 vs 案卷 already recorded; verify)
- [ ] 7.2 Update `docs/HANDOFF.md` snapshot (this change in flight)
- [ ] 7.3 Run full backend + frontend test suites and build; all green

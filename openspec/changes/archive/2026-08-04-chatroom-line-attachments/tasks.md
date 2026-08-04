## 1. Backend storage, routing, and lifecycle

- [x] 1.1 Add attachment limits (10 MB/file, 50 MB/meeting by default, environment overridable) and extension/MIME routing.
- [x] 1.2 Write blobs under the meeting attachment directory before appending `attachment-added` metadata events.
- [x] 1.3 Project attachment metadata, aggregate quota, download paths, and meeting cleanup from events.
- [x] 1.4 Route `.txt`/`.md` through the existing text-material contract; route every other extension to binary storage without a whitelist.
- [x] 1.5 Add append-only `attachment-removed` tombstones, blob deletion, quota release, removed-event projection, and download 404 behavior.
- [x] 1.6 Remove mirrored chatroom text evidence before tombstoning; guard legacy title fallback (0/1/>1 matches) and missing evidence IDs.

## 2. Backend API and projection boundaries

- [x] 2.1 Implement multipart upload and file download endpoints with synchronized transitions, terminal/running guards, limits, and safe MIME/content disposition.
- [x] 2.2 Implement all-mode attachment deletion with neutral irreversible confirmation support and the accepted running-meeting rejection.
- [x] 2.3 Keep binary attachments independent of `visible_roles`; keep text evidence visibility unchanged.
- [x] 2.4 Suppress chatroom `pending_impact` in material mutation and read projections, including legacy pending state.
- [x] 2.5 Exclude binary attachments and tombstones from runner, chatroom context, transcript, and other AI prompt projections.

## 3. Frontend upload, management, and feed

- [x] 3.1 Replace the modal/quick-menu upload entry with the direct LINE-style `+` native file picker; keep resident input and per-file upload state.
- [x] 3.2 Move attachment/material management and upload progress into the context panel materials tab with courtroom vocabulary.
- [x] 3.3 Render image thumbnail/lightbox, PDF/generic binary cards, and chatroom text reader cards; keep full text out of the feed.
- [x] 3.4 Show removed attachment bubbles as non-interactive “已刪除” cards and expose delete controls for all modes.
- [x] 3.5 Keep attachment counts and materials reload projections consistent, including removed attachments and chatroom text mirroring.

## 4. Verification and closeout

- [x] 4.1 Backend tests cover storage ordering, routing, limits, download/404, visibility, deletion, tombstones, evidence removal, quota, and AI exclusion.
- [x] 4.2 Frontend unit tests cover upload state, projection, counts, text reader, removal, and chatroom impact behavior.
- [x] 4.3 Focused/full relevant E2E and build evidence are recorded; Human Owner acceptance was obtained on 2026-08-04.
- [x] 4.4 Update canonical backlog and handoff with acceptance evidence, exact merge `cee96c1`, known Nit, and unverified scope.
- [x] 4.5 Run strict validation, sync delta specs, archive the change, and commit only closeout documentation/OpenSpec changes.

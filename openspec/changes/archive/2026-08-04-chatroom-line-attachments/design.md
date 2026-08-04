## Context

The accepted #96 implementation spans the original binary attachment capability and six follow-up acceptance rounds. The final contract is the implementation merged as `cee96c1`: direct LINE-style selection, a context-panel materials view, chatroom text mirroring, chatroom impact suppression, and all-mode removal with tombstones.

## Final design

1. **Storage and events.** Binary blobs live at `meetings/<meeting_id>/attachments/<file_id>`. The blob is written before `attachment-added`; removal appends `attachment-removed`, deletes the blob, and never rewrites the original event. Projections mark the original attachment `removed: true`, exclude removed files from quota/download/context, and return 404 for removed downloads.
2. **Routing.** Only `.txt` and `.md` are text. In chatroom mode the upload mutation mirrors the text into case evidence and records an attachment event; the attachment bubble is a text card with an on-demand reader, not full transcript text. Non-chatroom text keeps the existing case-material flow. Every other extension is binary with fixed MIME inference and the existing 10 MB/file, 50 MB/meeting defaults.
3. **UI.** Chatroom `+` directly opens the resident native file input. Upload progress and attachment management are in the context panel’s data/materials tab (courtroom uses 案卷/證物 vocabulary). Images use thumbnails/lightbox; PDFs and other binaries use filename/size/download cards; text cards open a reader.
4. **Deletion.** All modes expose a delete control. The endpoint rejects running meetings, removes mirrored evidence before writing the tombstone, protects legacy text evidence lookup against ambiguous titles, and confirms with neutral irreversible wording. Deleted bubbles remain visible but cannot open/download.
5. **Impact and AI boundaries.** Chatroom material mutations write no `pending_impact`; chatroom reads suppress legacy pending impact. Binary attachment metadata is excluded from runner/context/transcript AI assembly. Tombstones are excluded as content. Existing relay, parallel, and courtroom contracts remain unchanged except for shared attachment deletion.

## Known trade-off

Other already-connected WebSocket clients do not receive a synthetic deletion delta; their view self-heals on refresh/reconnect. The deleting client refetches immediately. This was explicitly accepted in round 7.

## Verification

Human Owner acceptance (2026-08-04) covered focused chatroom E2E 12/12, frontend unit 162/162, and `npm run build`. The merged implementation’s post-merge evidence also records backend 743 passed with one pre-existing timing flake, frontend unit 149, chatroom E2E 40, and the relay binary-delete control-flow case. The known non-blocking visual Nit is `AttachmentBubble.vue:247` using an undefined `--border` hover fallback.

## Why

Backlog #96 delivers the Human Owner-approved LINE-style attachment contract for chatroom `+`: binary files appear as downloadable feed bubbles, while text files remain AI-readable case material. The accepted implementation also includes the subsequent upload-management split, direct LINE-style picker, chatroom text mirroring and pending-impact suppression, and round-7 removal/tombstone behavior.

## What Changes

- Store binary uploads under the meeting attachment directory and record metadata in append-only events.
- Route only `.txt` and `.md` through the text-material contract. In chatroom mode they also receive an attachment event and render as a text attachment card whose content opens on demand; other modes retain the existing text-material endpoint contract.
- Render images, PDFs, and generic binary files as downloadable feed bubbles; keep attachment visibility independent of `visible_roles`.
- Make `+` open the native file picker directly. Keep management in the context panel’s data/materials tab, with mode-aware wording and upload progress.
- Allow deletion in every mode through an append-only `attachment-removed` tombstone. Removal deletes the blob, makes download return 404, releases quota, removes a mirrored text evidence item, and leaves a non-interactive “已刪除” bubble in the feed.
- Suppress chatroom `pending_impact` in both write and read projections so legacy pending state cannot deadlock chatroom responses. Binary attachments remain outside AI prompt/context; chatroom mirrored text remains AI-visible through case evidence.

## Non-Goals

- No historical event rewrite, migration, or backfill.
- No new attachment format, external index, multi-device event replay, or change to relay/courtroom execution semantics.

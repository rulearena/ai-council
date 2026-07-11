# 38 - Human Chair Message Correction

Status: resolved
Type: task

## What to build

Allow the chair to correct a previously submitted human message while preserving the event log as the source of truth.

## Blocked by

11 - Human Chair Message Slice; 17 - Terminal API Conflicts

## Acceptance Criteria

- [x] API exposes `POST /meetings/{meeting_id}/messages/{event_id}/correct`.
- [x] Correction events preserve the original human message and reference it through `corrects_event_id`.
- [x] Corrections reject unknown events and non-human message events.
- [x] Terminal meetings reject message corrections with `409`.
- [x] Transcript projection marks correction entries clearly.
- [x] Frontend API types and controls support correcting human chair messages.

## Resolution Notes

- The backend already persists corrections as append-only Human events with `corrects_event_id`.
- Transcript projection renders correction entries with a visible correction marker.
- The frontend exposes an edit action for original human chair messages.

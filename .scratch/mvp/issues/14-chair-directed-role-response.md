# 14 - Chair Directed Role Response

Status: resolved
Type: task

## What to build

Allow the chair to ask a specific AI role to respond without running the full Blue -> Red -> Blue -> Judge sequence.

## Blocked by

11 - Human Chair Message Slice
12 - Frontend E2E And Visual Smoke

## Acceptance Criteria

- [x] API can request a single Blue/Red/Judge response.
- [x] Directed response events are distinguishable from full-round events.
- [x] Directed response prompts include the existing transcript and chair feedback.
- [x] Frontend exposes role-specific response buttons.
- [x] Stable `data-testid` contract exists for the new controls.
- [x] E2E verifies a directed Blue response appears in timeline/debug/transcript.
- [x] Missing requested-role model assignment returns a clear `400`.

## Resolution Notes

- Added `MeetingRunner.respond_as_role()`.
- Added `POST /meetings/{meeting_id}/roles/{role}/respond`.
- Directed events use `directed-N-{role}-response` step ids.
- Directed events include `interaction_type: directed-role-response` and `directed_sequence`.
- Added frontend role action buttons for Blue/Red/Judge.
- Extended Playwright E2E and generated `.scratch/e2e-directed-role-smoke.png`.
- Hardened missing requested-role model assignment handling.

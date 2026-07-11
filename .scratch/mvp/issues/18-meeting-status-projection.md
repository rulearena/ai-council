# 18 - Meeting Status Projection

Status: resolved
Type: task

## What to build

Expose and display a simple meeting status so users can distinguish open, closed, and cancelled meetings.

## Blocked by

16 - Terminal State Enforcement

## Acceptance Criteria

- [x] `POST /meetings` returns `status: open`.
- [x] `GET /meetings` returns status per meeting.
- [x] `GET /meetings/{meeting_id}` returns status.
- [x] Closed meetings project as `closed`.
- [x] Cancelled meetings project as `cancelled`.
- [x] Frontend meeting list displays the status.
- [x] Frontend selected meeting heading displays the status.
- [x] E2E verifies open and closed statuses are visible.

## Resolution Notes

- Added API `project_meeting_status()` from event log.
- Status projection is intentionally simple: terminal events win, otherwise status is `open`.
- Added status badges to meeting list and selected meeting title.

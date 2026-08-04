## Why

The Human Owner's validation of meeting `meeting-627f03282ba44d22a7bd14ed7423c9bc` showed that an ordinary `@Advisor` chat reply is rendered as a formal report with 摘要／論點／風險／建議處置 sections. This contradicts the chatroom requirement for concise conversational replies and makes the mode feel unlike a live discussion, even though the current prompt already asks for natural chat.

## What Changes

- Introduce a dedicated `chat-message/v1` output contract for chatroom role responses with one conversational `message` value and optional evidence anchors embedded in that text.
- Make directed chatroom responses and `@all` fanout responses use the chat-message contract; the conversation bubble renders the natural message directly rather than formatting legacy role-output fields as a report.
- Preserve each event's raw model output, parsed output, schema identity/hash, prompt metadata, and evidence references for records, diagnostics, and audit consumers.
- Keep relay, parallel, brainstorm, courtroom, synthesis, and formal verdict output contracts unchanged.
- Keep historical events read-compatible: existing chatroom events are not rewritten, and the projection has a deterministic fallback for legacy structured events.

## Capabilities

### New Capabilities

- `chatroom-natural-response`: Defines the output contract, persistence, projection, and backward-compatibility behavior for natural chatroom replies.

### Modified Capabilities

- `chatroom-mode`: The concise response requirement now requires a chatroom-specific natural-message contract for directed and fanout replies while retaining evidence anchors and full diagnostics.
- `conversation-workspace`: Chatroom bubbles render the natural message without report-style section formatting; formal output presentation for other modes remains unchanged.

## Impact

- Backend prompt/schema registry, chatroom runner paths, and event contract tests.
- `frontend/src/meetingWorkspace.ts` and related conversation-workspace tests for message projection and legacy fallback.
- Chatroom prompt fixtures and API/Playwright coverage; no event migration, no historical event rewrite, and no changes to formal-mode schemas.

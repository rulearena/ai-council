## 1. Output contract and parser

- [ ] 1.1 Add red unit tests for `chat-message/v1`: the schema registry exposes it, valid `message` payloads parse, and missing/blank/non-object messages fail with `OutputParseError`.
- [ ] 1.2 Implement the `chat-message/v1` schema constant, parser, codec registration, and typed frontend/API event shape needed to carry `parsed_output.message`.
- [ ] 1.3 Add adapter/test fixtures that return the chat-message payload without changing the existing formal `role-output/v1` and verdict fixtures.

## 2. Chatroom prompt and runner integration

- [ ] 2.1 Update prompt-contract tests and `prompts/chatroom_response.md` so `message` is the complete concise conversational reply, formal report headings are forbidden, and visible evidence anchors may be retained.
- [ ] 2.2 Add red runner tests proving directed chatroom responses select `chat-message/v1`, persist the parsed message, and retain raw output, schema metadata, prompt metadata, and model diagnostics.
- [ ] 2.3 Update `respond_as_role()` to use `chat-message/v1` while preserving directed event correlation, context assembly, retry behavior, and evidence inputs.
- [ ] 2.4 Add red runner tests proving every successful `@all` member selects `chat-message/v1`, preserves its own parsed message and diagnostics, and records parse/model failures without synthesizing a formal response.
- [ ] 2.5 Update `fanout_chatroom_all()` to use the same chat-message contract without changing parallel execution, frozen context, arrival-order persistence, or `in_response_to_event_id` behavior.

## 3. Conversation projection

- [ ] 3.1 Add red frontend unit tests for a `chat-message/v1` event: the bubble shows exactly `parsed_output.message`, retains evidence-anchor text, and does not synthesize 摘要／論點／風險／建議處置 headings.
- [ ] 3.2 Update `meetingWorkspace.ts` message projection to prefer `parsed_output.message` for `chat-message/v1` while keeping the existing `content`/legacy parsed/raw fallback for historical events.
- [ ] 3.3 Add regression tests proving structured verdict and non-chatroom role outputs still use their existing formatted projections.
- [ ] 3.4 Add a read-time compatibility fixture/test proving historical chatroom JSONL events are not rewritten and remain renderable beside new chat-message events.
- [ ] 3.5 Add a regression test proving a pending `@all` fanout still renders its thinking indicators while new natural-message bubbles use the direct `message` projection.

## 4. End-to-end verification

- [ ] 4.1 Add or update API/runner integration coverage for directed and `@all` chatroom responses, including evidence anchors, parse failure, and audit-field preservation.
- [ ] 4.2 Run the focused backend and frontend unit suites, then the relevant full backend/frontend checks and build.
- [ ] 4.3 Add a Playwright assertion for an ordinary chatroom response that verifies natural bubble text and absence of formal report headings, while keeping existing formal-mode coverage green.
- [ ] 4.4 Confirm no historical events, relay/parallel/courtroom schemas, or formal output components are modified by the implementation.

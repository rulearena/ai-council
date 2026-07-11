# AI Council MVP PRD

Source spec: `spec.md`

Build a local single-user AI meeting orchestration app. MVP focuses on the red/blue review flow with fixed roles, local file persistence, OpenAI-compatible model adapters, FastAPI APIs/WebSocket, and a Vue control/debug UI.

## MVP Outcome

The user can create a meeting with a topic, pick model configs for Blue/Red/Judge, run the fixed red-blue-judge sequence, watch status updates, retry failed steps, cancel a run, and download a Markdown transcript.

## Delivery Rules

- Work from frontier tickets in dependency order.
- Backend core tickets use TDD.
- Keep local LLM executors advisory/experimental, not default mainline executors.
- Update this PRD/tickets/backlog when scope changes.

## Backlog

See `spec.md` section 15 for future/non-MVP work.

- Event log corruption handling policy: decide whether malformed JSONL should fail loudly, skip bad lines, or trigger repair tooling.
- Concurrent append hardening: add file locking or another serialization strategy if the backend grows beyond single-process local execution.
- Human chair / 主席介入: after MVP, support user messages inside a meeting, not only the initial topic. User feedback should be persisted as meeting events and injected into subsequent AI role prompts so the user can act like a chairperson directing AI members/employees during the discussion.
- Interactive round control: after user feedback, support continuing the meeting, asking a specific role to respond, requesting a revision, or ending the meeting.

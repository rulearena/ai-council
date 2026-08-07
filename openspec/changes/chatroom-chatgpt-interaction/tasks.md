## 1. Chatroom routing and `@` contract

- [ ] 1.1 Add failing backend tests for plain-text Host routing, explicit `@host`, mention-only activation, invalid normal mentions, `@all` precedence, duplicate targets, and no AI invocation before validation.
- [ ] 1.2 Add the fixed `host` role and Persona metadata to the chatroom mode definition, then add catalog and participant-projection tests for new and legacy meetings.
- [ ] 1.3 Extend `POST /meetings/{meeting_id}/chat/mention` with `content`, normalized `mentions`, ordered stable `source_refs`, and `quote_event_id`; implement the `202` response fields, `400`/`404`/`409` status contract, no-side-effect validation failures, and the `@all` ignored-token warning projection while preserving non-chatroom `/messages`.
- [ ] 1.4 Make the backend parser authoritative for `@` tokens, normalize responder targets, preserve the original human message, and route every chatroom send—including an empty mention list—through the chatroom path.
- [ ] 1.5 Update the runner and pending-role capture so Host is a normal target, multiple explicit roles fan out once each, `@all` includes Host, and mention-only instructions can reach the model as empty user text.
- [ ] 1.6 Add frontend stable-ID autocomplete for Host, active roles, and `@all`; retain invalid drafts for correction and surface ignored-invalid warnings for `@all`.
- [ ] 1.7 Add backend/frontend integration coverage for routing, event persistence, pending states, and the existing arrival-order `@all` display before moving to prompt changes.
- [ ] 1.8 Add direct API tests for valid `202`, invalid mention/source `400` with no event/job, missing meeting `404`, unavailable meeting `409`, stale role payloads, ordered source refs, same-label source IDs, and `@all` warnings.

## 2. Prompt layering and Persona

- [ ] 2.1 Add failing adapter and runner tests asserting separate system/developer/user chatroom messages, deterministic flattening, and normalized `prompt_messages` audit fields.
- [ ] 2.2 Extend `ModelRequest` with an optional layered message sequence while preserving the current flattened prompt and all existing non-chatroom call sites.
- [ ] 2.3 Implement provider-specific message mapping for OpenAI-compatible, Anthropic-style, `GeminiHTTPAdapter`, CLI, and mock adapters, including Gemini system-instruction/flattening behavior and regression coverage for existing adapter payloads and diagnostics.
- [ ] 2.4 Add stable Host, Advisor, Critic, Strategist, and Analyst Persona definitions and render them in the system layer without requiring role announcements.
- [ ] 2.5 Refactor the chatroom prompt builder into system/developer/user-context layers containing the normalized instruction, shared context boundary, quote, and output rules.
- [ ] 2.6 Update natural-response guidance and `chat-message/v1` validation for adaptive length, useful Markdown, no fixed report headings, and no post-generation truncation.
- [ ] 2.7 Verify that formal modes, their prompt templates, schemas, and historical chatroom read-time fallback remain unchanged.

## 3. Explicit `#` attachments

- [ ] 3.1 Add failing parser and composer tests for `#` autocomplete, multiple references, first-selection order, deduplication, stable file IDs, and independent `@`/`#` behavior.
- [ ] 3.2 Add chatroom attachment autocomplete and composer hints for `@指定 AI`, `#選取附件`, and the default Host rule without changing the immediate-upload `+` flow.
- [ ] 3.3 Implement the `chatroom_sources` projection and source listing for `attachment:<file_id>` uploads plus `evidence:<evidence_id>` legacy/initial case materials; use existing readers, apply Host visibility fallback, validate every source for every target role, and reject the complete request on any invalid reference.
- [ ] 3.4 Replace automatic chatroom case-material prompt injection with an explicit selected-source context seam that returns no attachment body when the request has no `#`.
- [ ] 3.5 Implement deterministic bounded retrieval for selected text files, including full-text fit, relevant paragraph selection, remaining-budget accounting, omission metadata, and no PDF/OCR/binary reads.
- [ ] 3.6 Extend `chat-message/v1` with validated `attachment_refs`: require an allow-listed `source_ref` when a concrete selected-source fact is used, allow omission for generic chat, preserve refs in event/audit projections, and reject citations outside the request allow-list; add prompt and event-projection coverage.
- [ ] 3.7 Render citation chips in the conversation feed, connect readable text chips to the existing reader, and show deleted/unavailable citations without breaking the bubble.
- [ ] 3.8 Add end-to-end tests covering no-`#` isolation, one and many selected attachments, deleted/unsupported rejection, bounded retrieval, citations, and existing attachment download/delete behavior.

## 4. Shared memory and summary

- [ ] 4.1 Add failing tests and a versioned derived-memory schema/store for facts, decisions, unresolved questions, next steps, revision, update time, and source boundary without modifying `events.jsonl`.
- [ ] 4.2 Implement a dedicated `chatroom-summary/v1` generator using the default Host model assignment without the Host chat Persona, and exclude attachment body text from the summary.
- [ ] 4.3 Add stable-round settlement hooks and threshold detection so summaries run only after the current round is terminal, with `@all` waiting for every expected role.
- [ ] 4.4 Extend the context builder to use the current shared summary before older transcript events, preserve current/quote blocks, freeze per fanout round, and fall back safely after summary failure.
- [ ] 4.5 Expose the fixed `chatroom_memory` projection (`summary`, `revision`, `updated_at`, `status`, `stale`, error metadata) in the right context panel; show empty/unavailable and stale/update-failed states, consume `chatroom_memory_updated`, refetch `GET /meetings/{meeting_id}` after reconnect, and never create a feed bubble or formal process indicator.
- [ ] 4.6 Add integration tests for summary generation, regeneration, stale/missing summaries, failure fallback, identical role context, fanout settlement, and historical meetings without a memory file.

## 5. Integration and acceptance verification

- [ ] 5.1 Run targeted backend routing, runner, context, attachment, summary, schema, and adapter suites; fix only failures within this change.
- [ ] 5.2 Run frontend unit/type/build checks and Playwright coverage for the composer, autocomplete, citation chips, summary panel, and fanout arrival behavior.
- [ ] 5.3 Run non-chatroom regression suites and historical-event fixtures to verify formal modes, old chatroom bubbles, attachment lifecycle, and no API-key exposure.
- [ ] 5.4 Review the final diff against the OpenSpec deltas and update implementation evidence before handing the change to the independent Reviewer for Gate B.

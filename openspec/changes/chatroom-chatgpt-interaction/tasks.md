## 1. Chatroom routing and `@` contract

- [ ] 1.1 Add failing backend tests for plain-text Host routing, Host display-name chip, chip-only activation, hand-typed invalid role-like tokens, stale chip payloads, `all` precedence, duplicate chips, and no AI invocation before validation.
- [ ] 1.2 Add the fixed `host` role and Persona metadata to the chatroom mode definition, then add catalog and participant-projection tests for new and legacy meetings.
- [ ] 1.3 Implement the exact `POST /meetings/{meeting_id}/chat/mention` schema: `content`, structured `mentions[{role_id,display_text}]`, ordered/deduplicated `source_refs`, and `quoted_event_id`; implement exact `202` accepted, `400` rejected error, `404`, and `409` bodies, no-side-effect rejection, and exact `IGNORED_INVALID_MENTION` warnings while preserving non-chatroom `/messages`.
- [ ] 1.4 Make the backend parser authoritative for `@` tokens, normalize responder targets, preserve the original human message, and route every chatroom send—including an empty mention list—through the chatroom path.
- [ ] 1.5 Update the runner and pending-role capture so Host is a normal target, multiple explicit roles fan out once each, `@all` includes Host, and mention-only instructions can reach the model as empty user text.
- [ ] 1.6 Add frontend display-name role-chip autocomplete for Host, active roles, and all; chips retain hidden stable IDs and serialize structured mentions, never `@Advisor`/`@host` visible text; retain invalid drafts and surface exact ignored-invalid warnings.
- [ ] 1.7 Add backend/frontend integration coverage for routing, event persistence, pending states, and the existing arrival-order `@all` display before moving to prompt changes.
- [ ] 1.8 Add direct API/UI tests for exact accepted/rejected schemas and status codes, no-event/no-job side effects, `INVALID_MENTION_TOKEN`, `STALE_MENTION_PAYLOAD`, ordered/deduplicated source refs, chip display/integrity, missing meeting, unavailable meeting, and exact all-warning objects.

## 2. Prompt layering and Persona

- [ ] 2.1 Add failing adapter and runner tests asserting separate system/developer/user chatroom messages, deterministic flattening, and normalized `prompt_messages` audit fields.
- [ ] 2.2 Extend `ModelRequest` with an optional layered message sequence while preserving the current flattened prompt and all existing non-chatroom call sites.
- [ ] 2.3 Implement provider-specific mapping for OpenAI-compatible, Anthropic-style, `GeminiHTTPAdapter`, CLI, and mock adapters. Add `supports_developer_role` (default false): true uses native developer; false merges system+developer in fixed order into system, then user/context, while retaining prompt flattening. Add native/fallback adapter regression tests.
- [ ] 2.4 Add stable Host, Advisor, Critic, Strategist, and Analyst Persona definitions and render them in the system layer without requiring role announcements.
- [ ] 2.5 Refactor the chatroom prompt builder into system/developer/user-context layers containing the normalized instruction, shared context boundary, quote, and output rules.
- [ ] 2.6 Update natural-response guidance and `chat-message/v1` validation for adaptive length, useful Markdown, no fixed report headings, and no post-generation truncation.
- [ ] 2.7 Verify that formal modes, their prompt templates, schemas, and historical chatroom read-time fallback remain unchanged.

## 3. Explicit `#` attachments

- [ ] 3.1 Add failing parser and composer tests for `#` source chips, uploads plus evidence, notes exclusion, multiple refs, first-selection order, deduplication, hidden stable source refs, same-label disambiguation, and independent role/source behavior.
- [ ] 3.2 Add chatroom display-name role chips and source autocomplete/hints for `@指定 AI`, `#選取附件`, and default Host routing without changing the immediate-upload `+` flow.
- [ ] 3.3 Implement the `chatroom_sources` projection/listing for `attachment:<file_id>` uploads plus `evidence:<evidence_id>` legacy/initial active text evidence; exclude notes; expose source_ref/label/kind/readable/active/reader_ref; use existing readers, Host evidence fallback, and whole-request validation for every multi-role/all target.
- [ ] 3.4 Replace automatic chatroom case-material prompt injection with an explicit selected-source context seam that returns no attachment body when the request has no `#`.
- [ ] 3.5 Implement deterministic bounded retrieval for selected text files, including full-text fit, relevant paragraph selection, remaining-budget accounting, omission metadata, and no PDF/OCR/binary reads.
- [ ] 3.6 Extend `chat-message/v1` with SHALL-required `attachment_refs` when a concrete selected-source fact is used; each item is `{source_ref,label,segment_refs}`, source_ref is selected allow-list only, generic chat may omit; preserve event/audit refs and add prompt/output/event projection tests.
- [ ] 3.7 Render source citation chips, connect active attachment/evidence refs to the existing reader, and show deleted/tombstoned/inactive citations as unavailable without breaking the bubble.
- [ ] 3.8 Add end-to-end tests covering no-# isolation, uploads/evidence, notes exclusion, legacy/initial evidence, Host fallback, multi-role/all visibility/readability rejection, ordered refs, bounded retrieval, exact citations, post-citation deletion, and existing download/delete behavior.

## 4. Shared memory and summary

- [ ] 4.1 Add failing tests and a versioned derived-memory schema/store for facts, decisions, unresolved questions, next steps, revision, update time, and source boundary without modifying `events.jsonl`.
- [ ] 4.2 Implement a dedicated `chatroom-summary/v1` generator using the default Host model assignment without the Host chat Persona, and exclude attachment body text from the summary.
- [ ] 4.3 Add stable-round settlement hooks and threshold detection so summaries run only after the current round is terminal, with `@all` waiting for every expected role.
- [ ] 4.4 Extend the context builder to use the current shared summary before older transcript events, preserve current/quote blocks, freeze per fanout round, and fall back safely after summary failure.
- [ ] 4.5 Implement `POST /meetings/{meeting_id}/chat/memory/regenerate` with exact idle `202` and running/terminal `409 CHATROOM_MEMORY_REGENERATION_NOT_ALLOWED`; expose `chatroom_memory` fields and empty/stale/update-failed states, consume `chatroom_memory_updated`, refetch `GET /meetings/{meeting_id}` after reconnect, and never create a feed bubble.
- [ ] 4.6 Add API/websocket/projection/UI integration tests for exact regeneration schemas, summary generation, stale/missing summaries (`empty` + `SUMMARY_UPDATE_FAILED` without prior revision), failure fallback, identical role context, fanout settlement, and historical meetings without a memory file.

## 5. Integration and acceptance verification

- [ ] 5.1 Run targeted backend routing, runner, context, attachment, summary, schema, and adapter suites; fix only failures within this change.
- [ ] 5.2 Run frontend unit/type/build checks and Playwright coverage for the composer, autocomplete, citation chips, summary panel, and fanout arrival behavior.
- [ ] 5.3 Run non-chatroom regression suites and historical-event fixtures to verify formal modes, old chatroom bubbles, attachment lifecycle, and no API-key exposure.
- [ ] 5.4 Review the final diff against the OpenSpec deltas and update implementation evidence before handing the change to the independent Reviewer for Gate B.

## 1. Chatroom routing and `@` contract

- [ ] 1.1 Add failing backend tests for plain-text Host routing, Host display-name chip, chip-only activation, hand-typed invalid role-like tokens, stale chip payloads, `all` precedence, duplicate chips, and no AI invocation before validation.
- [ ] 1.2 Add the fixed `host` role and Persona metadata to the chatroom mode definition, then add catalog and participant-projection tests for new and legacy meetings.
- [ ] 1.3 Implement the exact request schema: `content`, `mentions[{token_id,role_id,display_text,start,end}]`, `source_tokens[{token_id,source_ref,display_text,start,end}]`, ordered/deduplicated `source_refs`, and `quoted_event_id`; NFC-normalize before offset generation, reject non-NFC content, validate Python/Unicode code-point half-open spans, unique IDs, exact content slices, prefixes, bounds, overlap, and source_refs equality before routing. Use the complete table-driven 400 mapping (`INVALID_REQUEST_SCHEMA`, `MENTION_TOKEN_MISMATCH`, `STALE_MENTION_PAYLOAD`, `INVALID_MENTION_TOKEN`, `SOURCE_TOKEN_MISMATCH`, `STALE_SOURCE_PAYLOAD`, `INVALID_SOURCE_REF`, `SOURCE_NOT_VISIBLE_TO_TARGET`, `SOURCE_NOT_READABLE`) plus exact 404/409 envelopes.
- [ ] 1.4 Make the backend token validator authoritative: NFC-normalize composer content before spans, scan uncovered raw @ candidates using the Unicode XID_Continue/email grammar, skip verified chip spans including spaces, apply normal `INVALID_MENTION_TOKEN` vs all-chip warning precedence, treat uncovered # as ordinary text, preserve original content plus token metadata in the human event, remove verified chip spans from normalized prompt instruction, and route every send through chatroom path.
- [ ] 1.5 Update the runner and pending-role capture so Host is a normal target, multiple explicit roles fan out once each, `@all` includes Host, and mention-only instructions can reach the model as empty user text.
- [ ] 1.6 Add frontend display-name role-chip autocomplete for Host, active roles, and all; chips retain hidden stable IDs and serialize structured mentions, never `@Advisor`/`@host` visible text; retain invalid drafts and surface exact ignored-invalid warnings.
- [ ] 1.7 Add backend/frontend integration coverage for routing, event persistence, pending states, and the existing arrival-order `@all` display before moving to prompt changes.
- [ ] 1.8 Add table-driven direct API/UI tests asserting full response bodies, field mapping, and zero event/job side effects for missing/wrong/unknown fields, blank/non-NFC content, malformed quote, well-typed missing quote graceful ignore, malformed/non-overlap/mismatched spans, stale mention/source payloads, every closed-union 400 code, exact 404/409 envelopes, CJK, NFC combining/non-NFC, punctuation boundaries, email, hand-typed same-label beside a real chip, duplicate chips, raw @all plus all-chip warning, and # chip plus hashtag.

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
- [ ] 3.3 Implement the `chatroom_sources` projection/listing with the closed kind matrix: `attachment:<file_id>` readable only for active readable `.txt`/`.md` blobs, while `evidence:<evidence_id>` is readable for active non-empty string content regardless of extension; exclude notes; expose authoritative source_ref/label/kind/readable/active/reader_ref/available_segment_refs; test initial/legacy no-extension evidence, Host fallback, binary rejection, and whole-request validation for every multi-role/all target.
- [ ] 3.4 Replace automatic chatroom case-material prompt injection with an explicit selected-source context seam that returns no attachment body when the request has no `#`.
- [ ] 3.5 Implement deterministic bounded retrieval for selected text sources, including `segment_refs:["full"]` for full text, deterministic IDs such as `paragraph:0001` for segmented retrieval, remaining-budget accounting, omission metadata, and no PDF/OCR/binary reads.
- [ ] 3.6 Extend `chat-message/v1` with SHALL-required `attachment_refs` when a concrete selected-source fact is used; each item is `{source_ref,label,segment_refs}`, source_ref is selected allow-list only, label exactly matches projection, every segment ref is in request available_segment_refs, generic chat may omit; preserve event/audit refs and add full/segmented/wrong-label/unknown-segment/deleted/generic prompt/output/event tests.
- [ ] 3.7 Render source citation chips, connect active attachment/evidence refs to the existing reader, and show deleted/tombstoned/inactive citations as unavailable without breaking the bubble.
- [ ] 3.8 Add end-to-end tests covering no-# isolation, uploads/evidence, notes exclusion, legacy/initial evidence, Host fallback, multi-role/all visibility/readability rejection, ordered refs, bounded retrieval, exact citations, post-citation deletion, and existing download/delete behavior.

## 4. Shared memory and summary

- [ ] 4.1 Add failing tests and a versioned derived-memory schema/store for facts, decisions, unresolved questions, next steps, revision, update time, status/stale/error metadata, and source boundary without modifying `events.jsonl`; introduce a per-meeting `ChatroomMemoryTaskManager` separate from `MeetingJobManager`.
- [ ] 4.2 Implement a dedicated `chatroom-summary/v1` generator using the default Host model assignment without the Host chat Persona, and exclude attachment body text from the summary.
- [ ] 4.3 Add stable-round settlement hooks and threshold detection so automatic summaries reserve only after the target round is terminal, with `@all` waiting for every expected role; share an idempotent per-meeting reservation with manual regeneration.
- [ ] 4.4 Extend the context builder to use the snapshot's prior summary plus newer transcript events during generation, preserve current/quote blocks, freeze per fanout round, atomically reject stale-boundary writes, and fall back safely after failure without blocking chat.
- [ ] 4.5 Implement exact manual regeneration behavior: open chatroom/no active round/no generation and duplicate-generating calls return `202 {status,meeting_id,memory_status:"generating"}`; non-chatroom/closed/terminal/active-round calls return exact 409 envelope; memory generation never sets/consumes `MeetingJobManager` chat slots, and `chatroom_memory_updated` plus reconnect GET update the panel without feed events.
- [ ] 4.6 Add API/concurrency/websocket/projection/UI tests for summary generating + chat `202` while a chat job slot is occupied, duplicate regeneration/no duplicate task, exact rejection envelopes, `@all` terminal trigger (including completed/failed/cancelled outcomes), snapshot ordering, stale write discard/no event-log mutation, failure states, websocket update/no feed event, reconnect GET refresh, identical role context, and historical meetings without a memory file.

## 5. Integration and acceptance verification

- [ ] 5.1 Run targeted backend routing, runner, context, attachment, summary, schema, and adapter suites; fix only failures within this change.
- [ ] 5.2 Run frontend unit/type/build checks and Playwright coverage for the composer, autocomplete, citation chips, summary panel, and fanout arrival behavior.
- [ ] 5.3 Run non-chatroom regression suites and historical-event fixtures to verify formal modes, old chatroom bubbles, attachment lifecycle, and no API-key exposure.
- [ ] 5.4 Review the final diff against the OpenSpec deltas and update implementation evidence before handing the change to the independent Reviewer for Gate B.

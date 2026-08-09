## Context

Chatroom currently has three separate paths: `/messages` records a human-only event, `/chat/mention` routes explicit role mentions, and the runner renders one flattened `chatroom_response` prompt. The prompt builder projects recent transcript text and, through the existing case-material input path, can expose all visible text material. The model adapter contract is also a single `prompt` string, while the frontend composer parses only `@` tokens.

This change crosses the chatroom API, participant projection, runner/context builder, prompt rendering, model adapters, attachment projection, summary persistence, and Conversation workspace. The existing `events.jsonl` contract is append-only and is the source of truth for historical meetings. Existing formal modes, the accepted `@all` fanout-round display, attachment storage/deletion behavior, and legacy chatroom read projection must remain compatible.

The Human Owner has chosen one mandatory fixed Host role (`host`, 「主持 AI」), creation-time selection of the other four fixed roles, a roster that does not change after creation, default Host routing for plain chatroom text, explicit `@` responder selection, explicit `#` attachment selection, shared rather than private memory, adaptive natural replies, and a visible derived summary outside the message feed. User-authored roles/Persona are a separate backlog-93 capability and are not part of this change.

## Goals / Non-Goals

**Goals:**

- Make chatroom turns behave like a normal conversation: plain text persists and invokes Host, while explicit mentions remain deterministic.
- Keep role and source selection independent, with backend-authoritative validation for `@` and `#`.
- Give every chatroom role a distinct working Persona without imposing report headings or fixed response length.
- Keep Host active in every chatroom while allowing the user to choose the other fixed participants at creation; route and authorize only against that frozen active roster.
- Build bounded prompt context from layered instructions, shared summary, recent transcript, quote, and explicitly selected readable attachments.
- Preserve structured, verifiable attachment citations without forcing citation anchors into natural message text.
- Keep the complete transcript canonical and add a reconstructable shared summary that never appears as a fake chat bubble.
- Preserve existing events, old chatroom projections, non-chatroom behavior, and attachment lifecycle contracts.

**Non-Goals:**

- Private role memory, user-level memory, or memory shared across meetings.
- PDF extraction, image OCR, ZIP inspection, external vector databases, or cloud retrieval.
- Automatic responses in relay, parallel, courtroom, brainstorm, six-hats, or persona-testing modes.
- Rewriting, migrating, or backfilling historical JSONL events or existing meeting records.
- User accounts, multi-user permissions, or changes to attachment quotas and download authorization.
- User-authored roles, editable fixed-role Persona prompts, or post-creation roster changes.

## Decisions

### 1. Use five fixed Persona definitions and a creation-time active roster

`config/modes.yaml` will declare exactly five fixed chatroom roles: Host (`host`, 「主持 AI」), Advisor, Critic, Strategist, and Analyst. Each role entry owns two required non-blank strings: `persona_summary`, a short public description, and `persona_prompt`, the complete backend-only working Persona. `ModeRole`/`ModeCatalogRepository` validate both fields for these five chatroom roles and raise `ModeConfigError` when either is missing, blank, or non-string; no generic Persona is silently substituted. Non-chatroom role definitions remain valid without these fields and keep their current behavior.

`GET /modes` and meeting participant projections expose `persona_summary` but never `persona_prompt`. The prompt renderer resolves the complete Persona from the current backend mode definition by stable role ID. Existing meetings therefore gain the current fixed Persona definitions at read/run time without metadata or event migration.

Host is mandatory in every new chatroom. The creation UI keeps Host selected and allows Advisor, Critic, Strategist, and Analyst to be included or omitted; an explicit create payload that omits Host or contains an unknown/duplicate role is rejected, while an omitted participant list preserves the compatibility default of all five roles. The stored active roster is immutable after creation: meeting settings may change model assignments only for that exact role set. `@` autocomplete, `@all`, pending-role capture, source visibility, and model assignment use only the active meeting projection, not every catalog role.

For an old chatroom meeting whose stored participant snapshot does not contain Host, the read-time projector appends Host and resolves its model through the existing meeting-default/fallback assignment path; otherwise it preserves the stored active subset and does not append omitted member roles. It never rewrites metadata or historical events. This avoids migration while preventing inactive catalog roles from entering `@all` or source authorization.

### 2. Make the backend the routing authority and define the chat send contract

`POST /meetings/{meeting_id}/chat/mention` will accept this JSON request:

```json
{
  "content": "@顧問 請比較 #需求說明",
  "mentions": [{"token_id": "m-1", "role_id": "Advisor", "display_text": "@顧問", "start": 0, "end": 3}],
  "source_tokens": [{"token_id": "s-1", "source_ref": "attachment:att-123", "display_text": "#需求說明", "start": 8, "end": 13}],
  "source_refs": ["attachment:att-123"],
  "quoted_event_id": null
}
```

`content` is the exact composer text. The request fields are fixed: `content:string`, `mentions:Array<{token_id:string,role_id:string,display_text:string,start:int,end:int}>`, `source_tokens:Array<{token_id:string,source_ref:string,display_text:string,start:int,end:int}>`, `source_refs:string[]`, and `quoted_event_id:string|null`. Offsets use Python/Unicode code-point half-open indexing (`content[start:end]`); token IDs are unique within one request. Every mention/source span must be in bounds, non-overlapping, have the correct `@`/`#` prefix, and exactly equal its `display_text`. `role_id` and `source_ref` are authorization fields; display text is integrity/display only. `source_refs` must equal first-appearance, deduplicated `source_tokens[].source_ref` values or the request fails `STALE_SOURCE_PAYLOAD`. The composer renders display-name chips such as `@顧問`, `@主持 AI`, `@全部角色`, and source chips such as `#需求說明`; stable IDs are hidden and never become user-visible text. The human event preserves original content and token metadata; normalized prompt instruction removes only verified chip spans.

Before span calculation, both composer and backend SHALL NFC-normalize the canonical content. If submitted `content` differs from its NFC form, the backend SHALL return `400 INVALID_REQUEST_SCHEMA` with field `content`; the composer SHALL normalize first and then generate spans. All spans are Unicode code-point half-open `[start,end)` offsets.

The backend will validate the token model before routing:

- `content[start:end] == display_text`, correct prefix, bounds, non-overlap, and unique `token_id`;
- role chips carrying `role_id` values, including the `all` sentinel, and source chips carrying `source_ref` values;
- ordinary `@` characters such as email addresses, which are not tokens.

Same-label chips remain distinct by token ID and hidden stable ID. A hand-typed token with the same display text as a chip is still ordinary content unless its span is covered by that chip; in the normal path an uncovered role-like token produces `INVALID_MENTION_TOKEN`, while the `all`-chip precedence path ignores it with an `IGNORED_INVALID_MENTION` warning. A hashtag without a source chip is ordinary text and never authorizes a source.

The raw role-like candidate grammar is closed and Unicode-aware. An uncovered `@` is a candidate only when it is at content start or its preceding code point is neither Unicode `XID_Continue` nor `@`, `.`, `+`, or `-`; it is followed by 1–64 Unicode `XID_Continue` code points (including CJK letters, combining marks, decimal digits, and underscore), and the following code point is absent or neither `XID_Continue` nor `-`. Hyphen is available only inside a verified chip, never in a raw candidate. If the `@` is inside an email-like local/domain pattern (a preceding local run of XID/`.`/`+`/`-`, or candidate followed by `.` plus an XID domain), the whole sequence is ordinary text. Raw scanning never enters a verified chip span, including display text with spaces such as `@主持 AI`. Uncovered `#` is always ordinary hashtag/text and never produces validation or authorization.

The human event will preserve the exact user-visible message and quote reference. A normalized instruction used in the model prompt will remove routing tokens while retaining the natural-language request; selected attachments will be represented in their own context layer. A message containing only valid routing tokens therefore produces an empty instruction, which the chat Persona can answer with a clarification question.

Routing rules are applied in this order:

1. Validate all request fields and token spans; malformed schema, blank content, unknown fields, malformed quote IDs, span errors, token mismatches, stale mention metadata, and stale source payloads reject before side effects.
2. Scan uncovered role-like `@` tokens. If an `all` chip exists, it wins and uncovered invalid role-like tokens are ignored with `{code: "IGNORED_INVALID_MENTION", display_text}` warnings; otherwise they return `INVALID_MENTION_TOKEN`.
3. Resolve the `all` role chip first; it wins over other role chips. Otherwise validate every role chip atomically.
4. With no valid role chip, select Host.
5. Validate every selected `source_ref` immediately before execution for every target role; one invalid reference blocks the complete target set.

Successful requests return exactly HTTP `202` body `{status:"accepted",meeting_id:string,target_role_ids:string[],source_refs:string[],warnings:Array<{code:"IGNORED_INVALID_MENTION",display_text:string}>}`. Live completion is tracked by existing event/websocket identity; no `job_ids` is promised. Every other JSON validation rejection uses this closed mapping:

| Input failure | Code | Field | Detail keys |
|---|---|---|---|
| missing/wrong/unknown field or type, blank/non-NFC content, malformed `quoted_event_id` | `INVALID_REQUEST_SCHEMA` | `content`, `mentions`, `source_tokens`, `source_refs`, `quoted_event_id`, or `null` | only applicable optional keys |
| duplicate token ID, span out of range/overlap, content slice mismatch, missing/invalid `@` prefix | `MENTION_TOKEN_MISMATCH` | `mentions` | `token_id`, `role_id`, `display_text`, `start`, `end` |
| inactive role or display text no longer matches active projection | `STALE_MENTION_PAYLOAD` | `mentions` | `token_id`, `role_id`, `display_text` |
| uncovered raw role-like candidate | `INVALID_MENTION_TOKEN` | `content` | `display_text`, `start`, `end` |
| duplicate source token ID, span out of range/overlap, content slice mismatch, missing `#` prefix | `SOURCE_TOKEN_MISMATCH` | `source_tokens` | `token_id`, `source_ref`, `display_text`, `start`, `end` |
| `source_refs` differs from first-occurrence deduped source-token projection | `STALE_SOURCE_PAYLOAD` | `source_refs` | `source_ref`, `token_id` |
| invalid namespace/format, wrong meeting, deleted/tombstoned/inactive source | `INVALID_SOURCE_REF` | `source_refs` | `source_ref` |
| valid source not visible to one or more targets | `SOURCE_NOT_VISIBLE_TO_TARGET` | `source_refs` | `source_ref`, `role_id` |
| valid/visible source unsupported or has no readable body | `SOURCE_NOT_READABLE` | `source_refs` | `source_ref` |

Every 400 body is exactly `{status:"rejected",error:{code:one-of-table,field:string|null,details:Detail[]}}`; `Detail` has only optional `token_id?:string`, `role_id?:string`, `display_text?:string`, `source_ref?:string`, `start?:integer`, and `end?:integer`, omitting non-applicable keys. 404 is exactly `{status:"rejected",error:{code:"MEETING_NOT_FOUND",field:null,details:[]}}`; 409 is exactly `{status:"rejected",error:{code:"CHATROOM_NOT_ACCEPTING_INPUT",field:null,details:[]}}`. No other 400 code may be introduced without updating this table and direct tests. A well-typed but missing quoted event keeps existing graceful quote-ignore behavior. All rejection paths run before human-event/job creation.

The existing `/messages` endpoint remains available to preserve non-chatroom and historical callers. Chatroom composer sends will use the chatroom endpoint even when `mentions` is empty, so plain text cannot accidentally take the old human-only path.

The alternative was to trust the frontend's extracted mention list. That currently causes an invalid token to look like ordinary text and would allow routing drift between clients, so server validation is required.

### 3. Preserve the accepted fanout display while extending its target set

The runner will keep the existing frozen pre-send snapshot and arrival-order persistence. For a multi-role explicit mention and `@all`, the request creates one human event and one independent role invocation per deduplicated target. The Host is simply another expected role in the fanout projection; no new wrapper or display protocol is introduced.

The frontend pending-role capture will derive expected roles from the projected participants, which now includes Host. The existing `fanout-round-display` behavior for placeholders, arrival order, failures, terminal settlement, and reconnect degradation remains unchanged.

### 4. Introduce layered model requests without breaking existing adapters

`ModelRequest` will retain its current flattened `prompt` field for compatibility and gain an optional canonical `messages` sequence. Every chatroom request contains exactly three pre-transport messages in this order: `system`, `developer`, `user`. `prompt` is the deterministic labeled flattening `SYSTEM\n{system}\n\nDEVELOPER\n{developer}\n\nUSER\n{user}`. Non-chatroom runners continue to omit canonical messages and keep their current single-prompt path.

Adapter mapping will be explicit:

- Role capability is owned by adapter code/constructor state, not `ModelConfig`, meeting metadata, API payloads, or user settings. The adapter protocol exposes `supports_developer_role: bool = false`; a concrete adapter may opt in only in code.
- `OpenAICompatibleHTTPAdapter(supports_developer_role=true)` sends the canonical three messages unchanged. Its default/false form sends exactly two messages: one `system` whose content is the deterministic `SYSTEM` then `DEVELOPER` merge, followed by the canonical `user` message.
- `AnthropicHTTPAdapter` has no native developer role: it sends the deterministic system+developer merge in the top-level Anthropic `system` field and the canonical user/context content as one `user` message.
- `GeminiHTTPAdapter` has a code-owned `supports_system_instruction` capability, default true. True sends `{systemInstruction:{parts:[{text:merged_system_developer}]},contents:[{role:"user",parts:[{text:user_context}]}]}`; false sends `{contents:[{role:"user",parts:[{text:flattened_prompt}]}]}` with no `systemInstruction`. No paid retry is used to guess capabilities.
- `SubscriptionCLIAdapter` receives only the labeled flattened `prompt` through its existing `{prompt}` replacement. `MockModelAdapter` retains deterministic output, receives both fields, and exposes the canonical message sequence for assertions.
- When `ModelRequest.messages` is absent, every adapter preserves its current legacy single-prompt payload exactly; this is the non-chatroom compatibility path.

Every chatroom attempt event that currently carries prompt diagnostics—completed, adapter failure, parse/schema failure, and automatic retry—records the exact canonical pre-transport list as `prompt_messages`, byte-for-byte stable across providers and attempts that reuse the same context snapshot. Provider payload merges are not written into `prompt_messages`. Non-chatroom events retain their existing `[ {"role":"user","content":prompt} ]` audit shape. Existing audit fields, template metadata, schema IDs, token usage, and failure diagnostics remain unchanged.

### 5. Keep Persona and response contract in prompt layers

The Slice-2 chatroom prompt renderer will build:

- **System:** role identity, the selected Persona, meeting language, and hard safety/format rules.
- **Developer:** routing interpretation, transcript/quote budget rules, natural-response guidance, and the Slice-2 `chat-message/v1` contract.
- **User/context:** normalized current instruction, quoted event, and recent published transcript only.

Persona text is the validated backend-only `persona_prompt`: Host directs/clarifies/organizes; Advisor proposes practical options; Critic challenges assumptions and risks; Strategist weighs priorities and trade-offs; Analyst distinguishes evidence, data, and uncertainty. The prompt forbids role-announcement prefixes and fixed report headings unless the user explicitly requests a format. A user-authored Persona is not accepted by this change.

Slice 2 keeps `chat-message/v1` limited to the existing required non-blank `message` and changes only natural-response guidance/validation. It also removes the legacy chatroom `case_files`/case-material body injection before any model call: because Slice 2 does not yet accept selected sources, its prompt contains no attachment, evidence, or note body under any wording. Shared summary enters in Slice 4. Optional `attachment_refs`, selected-source semantic validation, and source excerpts enter together in Slice 3 so no schema field depends on an allow-list that does not yet exist.

### 6. Build explicit, bounded attachment context

The `#` source selector will list chat-upload attachments and independently created active evidence, including materials present when a legacy or new meeting was created, while excluding `notes`. A text upload produces one selector item only: canonical ref `attachment:<file_id>`; when its attachment event carries `evidence_id`, the linked mirrored `evidence:<evidence_id>` item is suppressed. Evidence without that exact active attachment link remains a separate `evidence:` source even when labels match; title matching never deduplicates. The meeting read projection and `GET /meetings/{meeting_id}/chat/sources` expose authoritative `source_ref`, display label, kind, readable/active state, `reader_ref`, and informational `available_segment_refs`; same-label independent sources show kind/size/date and retain the hidden ref.

The frontend preserves first-selection order and deduplicates repeated `source_ref` values. The backend resolves each source ref within the meeting, checks active state and target-role visibility, then applies the closed kind matrix. An `attachment:<file_id>` is readable only when its active blob has a `.txt` or `.md` extension. If it has a linked evidence ID, visibility and active state come from that exact evidence item (with the legacy Host fallback); an unlinked legacy attachment has meeting-wide visibility to the active roster because attachment events have no role ACL. An `evidence:<evidence_id>` is readable when its active version contains a non-empty string and follows its explicit `visible_roles`, without an extension check. For multi-role and `@all`, any target/source failure rejects the whole request. Existing data is projected at read time without migration.

After validation and retrieval, `AttachmentContextResolver` freezes one immutable `chatroom-source-context/v1` snapshot shared by every target in the request. Each source entry records `source_ref`, authoritative label/kind/reader ref, `content_identity`, exact ordered retrieved segments, `available_segment_refs` equal to the segment IDs actually placed in the canonical user/context message, and omission metadata. Attachment identity contains the immutable attachment event ID, file ID, size, and SHA-256 of the bytes read; evidence identity contains evidence ID and active version number. The snapshot's exact excerpt text is persisted once inside canonical `prompt_messages`; event field `selected_source_snapshot` stores the metadata/segment IDs/identities without duplicating body text.

Automatic parse/model retries reuse the same frozen snapshot and canonical prompt messages. Output validation receives its citation allow-list only from that snapshot—not from the current source projection—and accepts only its source refs, exact labels, and actual `available_segment_refs`. A new human send creates a new snapshot and revalidates current state. Completed event `attachment_refs` retains source/label/segment provenance; after deletion, the UI resolves the current source state and renders the historical citation unavailable without invalidating the message.

For small selected sources, full text is eligible if it fits and yields `segment_refs: ["full"]`. For larger sources, the resolver splits deterministic paragraph/line segments, ranks them by stable lexical relevance to the normalized instruction and quote, and includes only segments that fit the remaining budget. The context builder never scans all visible case materials by default.

The context builder will never scan all visible case materials by default. With no `#`, it will not open or read any attachment or evidence body. Unsupported selected attachments, inactive sources, and empty/non-string evidence fail validation before model execution; they remain downloadable/previewable when the existing UI supports it. This local deterministic strategy is preferred over adding a retrieval service or vector database because the current requirement is bounded selection, not global semantic search.

### 7. Add a derived, versioned summary store outside the event log

Each chatroom meeting SHALL lazily create a derived `chatroom-memory.json` when its first memory reservation or successful generation requires persistence. The meeting read model exposes `chatroom_memory: {summary, revision, updated_at, status, stale, error_code, error_message, source_event_boundary}`. The file contains the current summary revision, revision history, schema version, updated time, source event boundary, and summary fields: facts, decisions, unresolved questions, and next steps. It SHALL retain source metadata only and never source body text.

The dedicated per-meeting `ChatroomMemoryTaskManager` is separate from `MeetingJobManager`. A memory generation task does not set or consume a chat job running slot and is never rejected by `reject_running_meeting`; ordinary chat sends during `status: "generating"` return their normal `202`, append the human event, and launch chat jobs. The manager holds at most one generation reservation per meeting. Automatic threshold scheduling after a terminal response round and manual regeneration share the same idempotent reservation: a duplicate manual call while generating returns the same accepted `202` and creates no second task.

Manual `POST /meetings/{meeting_id}/chat/memory/regenerate` behavior is exact: an open chatroom with no generation returns `202 {status: "accepted", meeting_id, memory_status: "generating"}`; the same response is returned while generation is already reserved; non-chatroom, closed/terminal, or an explicitly active chat round returns exactly `409 {status: "rejected", error: {code: "CHATROOM_MEMORY_REGENERATION_NOT_ALLOWED", field: null, details: []}}`. Automatic scheduling occurs only after the target round is terminal; `@all` waits for every expected role to complete, fail, or cancel. It never blocks current or future chat.

When a reservation is created, the memory task snapshots the canonical transcript event boundary and current summary revision. Chat requests during generation use the previous summary, when present, plus newer transcript events and do not wait. Completion atomically publishes only when its snapshot boundary is not older than the stored boundary; an older result is discarded and retried by the next threshold, without event-log mutation. The task uses the default Host model assignment and dedicated `chatroom-summary/v1` prompt, not Host chat Persona. Failure retains the prior summary with `status: "stale"`, `stale: true`, `error_code: "SUMMARY_UPDATE_FAILED"`; with no prior summary it sets `status: "empty"`, `stale: false`, and the same error code.

The context panel receives the non-feed memory projection. Completion, failure, stale-result discard, and status changes emit the same `chatroom_memory_updated` websocket/projection event; no feed event is created. On reconnect or missed notification, the frontend re-fetches `GET /meetings/{meeting_id}` and replaces the current projection.

### 8. Preserve UI behavior and historical compatibility

The composer will add the `@`/`#` hint and two autocomplete paths while retaining the current `+` immediate-upload flow. Citation chips are rendered from structured `attachment_refs`; readable active text citations open the existing reader, deleted citations show unavailable state, and bubbles never expand full source text.

The meeting projection will expose Host, the source listing, and current summary state. The conversation feed will continue to use direct `parsed_output.message` for new chat events, the existing legacy fallback for old events, and the accepted fanout-round display for `@all`. No event migration is needed. Non-chatroom components, prompts, schemas, and `/messages` behavior remain unchanged unless they share a backward-compatible adapter type.

## Risks / Trade-offs

- **[Context budget competition]** Summary, quote, transcript, and selected sources can compete for limited space → reserve current instruction and summary first, evict old transcript before required blocks, then retrieve attachment segments against the remaining budget and record what was omitted.
- **[Provider message-role differences]** Adapters do not all support `developer` identically → keep a canonical layer model, implement provider-specific mapping, and preserve a deterministic flattened prompt for CLI/legacy paths.
- **[Old meetings lack Host assignment]** A stored participant/model snapshot may predate Host → append Host only in the chatroom read projection and resolve through the existing fallback model path; never rewrite old metadata.
- **[Summary becomes stale]** Derived memory can lag behind the feed or fail → update only after terminal rounds, retain revision/source boundary metadata, keep the transcript authoritative, and fall back without blocking chat.
- **[Citation hallucination]** A model may cite an unselected source → validate `attachment_refs` against the request allow-list and route invalid output through existing retry/failure diagnostics.
- **[Frontend/backend parser drift]** Different clients may serialize tokens differently → make backend parsing and stable-ID validation authoritative; use frontend parsing only for autocomplete and immediate UX feedback.
- **[Concurrent summary and next turn]** A summary write can race with a new request → snapshot context at request start, serialize summary revisions per meeting, and let each in-flight request retain its frozen snapshot.
- **[UI overload]** Adding chips, hints, and a summary panel can compete with the existing workspace → keep summary outside the feed, use compact chips, and preserve current collapse/filter behavior.

## Migration Plan

1. Implement and test routing/Host projection while retaining `/messages` and all existing event shapes.
2. Add layered prompt requests, validated fixed Persona rendering, creation-time active-role selection, canonical audits, and the no-source/no-body chatroom guard. Keep `chat-message/v1` message-only, omit shared summary/source context, and preserve formal-mode adapters/audits.
3. Add explicit `source_refs`, send-time validation, bounded text retrieval, schema references, and UI citation chips. Existing uploaded files remain stored; no body is automatically injected after deployment.
4. Add lazy `chatroom-memory.json` creation, summary generation, meeting projection, and context-panel rendering. Existing meetings start with the transcript fallback and no summary.
5. Run targeted backend/frontend tests, adapter regression suites, fanout browser smoke, and non-chatroom regression suites before Human acceptance.

Rollback is code-level and reversible: old event logs, attachment events, and meeting metadata remain readable by the existing projection. Removing the new code does not require deleting summary files or rewriting events; a future reader can ignore the derived summary file. No historical data migration or destructive cleanup is part of deployment.

## Open Questions

None for Gate A. Adapter capability ownership/mapping, canonical audit shape, Persona storage/projection/failure behavior, creation-time active roster, Slice-2 context boundary, mirrored-source identity/visibility, and immutable retrieval/citation snapshots are specified above and covered by task-level tests.

## Context

Chatroom currently has three separate paths: `/messages` records a human-only event, `/chat/mention` routes explicit role mentions, and the runner renders one flattened `chatroom_response` prompt. The prompt builder projects recent transcript text and, through the existing case-material input path, can expose all visible text material. The model adapter contract is also a single `prompt` string, while the frontend composer parses only `@` tokens.

This change crosses the chatroom API, participant projection, runner/context builder, prompt rendering, model adapters, attachment projection, summary persistence, and Conversation workspace. The existing `events.jsonl` contract is append-only and is the source of truth for historical meetings. Existing formal modes, the accepted `@all` fanout-round display, attachment storage/deletion behavior, and legacy chatroom read projection must remain compatible.

The Human Owner has chosen one fixed Host role (`host`, 「主持 AI」), default Host routing for plain chatroom text, explicit `@` responder selection, explicit `#` attachment selection, shared rather than private memory, adaptive natural replies, and a visible derived summary outside the message feed.

## Goals / Non-Goals

**Goals:**

- Make chatroom turns behave like a normal conversation: plain text persists and invokes Host, while explicit mentions remain deterministic.
- Keep role and source selection independent, with backend-authoritative validation for `@` and `#`.
- Give every chatroom role a distinct working Persona without imposing report headings or fixed response length.
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

## Decisions

### 1. Add Host to the chatroom role projection, not to other modes

`config/modes.yaml` will declare the fixed chatroom Host role with stable ID `host`, display name 「主持 AI」, and the chatroom Host Persona. The Host participates in the same model-assignment and status projection as the existing roles and is included in `@all`.

For an old chatroom meeting whose stored participant snapshot does not contain Host, the read-time chatroom participant projector will append the fixed Host and resolve its model through the existing meeting-default/fallback assignment path. It will not rewrite metadata or historical events. This preserves the no-migration rule while making Host behavior consistent for old and new meetings.

The alternative was to require a data migration for every existing chatroom. That would violate the historical-data constraint and create an unnecessary recovery path, so read-time projection is preferred.

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

`ModelRequest` will retain its current flattened `prompt` field for compatibility and gain an optional canonical `messages` sequence with `system`, `developer`, and `user` roles. Chatroom calls populate both: `messages` is authoritative for native-capable adapters, and `prompt` is a deterministic flattening for CLI, mock, and legacy adapters. Non-chatroom runners continue to use their current single-prompt path.

Adapter mapping will be explicit:

- OpenAI-compatible adapters expose `supports_developer_role`, defaulting to `false`; only `true` adapters send a native `developer` message. When false, system and developer layers are merged in fixed order into one system message, followed by the user/context message. All adapters retain the deterministic flattened `prompt`.
- Anthropic-style adapters map developer instructions into the provider's supported system/context representation and send user/context content as user messages.
- `GeminiHTTPAdapter` maps system/developer instructions to Gemini's system-instruction/content representation; when a deployed Gemini endpoint cannot represent a layer natively, it receives the same deterministic labeled flattening used by legacy adapters.
- CLI adapters receive the stable flattened form with visible layer labels.
- Mock adapters and test doubles retain the current deterministic behavior while exposing the normalized message list for assertions.

Every saved chatroom event will record normalized `prompt_messages`, not only a single synthetic user message. Existing audit fields, template metadata, schema IDs, token usage, and failure diagnostics remain unchanged. The alternative was to put all instructions back into one larger prompt; that would preserve the present context ambiguity and prevent provider-native separation.

### 5. Keep Persona and response contract in prompt layers

The chatroom prompt renderer will build:

- **System:** role identity, the selected Persona, meeting language, and hard safety/format rules.
- **Developer:** routing interpretation, shared-memory rules, context/token budget, attachment citation rules, and the `chat-message/v1` contract.
- **User/context:** normalized current instruction, shared summary, quoted event, recent published transcript, and bounded excerpts from selected attachments.

Persona text will be stable and configuration-driven: Host directs/clarifies/organizes; Advisor proposes practical options; Critic challenges assumptions and risks; Strategist weighs priorities and trade-offs; Analyst distinguishes evidence, data, and uncertainty. The prompt will forbid role-announcement prefixes and fixed report headings unless the user explicitly requests a format.

The `chat-message/v1` schema will continue to require a non-blank `message` and will add optional `attachment_refs`. If the response uses a concrete fact from a selected source, the prompt and output validator SHALL require `attachment_refs`; each item is exactly `{source_ref, label, segment_refs}`, `source_ref` must belong to the request's validated selected set, `label` must exactly match the authoritative source projection, and every segment ref must belong to the request's retrieved `available_segment_refs`. Generic chat may omit the array. Invalid references follow the existing parse-error/retry/failure path rather than becoming unverified UI citations.

### 6. Build explicit, bounded attachment context

The `#` source selector will list both chat-upload attachments and active text evidence, including materials present when a legacy or new meeting was created, while excluding `notes`. Stable source refs use separate namespaces: `attachment:<file_id>` for chat uploads and `evidence:<evidence_id>` for active evidence. The meeting read projection and `GET /meetings/{meeting_id}/chat/sources` expose authoritative `source_ref`, display label, kind, readable/active state, `reader_ref`, and `available_segment_refs`; same-label sources show kind/size/date and retain the hidden source ref. Attachments resolve through the attachment reader/blob store, while evidence resolves through the current active-version reader. Deletion, tombstoning, or inactive evidence makes the source invalid at send time.

The frontend preserves first-selection order and deduplicates repeated `source_ref` values. The backend resolves each source ref within the meeting, checks active state, extension, and target-role visibility, then loads only `.txt`/`.md` content. Host is the fixed chatroom coordinator and may read evidence at read time even when legacy `visible_roles` omits `host`; other roles follow `visible_roles`. For multi-role and `@all`, every selected source is validated independently for every target; any target/source failure returns `SOURCE_NOT_VISIBLE_TO_TARGET` and rejects the whole request. Existing meeting files are read-time projected; no migration or metadata rewrite is performed. `file_id` appears only inside the `attachment:<file_id>` namespace and is never the authorization field.

An `AttachmentContextResolver` (or equivalent context-builder seam) will use the existing attachment event's evidence linkage when text was mirrored into case materials, and the existing blob/material store as the source of readable text. For small selected sources, full text is eligible if it fits. For larger sources, the resolver will split deterministic paragraph/line segments, rank them by stable lexical relevance to the normalized instruction and quote, and include only segments that fit the remaining budget. Each block carries authoritative `source_ref`, display label, and segment metadata.

The context builder will never scan all visible case materials by default. With no `#`, it will not open or read any attachment body. Unsupported selected files fail validation before model execution; they remain downloadable/previewable through the current UI. This local deterministic strategy is preferred over adding a retrieval service or vector database because the current requirement is bounded selection, not global semantic search.

### 7. Add a derived, versioned summary store outside the event log

Each chatroom meeting may lazily create a derived `chatroom-memory.json` under that meeting's existing data directory. The meeting read model exposes `chatroom_memory: {summary, revision, updated_at, status, stale, error_code, error_message, source_event_boundary}`. The file contains the current summary revision, revision history, schema version, updated time, source event boundary, and summary fields: facts, decisions, unresolved questions, and next steps. It may retain attachment references/metadata but never attachment body text.

The full transcript remains canonical and summary regeneration reads it without rewriting it. Writes will be atomic and serialized per meeting. Old meetings without this file use recent transcript context and show the summary empty state until a successful generation.

The summary service will be scheduled when the transcript/context approaches the configured budget (default trigger ratio 75%, with an environment override) and the current response round is terminal. `@all` waits for all expected role outcomes, including Host. `POST /meetings/{meeting_id}/chat/memory/regenerate` is also available while the meeting is idle/able to receive chat and returns exactly `202 {status: "accepted", meeting_id, memory_status: "generating"}`. Running or terminal meetings return exactly `409 {status: "rejected", error: {code: "CHATROOM_MEMORY_REGENERATION_NOT_ALLOWED"}}`. The service uses the default Host model assignment with a dedicated `chatroom-summary/v1` schema and prompt, not the Host chat Persona. Completion or failure updates the same `chatroom_memory_updated` projection event; a failed task retains the previous revision with `status: "stale"`, `stale: true`, and `error_code: "SUMMARY_UPDATE_FAILED"`, or uses `status: "empty"` with that error code when no prior revision exists. It never blocks the user response.

The context panel receives the non-feed memory projection. When the current projection changes, the backend emits a dedicated `chatroom_memory_updated` websocket/projection event containing the meeting ID and new revision; the frontend updates the panel without adding a feed event. On reconnect or missed notification, the frontend re-fetches `GET /meetings/{meeting_id}` and replaces the current projection. A failed task preserves the prior summary and sets `status: "stale"`, `stale: true`, and error metadata; the panel visibly reports stale/update-failed state while chat continues.

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
2. Add layered prompt requests and Persona rendering; keep `prompt` fallback and formal-mode adapters unchanged.
3. Add explicit `source_refs`, send-time validation, bounded text retrieval, schema references, and UI citation chips. Existing uploaded files remain stored; no body is automatically injected after deployment.
4. Add lazy `chatroom-memory.json` creation, summary generation, meeting projection, and context-panel rendering. Existing meetings start with the transcript fallback and no summary.
5. Run targeted backend/frontend tests, adapter regression suites, fanout browser smoke, and non-chatroom regression suites before Human acceptance.

Rollback is code-level and reversible: old event logs, attachment events, and meeting metadata remain readable by the existing projection. Removing the new code does not require deleting summary files or rewriting events; a future reader can ignore the derived summary file. No historical data migration or destructive cleanup is part of deployment.

## Open Questions

None for Gate A. Provider role mapping, summary trigger configuration, attachment segmentation, and old-meeting Host fallback are specified above as implementation decisions and are covered by the task-level tests.

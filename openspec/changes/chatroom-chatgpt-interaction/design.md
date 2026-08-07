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
  "mentions": [{"role_id": "Advisor", "display_text": "@顧問"}],
  "source_refs": ["attachment:att-123"],
  "quoted_event_id": null
}
```

`content` is the exact composer text, `mentions` is an ordered structured chip list, `source_refs` is the ordered, deduplicated source-selection list and the only source authorization, and `quoted_event_id` preserves the existing quote behavior. The composer renders role display-name chips such as `@顧問`, `@主持 AI`, and `@全部角色`; each chip contains a hidden stable `role_id` and is not rendered as `@Advisor` or `@host`. The backend uses only `role_id` for routing, verifies `display_text` against the active projection for token integrity, and rejects stale metadata. A hand-typed role-like token without a corresponding chip is invalid; email and ordinary `@` text are not mentions. The human event preserves the display text. Filenames, display names, and ordinary hashtags are never used as source authorization. Same-label sources are disambiguated by metadata and hidden stable source ID.

The parser will distinguish:

- role chips carrying `role_id` values, including the `all` sentinel;
- `#` source chips resolved to stable `source_ref` values;
- ordinary `@` characters such as email addresses.

The human event will preserve the exact user-visible message and quote reference. A normalized instruction used in the model prompt will remove routing tokens while retaining the natural-language request; selected attachments will be represented in their own context layer. A message containing only valid routing tokens therefore produces an empty instruction, which the chat Persona can answer with a clarification question.

Routing rules are applied in this order:

1. Resolve the `all` role chip first; it wins over other role chips. Invalid extra role-like tokens in this branch are ignored and returned as `{code: "IGNORED_INVALID_MENTION", display_text}` warnings.
2. Otherwise validate every role chip atomically; a hand-typed role-like token or stale chip blocks the request before an event or AI job is created.
3. With no valid `@` token, select Host.
4. Validate every selected `source_ref` immediately before execution for every target role; one invalid reference blocks the complete target set.

Successful requests return HTTP `202` with exactly `{status: "accepted", meeting_id, target_role_ids, source_refs, warnings}`. Live completion is tracked by the existing event/websocket identity; the response does not promise `human_event_id` or `job_ids`. Warning items have exactly `{code: "IGNORED_INVALID_MENTION", display_text}`. Normal validation failures return HTTP `400` with exactly `{status: "rejected", error: {code, field, details}}`, where `code` is one of `INVALID_MENTION_TOKEN`, `STALE_MENTION_PAYLOAD`, `INVALID_SOURCE_REF`, `SOURCE_NOT_VISIBLE_TO_TARGET`, or `SOURCE_NOT_READABLE`; each detail may contain only the relevant `source_ref`, `role_id`, and/or `display_text`. A missing meeting returns exactly `{status: "rejected", error: {code: "MEETING_NOT_FOUND"}}` with `404`; a meeting that cannot accept chat input returns exactly `{status: "rejected", error: {code: "CHATROOM_NOT_ACCEPTING_INPUT"}}` with `409`. All rejection paths run before event/job creation. After validation, the server appends the human event and launches jobs. This contract is covered by direct API tests, not only browser tests.

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

The `chat-message/v1` schema will continue to require a non-blank `message` and will add optional `attachment_refs`. If the response uses a concrete fact from a selected source, the prompt and output validator SHALL require `attachment_refs`; each item is exactly `{source_ref, label, segment_refs}` and `source_ref` must belong to the request's validated selected set. Generic chat may omit the array. Invalid references follow the existing parse-error/retry/failure path rather than becoming unverified UI citations.

### 6. Build explicit, bounded attachment context

The `#` source selector will list both chat-upload attachments and active text evidence, including materials present when a legacy or new meeting was created, while excluding `notes`. Stable source IDs use separate namespaces: `attachment:<file_id>` for chat uploads and `evidence:<evidence_id>` for active evidence. The meeting read projection and `GET /meetings/{meeting_id}/chat/sources` expose `source_ref`, display label, kind, readable/active state, and `reader_ref`; same-label sources show kind/size/date and retain the hidden source ref. Attachments resolve through the attachment reader/blob store, while evidence resolves through the current active-version reader. Deletion, tombstoning, or inactive evidence makes the source invalid at send time.

The frontend preserves first-selection order and deduplicates repeated `source_ref` values. The backend resolves each source ref within the meeting, checks active state, extension, and target-role visibility, then loads only `.txt`/`.md` content. Host is the fixed chatroom coordinator and may read evidence at read time even when legacy `visible_roles` omits `host`; other roles follow `visible_roles`. For multi-role and `@all`, every selected source is validated independently for every target; any target/source failure returns `SOURCE_NOT_VISIBLE_TO_TARGET` and rejects the whole request. Existing meeting files are read-time projected; no migration or metadata rewrite is performed. `file_id` appears only inside the `attachment:<file_id>` namespace and is never the authorization field.

An `AttachmentContextResolver` (or equivalent context-builder seam) will use the existing attachment event's `evidence_id` when text was mirrored into case materials, and the existing blob/material store as the source of readable text. For small selected files, full text is eligible if it fits. For larger files, the resolver will split deterministic paragraph/line segments, rank them by stable lexical relevance to the normalized instruction and quote, and include only segments that fit the remaining budget. Each block carries stable source ID, display label, and segment metadata.

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
3. Add explicit attachment IDs, send-time validation, bounded text retrieval, schema references, and UI citation chips. Existing uploaded files remain stored; no body is automatically injected after deployment.
4. Add lazy `chatroom-memory.json` creation, summary generation, meeting projection, and context-panel rendering. Existing meetings start with the transcript fallback and no summary.
5. Run targeted backend/frontend tests, adapter regression suites, fanout browser smoke, and non-chatroom regression suites before Human acceptance.

Rollback is code-level and reversible: old event logs, attachment events, and meeting metadata remain readable by the existing projection. Removing the new code does not require deleting summary files or rewriting events; a future reader can ignore the derived summary file. No historical data migration or destructive cleanup is part of deployment.

## Open Questions

None for Gate A. Provider role mapping, summary trigger configuration, attachment segmentation, and old-meeting Host fallback are specified above as implementation decisions and are covered by the task-level tests.

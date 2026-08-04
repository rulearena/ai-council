## Context

Chatroom directed responses and `@all` fanout responses already use the `chatroom_response` prompt, which asks for a short conversational answer. They nevertheless request the global `role-output/v1` schema (`summary`, `arguments`, `risks`, and `recommendation`), and the conversation projection formats those parsed fields into a formal report. The problem therefore crosses prompt/schema selection, event persistence, and the shared frontend projection.

The event log is append-only and is the source of truth. Formal modes depend on their structured schemas and presentation, so the change must be scoped to chatroom response paths and must not rewrite historical events.

## Goals / Non-Goals

**Goals:**

- Give every new directed and `@all` chatroom response a dedicated, parseable natural-message contract.
- Render the parsed chat message directly in the chatroom bubble, including any evidence anchors that the model places in the message.
- Preserve raw output, parsed output, schema identity/hash, prompt metadata, and failure diagnostics in events.
- Keep historical events readable and leave relay, parallel, brainstorm, courtroom, and formal verdict behavior unchanged.

**Non-Goals:**

- No change to the chatroom fanout execution or event ordering; that is tracked by #98.
- No automatic rewriting, migration, or re-generation of existing events.
- No removal of structured role output from records, role-detail views, or formal meeting modes.
- No post-generation truncation or word-count enforcement in the frontend.

## Decisions

### Use a dedicated `chat-message/v1` codec

The schema registry will add `chat-message/v1` with a single required string field, `message`. The parser will reject a non-object, a missing field, or a blank message. A separate codec makes the chatroom contract explicit and prevents the legacy report fields from leaking into ordinary chat. Reusing `role-output/v1` would preserve the source of the current mismatch; accepting unstructured raw text would lose deterministic parsing and diagnostics.

### Keep the existing chatroom prompt route and replace its schema contract

Both `respond_as_role()` and `fanout_chatroom_all()` will select `chat-message/v1` while continuing to use `chatroom_response`. The prompt will state that the JSON object's `message` value is the complete reply, must be concise and conversational, and may retain visible `[附件N]` anchors when referring to case materials. A new template would duplicate the same context assembly without providing a behavioral benefit.

### Preserve audit data and add a display-safe projection

New completed chatroom events will retain `raw_output`, `parsed_output`, `output_schema_id`, `output_schema_hash`, `prompt_messages`, prompt template metadata, and existing model/timing/token fields. The display projection will prefer `parsed_output.message` when the event uses `chat-message/v1`; the legacy formatter remains the fallback for old structured events. If the event contract exposes a plain `content` display value, it must equal the parsed message and must not replace the raw or parsed audit fields.

### Keep legacy events append-only and mode-aware

Read-time projection will branch on the event schema and meeting mode. Old `role-output/v1` chatroom events remain valid and are displayed through the existing compatibility formatter; new chatroom events display the message field directly. Structured verdict and other formal events continue to use their existing formatters. No historical JSONL line is rewritten.

## Risks / Trade-offs

- [Legacy chatroom events still look formal] → Keep them readable with the existing formatter; apply the natural contract only to newly generated responses, without silently rewriting history.
- [A model returns invalid or blank JSON] → Reuse the existing parse-error/retry/failure event path, retaining the raw output and diagnostics; cover it with parser and runner tests.
- [A permissive renderer leaks report sections again] → Make `chat-message/v1` the only schema accepted by chatroom runner paths and add projection tests that assert the bubble contains the message without synthesized headings.
- [Evidence anchors are lost during projection] → Treat the message string as opaque display content and test `[附件一]`/`[證物一]`-style anchor text is preserved; formal evidence validation remains in courtroom schemas.
- [A frontend or backend rollback sees a new schema] → Keep `content`/raw fallback behavior deterministic and retain schema metadata so an older reader can still inspect the event; verify read-time compatibility with a fixture containing `chat-message/v1`.

## Migration Plan

1. Add the codec, update chatroom prompt/runner schema selection, and update frontend projection/tests.
2. Deploy normally; new chatroom events use `chat-message/v1`, while existing events remain untouched.
3. Roll back code if needed; retain the append-only events and use the compatibility projection to inspect them. Do not run a data migration.

## Open Questions

- None for Gate A. The exact message length remains prompt guidance, consistent with the existing no-post-generation-truncation requirement.

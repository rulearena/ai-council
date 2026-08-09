## Why

聊天室目前已能以 `@角色` 或 `@all` 呼叫 AI，但普通文字只會被保存，且所有可見案卷內容會自動進入 prompt。即使回覆契約已改成自然訊息，現行 prompt 仍以單一 user prompt、正式 transcript 與固定短句規則組裝，缺少穩定主持角色、角色工作視角、長對話摘要與明確附件選取，因此互動不像一般 ChatGPT 對話，也有 context 無限膨脹與附件誤讀風險。

## What Changes

- 將聊天室的主持 AI 定義為固定 `host` role；建立會議時 Host 必選，Advisor／Critic／Strategist／Analyst 可選且建立後 roster 固定；未指定 `@` 時由主持回覆，`@all` 只包含 Host 與本場 active roles，明確角色 mention 則只呼叫指定角色。
- 將 display-name role chips、結構化 `mentions[{role_id,display_text}]`、無效 mention、`all` 優先級與多角色平行回覆整理成可預期的 routing contract；穩定 ID 永不作使用者可見文字。
- 在 composer 增加 `#` source autocomplete；只有使用者明確選取、仍存在且對目標角色可讀的 approved source 才可被檢索並注入 prompt：chat-upload 僅限 active `.txt/.md` blob，evidence 僅限 active 且 content 為非空 string；`notes` 排除。
- 支援一則訊息引用多個 ordered/deduped `source_refs`、失效引用阻擋、相關段落擷取與結構化 source citation chip；沒有 source chip 時不讀取任何 attachment/evidence body。
- 將固定角色 Persona、語氣與硬規則分離到 canonical system/developer prompt；當輪訊息、共享記憶、引用與選取附件成為 user/context 層。Prompt audit 永遠保存 transport 前的 `system → developer → user` 三層，不隨 provider mapping 改變。
- 讓聊天室回覆長度與 Markdown 使用自適應，JSON 只作傳輸格式，不再要求固定報告欄位或固定句數。
- 保存完整共享 transcript，並以專用摘要任務建立可重建、可查看但不產生聊天氣泡的共享會議摘要。
- 保留現有事件 append-only、歷史事件 read-time 相容，以及 relay、parallel、courtroom、brainstorm 與正式 schema 行為不變。

## Capabilities

### New Capabilities

- `chatroom-memory`: Defines shared transcript context, rolling meeting summaries, summary visibility, update timing, and failure fallback.

### Modified Capabilities

- `chatroom-mode`: Changes chatroom routing, host participation, context assembly, prompt layering, attachment visibility, and adaptive response behavior.
- `structured-mentions`: Adds display-name autocomplete semantics, default-host routing, strict invalid-mention handling, and `#` attachment references.
- `chatroom-attachments`: Adds explicit attachment-reference, bounded retrieval, validation, and citation contracts while retaining existing storage and type routing.
- `chatroom-natural-response`: Changes natural response guidance from fixed short sentences to adaptive conversational generation and structured attachment references.
- `conversation-workspace`: Adds composer affordances, attachment citation chips, and shared-summary visibility without changing non-chatroom presentation.

## Impact

- Chatroom mode catalog and participant projection gain a fixed host role and role-specific Persona data.
- The chat mention API and runner gain default-host routing, explicit attachment-reference inputs, and frozen context snapshots that include only selected material.
- Model request adapters gain a message-layer contract capable of carrying system/developer instructions separately from user/context content while preserving existing provider adapters.
- Prompt assembly gains bounded attachment retrieval and shared-summary context selection; the append-only event log remains the source of truth.
- Frontend composer, autocomplete, message projection, attachment reader, context panel, and Playwright regression coverage change. Other modes and historical event files remain compatible.

## User Stories

1. As a chatroom user, I want ordinary text to receive a reply from the host, so that I can converse naturally without adding a mention every time.
2. As a chatroom user, I want to mention one or more named roles, so that only the roles I selected answer.
3. As a chatroom user, I want `@all` to include the host and all active roles, so that I can explicitly start a group discussion.
4. As a chatroom user, I want invalid role mentions to be caught before execution, so that a typo never silently invokes the wrong AI.
5. As a chatroom user, I want autocomplete to show friendly role names while the system uses stable IDs, so that the UI is readable and routing remains deterministic.
6. As a chatroom user, I want to type `#` and select specific attachments, so that the AI reads only the material I intended.
7. As a chatroom user, I want to reference several attachments in one message, so that I can compare documents without uploading them again.
8. As a chatroom user, I want the system to reject a deleted or unreadable selected attachment, so that the AI never answers as if it had seen missing context.
9. As a chatroom user, I want attachment citations to be clickable, so that I can verify which source supported an answer.
10. As a chatroom user, I want the AI to respond like a conversation partner, so that simple questions are brief and complex questions receive enough explanation.
11. As a chatroom user, I want each role to have a recognizable working perspective, so that Advisor, Critic, Strategist, Analyst, and Host provide meaningfully different contributions.
12. As a chatroom user, I want Host to remain available while choosing which other fixed roles join a new meeting, so that `@` and `@all` only involve the participants I selected.
13. As a chatroom user, I want long conversations to retain important decisions without sending the entire transcript every time, so that context remains useful and bounded.
14. As a chatroom user, I want to inspect the shared summary without seeing it as a fake AI message, so that memory remains understandable and auditable.
15. As an existing meeting user, I want old events and non-chatroom modes to remain readable and unchanged, so that this interaction redesign does not require migration.

## Implementation Decisions

- The host is one fixed chatroom role with internal ID `host` and display name 「主持 AI」; it is mandatory in every chatroom participant set and uses the existing meeting model-assignment mechanism. The other four fixed roles are selected at meeting creation, the active roster is immutable afterwards, and `@all` resolves only that active set.
- Each fixed role owns a required non-blank backend `persona_prompt` and a public `persona_summary` in `config/modes.yaml`. The catalog/meeting APIs expose only the summary; missing fixed-role Persona configuration is a configuration error, while old meetings resolve the current definitions at read/run time without migration.
- Adapter role support is code-owned capability, never meeting/model/user configuration. `supports_developer_role` defaults to false; canonical chatroom audits always store the pre-transport `system`, `developer`, `user` layers in that order.
- Routing and attachment selection are separate: `@` chooses responders, while `#` chooses allowable material sources.
- Same-round fanout roles receive one frozen pre-send context and cannot observe each other’s in-flight output; later turns can observe completed published events.
- Full transcript remains canonical. A shared summary is derived state, not a replacement for events, and can be regenerated.
- Attachment body content is never inferred from a natural-language reference. Only explicit `#` references can authorize retrieval; binary and unsupported files remain AI-invisible.
- Structured attachment references are carried beside the natural message and projected as UI chips; the message body is not forced to contain report-style anchors.
- The chat mention API has one fixed accepted/rejected envelope; rejection occurs before human-event/job creation, and live completion remains tracked by existing event/websocket identities.
- Source authorization uses only `attachment:<file_id>` and `evidence:<evidence_id>` refs; source labels are display-only, notes are excluded, and every target in a multi-role/all request is validated.
- Source readability is kind-specific: attachments require active readable `.txt`/`.md` blobs; evidence requires an active version with non-empty string content and no extension check. Initial/legacy no-extension evidence is approved; notes are excluded.
- The chat request uses code-point half-open token spans: `mentions[{token_id,role_id,display_text,start,end}]`, `source_tokens[{token_id,source_ref,display_text,start,end}]`, ordered/deduped `source_refs`, and `quoted_event_id`; verified chip spans are removed only from normalized prompt instruction while the human event preserves original content and metadata.
- All validation errors use closed 400/404/409 envelopes with no event/job side effects; `source_refs` and retrieved segment IDs are the only authorization/provenance fields.
- Canonical content is NFC-normalized before span generation; raw uncovered `@` follows the Unicode XID_Continue/email grammar, raw uncovered `#` is always ordinary text, and the closed error mapping is table-driven with no unlisted 400 codes.
- Summary regeneration uses `POST /meetings/{meeting_id}/chat/memory/regenerate`; completion and failure use the same `chatroom_memory_updated` projection event.
- `ChatroomMemoryTaskManager` is isolated from `MeetingJobManager`, with one idempotent per-meeting reservation shared by automatic terminal-round triggers and manual regeneration; generation never blocks chat.
- Existing formal response schemas, event IDs, historical JSONL, and non-chatroom presentation are out of scope for migration.

## Testing Decisions

- Tests assert observable routing, prompt contents, event persistence, context boundaries, and rendered UI behavior rather than private helper implementation.
- Backend coverage will exercise default host, display-name chip routing, code-point span validation, exact closed API envelopes/statuses, no-side-effect rejection, multi-role/all fanout, invalid/stale chip rejection, source authorization and kind-specific readability, notes exclusion, initial/legacy no-extension evidence, Host fallback, bounded full/segmented retrieval, exact citation provenance, summary regeneration/status events, concurrent chat during generation, duplicate reservation, terminal `@all` scheduling, stale-write ordering, and adapter message-layer contracts.
- Mode/catalog coverage will exercise required fixed Persona validation, public-summary-only projection, mandatory Host plus optional member selection, immutable active rosters, and old-meeting Host/Persona read-time fallback.
- Frontend unit and Playwright coverage will exercise role/source chips, composer hints, mixed role/source input, citation chips, exact summary regeneration states, summary visibility, pending fanout behavior, and non-chatroom regressions.
- Existing formal-mode tests and historical-event fixtures remain regression gates.
- Slice acceptance includes targeted tests, frontend build, relevant full suites, and direct browser smoke for the composer and context panel.

## Out of Scope

- Private long-term memory for individual AI roles.
- Cross-meeting or user-level memory.
- PDF extraction, image OCR, ZIP inspection, or new binary attachment parsing.
- External vector databases or cloud retrieval services.
- Automatic AI replies in relay, parallel, courtroom, or other non-chatroom modes.
- Rewriting, migrating, or backfilling historical events or existing meeting data.
- User accounts, multi-user permissions, or shared workspace collaboration.
- User-authored/custom chatroom roles or editable Persona prompts. That separately approved future capability remains backlog 93; user-authored Persona will be untrusted `user/context` content and will not replace system/developer rules.

## Further Notes

The change is intentionally split into four implementation slices: chatroom routing, prompt/Persona, explicit attachments, and shared memory. Each slice must remain independently testable and preserve the append-only event and existing mode contracts before the next slice proceeds.

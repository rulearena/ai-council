## ADDED Requirements

### Requirement: Explicit source references authorize prompt material
Chatroom prompt construction SHALL accept source material only through explicit composer `#` reference chips represented in the request's ordered, deduplicated `source_refs` list. Source IDs SHALL use `attachment:<file_id>` for chat uploads and `evidence:<evidence_id>` for active evidence. `notes` SHALL be excluded from the selector and SHALL not be automatically injected by this change. A natural-language mention of a filename, an earlier upload, or "剛剛那份附件" SHALL NOT authorize retrieval. The backend SHALL preserve selection order and SHALL pass only sources belonging to the current meeting. Display labels and ordinary hashtags are presentation/text only; `source_refs` are the sole source authorization.

#### Scenario: Explicit reference selects one source
- **WHEN** a human message contains a selected `#需求說明` reference
- **THEN** the request contains the stable ID for that attachment
- **AND** only that attachment is eligible for prompt retrieval

#### Scenario: Natural wording does not select a source
- **WHEN** a human writes "請看剛剛那份附件" without a `#` reference
- **THEN** no attachment body is retrieved
- **AND** the role is not told that it read an attachment

#### Scenario: Cross-meeting reference is rejected
- **WHEN** a request contains a `source_ref` that belongs to another meeting
- **THEN** the chatroom request is rejected before AI execution
- **AND** no cross-meeting content enters the prompt

### Requirement: Chatroom source projection includes attachments and case materials
The chatroom source selector SHALL project active chat-upload attachments and independently created active evidence with non-empty string content from the current meeting, excluding `notes`. A text-upload attachment whose event carries `evidence_id` SHALL appear exactly once using canonical `attachment:<file_id>`; its exactly linked mirrored `evidence:<evidence_id>` option SHALL be suppressed and SHALL NOT be injected or cited separately. Evidence without that exact active attachment link remains a separate `evidence:` source even when its label matches; title/label matching SHALL never deduplicate. `GET /meetings/{meeting_id}/chat/sources` and the meeting read projection SHALL expose each source's authoritative `source_ref`, display label, kind, readable/active state, `reader_ref`, and informational `available_segment_refs`. Same-name independent sources SHALL show kind/size/date and retain the hidden source ref. Existing meetings SHALL be projected at read time without migration.

#### Scenario: Legacy case material is selectable
- **WHEN** an old meeting already has a readable text case material
- **THEN** it appears in the source projection with an `evidence:` ID
- **AND** it can be selected with `#` without rewriting meeting metadata

#### Scenario: Mirrored text upload appears once
- **WHEN** an active `.md` attachment event links to a mirrored evidence ID
- **THEN** the selector contains only its `attachment:<file_id>` option
- **AND** no duplicate linked `evidence:<evidence_id>` option can be injected or cited

#### Scenario: Same-label independent evidence remains separate
- **WHEN** an attachment and an independently created evidence item have the same display label but no exact link
- **THEN** both options remain selectable with distinct refs and kind metadata
- **AND** the system does not infer identity from the label

#### Scenario: Host fallback sees legacy material
- **WHEN** a legacy case material has no explicit `host` in `visible_roles`
- **THEN** the fixed chatroom Host can select and read it through the chatroom-role visibility fallback
- **AND** other roles still use their explicit visibility rules

#### Scenario: @all validates every target
- **WHEN** `@all` selects a source visible to some but not all active roles
- **THEN** validation fails before any target job or human event is created
- **AND** the response identifies the target/source visibility failure

### Requirement: Approved source kinds have separate readability rules
The system SHALL apply this closed source-kind matrix:

| Source kind | Stable namespace | Readable condition | Unreadable condition |
|---|---|---|---|
| Chat-upload attachment | `attachment:<file_id>` | extension is `.txt` or `.md` and the active blob is readable | PDF, image, ZIP, or any other binary/extension, or inactive/unreadable blob → `SOURCE_NOT_READABLE` |
| Versioned case-material evidence | `evidence:<evidence_id>` | active evidence version has non-empty string `content`; no extension check | inactive evidence or empty/non-string content → `SOURCE_NOT_READABLE` |

Evidence readability SHALL depend on the evidence data model's `title`, `content`, and `visible_roles`, not on a filename or extension. Initial and legacy evidence without an extension SHALL therefore be readable when active with non-empty string content. A linked text attachment SHALL use the exact linked evidence item's active state and `visible_roles`, with the existing legacy Host fallback; an unlinked legacy attachment SHALL be meeting-wide to the frozen active roster because attachment events have no role ACL. `notes` SHALL never appear in the source projection or prompt authorization. Both kinds SHALL expose `source_ref`, label, kind, `reader_ref`, and informational projection segment refs, while only the frozen invocation snapshot authorizes citations.

#### Scenario: Initial no-extension evidence is readable
- **WHEN** a new or legacy meeting has active evidence with title/content but no filename extension
- **THEN** it is projected as `evidence:<evidence_id>` with `readable: true`
- **AND** it can be selected and retrieved as text

#### Scenario: Legacy evidence is readable for Host
- **WHEN** legacy active evidence has non-empty content and omits `host` from `visible_roles`
- **THEN** Host can select/read it through the fixed coordinator fallback
- **AND** other roles still require their explicit visibility

#### Scenario: @all validates source visibility for every target
- **WHEN** `@all` selects active evidence visible to some but not all targets
- **THEN** the whole request returns `SOURCE_NOT_VISIBLE_TO_TARGET` before any event/job

#### Scenario: Binary attachment is not evidence-readable
- **WHEN** a selected `attachment:<file_id>` points to a PDF, image, ZIP, or other binary
- **THEN** the whole request returns `SOURCE_NOT_READABLE`
- **AND** a selected `evidence:<evidence_id>` is evaluated by active content instead of extension

#### Scenario: Linked attachment inherits evidence visibility
- **WHEN** a text attachment links to evidence visible to Advisor but not Critic
- **THEN** its canonical `attachment:` source is visible to Advisor and not Critic
- **AND** a request targeting both roles is rejected atomically

#### Scenario: Unlinked legacy attachment is meeting-wide
- **WHEN** a legacy readable attachment has no evidence link or role ACL
- **THEN** it is visible to every frozen active chatroom role
- **AND** no omitted catalog role gains access

### Requirement: Attachment references are validated at send time
Every selected `source_ref` SHALL be validated immediately before the AI job starts using the approved source-kind matrix. The source SHALL exist, be active, belong to the meeting, be visible to the target role, and have a readable body under its kind rule. If any selected source ref fails validation, the entire AI request SHALL be blocked; the system SHALL not silently skip, substitute, or downgrade that source. The composer SHALL preserve the input and source tokens for correction.

#### Scenario: Deleted reference blocks request
- **WHEN** a selected attachment is deleted after the composer opened and before send
- **THEN** the request returns HTTP `400` with `error.code: "INVALID_SOURCE_REF"`
- **AND** no target role is invoked
- **AND** the selected reference remains visible for correction

#### Scenario: Unsupported type blocks request
- **WHEN** a user attempts to send a selected PDF, image, ZIP, or other non-`.txt`/`.md` file as prompt material
- **THEN** the request returns HTTP `400` with `error.code: "SOURCE_NOT_READABLE"`
- **AND** the file remains available through its existing download/preview behavior

#### Scenario: Valid multi-role request validates for every target
- **WHEN** a message targets Advisor and Critic and contains one selected readable attachment
- **THEN** the attachment is validated against both target roles before either job starts
- **AND** both roles receive the same authorized source snapshot

### Requirement: Readable attachment retrieval is bounded and auditable
Approved readable sources SHALL be text bodies from either a readable `.txt`/`.md` attachment or active evidence with non-empty string content. After send-time validation, retrieval SHALL freeze one immutable `chatroom-source-context/v1` snapshot per human request, shared by every fanout target. Each source entry SHALL contain `source_ref`, authoritative label/kind/reader ref, `content_identity`, exact ordered retrieved segments, `available_segment_refs` equal to the segment IDs actually included in canonical user/context, and deterministic omission metadata. Attachment identity SHALL include attachment event ID, file ID, byte size, and SHA-256 of the bytes read; evidence identity SHALL include evidence ID and active version number.

The exact excerpt text SHALL be persisted in canonical `prompt_messages`; the attempt event SHALL also persist `selected_source_snapshot` metadata without duplicating the excerpt body. Automatic model/parse retries SHALL reuse the same snapshot and prompt messages. A new human request SHALL revalidate and create a new snapshot. The output validator SHALL use only this frozen snapshot—never the current source listing—as its citation allow-list.

A small selected source SHALL be eligible for full-text inclusion when it fits the context budget, yielding `segment_refs: ["full"]`. A larger selected source SHALL be segmented and searched for relevant paragraphs using a deterministic local retrieval strategy, yielding IDs such as `paragraph:0001`; retrieved content SHALL be bounded by the remaining token budget and SHALL carry source metadata. The system SHALL not silently truncate a source while claiming to have read it, and PDF extraction, image OCR, ZIP inspection, external vector databases, and cloud retrieval SHALL remain out of scope.

#### Scenario: Small file fits in context
- **WHEN** a selected `.md` file is small enough for the remaining budget
- **THEN** its full readable text can be included
- **AND** its full readable text is recorded with `segment_refs: ["full"]` and the source ref/display label

#### Scenario: Large file uses relevant segments
- **WHEN** a selected `.txt` file is larger than the remaining prompt budget
- **THEN** deterministic relevant paragraphs are retrieved within the budget
- **AND** the prompt metadata identifies the source and deterministic IDs such as `paragraph:0001`

#### Scenario: Omitted content is not claimed as read
- **WHEN** selected attachment content cannot fit within the budget
- **THEN** the prompt tells the role that only selected excerpts are available
- **AND** no full-document claim is generated by the retrieval layer

#### Scenario: Retry reuses the same source snapshot
- **WHEN** an automatic retry follows an adapter or output-parse failure
- **THEN** it reuses byte-identical canonical prompt messages and the same content identities/segment allow-list
- **AND** a changed or deleted current source does not silently replace the in-flight snapshot

#### Scenario: Snapshot distinguishes projection from actual retrieval
- **WHEN** the source projection advertises more segments than fit the invocation budget
- **THEN** only the snapshot's actual `available_segment_refs` authorize output citations
- **AND** projection metadata alone cannot validate an omitted segment

### Requirement: Attachment source citations are structured
When a Slice-3 chatroom response uses a concrete fact from a selected source, the prompt and output contract SHALL require a structured `attachment_refs` array. Each item SHALL be exactly `{source_ref: string, label: string, segment_refs: string[]}`; `source_ref`, exact label, and every segment ref SHALL be validated solely against the request's frozen `chatroom-source-context/v1` snapshot, with at least one actual retrieved segment. Generic chat that does not use selected-source facts MAY omit `attachment_refs`. Wrong labels, unselected refs, or segments absent from the snapshot SHALL fail existing output parse/semantic validation. Deletion after completion SHALL not retroactively invalidate the event; the current UI SHALL render that historical citation unavailable. The natural `message` text SHALL remain free-form and SHALL not be forced to contain `[附件一]` anchors.

#### Scenario: Factual answer carries a source chip
- **WHEN** a role answers using a concrete fact from a selected source
- **THEN** the completed event contains a structured attachment reference for that source
- **AND** the frontend can render it as a clickable citation chip

#### Scenario: Generic chat has no artificial citation
- **WHEN** a role answers a question without relying on selected attachment facts
- **THEN** the response may omit `attachment_refs`
- **AND** the UI does not add a fake attachment citation

#### Scenario: Unselected source cannot be cited
- **WHEN** the model attempts to cite an attachment that was not selected with `#`
- **THEN** the backend removes or rejects that invalid reference during output validation
- **AND** the completed event does not claim that source supported the answer

#### Scenario: Citation provenance is exact
- **WHEN** a response cites a source with a wrong label, unknown segment, or ref absent from the frozen snapshot
- **THEN** output parse/semantic validation fails
- **AND** no completed event contains that citation

#### Scenario: Deleted historical citation remains auditable
- **WHEN** a correctly cited source is deleted after the completed event is saved
- **THEN** the event retains its frozen source ref, label, and segment refs
- **AND** the current UI shows the citation as unavailable without breaking the message

## MODIFIED Requirements

### Requirement: Attachment file-type routing
Only chat-upload attachments with `.txt` and `.md` SHALL use the attachment text-material contract. In chatroom mode a text upload SHALL also record an attachment event pointing to the mirrored evidence; in other modes text SHALL retain the existing case-material behavior. Every other extension SHALL be stored as a binary attachment without a type whitelist and SHALL be `SOURCE_NOT_READABLE` for prompt use. Evidence follows the separate active-content rule above. Storage and reader behavior SHALL remain independent from prompt authorization: either approved source kind SHALL become prompt-eligible only after explicit `source_tokens` selection.

#### Scenario: Chatroom text attachment
- **WHEN** a user uploads a `.txt` or `.md` in chatroom mode
- **THEN** it is mirrored using the existing case-evidence contract
- **AND** it appears as an attachment card with on-demand text reading
- **AND** its body is not injected into an AI prompt until explicitly selected with `#`

#### Scenario: Non-text attachment
- **WHEN** a user uploads a PDF, image, ZIP, or other non-text file
- **THEN** it is stored as a binary attachment and is not prompt-readable

### Requirement: AI boundary
Binary attachment metadata and attachment tombstones SHALL NOT be injected into model prompts, chatroom context, or transcript content. Approved attachment text and active evidence SHALL remain available through their existing readers, but a body SHALL be injected only when the current message explicitly selects its `source_ref` through a `source_token`. Without a source token, no attachment or evidence body SHALL be retrieved, regardless of previous turns or natural-language references.

#### Scenario: Binary stays outside AI context
- **WHEN** a role responds in a meeting containing a binary attachment
- **THEN** the assembled prompt and context contain no binary attachment metadata or body

#### Scenario: No # means no text body
- **WHEN** a chatroom contains an active `.txt` attachment and the user sends `請延續剛剛的討論` without a `#` reference
- **THEN** the prompt contains no attachment body
- **AND** the role receives only the allowed transcript, summary, quote, and user instruction

#### Scenario: # authorizes only the selected text
- **WHEN** a chatroom contains `需求.md` and `競品.md` and the user selects only `#需求`
- **THEN** only `需求.md` is eligible for prompt retrieval
- **AND** `競品.md` remains absent from the prompt

### Requirement: Attachment deletion
Every mode SHALL expose attachment deletion. The endpoint SHALL reject running meetings, remove mirrored text evidence before writing the tombstone, and protect legacy title fallback against ambiguous matches. Existing events SHALL remain append-only. Any active `source_ref` to the deleted source SHALL fail send-time validation rather than being silently removed.

#### Scenario: Delete mirrored text attachment
- **WHEN** a user deletes a chatroom text attachment
- **THEN** its mirrored evidence is removed before the tombstone is recorded
- **AND** ambiguous legacy evidence matching returns a client error

#### Scenario: Deleted reference cannot execute
- **WHEN** a composer still contains a `#` reference after that attachment is deleted
- **THEN** sending is rejected before any AI invocation
- **AND** the user can remove or replace the reference

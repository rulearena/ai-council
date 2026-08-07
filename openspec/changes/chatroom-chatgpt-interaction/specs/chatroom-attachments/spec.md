## ADDED Requirements

### Requirement: Explicit source references authorize prompt material
Chatroom prompt construction SHALL accept source material only through explicit composer `#` reference chips represented in the request's ordered, deduplicated `source_refs` list. Source IDs SHALL use `attachment:<file_id>` for chat uploads and `evidence:<evidence_id>` for active text evidence. `notes` SHALL be excluded from the selector and SHALL not be automatically injected by this change. A natural-language mention of a filename, an earlier upload, or "剛剛那份附件" SHALL NOT authorize retrieval. The backend SHALL preserve selection order and SHALL pass only sources belonging to the current meeting. Display labels and ordinary hashtags are presentation/text only; `source_refs` are the sole source authorization.

#### Scenario: Explicit reference selects one source
- **WHEN** a human message contains a selected `#需求說明` reference
- **THEN** the request contains the stable ID for that attachment
- **AND** only that attachment is eligible for prompt retrieval

#### Scenario: Natural wording does not select a source
- **WHEN** a human writes "請看剛剛那份附件" without a `#` reference
- **THEN** no attachment body is retrieved
- **AND** the role is not told that it read an attachment

#### Scenario: Cross-meeting reference is rejected
- **WHEN** a request contains an attachment ID that belongs to another meeting
- **THEN** the chatroom request is rejected before AI execution
- **AND** no cross-meeting content enters the prompt

### Requirement: Chatroom source projection includes attachments and case materials
The chatroom source selector SHALL project active chat-upload attachments and existing or newly created active text evidence from the current meeting, excluding `notes`. Attachment sources SHALL use `attachment:<file_id>` IDs; evidence sources SHALL use `evidence:<evidence_id>` IDs. `GET /meetings/{meeting_id}/chat/sources` and the meeting read projection SHALL expose each source's `source_ref`, display label, kind, readable/active state, and `reader_ref`. Same-name sources SHALL show kind/size/date and retain the hidden source ref for disambiguation. Existing meetings SHALL be projected at read time without migration. A source SHALL be readable through the attachment reader/blob store or current active evidence-version reader, and deletion, tombstoning, or inactive status SHALL make it invalid for send-time validation.

#### Scenario: Legacy case material is selectable
- **WHEN** an old meeting already has a readable text case material
- **THEN** it appears in the source projection with an `evidence:` ID
- **AND** it can be selected with `#` without rewriting meeting metadata

#### Scenario: Host fallback sees legacy material
- **WHEN** a legacy case material has no explicit `host` in `visible_roles`
- **THEN** the fixed chatroom Host can select and read it through the chatroom-role visibility fallback
- **AND** other roles still use their explicit visibility rules

#### Scenario: @all validates every target
- **WHEN** `@all` selects a source visible to some but not all active roles
- **THEN** validation fails before any target job or human event is created
- **AND** the response identifies the target/source visibility failure

### Requirement: Attachment references are validated at send time
Every selected attachment reference SHALL be validated immediately before the AI job starts. The attachment SHALL exist, be active, belong to the meeting, be visible to the target role, and use a currently AI-readable type. If any selected reference fails validation, the entire AI request SHALL be blocked; the system SHALL not silently skip, substitute, or downgrade that reference. The composer SHALL preserve the input and references for correction.

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
The current prompt-readable attachment types SHALL remain `.txt` and `.md`. A small selected text attachment SHALL be eligible for full-text inclusion when it fits the context budget. A larger selected file SHALL be segmented and searched for relevant paragraphs using a deterministic local retrieval strategy; retrieved content SHALL be bounded by the remaining token budget and SHALL carry source metadata. The system SHALL not silently truncate a source while claiming to have read it, and PDF extraction, image OCR, ZIP inspection, external vector databases, and cloud retrieval SHALL remain out of scope.

#### Scenario: Small file fits in context
- **WHEN** a selected `.md` file is small enough for the remaining budget
- **THEN** its full readable text can be included
- **AND** the prompt records its stable source ID and display label

#### Scenario: Large file uses relevant segments
- **WHEN** a selected `.txt` file is larger than the remaining prompt budget
- **THEN** deterministic relevant paragraphs are retrieved within the budget
- **AND** the prompt metadata identifies the source and retrieved segments

#### Scenario: Omitted content is not claimed as read
- **WHEN** selected attachment content cannot fit within the budget
- **THEN** the prompt tells the role that only selected excerpts are available
- **AND** no full-document claim is generated by the retrieval layer

### Requirement: Attachment source citations are structured
When a chatroom response uses a concrete fact from a selected source, the prompt and output contract SHALL require a structured `attachment_refs` array. Each item SHALL be exactly `{source_ref: string, label: string, segment_refs: string[]}`; `source_ref` SHALL belong to the selected allow-list. Generic chat that does not use selected-source facts MAY omit `attachment_refs`. The natural `message` text SHALL remain free-form and SHALL not be forced to contain `[附件一]` anchors. A response SHALL not contain source references for unselected or unavailable sources.

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

## MODIFIED Requirements

### Requirement: Attachment file-type routing
Only `.txt` and `.md` SHALL use the text-material contract. In chatroom mode a text upload SHALL also record an attachment event pointing to the mirrored evidence; in other modes text SHALL retain the existing case-material behavior. Every other extension SHALL be stored as a binary attachment without a type whitelist. Storage and reader behavior SHALL remain independent from prompt authorization: a chatroom text attachment SHALL become prompt-eligible only after the user explicitly selects it with `#`.

#### Scenario: Chatroom text attachment
- **WHEN** a user uploads a `.txt` or `.md` in chatroom mode
- **THEN** it is mirrored using the existing case-evidence contract
- **AND** it appears as an attachment card with on-demand text reading
- **AND** its body is not injected into an AI prompt until explicitly selected with `#`

#### Scenario: Non-text attachment
- **WHEN** a user uploads a PDF, image, ZIP, or other non-text file
- **THEN** it is stored as a binary attachment and is not prompt-readable

### Requirement: AI boundary
Binary attachment metadata and attachment tombstones SHALL NOT be injected into model prompts, chatroom context, or transcript content. Mirrored chatroom text SHALL remain available through the existing case-material and reader contracts, but its body SHALL be injected into a chatroom prompt only when the current message explicitly selects that attachment with `#`. Without `#`, no attachment body SHALL be retrieved, regardless of previous turns or natural-language references.

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
Every mode SHALL expose attachment deletion. The endpoint SHALL reject running meetings, remove mirrored text evidence before writing the tombstone, and protect legacy title fallback against ambiguous matches. Existing events SHALL remain append-only. Any active `#` reference to the deleted attachment SHALL fail send-time validation rather than being silently removed.

#### Scenario: Delete mirrored text attachment
- **WHEN** a user deletes a chatroom text attachment
- **THEN** its mirrored evidence is removed before the tombstone is recorded
- **AND** ambiguous legacy evidence matching returns a client error

#### Scenario: Deleted reference cannot execute
- **WHEN** a composer still contains a `#` reference after that attachment is deleted
- **THEN** sending is rejected before any AI invocation
- **AND** the user can remove or replace the reference

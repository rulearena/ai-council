## ADDED Requirements

### Requirement: Binary attachment storage
The system SHALL store binary chat attachments as immutable blobs in a data-dir attachments directory (`<meeting_id>/attachments/`), keyed by a unique `file_id`. The blob SHALL be written before the metadata event is appended. Metadata (filename, size, mime_type, file_id) SHALL be persisted as an append-only event in the meeting's `events.jsonl`. The system SHALL NOT rewrite, backfill, or migrate historical events.

#### Scenario: Upload writes blob then event
- **WHEN** the user uploads a PDF through the `+` modal
- **THEN** the blob is stored under the meeting's attachments directory
- **AND** an attachment metadata event is appended to `events.jsonl`

#### Scenario: Download resolves by file_id
- **WHEN** a user requests an attachment by `file_id`
- **THEN** the system resolves the real path from the metadata event and serves the blob

#### Scenario: Unknown file_id is rejected
- **WHEN** a user requests an attachment with an unknown `file_id`
- **THEN** the system returns a not-found error

### Requirement: Attachment file-type routing
Uploaded files SHALL be routed by extension: `.txt` and `.md` files follow the existing versioned case-files contract (AI-visible, per-file character limit, `visible_roles`, revisioning); all other file types SHALL be stored as binary attachments.

#### Scenario: Text file uses case-files contract
- **WHEN** the user uploads a `.txt` file via the `+` modal
- **THEN** the file is ingested as a versioned case-file with the existing character limit and `visible_roles`
- **AND** it does not appear as a chat bubble

#### Scenario: PDF stored as binary attachment
- **WHEN** the user uploads a PDF via the `+` modal
- **THEN** the file is stored as a binary attachment with a metadata event
- **AND** it appears as a downloadable card in the chat feed

#### Scenario: Non-text file stored as binary
- **WHEN** the user uploads a `.zip` file via the `+` modal
- **THEN** the file is stored as a binary attachment with a metadata event
- **AND** it appears as a downloadable card in the chat feed

### Requirement: Attachment size limits
Binary attachments SHALL be limited to 10 MB per file and 50 MB total per meeting by default. These limits SHALL be overridable via environment variables. Text attachments SHALL use the existing case-files character limits.

#### Scenario: File over per-file limit rejected
- **WHEN** the user uploads a 12 MB PNG
- **THEN** the upload is rejected with an inline error
- **AND** no blob is stored

#### Scenario: Meeting over aggregate limit rejected
- **WHEN** uploading a file would exceed the meeting's aggregate attachment quota
- **THEN** the upload is rejected with an inline error

### Requirement: Binary attachment visibility
Binary attachments SHALL be visible and downloadable to all participants of the meeting, independent of any role. Text attachments SHALL continue to honor the existing case-files `visible_roles`.

#### Scenario: Binary attachment visible to all roles
- **WHEN** a meeting with multiple roles has an uploaded image
- **THEN** every participant sees the image bubble and can download it

### Requirement: AI unaware of binary attachments
Binary attachments SHALL NOT be injected into the model prompt and SHALL NOT be mentioned in the AI context. The AI SHALL have no knowledge that binary attachments exist in the meeting.

#### Scenario: AI context excludes binary attachments
- **WHEN** a binary attachment exists in the meeting and an AI role responds
- **THEN** the prompt and context assembled for the model contain no attachment metadata
- **AND** the AI response does not reference the attachment (manual acceptance description; LLM output is not deterministically testable)

### Requirement: Attachments are append-only
Binary attachments SHALL NOT be deletable or deactivatable in v1. An uploaded attachment, its blob, and its metadata event SHALL remain for the lifetime of the meeting.

#### Scenario: No delete control for attachments
- **WHEN** a user inspects the controls available for an uploaded attachment
- **THEN** no delete or deactivate control is present

### Requirement: Upload timing
The system SHALL upload a selected file immediately upon selection in the `+` modal, without requiring accompanying text. Upload progress and failures SHALL be shown inline, and a failed upload SHALL be retryable.

#### Scenario: Immediate upload without text
- **WHEN** the user selects a file in the `+` modal without typing any text
- **THEN** the file uploads immediately
- **AND** the attachment appears in the chat feed once complete

#### Scenario: Upload failure shows inline error
- **WHEN** an upload fails (for example, exceeding a size limit)
- **THEN** the modal shows an inline error for that file
- **AND** the user can retry or dismiss the failed upload

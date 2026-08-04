# chatroom-attachments Specification

## Purpose
TBD - created by archiving change chatroom-line-attachments. Update Purpose after archive.
## Requirements
### Requirement: Binary attachment storage and lifecycle
The system SHALL store binary chat attachments under the meeting attachment directory, keyed by `file_id`, writing the blob before appending an `attachment-added` event. Removal SHALL append an `attachment-removed` tombstone, delete the blob, release quota, and never rewrite the original event. Removed attachments SHALL project as `removed: true` and downloads SHALL return not found.

#### Scenario: Upload and remove attachment
- **WHEN** a user uploads and later removes a PDF
- **THEN** the blob is written before its metadata event
- **AND** removal appends a tombstone and deletes the blob
- **AND** the feed retains a non-interactive removed card

#### Scenario: Unknown or removed file is rejected
- **WHEN** a user requests an unknown or removed `file_id`
- **THEN** the system returns a not-found error

### Requirement: Attachment file-type routing
Only `.txt` and `.md` SHALL use the text-material contract. In chatroom mode a text upload SHALL also record an attachment event pointing to the mirrored evidence; in other modes text SHALL retain the existing case-material behavior. Every other extension SHALL be stored as a binary attachment without a type whitelist.

#### Scenario: Chatroom text attachment
- **WHEN** a user uploads a `.txt` or `.md` in chatroom mode
- **THEN** it is AI-visible through mirrored case evidence
- **AND** an attachment card appears in the feed with on-demand text reading

#### Scenario: Non-text attachment
- **WHEN** a user uploads a PDF, image, ZIP, or other non-text file
- **THEN** it is stored as a binary attachment and is AI-invisible

### Requirement: Attachment limits and visibility
Binary attachments SHALL be limited to 10 MB per file and 50 MB total per meeting by default, with environment overrides. Binary attachments SHALL be visible/downloadable to all meeting participants independent of `visible_roles`; text evidence SHALL retain its existing visibility rules.

#### Scenario: Limit and visibility enforcement
- **WHEN** an upload exceeds either binary limit
- **THEN** it is rejected without a blob or event
- **AND** an accepted binary remains downloadable to every participant

### Requirement: AI boundary
Binary attachment metadata and attachment tombstones SHALL NOT be injected into model prompts, chatroom context, or transcript content. Mirrored chatroom text SHALL remain AI-visible through case evidence.

#### Scenario: Binary stays outside AI context
- **WHEN** a role responds in a meeting containing a binary attachment
- **THEN** the assembled prompt and context contain no binary attachment metadata

### Requirement: Attachment deletion
Every mode SHALL expose attachment deletion. The endpoint SHALL reject running meetings, remove mirrored text evidence before writing the tombstone, and protect legacy title fallback against ambiguous matches. Existing events SHALL remain append-only.

#### Scenario: Delete mirrored text attachment
- **WHEN** a user deletes a chatroom text attachment
- **THEN** its mirrored evidence is removed before the tombstone is recorded
- **AND** ambiguous legacy evidence matching returns a client error

### Requirement: Chatroom pending-impact projection
Chatroom material mutations SHALL not create pending impact, and chatroom read projections SHALL suppress legacy pending impact so existing meetings cannot be deadlocked by an old impact marker. Other modes SHALL retain their existing impact behavior.

#### Scenario: Legacy impact does not deadlock chatroom
- **WHEN** a chatroom has legacy pending impact and the user sends a response
- **THEN** the chatroom projection omits the impact and the response is not blocked by it

### Requirement: Upload timing
Selecting a file SHALL upload it immediately through the resident file input. Progress and failures SHALL be shown inline and failed uploads SHALL be retryable.

#### Scenario: Immediate upload and retry
- **WHEN** the user selects a file and the first upload fails
- **THEN** progress and the failure are shown inline
- **AND** retrying uploads the same file without requiring message text

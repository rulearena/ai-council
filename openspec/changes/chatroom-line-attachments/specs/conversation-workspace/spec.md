## MODIFIED Requirements

### Requirement: Case file entry point in chatroom composer
The chatroom composer SHALL include a "+" button or equivalent that opens the unified case-files and attachment upload/management flow. The "+" entry point SHALL present a single modal combining a file-upload zone and the existing case-files list, and SHALL work identically in relay/parallel modes. `.txt/.md/.markdown` files are ingested into the versioned case-files flow; PDF/PNG/JPG files are uploaded as binary chat attachments. An "附件（N）" count SHALL total both binary attachments and text case-files.

#### Scenario: Case files accessible from chatroom
- **WHEN** the user clicks the case file entry point in chatroom mode
- **THEN** the unified attachment/case-files modal opens with an upload zone and the existing case-files list

#### Scenario: Text file ingested as case-file
- **WHEN** the user uploads a `.md` file from the unified modal
- **THEN** the file is ingested into the versioned case-files flow and appears in the case-files list

#### Scenario: Binary file uploaded as attachment
- **WHEN** the user uploads a JPEG from the unified modal
- **THEN** the file is stored as a binary attachment and appears as a chat bubble

#### Scenario: Attachment count totals both kinds
- **WHEN** a meeting has 2 binary attachments and 3 active text case-files
- **THEN** the "附件（N）" label shows 附件（5）

## ADDED Requirements

### Requirement: Attachment bubbles in chat feed
Binary attachment metadata SHALL be rendered in the chat feed as message bubbles: image attachments (PNG/JPG) SHALL display an inline thumbnail that opens a lightbox view on click; PDF attachments SHALL display a card with filename, size, and a download control. Text case-files SHALL NOT appear as chat bubbles. Downloading an attachment SHALL use the file_id-based download endpoint.

#### Scenario: Image renders as thumbnail with lightbox
- **WHEN** the chat feed contains an image attachment bubble
- **THEN** the bubble shows an inline thumbnail
- **AND** clicking the thumbnail opens a full-size lightbox view

#### Scenario: PDF renders as download card
- **WHEN** the chat feed contains a PDF attachment bubble
- **THEN** the bubble shows a card with the filename and size
- **AND** a download control fetches the file by file_id

#### Scenario: Text case-files stay out of the feed
- **WHEN** a meeting has an active text case-file
- **THEN** no chat bubble is rendered for it
- **AND** it remains available only in the case-files modal

### Requirement: Courtroom attachment wording
In courtroom (court) meetings, the unified attachment/case-files modal SHALL reuse the same upload flow and list as chatroom/relay/parallel modes, with the terminology localized to "證物" for binary attachments and case-files.

#### Scenario: Court mode uses evidence wording
- **WHEN** a courtroom meeting opens the unified attachment/case-files modal
- **THEN** the modal labels binary attachments and case-files with "證物" wording

### Requirement: Attachment bubble downloadability for all participants
Every participant in the meeting SHALL see binary attachment bubbles and be able to download them, independent of role or visibility settings.

#### Scenario: All roles can download a shared attachment
- **WHEN** any participant clicks the download control on an attachment bubble
- **THEN** the file is served from the file_id-based download endpoint

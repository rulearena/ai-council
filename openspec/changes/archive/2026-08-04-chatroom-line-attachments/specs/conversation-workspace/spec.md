## MODIFIED Requirements

### Requirement: Case file entry point in chatroom composer
The chatroom composer SHALL include a `+` button that directly opens the native file picker through a resident input. It SHALL not open a modal or quick-menu. Upload progress and attachment management SHALL be available in the context panel’s materials/data tab, with courtroom wording localized to 案卷/證物. `.txt` and `.md` files SHALL follow the chatroom text-mirroring contract; other files SHALL be binary attachments. The count SHALL exclude removed attachments.

#### Scenario: Direct LINE-style upload
- **WHEN** the user clicks `+` and selects a file
- **THEN** the file uploads immediately without an intermediate menu or modal
- **AND** progress is visible in the materials tab

#### Scenario: Materials management
- **WHEN** the user opens the context panel materials/data tab
- **THEN** active attachments, upload progress, and the accepted simple chatroom text projection are visible
- **AND** chatroom does not expose the old notes/form/version-management flow

## ADDED Requirements

### Requirement: Attachment bubbles in chat feed
Binary attachment metadata SHALL render as feed bubbles: images as thumbnail/lightbox, PDFs and generic binaries as filename/size/download cards. Chatroom text attachments SHALL render as a card with an on-demand reader, not full text. Removed attachments SHALL remain as non-clickable “已刪除” cards. Downloads SHALL use `file_id`.

#### Scenario: Render active and removed attachments
- **WHEN** the feed contains an image, PDF, generic binary, text, and removed attachment
- **THEN** each active type uses its corresponding card/reader presentation
- **AND** the removed card cannot be opened or downloaded

### Requirement: Attachment deletion in feed
Each active attachment bubble SHALL expose a delete control. The control SHALL use neutral irreversible confirmation. After deletion the bubble SHALL remain visible as a non-interactive removed card and the management list/count SHALL refresh.

#### Scenario: Delete from feed
- **WHEN** the user confirms deletion from an active attachment bubble
- **THEN** the bubble becomes a non-interactive removed card
- **AND** the materials list and count refresh

### Requirement: Attachment bubble downloadability for all participants
Every participant SHALL see active binary attachment bubbles and be able to download them independent of role or visibility settings.

#### Scenario: Shared binary download
- **WHEN** any participant activates a binary attachment download control
- **THEN** the file is served by its `file_id`

# 42 - Prompt Version Metadata Persistence

Status: resolved
Type: task

## What to build

Persist lightweight prompt and schema version metadata on model attempt events so future debugging, replay, and prompt/schema migration work can identify which prompt template and output schema were used.

## Blocked by

04 - Prompt Rendering And Output Parsing; 06 - MeetingRunner Red/Blue/Judge Flow

## Acceptance Criteria

- [x] Completed model events include `prompt_template_name`.
- [x] Completed model events include `prompt_template_hash`.
- [x] Failed model attempt events include `prompt_template_name` and `prompt_template_hash`.
- [x] Model attempt events include `output_schema_hash`.
- [x] Fixed-flow events preserve the correct template name for each stage.
- [x] Frontend API event types include the optional metadata fields.

## Resolution Notes

- Added SHA-256 hashes for prompt template file contents and the shared output schema string.
- Runner now persists prompt template and schema hashes on completed and failed model attempt events.
- Frontend API types were updated only for the new optional event fields; no UI was added.

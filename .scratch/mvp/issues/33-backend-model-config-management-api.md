# 33 - Backend Model Config Management API

Status: resolved
Type: task

## What to build

Add backend-only model config management so a future frontend settings page can edit `config/models.yaml` through supported APIs.

## Blocked by

03 - Model Config Repository; 20 - Model Connection Test

## Acceptance Criteria

- [x] Repository can add a new model config and persist it to YAML.
- [x] Repository can update an existing model config without reordering other entries.
- [x] Repository can delete an existing model config.
- [x] Repository validates adapter-specific required fields before writing YAML.
- [x] API exposes `PUT /models/{model_config_id}`.
- [x] API exposes `DELETE /models/{model_config_id}`.
- [x] Invalid model config writes return `400`.

## Resolution Notes

- Added `ModelConfigRepository.save_model()` and `delete_model()`.
- Added adapter-specific write validation for HTTP and subscription CLI configs.
- Added backend API routes for upsert and delete.
- Preserved existing permissive read behavior for unknown manually configured adapters so existing runner failure behavior remains intact.


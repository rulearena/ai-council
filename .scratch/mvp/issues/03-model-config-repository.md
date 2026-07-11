# 03 - Model Config Repository

Status: resolved
Type: task

## What to build

Create a file-backed model configuration repository that loads configured model endpoints and represents availability status without blocking backend startup.

## Blocked by

01 - Backend Skeleton And MeetingRepository

## Acceptance Criteria

- [x] `config/models.yaml` style config loads into typed model config objects.
- [x] Missing config returns an empty configured model list.
- [x] qwen27/ornith example configs remain representable, including `extra_body`.
- [x] Model status can be reported as `unknown`, `available`, or `unavailable`.

## Test Strategy

Use TDD at the `ModelConfigRepository` public interface seam. Tests should load YAML from temp files and assert model ids, adapter fields, JSON mode flag, extra request body, and default unknown status.

## Answer

Implemented file-backed `ModelConfigRepository` and typed `ModelConfig`.

Validation:

```bash
cd backend && /Users/chrischiu/.pyenv/versions/3.11.9/bin/python -m pytest tests/test_model_config_repository.py
```

Result: 3 passed.

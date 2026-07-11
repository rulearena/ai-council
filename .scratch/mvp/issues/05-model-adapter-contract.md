# 05 - ModelAdapter Contract With Mock And OpenAI-Compatible HTTP

Status: resolved
Type: task

## What to build

Create a model adapter contract with a deterministic mock adapter and an OpenAI-compatible HTTP adapter that can call cloud or local endpoints.

## Blocked by

03 - Model Config Repository
04 - Prompt Rendering And Output Parsing

## Acceptance Criteria

- [x] Mock adapter returns deterministic valid role output.
- [x] HTTP adapter calls `/v1/chat/completions`.
- [x] JSON mode and extra request body are supported when configured.
- [x] Adapter errors surface as structured failures.

## Test Strategy

Use TDD at the adapter public interface seam. Test mock adapter directly and HTTP adapter with a local in-process HTTP server.

## Answer

Implemented `MockModelAdapter` and `OpenAICompatibleHTTPAdapter`.

Validation:

```bash
cd backend && /Users/chrischiu/.pyenv/versions/3.11.9/bin/python -m pytest tests/test_model_adapters.py
```

Result: 3 passed.

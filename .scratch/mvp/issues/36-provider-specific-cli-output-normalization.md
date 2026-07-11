# 36 - Provider-Specific CLI Output Normalization

Status: resolved
Type: task

## What to build

Let subscription CLI configs opt into provider-specific stdout cleanup without changing the core parser.

## Blocked by

32 - Subscription CLI Provider

## Acceptance Criteria

- [x] `subscription-cli` still strips ANSI control codes for all providers.
- [x] Model configs can declare a CLI provider through `extra_body.cli_provider`.
- [x] Codex provider normalization can extract content wrapped in `<codex-output>...</codex-output>`.
- [x] Unknown providers fall back to safe generic normalization.
- [x] `config/models.yaml.example` marks `codex-subscription` with `cli_provider: codex`.

## Resolution Notes

- Added provider-aware CLI output normalization.
- Kept generic ANSI stripping as the baseline for every subscription CLI.
- Added Codex-specific wrapper extraction.


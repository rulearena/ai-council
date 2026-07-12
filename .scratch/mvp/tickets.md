# Tickets: AI Council MVP

Build the MVP described in `spec.md`: a local AI meeting orchestration app with a fixed red/blue/judge flow, local event persistence, model adapters, API/WebSocket, and Vue control/debug UI.

Work the **frontier**: any ticket whose blockers are all done. For this MVP, start at Ticket 01.

## 01 - Backend Skeleton And MeetingRepository

**What to build:** A testable backend package with file-backed meeting event storage so the system can append and replay JSONL meeting events.

**Blocked by:** None - can start immediately.

- [x] Backend package and pytest setup exist.
- [x] `MeetingRepository` appends events under `data/meetings/<meeting_id>/events.jsonl`.
- [x] Reading missing meeting events returns an empty list.
- [x] Appended events round-trip in order.
- [x] Data directory can be injected for tests/local runs.

## 02 - Transcript Projection

**What to build:** A transcript projector that turns stored events into a human-readable Markdown transcript without making Markdown the source of truth.

**Blocked by:** 01 - Backend Skeleton And MeetingRepository.

- [x] Transcript output is derived from events.
- [x] Blue/Red/Judge completed outputs render clearly.
- [x] Failed/cancelled steps render as status entries.
- [x] Projection is deterministic and covered by tests.

## 03 - Model Config Repository

**What to build:** File-backed model configuration loading so the backend can list configured local/cloud OpenAI-compatible models and expose availability status.

**Blocked by:** 01 - Backend Skeleton And MeetingRepository.

- [x] `config/models.yaml` style config loads into typed model config objects.
- [x] Missing config can fall back to safe defaults or clear errors.
- [x] qwen27/ornith example configs remain representable.
- [x] Model status can be reported as `unknown`, `available`, or `unavailable`.

## 04 - Prompt Rendering And Output Parsing

**What to build:** Prompt template rendering and schema-based parser for the shared role output JSON.

**Blocked by:** 01 - Backend Skeleton And MeetingRepository.

- [x] Role/stage prompt templates load from files.
- [x] Topic, prior transcript, role, and required JSON schema are injected.
- [x] Parser handles JSON code fences and surrounding text.
- [x] Invalid output produces a structured parse failure.

## 05 - ModelAdapter Contract With Mock And OpenAI-Compatible HTTP

**What to build:** A model adapter interface with a deterministic mock adapter and an OpenAI-compatible HTTP adapter that can call cloud or local endpoints.

**Blocked by:** 03 - Model Config Repository; 04 - Prompt Rendering And Output Parsing.

- [x] Mock adapter returns deterministic valid role output.
- [x] HTTP adapter calls `/v1/chat/completions`.
- [x] JSON mode and extra request body are supported when configured.
- [x] Adapter errors surface as structured failures.

## 06 - MeetingRunner Red/Blue/Judge Flow

**What to build:** The core meeting runner that executes Blue propose, Red critique, Blue revise, and Judge decide using event log persistence.

**Blocked by:** 02 - Transcript Projection; 05 - ModelAdapter Contract With Mock And OpenAI-Compatible HTTP.

- [x] Runner creates ordered step events.
- [x] Successful mock run completes all four steps.
- [x] Parse/adapter failure marks the step failed.
- [x] Failed step retry creates a new attempt and can continue the meeting.
- [x] Cancel stops unstarted steps and records cancellation.

## 07 - FastAPI Meeting And Model API

**What to build:** HTTP API endpoints for models, meetings, run control, retry, cancel, and transcript download.

**Blocked by:** 06 - MeetingRunner Red/Blue/Judge Flow.

- [x] `GET /models` and model test endpoint work.
- [x] Meeting create/list/get endpoints work.
- [x] Start/cancel/retry endpoints invoke runner behavior.
- [x] Transcript download returns generated Markdown.

## 08 - WebSocket Event Feed

**What to build:** A WebSocket feed that lets the frontend subscribe to meeting events/status updates.

**Blocked by:** 07 - FastAPI Meeting And Model API.

- [x] Clients can subscribe to a meeting event stream.
- [x] Existing meeting events are replayed to subscribers.
- [x] Refresh still reconstructs state through HTTP API.
- [x] WebSocket code does not own orchestration logic.

## 09 - Vue Control And Debug UI

**What to build:** A Vue 3 control/debug UI for creating meetings, selecting models, starting/cancelling runs, viewing timeline/debug output, and previewing transcripts.

**Blocked by:** 07 - FastAPI Meeting And Model API; 08 - WebSocket Event Feed.

- [x] Meeting list and create flow work.
- [x] Blue/Red/Judge model selectors work.
- [x] Timeline reflects step status.
- [x] Debug panel shows raw/parsed/error details.
- [x] Transcript preview and download are available.
- [x] Required `data-testid` contract is present.

## 10 - Local Dev Documentation And Examples

**What to build:** Local setup docs and examples so the MVP can be run and tested consistently.

**Blocked by:** 07 - FastAPI Meeting And Model API; 09 - Vue Control And Debug UI.

- [x] README documents backend and frontend dev commands.
- [x] `.env.example` documents data/config variables.
- [x] `config/models.yaml.example` stays aligned with implemented config schema.
- [x] Prompt templates are documented or discoverable.

## 11 - Human Chair Message Slice

**What to build:** Allow the user to add chairperson feedback inside an existing meeting, so the user can act as the meeting chair instead of only defining the initial topic.

**Blocked by:** 09 - Vue Control And Debug UI.

- [x] API can append a human chair message to a meeting.
- [x] Human chair messages are persisted as JSONL events.
- [x] Transcript projection renders human chair messages as plain meeting turns.
- [x] Future AI prompts include human chair messages through `prior_transcript`.
- [x] Frontend exposes a chair message input and submit action.
- [x] Stable `data-testid` contract exists for the new controls.

## 12 - Frontend E2E And Visual Smoke

**What to build:** Add a real browser E2E/DOM smoke test for the Vue control/debug UI before continuing broader second-version work.

**Blocked by:** 09 - Vue Control And Debug UI; 11 - Human Chair Message Slice.

- [x] E2E test uses stable `data-testid` selectors.
- [x] E2E creates a meeting through the UI.
- [x] E2E selects `mock-fast` for Blue/Red/Judge.
- [x] E2E starts a mock run and verifies timeline/debug/transcript updates.
- [x] E2E sends a chair message and verifies timeline/debug/transcript updates.
- [x] Visual smoke screenshot is generated and inspected.

## 13 - Follow-Up Round Event Naming

**What to build:** Make follow-up discussion rounds distinguishable after the chair adds feedback and continues the meeting.

**Blocked by:** 11 - Human Chair Message Slice; 12 - Frontend E2E And Visual Smoke.

- [x] First AI round keeps existing MVP step ids.
- [x] Second and later AI rounds use `round-N-*` step ids.
- [x] Events record `round` and `base_step_id`.
- [x] Event ids are unique across rounds.
- [x] Follow-up prompts include the human chair feedback in prior transcript.
- [x] E2E verifies `round-2-*` steps appear in the UI after continuing.

## 14 - Chair Directed Role Response

**What to build:** Allow the chair to ask a specific AI role to respond without running the full Blue -> Red -> Blue -> Judge sequence.

**Blocked by:** 11 - Human Chair Message Slice; 12 - Frontend E2E And Visual Smoke.

- [x] API can request a single Blue/Red/Judge response.
- [x] Directed response events are distinguishable from full-round events.
- [x] Directed response prompts include the existing transcript and chair feedback.
- [x] Frontend exposes role-specific response buttons.
- [x] Stable `data-testid` contract exists for the new controls.
- [x] E2E verifies a directed Blue response appears in timeline/debug/transcript.
- [x] Missing requested-role model assignment returns a clear `400`.

## 15 - Chair Close Meeting

**What to build:** Allow the chair to close a meeting and prevent future AI steps from being appended after closure.

**Blocked by:** 11 - Human Chair Message Slice; 14 - Chair Directed Role Response.

- [x] API can close a meeting.
- [x] Closing writes a System `closed` event.
- [x] Transcript projection shows the closed status.
- [x] Runner does not start full rounds after closure.
- [x] Runner does not run directed role responses after closure.
- [x] Frontend exposes a close meeting button.
- [x] E2E verifies closed status appears in timeline/transcript.

## 16 - Terminal State Enforcement

**What to build:** Make closed/cancelled meetings behave as terminal states across backend and frontend.

**Blocked by:** 15 - Chair Close Meeting.

- [x] Closing/cancelling a meeting is idempotent.
- [x] Closed meetings cannot append future full-round AI events.
- [x] Closed meetings cannot append future directed role response events.
- [x] Frontend disables start/cancel/close once a meeting is terminal.
- [x] Frontend disables chair message input and role response buttons once terminal.
- [x] E2E verifies terminal controls are disabled after closure.

## 17 - Terminal API Conflicts

**What to build:** Return clear API conflicts when a closed/cancelled meeting receives event-creating requests.

**Blocked by:** 16 - Terminal State Enforcement.

- [x] `POST /meetings/{meeting_id}/start` returns `409` when terminal.
- [x] `POST /meetings/{meeting_id}/messages` returns `409` when terminal.
- [x] `POST /meetings/{meeting_id}/roles/{role}/respond` returns `409` when terminal.
- [x] `POST /meetings/{meeting_id}/steps/{step_id}/retry` returns `409` when terminal.
- [x] Rejected terminal calls do not append events.

## 18 - Meeting Status Projection

**What to build:** Expose and display a simple meeting status so users can distinguish open, closed, and cancelled meetings.

**Blocked by:** 16 - Terminal State Enforcement.

- [x] `POST /meetings` returns `status: open`.
- [x] `GET /meetings` returns status per meeting.
- [x] `GET /meetings/{meeting_id}` returns status.
- [x] Closed meetings project as `closed`.
- [x] Cancelled meetings project as `cancelled`.
- [x] Frontend meeting list displays the status.
- [x] Frontend selected meeting heading displays the status.
- [x] E2E verifies open and closed statuses are visible.

## 19 - Round Scoped Retry

**What to build:** Allow failed steps from later rounds, such as `round-2-red-critique`, to be retried correctly.

**Blocked by:** 13 - Follow-Up Round Event Naming.

- [x] Retry accepts a round-scoped failed `step_id`.
- [x] Retry uses `base_step_id` to map back to the fixed step sequence.
- [x] Retry keeps the failed event's round number.
- [x] Retry emits round-scoped completed step ids after success.
- [x] Retry continues from the failed step through the rest of that round.

## 20 - Model Connection Test

**What to build:** Make model connection testing actually exercise configured adapters and expose the result in the frontend.

**Blocked by:** 07 - FastAPI Meeting And Model API; 09 - Vue Control And Debug UI.

- [x] Mock model test returns `available`.
- [x] OpenAI-compatible HTTP model test calls the adapter.
- [x] HTTP adapter success returns `available`.
- [x] HTTP adapter failure returns `unavailable` with an error message.
- [x] Frontend exposes model test buttons for Blue/Red/Judge selections.
- [x] Frontend displays model test status.
- [x] E2E verifies `mock-fast` reports available.

## 21 - Role Sequence Auto-Continuation

**What to build:** Allow the chair to run a preset sequence of Blue/Red/Judge responses so multiple roles can respond automatically after chair feedback.

**Blocked by:** 14 - Chair Directed Role Response; 17 - Terminal API Conflicts.

- [x] Runner can execute an ordered role sequence.
- [x] Sequence events are distinguishable from directed single-role events.
- [x] Sequence events record `sequence` and `sequence_index`.
- [x] API exposes `POST /meetings/{meeting_id}/sequences`.
- [x] Unknown roles return a clear `400`.
- [x] Terminal meetings reject sequence requests with `409`.

## 22 - Frontend Topology Presets

**What to build:** Add a minimal frontend control for preset speaking orders without introducing a full drag-and-drop topology editor.

**Blocked by:** 21 - Role Sequence Auto-Continuation.

- [x] Frontend exposes a sequence preset selector.
- [x] Frontend can run `Red -> Blue -> Judge`.
- [x] Frontend can run smaller presets such as `Red -> Blue` and `Judge only`.
- [x] Sequence controls use stable `data-testid` selectors.
- [x] Sequence controls are disabled after terminal state.

## 23 - Expanded E2E Flow

**What to build:** Extend the browser smoke test to cover model availability, human feedback, directed responses, role sequence auto-continuation, follow-up rounds, and terminal controls.

**Blocked by:** 12 - Frontend E2E And Visual Smoke; 22 - Frontend Topology Presets.

- [x] E2E verifies `mock-fast` model test status.
- [x] E2E verifies directed role response events.
- [x] E2E verifies role-sequence events in timeline/debug/transcript.
- [x] E2E verifies follow-up round after sequence execution.
- [x] E2E verifies terminal controls are disabled after closure.

## 24 - Local Run And Test Scripts

**What to build:** Add repo-local scripts for repeatable backend/frontend startup and validation without managing local model services.

**Blocked by:** 10 - Local Dev Documentation And Examples.

- [x] `scripts/dev_backend.sh` starts the FastAPI app using repo-local defaults.
- [x] `scripts/dev_frontend.sh` starts Vite with the configured API base URL.
- [x] `scripts/test_all.sh` runs backend tests and frontend build.
- [x] README documents the scripts and E2E validation flow.

## 25 - Meeting Activity Projection

**What to build:** Expose richer meeting state so the UI can show whether the latest meeting activity is idle, waiting, completed, failed, closed, or cancelled.

**Blocked by:** 18 - Meeting Status Projection.

- [x] Events receive `created_at` timestamps when appended.
- [x] Meeting create/list/get responses include `created_at` and `updated_at`.
- [x] Meeting create/list/get responses include `activity_status`.
- [x] Meeting create/list/get responses include `last_step_id`.
- [x] Action endpoints return projected activity status after execution.

## 26 - Frontend Failed Step Retry

**What to build:** Let the user retry failed steps directly from the timeline.

**Blocked by:** 19 - Round Scoped Retry; 25 - Meeting Activity Projection.

- [x] Frontend API client exposes retry step.
- [x] Failed timeline events show a retry button.
- [x] Retry refreshes meeting state and transcript after completion.
- [x] Retry controls are disabled for terminal meetings or missing model selections.
- [x] Retry API returns `400` for non-failed steps instead of leaking a server error.

## 27 - Model Test Detail Display

**What to build:** Make model test results more useful during local model validation.

**Blocked by:** 20 - Model Connection Test.

- [x] Model test response includes `tested_at`.
- [x] Frontend displays status per role.
- [x] Frontend displays last tested time.
- [x] Frontend displays adapter error text when unavailable.

## 28 - Meeting List Usability

**What to build:** Improve meeting navigation once the user has more than a few meetings.

**Blocked by:** 18 - Meeting Status Projection; 25 - Meeting Activity Projection.

- [x] Meeting list supports text search.
- [x] Meeting list supports status filter.
- [x] Meeting list sorts by `updated_at` descending.
- [x] Meeting rows show status, activity status, last updated time, and id.

## 29 - Role Output Cards

**What to build:** Add a readable role-output view so users do not have to inspect raw JSON for normal review.

**Blocked by:** 09 - Vue Control And Debug UI; 23 - Expanded E2E Flow.

- [x] Frontend renders parsed role outputs as cards.
- [x] Cards show role and step id.
- [x] Cards separate summary, arguments, risks, and recommendation.
- [x] E2E verifies role-output cards update after a mock round.

## 30 - Background Meeting Progress

**What to build:** Return from meeting start immediately and stream real execution progress to the browser.

**Blocked by:** 08 - WebSocket Event Feed; 25 - Meeting Activity Projection.

- [x] `POST /meetings/{meeting_id}/start` returns `202` with `running`.
- [x] Duplicate starts for an active meeting return `409`.
- [x] WebSocket connections remain open and stream status plus new events.
- [x] Frontend displays running state and incremental timeline updates.
- [x] Cancellation remains terminal when an in-flight model call returns.
- [x] Slow-mock E2E verifies running, incremental steps, and completion.

## 31 - Meeting Deletion

**What to build:** Permanently delete a meeting and its local event data after explicit confirmation.

**Blocked by:** 28 - Meeting List Usability.

- [x] `DELETE /meetings/{meeting_id}` returns `204`.
- [x] Running meetings reject deletion with `409`.
- [x] Meeting metadata, events, and derived transcript become unavailable.
- [x] Frontend requires an irreversible-action confirmation.
- [x] Deleting the selected meeting clears transcript, timeline, and event selection.
- [x] E2E verifies deletion removes the meeting from the list.

## 32 - Subscription CLI Provider

**What to build:** Use already authenticated subscription CLIs as model providers without API tokens.

**Blocked by:** 05 - Model Adapter Interface; 30 - Background Meeting Progress.

- [x] `subscription-cli` executes configured argument arrays without a shell.
- [x] A required `{prompt}` placeholder receives the rendered role prompt.
- [x] Stdout is passed through the existing structured-output parser.
- [x] Missing commands, non-zero exits, empty output, and timeout become adapter errors.
- [x] Example configs include `claude -p`, `codex exec`, and `agy -p`.
- [x] README states that CLI installation and authentication remain user-managed.
- [x] Follow-up: terminate an active CLI subprocess immediately when a meeting is cancelled.
- [x] Follow-up: strip ANSI control codes from subscription CLI stdout before parsing.
- [x] Follow-up: add provider/version-specific output normalizers if plain stdout changes.

## 33 - Backend Model Config Management API

**What to build:** Add backend-only model config management so a future frontend settings page can edit `config/models.yaml` through supported APIs.

**Blocked by:** 03 - Model Config Repository; 20 - Model Connection Test.

- [x] Repository can add a new model config and persist it to YAML.
- [x] Repository can update an existing model config without reordering other entries.
- [x] Repository can delete an existing model config.
- [x] Repository validates adapter-specific required fields before writing YAML.
- [x] API exposes `PUT /models/{model_config_id}`.
- [x] API exposes `DELETE /models/{model_config_id}`.
- [x] Invalid model config writes return `400`.

## 34 - Backend Credential Readiness Projection

**What to build:** Let the backend report whether an API-backed model's configured environment variable exists without exposing the secret value.

**Blocked by:** 33 - Backend Model Config Management API.

- [x] `GET /models` includes credential readiness for `api_key_env` configs.
- [x] Credential readiness object returns env var name and configured boolean only.
- [x] Credential readiness never returns secret values.
- [x] Existing `api_key_env` config metadata remains visible because it is an env var name, not a secret value.
- [x] Local/no-key models return no credential requirement.

## 35 - OpenAI-Compatible Model Discovery

**What to build:** Allow OpenAI-compatible HTTP configs to list available model ids from their endpoint.

**Blocked by:** 05 - Model Adapter Contract With Mock And OpenAI-Compatible HTTP.

- [x] OpenAI-compatible adapter can call `GET /models`.
- [x] API exposes `GET /models/{model_config_id}/available-models`.
- [x] Discovery returns available model ids.
- [x] Unsupported adapters return a clear error instead of pretending discovery works.

## 36 - Provider-Specific CLI Output Normalization

**What to build:** Let subscription CLI configs opt into provider-specific stdout cleanup without changing the core parser.

**Blocked by:** 32 - Subscription CLI Provider.

- [x] `subscription-cli` still strips ANSI control codes for all providers.
- [x] Model configs can declare a CLI provider through `extra_body.cli_provider`.
- [x] Codex provider normalization can extract content wrapped in `<codex-output>...</codex-output>`.
- [x] Unknown providers fall back to safe generic normalization.
- [x] `config/models.yaml.example` marks `codex-subscription` with `cli_provider: codex`.

## 37 - Token Usage Metadata Tracking

**What to build:** Preserve provider token usage metadata in completed events and expose meeting-level totals.

**Blocked by:** 05 - Model Adapter Contract With Mock And OpenAI-Compatible HTTP; 18 - Meeting Status Projection.

- [x] OpenAI-compatible responses map `usage` into normalized token usage.
- [x] Anthropic responses map `usage.input_tokens` / `usage.output_tokens`.
- [x] Gemini responses map `usageMetadata`.
- [x] Runner persists `token_usage` on completed model events when available.
- [x] Meeting read models include cumulative `token_usage` totals.
- [x] Frontend API types include the new `token_usage` fields.

## 38 - Human Chair Message Correction

**What to build:** Allow the chair to correct a previously submitted human message while preserving the event log as the source of truth.

**Blocked by:** 11 - Human Chair Message Slice; 17 - Terminal API Conflicts.

- [x] API exposes `POST /meetings/{meeting_id}/messages/{event_id}/correct`.
- [x] Correction events preserve the original human message and reference it through `corrects_event_id`.
- [x] Corrections reject unknown events and non-human message events.
- [x] Terminal meetings reject message corrections with `409`.
- [x] Transcript projection marks correction entries clearly.
- [x] Frontend API types and controls support correcting human chair messages.

## 39 - Token Streaming Backend Foundation

**What to build:** Let model adapters emit non-persistent token deltas during a running step and expose them through the existing meeting WebSocket.

**Blocked by:** 08 - WebSocket Event Feed; 30 - Background Meeting Progress.

- [x] `ModelRequest` can carry an optional token-delta callback.
- [x] Mock model configs can emit deterministic `mock_stream_chunks` for tests.
- [x] Runner converts token deltas into step-scoped stream events.
- [x] WebSocket snapshot/update payloads include `stream_events`.
- [x] Token delta stream events are not persisted to `events.jsonl`.
- [x] Frontend API types include token-delta stream event payloads.

## 40 - Interrupted Execution Recovery State

**What to build:** Persist the currently running model step so backend startup can detect interrupted executions and hand them back to manual retry.

**Blocked by:** 06 - MeetingRunner Red/Blue/Judge Flow; 25 - Meeting Activity Projection; 30 - Background Meeting Progress.

- [x] Runner writes `execution.json` before calling a model adapter.
- [x] Runner clears `execution.json` after normal completion or handled failure.
- [x] Backend startup scans leftover execution state.
- [x] Leftover execution state appends a failed event for the interrupted step.
- [x] Recovered failures project meeting `activity_status: failed`.
- [x] Recovery does not automatically resend model requests.

## 41 - Background Model Health Checks

**What to build:** Run backend startup health checks for configured models and expose the latest result through `GET /models`.

**Blocked by:** 20 - Model Connection Test; 25 - Meeting Activity Projection.

- [x] Backend startup schedules model health checks without blocking app creation.
- [x] Successful checks mark models `available`.
- [x] Adapter failures mark models `unavailable` with an error string.
- [x] `GET /models` includes health check timestamp and error metadata.
- [x] Health status stays in memory and does not rewrite `config/models.yaml`.

## 42 - Prompt Version Metadata Persistence

**What to build:** Persist lightweight prompt and schema version metadata on model attempt events.

**Blocked by:** 04 - Prompt Rendering And Output Parsing; 06 - MeetingRunner Red/Blue/Judge Flow.

- [x] Completed model events include `prompt_template_name`.
- [x] Completed model events include `prompt_template_hash`.
- [x] Failed model attempt events include `prompt_template_name` and `prompt_template_hash`.
- [x] Model attempt events include `output_schema_hash`.
- [x] Fixed-flow events preserve the correct template name for each stage.
- [x] Frontend API event types include the optional metadata fields.

## 43 - Token Cost Estimate Backend Foundation

**What to build:** Add backend-only token cost estimate support using optional model pricing metadata and existing token usage totals.

**Blocked by:** 37 - Token Usage Metadata Tracking; 33 - Backend Model Config Management API.

- [x] Model configs can declare optional `pricing` metadata with `currency`, `input_per_1m_tokens`, and `output_per_1m_tokens`.
- [x] Model config repository preserves pricing metadata when loading and saving YAML.
- [x] Meeting read models include `estimated_cost` as `{currency, amount}` when all token-usage events can be priced.
- [x] Meeting read models return `estimated_cost: null` when pricing metadata is unavailable.
- [x] `GET /meetings` and `GET /meetings/{meeting_id}` return consistent `estimated_cost` values.
- [x] Frontend API types include the new optional model pricing and meeting estimated cost fields.

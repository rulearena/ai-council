# AI Council

Local single-user AI meeting orchestration app.

The MVP runs a fixed Red/Blue/Judge flow:

1. Blue proposes
2. Red critiques
3. Blue revises
4. Judge decides

The chair can also add human feedback during a meeting, ask a single role to respond,
or run a preset role sequence such as `Red -> Blue -> Judge` for automatic follow-up.

The backend stores meeting events as JSONL under `data/meetings/<meeting_id>/events.jsonl`. Markdown transcripts are derived read models, not the source of truth.

## Project Layout

- `backend/` - FastAPI app, meeting runner, persistence, prompt rendering, output parsing, and model adapters.
- `frontend/` - Vue 3 control/debug UI.
- `config/models.yaml.example` - example OpenAI-compatible model configuration.
- `prompts/` - prompt templates used by the fixed meeting flow.
- `.scratch/mvp/` - local PRD, tickets, and issue files for this MVP.

## Backend Setup

Use Python 3.11 or newer. Backend dependency management is standardized on `uv`,
which creates and uses the project virtual environment for you.

```bash
cd backend
uv sync --extra dev
```

Create a local model config:

```bash
cd ..
cp config/models.yaml.example config/models.yaml
```

Start the API:

```bash
scripts/dev_backend.sh
```

Run backend tests:

```bash
cd backend
uv run pytest
```

## Frontend Setup

```bash
cd frontend
npm install
../scripts/dev_frontend.sh
```

The Vite app defaults to `http://localhost:5009` for API calls. Override it with:

```bash
VITE_API_BASE_URL=http://localhost:5009 npm run dev
```

Build the frontend:

```bash
cd frontend
npm run build
```

## Validation

Run backend tests and frontend typecheck/build:

```bash
scripts/test_all.sh
```

Run Playwright E2E after starting the backend and frontend dev servers:

```bash
RUN_E2E=1 scripts/test_all.sh
```

The E2E flow creates a mock meeting, tests the mock model, starts a full round,
adds chair feedback, runs a single-role response, runs a preset role sequence,
continues the fixed round, and closes the meeting.

## Model Configuration

`config/models.yaml` contains one or more model configs:

```yaml
models:
  - id: qwen27
    adapter: openai-compatible-http
    base_url: http://host:port/v1
    model: model-id
    api_key_env: null
    supports_json_mode: true
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
```

Supported adapters in the MVP:

- `mock` - deterministic local test adapter.
- `openai-compatible-http` - calls `/v1/chat/completions` on an OpenAI-compatible server.
- `subscription-cli` - runs an already authenticated CLI process without an API token.

Subscription CLI models use an argument list with a required `{prompt}` placeholder:

```yaml
- id: claude-subscription
  adapter: subscription-cli
  command: [claude, -p, "{prompt}"]
  timeout_seconds: 300

- id: codex-subscription
  adapter: subscription-cli
  command: [codex, -p, "{prompt}"]
  timeout_seconds: 300

- id: agy-subscription
  adapter: subscription-cli
  command: [agy, -p, "{prompt}"]
  timeout_seconds: 300
```

Install and authenticate each CLI separately before selecting it in AI Council. The app
does not read or manage subscription credentials. Commands run directly without a shell;
non-zero exits, missing executables, empty output, and timeouts are surfaced as model errors.
Cancelling a meeting immediately terminates any subscription CLI process still running for it.

The app does not manage or start local model services. It calls configured OpenAI-compatible
HTTP endpoints or explicitly configured subscription CLI commands.

## Prompt Templates

The runner reads these files from `AI_COUNCIL_PROMPT_DIR`:

- `blue_propose.md`
- `red.md`
- `blue_revise.md`
- `judge.md`

Available template variables:

- `{{ role }}`
- `{{ topic }}`
- `{{ prior_transcript }}`
- `{{ required_json_schema }}`

Model output must contain one JSON object with:

```json
{
  "summary": "string",
  "arguments": [{ "title": "string", "detail": "string" }],
  "risks": [{ "title": "string", "detail": "string" }],
  "recommendation": "string"
}
```

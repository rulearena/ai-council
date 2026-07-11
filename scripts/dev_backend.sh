#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${AI_COUNCIL_BACKEND_PORT:-8000}"
MODEL_CONFIG_PATH="${AI_COUNCIL_MODEL_CONFIG_PATH:-$ROOT_DIR/config/models.yaml}"

if [[ ! -f "$MODEL_CONFIG_PATH" ]]; then
  MODEL_CONFIG_PATH="$ROOT_DIR/config/models.yaml.example"
fi

cd "$ROOT_DIR/backend"
if command -v uv >/dev/null 2>&1; then
  PYTHON_RUNNER=(uv run)
else
  PYTHON_RUNNER=(python -m)
fi

AI_COUNCIL_DATA_DIR="${AI_COUNCIL_DATA_DIR:-$ROOT_DIR/data}" \
AI_COUNCIL_MODEL_CONFIG_PATH="$MODEL_CONFIG_PATH" \
AI_COUNCIL_PROMPT_DIR="${AI_COUNCIL_PROMPT_DIR:-$ROOT_DIR/prompts}" \
"${PYTHON_RUNNER[@]}" uvicorn ai_council.main:app --reload --host 127.0.0.1 --port "$PORT"

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR/backend"
if command -v uv >/dev/null 2>&1; then
  uv run pytest
else
  python -m pytest
fi

cd "$ROOT_DIR/frontend"
npm run build

if [[ "${RUN_E2E:-0}" == "1" ]]; then
  PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$ROOT_DIR/frontend/.cache/ms-playwright}" \
  npm run test:e2e
fi

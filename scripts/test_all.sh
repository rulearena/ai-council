#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR/backend"
python -m pytest

cd "$ROOT_DIR/frontend"
npm run build

if [[ "${RUN_E2E:-0}" == "1" ]]; then
  PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$ROOT_DIR/frontend/.cache/ms-playwright}" \
  npm run test:e2e
fi

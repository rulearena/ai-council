#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${AI_COUNCIL_BACKEND_PORT:-8000}"
FRONTEND_PORT="${AI_COUNCIL_FRONTEND_PORT:-5173}"

cd "$ROOT_DIR/frontend"
VITE_API_BASE_URL="${VITE_API_BASE_URL:-http://127.0.0.1:$BACKEND_PORT}" \
npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT"

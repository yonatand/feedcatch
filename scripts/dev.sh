#!/usr/bin/env bash
# Run backend (uvicorn --reload, auth disabled, data in backend/.data) and the Vite dev server together.
# Usage: scripts/dev.sh      then open http://localhost:5173  (Ctrl+C stops both)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

(cd "$ROOT/backend" && uv sync --all-extras)
[ -d "$ROOT/frontend/node_modules" ] || (cd "$ROOT/frontend" && bun install --frozen-lockfile)

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

(cd "$ROOT/backend" && APP_AUTH_DISABLED="${APP_AUTH_DISABLED:-true}" APP_DATA_DIR="${APP_DATA_DIR:-./.data}" \
  uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload) &
(cd "$ROOT/frontend" && bun run dev) &
wait

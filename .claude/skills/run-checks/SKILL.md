---
name: run-checks
description: Run lint, typecheck, tests and build for backend and frontend of feedcatch; use before claiming any task done or when asked to verify.
---

# run-checks

Run from repo root. Windows dev box uses Git Bash; paths with spaces must be quoted.

## Backend
```bash
cd backend
uv sync --all-extras            # first time / after dependency change
uv run ruff check .
uv run ruff format --check .    # `uv run ruff format .` to fix
uv run mypy app
uv run pytest -q                # add -x to stop at first failure, -k name to filter
```

## Frontend
```bash
cd frontend
npm ci                          # first time / after package change (npm install if lockfile missing)
npm run typecheck
npm run build                   # outputs to backend/app/static; note gzip sizes printed by Vite
```

## Local run (two terminals) or one-shot
```bash
cd backend && APP_AUTH_DISABLED=true APP_DATA_DIR=./.data uv run uvicorn app.main:app --port 8000
cd frontend && npm run dev      # http://localhost:5173, proxies /api -> :8000
```
After `npm run build`, the backend alone serves the SPA at http://localhost:8000.

## Docker
```bash
docker build -t feedcatch .
docker compose config
docker compose up -d && curl -s localhost:8000/healthz
```

## Interpreting results
- ruff `I001` = import sort; run `uv run ruff check --fix .`.
- mypy errors in `alembic/` are ignored (only `app` is checked).
- Vite warns above 500 KB chunk; our budget is far lower (120 KB gzip entry). If exceeded, check for accidental non-lazy imports of pages.

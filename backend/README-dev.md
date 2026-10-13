# Backend dev notes

```bash
cd backend
uv sync --all-extras
uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest -q
```

- Non-package uv project (`[tool.uv] package = false`); `pytest` adds `.` to `sys.path`.
- Migrations are hand-written in `alembic/versions/` and applied with `app.db.run_migrations(url)`
  (the app calls it at startup; tests call it on a tmp SQLite file). Manual CLI: `uv run alembic upgrade head`.
- ORM JSON columns are exposed without the `_json` suffix (e.g. `Series.aliases` -> column `aliases_json`).
- Datetimes: `UTCDateTime` stores naive UTC, returns aware UTC; schemas serialize with a trailing `Z`.
- `app/services/paths.py` is pure string logic; it must never touch the filesystem.

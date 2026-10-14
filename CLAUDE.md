# feedcatch

Self-hosted RSS -> qBittorrent automation for ongoing series (anime or TV). Replaces Sonarr/autobrr/FlexGet for one job:
poll AnimeTosho-style RSS, match releases against user rules, send magnet/torrent to an existing
qBittorrent-nox with an explicit per-torrent `savepath`. The app NEVER touches media files.

Full requirements: `docs/requirements.md` (source of truth for scope).

## Layout
- `backend/`  Python 3.12+ / FastAPI / SQLAlchemy 2 / SQLite / APScheduler / httpx / feedparser. Managed with `uv`.
- `frontend/` React 18 + Vite + TypeScript SPA (Bun as package manager/runner), built into `backend/app/static/` and served by FastAPI.
- `Dockerfile` (multi-stage: node build -> python runtime), `docker-compose.yml`, `.env.example`.

## Rules and skills (read before working)
- `.claude/rules/architecture.md`   data model, pipeline, decisions already made. Do not re-decide.
- `.claude/rules/api-contract.md`   exact HTTP API. Frontend and backend both follow it.
- `.claude/rules/safety-invariants.md`  hard constraints (no media access, no secrets in logs, path safety, SSRF).
- `.claude/rules/backend.md` / `.claude/rules/frontend.md`  conventions per side; `.claude/rules/mobile.md`  phone layout rules.
- `.claude/rules/metadata.md`  pluggable metadata providers (AniList, TMDB), seeding/onboarding; `anilist.md` keeps the AniList API facts.
- `.claude/rules/episodes.md`  episode lists, release search (historic episodes), calendar, wanted.
- `.claude/rules/verification.md`  what must pass before claiming done.
- `.claude/skills/run-checks`  commands to lint/typecheck/test/build.
- `.claude/skills/qbittorrent-api`  Web API facts we rely on (incl. live-observed v5.2.4 differences).
- `.claude/skills/animetosho-feed`  observed live feed structure + real fixture.
- `.claude/skills/live-smoke-test`  end-to-end check with a throwaway real qBittorrent container.
- `.claude/skills/release-title-parsing`  parser patterns and the fixture table.
- `.claude/skills/orchestration`  how the orchestrator (Fable) drives Opus sub-agents; lessons learned.

## Commands (from repo root)
```
cd backend && uv sync --all-extras && uv run pytest -q && uv run ruff check . && uv run mypy app
cd frontend && bun install --frozen-lockfile && bun run typecheck && bun run build
docker compose up --build
```

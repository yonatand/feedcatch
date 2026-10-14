---
name: orchestration
description: How the orchestrator (Fable) drives Opus sub-agents on this repo: phase plan, agent prompts, ownership boundaries, and lessons learned. Read when planning multi-agent work here.
---

# Orchestration playbook

Operator model: Fable thinks, decides, writes contracts into `.claude/`; Opus agents implement in parallel against those contracts; Fable verifies with
`.claude/skills/run-checks` and feeds failures back to agents. Every non-obvious learning is appended to the "Lessons" section below.

## Ownership boundaries (never let two concurrent agents touch the same directory)
- `backend/app/{models,db,schemas,config}.py`, `alembic/`, `services/{parser,matcher,paths,crypto,auth,settings_store,activity,seed}.py`, `tests/test_{parser,paths,matcher}.py`: **foundation agent**
- `backend/app/services/{ssrf,feeds,qbit,dispatcher,poller,scheduler}.py`, `backend/app/api/*`, `main.py`, remaining tests: **integration agent** (runs after foundation)
- `frontend/**`: **frontend agent** (parallel with foundation; depends only on `api-contract.md`)
- `Dockerfile`, `docker-compose.yml`, `.env.example`, `README.md`, `scripts/`: **delivery agent** (after integration)
- `.claude/**`, `CLAUDE.md`: orchestrator only. Agents may propose edits in their final report.

## Phases
1. Contracts (orchestrator): architecture, api-contract, safety, conventions, skills.
2. Parallel: foundation (backend core) + frontend.
3. Integration (backend services + API + main) once foundation reports green tests.
4. Delivery (Docker/README/checklist) in parallel with a fix-up pass if needed.
5. Orchestrator runs full checks, builds Docker image, smoke-tests `/healthz` and the SPA, reviews for invariant violations, writes lessons.

## Agent prompt template
- State the agent's ownership, the files to read first (`CLAUDE.md`, relevant rules/skills), the exact deliverables, and "run `run-checks` for your part before reporting".
- Demand a final report: files created, commands run with pass/fail, deviations from the contract (with reason), open questions.
- Forbid: changing the API contract, adding runtime dependencies beyond the allowed list, touching other agents' directories, declaring live integration tested.

## Lessons (append-only, dated)
- 2026-10-13: Bash heredocs of long Markdown with mixed quotes failed on this Windows Git Bash; use the Write tool for long files.
- 2026-10-13: Local toolchain: Python 3.13 + uv 0.10, Node 22, Bun 1.4, Docker 29 with Compose v2.40. No pnpm. Frontend moved to Bun on 2026-10-13 (bun.lock; Docker ui stage oven/bun:1-alpine; CI oven-sh/setup-bun@v2).
- 2026-10-13: Foundation agent (Opus) delivered models/parser/matcher/paths with 141 tests in one pass. ORM attrs drop the `_json` suffix (`Series.aliases` -> column `aliases_json`). `LoginRateLimiter` instance belongs on `app.state`. Pydantic validation errors are 422; routers must remap regex/path errors to 400 per contract.
- 2026-10-13: Resolved versions: SQLAlchemy 2.1.x, FastAPI/Starlette 1.x, structlog 26. uv project uses `[tool.uv] package=false` and pytest `pythonpath=["."]`.
- 2026-10-13: Frontend agent (Opus) built the SPA at ~71 KB gzip initial (vendor 64.6 KB + entry 6 KB), all pages lazy. Lesson: the wizard's "test filters before saving" step needed `/api/rules/simulate` to accept an unsaved `series` inline; writing the contract with a saved-series assumption forced a mid-flight amendment. Design preview/simulate endpoints to accept unsaved input from the start.
- 2026-10-13: Vite's `emptyOutDir` deletes `backend/app/static/.gitkeep`; re-touch it after builds (the .gitignore keeps only the .gitkeep tracked).
- 2026-10-13: `ghcr.io/astral-sh/uv` pulls fail on this machine (docker credential helper "denied"); use `astral/uv:0.10` from Docker Hub in the Dockerfile.
- 2026-10-13: compose `env_file` must be `{path: .env, required: false}` so `docker compose config` works before the user creates `.env`. Any non-empty `QBIT_*`/`ALLOW_PRIVATE_FEED_HOSTS` env locks that field in the UI (reported as source=env); `.env.example` leaves most empty on purpose.
- 2026-10-13: Image: python:3.12-slim + uv `--frozen --no-dev --no-install-project`, CMD runs `.venv/bin/uvicorn` directly; ~485 MB on disk. Runs as uid 1000 with `/data` volume; entrypoint checks writability.
- 2026-10-13: Mocked tests passed but the LIVE qBittorrent 5.2.4 differed from the documented API in three ways (204 login, 401 on bad creds, JSON add response). Lesson: always run one real-service smoke test (throwaway `qbittorrentofficial/qbittorrent-nox` container on a shared docker network, temp password from its logs) before declaring an integration done; put every observed difference into the qbittorrent-api skill.
- 2026-10-13: Git Bash `/tmp` is not Python's `/tmp` on Windows; pass the scratchpad dir explicitly when a shell pipeline hands files to `python -I`.
- 2026-10-13: Claude-in-Chrome extension was not connected; a Playwright-driven Opus QA agent (tooling kept in the scratchpad dir, never in the repo) is a good substitute. It found two bugs that typecheck/build cannot catch: a nested `<form>` whose submit reloaded the page, and a CSS specificity clash (`.menu-toggle` overridden by a later `.btn`). Lesson: always run a click-through QA pass at desktop and 390px widths before calling the UI done.
- 2026-10-13: Measured in-container: every route DOMContentLoaded ~60 ms, ~80-92 KB compressed JS+CSS per route, zero console errors, no horizontal overflow at 390px.
- 2026-10-13: Renaming the project (pyproject `name`) requires `cd backend && uv lock`, otherwise the Docker `uv sync --frozen` step fails. The compose service is now `feedcatch` (was `scheduler`). Repo: https://github.com/yonatand/feedcatch
- 2026-10-13: AniList feature shipped by two parallel Opus agents (backend + frontend) against `.claude/rules/anilist.md`; zero integration mismatches because the contract listed exact field names. Live rate limit is 30 req/min (not 90): cache queries. Alias filter 'contains an ASCII letter' still lets Vietnamese/Latin-script synonyms through; acceptable, user can prune.
- 2026-10-13: GHCR publishing is done by `.github/workflows/docker.yml` with GITHUB_TOKEN (never a local `docker login`); first run creates a private package the user must make public.
- 2026-10-14: Mid-flight scope change (generic metadata providers, no demo seed) was absorbed by messaging the running backend agent with a precise amendment and writing `metadata.md`; the frontend agent then read the backend's in-progress schemas directly and aligned types, which avoided a second round. Lesson: when two agents build against a contract concurrently, tell the later one to read the earlier one's actual code before finishing.
- 2026-10-14: AniList `airingSchedule(perPage:50)` silently returns 25 nodes; always paginate on `hasNextPage`. AniList is anime-only; TMDB needs a key (untested live here). Jikan times out from this network.
- 2026-10-14: SQLite migrations that drop columns must use native DROP COLUMN; Alembic batch rebuild with `PRAGMA foreign_keys=ON` cascade-deletes children.
- 2026-10-14: First real user report ('episode list doesn't work') was an upgrade-path gap: migration preserved the series link but not seasons, and the UI had no visible way out. Lessons: (1) always replay an upgrade from the previously published image with real data (build it from the git tag with a worktree when the registry pull fails locally); (2) every empty state needs a call to action; (3) external fallbacks (Jikan) must fail fast and back off, or they tax every request.
- 2026-10-14: Second user report ("why is it not finding the episode") was a parser gap (parenthetical alternate titles glued into the series title). Lessons: (1) for any "no match" outcome, the UI must show what was fetched and the first failing check; silence makes every matching bug look like a search bug; (2) reproduce with the exact title through `parse_title` + `matcher.evaluate` before touching code; it took one command.

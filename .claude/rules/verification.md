# Verification (nothing is "done" until these pass locally)

Backend (`cd backend`): `uv sync --all-extras`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy app`, `uv run pytest -q`.
Frontend (`cd frontend`): `bun install --frozen-lockfile`, `bun run typecheck`, `bun run build` (check reported gzip sizes).
Docker: `docker build -t feedcatch .` and `docker compose config` must succeed. `docker run --rm -p 8000:8000 -e APP_AUTH_DISABLED=true feedcatch` then `curl localhost:8000/healthz`.

Required test coverage (pytest):
- parser: every row of the fixture table in `.claude/skills/release-title-parsing/SKILL.md`.
- paths: sanitize edge cases (`..`, `/`, `\`, control chars, `Re:Zero`, trailing dots, unicode); template token validation; overrides; `Black Clover` + season 2 -> `/home/qbittorrent-nox/media/Black Clover/Season 02`.
- matcher: accept `[DKB] Black Clover Season 2 - 01 [1080p]`; reject other group; reject other series; reject season mismatch; `[DKB] Black Clover - 171` rejected without absolute range and accepted (episode 171-abs_min+1) with range; include/exclude keywords; resolution; size bounds; regex; require_group_prefix.
- feeds: parse AnimeTosho-like RSS fixture (magnet in description + .torrent enclosure + nzb link), Atom fixture, invalid XML, DOCTYPE rejection, NZB-only entry yields no torrent url, conditional GET 304, size cap, timeout -> FeedFetchError.
- ssrf: private IPs rejected, redirect to private rejected, allow flag honored, non-http scheme rejected.
- qbit client: login 200 "Ok." then add; login "Fails." -> QbitError; 403 on add -> re-login once; timeout -> transient; add "Fails." -> permanent; info returns save_path; Referer/Origin headers set.
- dispatcher/poller integration (respx): first poll with backfill skip marks historical and sends nothing; second poll with a new matching entry creates Download and POSTs `torrents/add` with `savepath=/home/qbittorrent-nox/media/Black Clover/Season 02` and `autoTMM=false`; duplicate episode second time -> 'duplicate', no POST; category override honored; path_mismatch detected when qbit reports different save_path; transient failure -> pending + next_retry_at; uncertain add then info shows present -> 'exists' with no second add.
- api: auth (setup/login/logout/401), feeds CRUD + SSRF 400, series/season CRUD + 409, rules CRUD + invalid regex 400, simulate, entries list/detail, grab preview+confirm, qbit config never returns password, settings PUT, healthz.

Report honestly: list what ran and passed, what was not run, and that live AnimeTosho/qBittorrent were not exercised unless they actually were.

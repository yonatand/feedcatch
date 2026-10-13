# Architecture (decided; do not re-litigate)

## Stack
- Backend: Python 3.12+ (dev on 3.13), FastAPI, **sync** SQLAlchemy 2.x ORM, SQLite (WAL mode), Alembic migrations,
  APScheduler 3.x `BackgroundScheduler`, **sync** `httpx.Client`, `feedparser`, pydantic v2 + pydantic-settings, `bcrypt`,
  `cryptography` (Fernet), `itsdangerous` (signed session cookie), `structlog` JSON logs. Endpoints are plain `def`
  (threadpool), not `async def`.
- Frontend: React 18 + Vite 5 + TypeScript, `react-router-dom` (lazy routes), `@tanstack/react-query`. No UI framework;
  hand-written CSS with variables. Bundle budget: initial JS < 120 KB gzip.
- One container, one process (`uvicorn --workers 1`). FastAPI serves `/api/*`, `/healthz`, and the built SPA from `app/static`.
- Data dir `/data` (volume): `app.db`, `secret.key` (auto-generated if `APP_SECRET_KEY` env unset).

## Repo layout
```
backend/
  pyproject.toml            # uv project; deps + dev extras (pytest, respx, ruff, mypy, freezegun)
  alembic.ini, alembic/     # migrations; run programmatically at startup (upgrade head)
  app/
    main.py                 # create_app(); lifespan: migrate -> seed demo -> start scheduler; shutdown -> scheduler.shutdown(wait=True)
    config.py               # Settings from env (pydantic-settings): APP_DATA_DIR, APP_SECRET_KEY, APP_PASSWORD, APP_AUTH_DISABLED,
                            #   APP_HOST, APP_PORT, APP_LOG_LEVEL, QBIT_URL, QBIT_USERNAME, QBIT_PASSWORD, FEED_URL, ALLOW_PRIVATE_FEED_HOSTS
    db.py                   # engine (sqlite, WAL, foreign_keys=ON, check_same_thread=False), SessionLocal, get_db dependency
    models.py               # SQLAlchemy models (below)
    schemas.py              # pydantic request/response models mirroring .claude/rules/api-contract.md
    logging_setup.py        # structlog setup; redaction processor for keys matching pass|secret|token|cookie|authorization
    api/                    # routers: auth, dashboard, feeds, series, seasons, rules, entries, downloads, qbit, settings, activity, health
    services/
      crypto.py             # Fernet encrypt/decrypt of qbit password with key from secret.key / APP_SECRET_KEY
      auth.py               # password hash/verify, session cookie, dependency `require_auth`
      settings_store.py     # typed get/set over `settings` table (JSON values); env override precedence
      ssrf.py               # validate_feed_url(); manual redirect following (max 5) re-validating each hop
      feeds.py              # fetch(feed) -> FetchResult; conditional GET; size cap 10 MiB; feedparser; extract links (magnet/torrent/nzb), size, infohash
      parser.py             # parse_title(str) -> ParsedRelease (see skill release-title-parsing)
      matcher.py            # evaluate(entry, parsed, rule, series, seasons, settings) -> Evaluation(matched, conditions[], season_id, episode_number)
      paths.py              # sanitize_component(), render_season_folder(), build_save_path(settings, series, season) -> str
      qbit.py               # QbitClient: login, version, api_version, preferences, add(...), info(hashes), categories
      dispatcher.py         # create Download rows for accepted evaluations; submit(download) idempotently; verify save_path after add
      poller.py             # poll_feed(feed_id): per-feed lock, fetch, upsert entries, historical marking, evaluate, dispatch
      scheduler.py          # APScheduler jobs: per-feed interval (reschedule on change), retry queue (60s), qbit status poll (120s, optional), log retention (daily)
      activity.py           # log_event(db, level, event_type, message, details=None, entry_id=None, download_id=None)
      seed.py               # demo data (idempotent): feed, series Black Clover (monitored=False) + season 2 + rule DKB 1080p
    static/                 # built frontend (gitignored except .gitkeep)
  tests/                    # pytest; fixtures: tmp sqlite db, TestClient, respx mocks for feed + qbit; fixtures/ with sample RSS XML
frontend/
  src/{api/,pages/,components/,lib/}, index.html, vite.config.ts (build.outDir = ../backend/app/static, emptyOutDir: true)
```

## Data model (SQLAlchemy; every table has integer PK `id` and `created_at` UTC datetime)
- `feed_sources`: name, url (unique), enabled, poll_interval_minutes (default 15, min 5, max 1440), backfill_mode ('skip'|'process', default 'skip'),
  etag, last_modified, last_checked_at, last_success_at, last_status ('never'|'ok'|'error'), last_error, consecutive_failures, initial_poll_done (bool)
- `feed_entries`: feed_id FK, guid, title, link, published_at, first_seen_at, magnet_url, torrent_url, nzb_url, size_bytes, infohash (lower hex 40 chars),
  is_historical, processed_at, outcome ('unprocessed'|'accepted'|'rejected'|'no_match'|'historical'|'duplicate'), outcome_summary, parsed_json.
  UNIQUE(feed_id, guid). Indexes: first_seen_at, infohash, outcome.
- `series`: name (canonical path component; unique, case-insensitive), aliases_json (list[str]), monitored (bool), season_folder_format
  (default 'Season {season:02d}'), path_override (nullable; absolute posix path replacing base/series), category_override (nullable)
- `seasons`: series_id FK (cascade delete), season_number (int >= 0), monitored, path_override (nullable; absolute posix path replacing the whole path),
  episode_min, episode_max (nullable; season-relative numbering), absolute_min, absolute_max (nullable; absolute-numbered range that maps to this season;
  season_episode = absolute - absolute_min + 1). UNIQUE(series_id, season_number).
- `rules`: series_id FK (cascade), season_id FK nullable (cascade), name, enabled, priority (int, higher wins, default 0), release_group (nullable),
  require_group_prefix (bool), include_keywords_json, exclude_keywords_json, resolutions_json, sources_json, codecs_json, language_keywords_json (all list[str]),
  min_size_mb, max_size_mb (nullable), regex (nullable; validated with `re.compile` at save; applied with `re.search`, IGNORECASE)
- `evaluations`: entry_id FK (cascade), rule_id FK (cascade), matched (bool), season_id nullable, episode_number nullable,
  conditions_json (list[{check, passed, detail}]), evaluated_at. UNIQUE(entry_id, rule_id). Re-evaluating replaces the row.
- `downloads`: entry_id FK, series_id FK, season_id FK, episode_number, rule_id FK nullable (SET NULL), infohash nullable, source_url, source_url_kind ('magnet'|'torrent'),
  save_path, category nullable, status ('pending'|'submitted'|'failed'|'exists'|'path_mismatch'), attempts, next_retry_at, last_error,
  qbit_hash, qbit_state, qbit_progress (float), qbit_save_path, forced (bool), updated_at.
  Partial UNIQUE index `ux_downloads_episode_active`: (season_id, episode_number) WHERE status != 'failed' AND forced = 0.
  Partial UNIQUE index `ux_downloads_infohash_active`: (infohash) WHERE infohash IS NOT NULL AND status != 'failed'.
- `activity_log`: ts, level ('info'|'warning'|'error'), event_type (str), message, details_json, entry_id nullable, download_id nullable. Index ts.
- `settings`: key (PK str), value_json. Keys: media_base_path (default '/home/qbittorrent-nox/media'), default_season_folder_format ('Season {season:02d}'),
  duplicate_policy ('one_per_episode'|'allow_upgrades'; default one_per_episode; in the MVP allow_upgrades only means a non-forced manual grab may replace a 'failed' row),
  allow_private_feed_hosts (bool, false), feed_fetch_timeout_seconds (20), log_retention_days (30), auth_password_hash, qbit_url, qbit_username,
  qbit_password_enc, qbit_category, qbit_timeout_seconds (15), qbit_start_immediately (true), qbit_poll_status (true), qbit_last_test_json.
  Env vars (QBIT_URL/QBIT_USERNAME/QBIT_PASSWORD, APP_PASSWORD, ALLOW_PRIVATE_FEED_HOSTS) take precedence over DB values when set; the API reports
  `source: "env"` for those fields and PUT ignores them with a warning in the response.

## Pipeline (poller.poll_feed)
1. Acquire per-feed `threading.Lock` (non-blocking; skip with a log line if held). Fetch with conditional GET. On 304: update last_checked_at, status ok, done.
2. Parse entries. Upsert by (feed_id, guid). New rows get `first_seen_at=now`, `parsed_json`. If `not feed.initial_poll_done and backfill_mode=='skip'`:
   new rows get `is_historical=True, outcome='historical'`; still store evaluations (for preview) but never dispatch. Then set initial_poll_done=True.
3. For each new non-historical entry: for every enabled rule whose series is monitored (and whose season, if bound, is monitored): `evaluate(...)` -> store evaluation.
   Collect matched evaluations; group by (season_id, episode_number); choose highest rule.priority then lowest rule.id.
4. For each chosen: if entry has no magnet/torrent url -> outcome 'rejected', summary "no torrent/magnet link (NZB-only)". Else check duplicate
   (existing non-failed download for (season_id, episode_number) or infohash) -> outcome 'duplicate'. Else build save_path, create Download(status pending), outcome 'accepted'.
5. dispatcher.submit for each pending download created in this poll (inline, bounded by qbit timeout). Transient failure -> stays pending, attempts+1,
   next_retry_at = now + min(2**attempts, 60) minutes; after 8 attempts -> 'failed'. Permanent failure ("Fails." or HTTP 4xx other than 403) -> 'failed'.
6. Entries with zero matched rules -> outcome 'no_match', summary "no rule matched (N evaluated)". Entries with zero enabled rules at all -> 'no_match', "no active rules".
7. Update feed last_* fields, consecutive_failures; log one activity event per poll summarizing counts, plus one per accepted/duplicate/rejected-with-match entry.

## dispatcher.submit(download) idempotency
- If infohash known: `qbit.info(hashes=infohash)`; if present -> verify path -> status 'exists' (and warn if save_path differs), do not re-add.
- `qbit.add(url, savepath, category, autoTMM=False, paused=not start_immediately)`. "Ok." -> sleep 1s, `info(hashes)` -> read save_path;
  compare normalized (rstrip '/') -> 'submitted' or 'path_mismatch' (last_error explains; it still counts as sent). "Fails." -> 'failed'.
- Timeout/connection error AFTER add was sent: do not mark failed; stay pending with next_retry; next attempt begins with the info(hashes) check.
- For `.torrent` URLs without infohash: after "Ok." poll `info()` for up to 10s for a torrent whose `added_on` >= submit time and whose name shares the entry title stem;
  if unresolvable, mark 'submitted' with qbit_hash null and a warning in last_error.
- Transient = httpx timeout/connect error, HTTP 5xx, 403 once (re-login then retry once in same attempt).

## Auth
- Modes: `APP_AUTH_DISABLED=true` -> no auth (documented: trusted network / reverse proxy only). Else password mode:
  `APP_PASSWORD` env, or first-run setup via UI storing bcrypt hash in settings. Session: itsdangerous signed cookie `feedcatch_session`, 7 days, HttpOnly, SameSite=Lax,
  Secure when request scheme is https.
- Every `/api/*` except `/api/auth/*` requires auth (401 JSON `{detail:"unauthenticated"}`). `/healthz` is open.

## Frontend routes
`/` dashboard, `/feeds`, `/series`, `/series/new` (wizard), `/series/:id` (seasons + rules + path preview), `/rules`, `/releases`,
`/releases/:id` (match inspector), `/downloads`, `/qbittorrent`, `/activity`, `/settings`, `/login`, `/setup`.

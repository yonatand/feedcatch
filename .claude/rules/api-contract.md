# HTTP API contract (both sides implement exactly this)

Base: `/api`. JSON only. Timestamps are ISO-8601 UTC strings with `Z` (or null). Errors: `{"detail": string}` with 4xx/5xx; validation 422 (FastAPI default).
Auth: cookie session. Unauthenticated -> 401 `{"detail":"unauthenticated"}`. `GET /healthz` is open.
Lists are `{ "items": T[], "total": number }` with `?limit=` (default 50, max 200) and `?offset=`.

## Shared types
```ts
type Condition = { check: string; passed: boolean; detail: string };
type ParsedRelease = {
  group: string | null; title: string; season: number | null; episode: number | null; episode_end: number | null;
  absolute: boolean;            // true when the number was given without an explicit season (e.g. "- 171")
  version: number | null; resolution: string | null; source: string | null; codec: string | null;
  audio: string | null; subs: string[]; is_batch: boolean; raw: string;
};
type FeedSource = {
  id: number; name: string; url: string; enabled: boolean; poll_interval_minutes: number; backfill_mode: 'skip' | 'process';
  last_checked_at: string | null; last_success_at: string | null; last_status: 'never' | 'ok' | 'error'; last_error: string | null;
  consecutive_failures: number; initial_poll_done: boolean; entry_count: number; created_at: string;
};
type FeedEntryPreview = {   // live, unpersisted
  guid: string; title: string; link: string | null; published_at: string | null; magnet_url: string | null; torrent_url: string | null;
  has_nzb: boolean; size_bytes: number | null; infohash: string | null; parsed: ParsedRelease;
};
type FeedEntry = FeedEntryPreview & {
  id: number; feed_id: number; feed_name: string; first_seen_at: string; is_historical: boolean; processed_at: string | null;
  outcome: 'unprocessed' | 'accepted' | 'rejected' | 'no_match' | 'historical' | 'duplicate'; outcome_summary: string | null;
};
type Evaluation = {
  rule_id: number; rule_name: string; series_id: number; series_name: string; season_id: number | null; season_number: number | null;
  episode_number: number | null; matched: boolean; conditions: Condition[]; evaluated_at: string;
};
type FeedEntryDetail = FeedEntry & { evaluations: Evaluation[]; downloads: Download[] };
type Season = {
  id: number; series_id: number; season_number: number; monitored: boolean; path_override: string | null;
  episode_min: number | null; episode_max: number | null; absolute_min: number | null; absolute_max: number | null;
  computed_save_path: string; created_at: string;
};
type SeasonIn = Omit<Season, 'id' | 'series_id' | 'computed_save_path' | 'created_at'>;
type Series = {
  id: number; name: string; aliases: string[]; monitored: boolean; season_folder_format: string; path_override: string | null;
  category_override: string | null; seasons: Season[]; rule_count: number; created_at: string;
};
type SeriesIn = { name: string; aliases: string[]; monitored: boolean; season_folder_format?: string; path_override?: string | null;
  category_override?: string | null; seasons?: SeasonIn[] };   // seasons only honored on POST
type Rule = {
  id: number; series_id: number; season_id: number | null; name: string; enabled: boolean; priority: number;
  release_group: string | null; require_group_prefix: boolean; include_keywords: string[]; exclude_keywords: string[];
  resolutions: string[]; sources: string[]; codecs: string[]; language_keywords: string[];
  min_size_mb: number | null; max_size_mb: number | null; regex: string | null;
  series_name: string; season_number: number | null; created_at: string;
};
type RuleIn = Omit<Rule, 'id' | 'series_name' | 'season_number' | 'created_at'>;
type SimulationResult = { title: string; parsed: ParsedRelease; matched: boolean; season_number: number | null; episode_number: number | null;
  save_path: string | null; conditions: Condition[] };
type Download = {
  id: number; entry_id: number; entry_title: string; series_id: number; series_name: string; season_id: number; season_number: number;
  episode_number: number; rule_id: number | null; rule_name: string | null; infohash: string | null; source_url: string; source_url_kind: 'magnet' | 'torrent';
  save_path: string; category: string | null; status: 'pending' | 'submitted' | 'failed' | 'exists' | 'path_mismatch';
  attempts: number; next_retry_at: string | null; last_error: string | null; qbit_hash: string | null; qbit_state: string | null;
  qbit_progress: number | null; qbit_save_path: string | null; forced: boolean; created_at: string; updated_at: string;
};
type GrabPreview = { entry_id: number; season_id: number; episode_number: number; save_path: string; category: string | null;
  source_url: string; source_url_kind: 'magnet' | 'torrent'; infohash: string | null; duplicate_of: Download | null; warnings: string[] };
type ActivityEvent = { id: number; ts: string; level: 'info' | 'warning' | 'error'; event_type: string; message: string;
  details: Record<string, unknown> | null; entry_id: number | null; download_id: number | null };
type QbitTestResult = { ok: boolean; at: string; version: string | null; api_version: string | null; auto_tmm_enabled: boolean | null;
  default_save_path: string | null; category_exists: boolean | null; warnings: string[]; error: string | null };
type QbitConfig = { url: string; username: string; password_set: boolean; category: string | null; timeout_seconds: number;
  start_immediately: boolean; poll_status: boolean; sources: Record<string, 'env' | 'db'>; warnings: string[]; last_test: QbitTestResult | null };
type QbitConfigIn = { url: string; username: string; password?: string; category: string | null; timeout_seconds: number;
  start_immediately: boolean; poll_status: boolean };   // password omitted/undefined = unchanged; "" = clear
type AppSettings = { media_base_path: string; default_season_folder_format: string; duplicate_policy: 'one_per_episode' | 'allow_upgrades';
  allow_private_feed_hosts: boolean; feed_fetch_timeout_seconds: number; log_retention_days: number; sources: Record<string, 'env' | 'db'>; warnings: string[] };
type AuthStatus = { auth_mode: 'password' | 'disabled'; setup_required: boolean; authenticated: boolean };
type Dashboard = {
  feeds: FeedSource[];
  counts: { series_total: number; series_monitored: number; rules_active: number; entries_24h: number;
            downloads_submitted_24h: number; downloads_pending: number; downloads_failed: number };
  recent_downloads: Download[];     // last 10 any status
  failed_downloads: Download[];     // last 10 failed/path_mismatch
  recent_entries: FeedEntry[];      // last 10
  qbit: { configured: boolean; last_test: QbitTestResult | null };
  scheduler: { running: boolean; next_feed_poll_at: string | null };
};
```

## Endpoints
Auth
- `GET  /api/auth/status` -> AuthStatus (open)
- `POST /api/auth/setup` `{password}` -> 204. Only when setup_required; else 409. Password min 8 chars.
- `POST /api/auth/login` `{password}` -> 204 | 401. Rate limit: 5 failures/minute/IP -> 429.
- `POST /api/auth/logout` -> 204

Dashboard
- `GET /api/dashboard` -> Dashboard

Feeds
- `GET /api/feeds` -> `{items: FeedSource[], total}`
- `POST /api/feeds` `{name, url, enabled, poll_interval_minutes, backfill_mode}` -> FeedSource (201). URL validated (SSRF) -> 400 with reason.
- `GET/PUT/DELETE /api/feeds/{id}` (PUT same body as POST, all fields required) -> FeedSource | 204
- `POST /api/feeds/test` `{url}` -> `{ok, feed_title, entry_count, sample: FeedEntryPreview[] (<=5), error}` (live fetch, not persisted, 200 even if ok=false)
- `GET  /api/feeds/{id}/preview?limit=50` -> `{items: FeedEntryPreview[], total}` (live fetch, not persisted; 502 on fetch failure)
- `POST /api/feeds/{id}/poll` -> `{fetched, new_entries, historical, accepted, duplicate, rejected, no_match, submitted, errors: string[]}` (synchronous; 409 if poll in progress)

Series / seasons
- `GET /api/series` -> `{items: Series[], total}`
- `POST /api/series` SeriesIn -> Series (201). Name sanitized for path; conflict 409.
- `GET/PUT/DELETE /api/series/{id}` -> Series | 204 (PUT ignores `seasons`)
- `POST /api/series/{id}/seasons` SeasonIn -> Season (201); 409 on duplicate season_number
- `PUT/DELETE /api/seasons/{id}` -> Season | 204
- `GET /api/series/{id}/paths` -> `{items: {season_id, season_number, save_path}[]}`
- `POST /api/series/preview-path` `{name, season_folder_format, path_override, season_number, season_path_override}` -> `{save_path}` | 400 with reason

Rules
- `GET /api/rules?series_id=` -> `{items: Rule[], total}`
- `POST /api/rules` RuleIn -> Rule (201); regex invalid -> 400 `{detail: "invalid regex: ..."}`
- `GET/PUT/DELETE /api/rules/{id}`
- `POST /api/rules/simulate` `{rule: RuleIn, titles: string[], series?: SeriesIn}` -> `{items: SimulationResult[]}`. The rule need not be saved.
  If `series` is given (unsaved series incl. its `seasons`), it is used in-memory and `rule.series_id` is ignored (send 0); `rule.season_id` then refers to
  the index in `series.seasons` (0-based) or null. Otherwise `rule.series_id` must be an existing series.
- `POST /api/rules/{id}/test-recent?limit=100` -> `{items: (SimulationResult & {entry_id: number})[]}` (against stored entries, newest first, no side effects)
- `POST /api/rules/validate-regex` `{pattern}` -> `{valid: boolean, error: string | null}`

Entries (Recent Releases + Match Inspector)
- `GET /api/entries?feed_id=&outcome=&q=&limit=&offset=` -> `{items: FeedEntry[], total}` newest first
- `GET /api/entries/{id}` -> FeedEntryDetail
- `POST /api/entries/{id}/evaluate` -> FeedEntryDetail (re-runs all rules, stores evaluations, no dispatch, does not change outcome of processed entries)
- `POST /api/entries/{id}/grab` `{season_id, episode_number, force: boolean, confirm: boolean}` -> if `confirm=false`: GrabPreview; if `confirm=true`: Download (201).
  409 if duplicate and not force. 400 if entry has no magnet/torrent.

Downloads
- `GET /api/downloads?status=&series_id=&limit=&offset=` -> `{items: Download[], total}` newest first
- `GET /api/downloads/{id}` -> Download
- `POST /api/downloads/{id}/retry` -> Download (sets pending, attempts unchanged, submits immediately)
- `POST /api/downloads/retry-failed` -> `{retried: number}`
- `POST /api/downloads/refresh-status` -> `{updated: number}` (polls qBittorrent for all with qbit_hash)

qBittorrent
- `GET /api/qbit` -> QbitConfig
- `PUT /api/qbit` QbitConfigIn -> QbitConfig
- `POST /api/qbit/test` `{}` or QbitConfigIn (if body given, test those values without saving; password omitted = use stored) -> QbitTestResult (200 even if ok=false)

Settings
- `GET /api/settings` -> AppSettings
- `PUT /api/settings` (AppSettings minus `sources`/`warnings`) -> AppSettings; media_base_path must be absolute posix

Activity
- `GET /api/activity?level=&event_type=&limit=&offset=` -> `{items: ActivityEvent[], total}` newest first

Health
- `GET /healthz` -> `{status: 'ok', db: 'ok', scheduler: 'running' | 'stopped', version: string}` (503 if db fails)

## Clarifications (decided 2026-10-13)
- `sources` keys are the field names of the response (`url`, `username`, `password`, `category`, ... / `media_base_path`, ...). Value `'env'` means read-only.
- `POST /api/qbit/test` with `password: ""` tests with an empty password; omitted password = stored one.
- `POST /api/entries/{id}/evaluate` runs every **enabled** rule regardless of series monitored state (the inspector must explain hypothetical matches); the poller only dispatches for monitored series/seasons.
- `event_type` filter is an exact match. Deleting a feed/series cascades to its entries/evaluations/downloads (204).
- Grab preview (`confirm:false`) returns 200 with `duplicate_of` set when a duplicate exists; only `confirm:true` without `force` returns 409.
- Feed test response: `{ok, feed_title: string|null, entry_count, sample, error: string|null}`.
- `POST /api/auth/setup` does not set a cookie; the UI logs in afterwards.

## AniList (added 2026-10-13)
See `.claude/rules/anilist.md` for the AniList endpoints (`/api/anilist/search`, `/api/anilist/{id}`, `/api/anilist/{id}/suggest`, `PUT /api/series/{id}/anilist`) and the new `anilist_id` / `cover_url` / `anilist` fields on `Series` and `SeriesIn`.

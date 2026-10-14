# Episodes, release search, calendar, wanted (decided 2026-10-14)

Problem: the RSS feed only carries the newest ~75 releases and everything present at first poll is "historical", so already-aired
episodes (e.g. Black Clover S2 E01-E02) are never grabbed. Also users cannot see which episodes exist or are downloaded.

## Facts (observed live 2026-10-14)
- AnimeTosho search feed: `https://feed.animetosho.net/rss2?q=<urlencoded query>` returns the same RSS2 item format as the main feed,
  filtered by the query (e.g. `black clover S02` -> FrixySubs/Buzz-Subs/Feibanyama/Anime Time S02E01-02). Newest first, ~75 items max.
- AniList `Media(id){ episodes idMal status nextAiringEpisode{episode airingAt} airingSchedule(page,perPage:50){pageInfo{hasNextPage} nodes{episode airingAt}}
  streamingEpisodes{title site url} }`: airingSchedule lists EVERY episode with a unix `airingAt` (past and future; Black Clover S1 has 170+ nodes,
  S2 has nodes for ep 1..N while RELEASING). `streamingEpisodes` titles look like `Episode 3 - To the Royal Capital of the Clover Kingdom`
  (Crunchyroll); empty for new seasons. `episodes` is null while airing.
- Jikan (`https://api.jikan.moe/v4/anime/{idMal}/episodes?page=N`, 100 per page, rate limit 3/s and 60/min) has per-episode titles and
  air dates, but it TIMED OUT from the dev network. It is a best-effort fallback only: timeout 8 s, never required, never retried in the same run.

## Data model (migration `0003_episodes`)
- `seasons`: add `anilist_id` (Integer, nullable, unique index `ux_seasons_anilist_id`), `metadata_refreshed_at` (datetime nullable).
- `episodes` (new): id, season_id FK cascade, episode_number (int), title (nullable), air_date (UTC datetime nullable), source ('anilist'|'jikan'|'manual'),
  created_at, updated_at. UNIQUE(season_id, episode_number).
- `feed_sources`: add `search_url_template` (String nullable). Must contain `{query}` exactly once; same SSRF validation as `url` (validate the template
  with `{query}` replaced by `test`). Seed sets it for the demo AnimeTosho feed to `https://feed.animetosho.net/rss2?q={query}`; also backfill it on startup
  for an existing feed whose url is exactly `https://feed.animetosho.net/rss2` and template is null (idempotent, logged once).
- `feed_entries.outcome` gains value `'searched'`: an entry that arrived through a release search, never auto-dispatched by the poller.
- settings keys: `auto_search_missing` (bool, false), `search_interval_hours` (int, 24, min 1), `metadata_refresh_hours` (int, 12, min 1),
  `search_delay_seconds` (int, 3: pause between consecutive search feed fetches).

## Episode status (derived, never stored) — `services/episodes.py: compute_status(episode, downloads, now)`
Consider the newest non-failed download for (season_id, episode_number):
- download.status in {submitted, exists, path_mismatch} and (qbit_progress >= 0.999 or qbit_state in {uploading, stalledUP, pausedUP, stoppedUP, queuedUP, forcedUP, checkingUP}) -> `downloaded`
- same statuses otherwise -> `downloading` (progress shown)
- download.status == pending -> `pending`
- no active download: air_date is null -> `unknown`; air_date > now -> `unaired`; air_date <= now -> `missing`
- only failed downloads and aired -> `missing` (the failed download is still shown)
Season summary: `episode_count`, `downloaded_count`, `missing_count` (missing = aired with no active download).

## Metadata service — `services/metadata.py`
- `refresh_season(db, season, settings) -> list[Episode]`: requires `season.anilist_id` (else `MetadataError(not_linked=True)`). Fetch AniList
  (reuse `anilist.AnilistClient` with a new `episodes(id)` method that paginates airingSchedule up to 12 pages and returns
  `{episodes, idMal, status, airing: {ep: airingAt}, titles: {ep: title}}`; titles parsed from streamingEpisodes `^Episode\s+(\d+)\s*[-:]\s*(.+)$`).
  Episode numbers = airing keys ∪ title keys ∪ range(1..episodes). If some aired episodes have no title and idMal: try Jikan (max 5 pages, 0.4 s between pages);
  Jikan `aired` fills missing air dates too. Upsert into `episodes`; never overwrite a row with source 'manual'; never delete rows (an episode
  that disappeared upstream keeps its data). Set `metadata_refreshed_at`. Log an activity event `metadata_refreshed` with counts.
- Triggers: `PUT /api/seasons/{id}` when anilist_id changes (sync, best effort: failure returns 200 with a `warnings` entry);
  `POST /api/seasons/{id}/episodes/refresh` (sync, 502 on failure); scheduler job `metadata_refresh` every `metadata_refresh_hours`
  for monitored seasons whose season has anilist_id (stale first); `PUT /api/series/{id}/anilist` sets season 1's anilist_id when that season
  has none, and the wizard sends `anilist_id` per season (suggestion seasons carry the media id; "Add as season" carries the related id).

## Release search — `services/search.py`
- `search_season(db, season, settings, query: str | None) -> SearchResult`: queries = [query] if given else unique, non-empty
  `[series.name] + aliases[:2]`, each suffixed with ` S{season:02d}` only when the season has no absolute range (absolute-numbered groups
  do not use S02). For each enabled feed with `search_url_template`, for each query: build URL (urlencode), `feeds.fetch_feed` (same SSRF/size rules),
  upsert entries with `outcome='searched'` (existing entries keep their outcome), parse + evaluate against the enabled rules of this series that are
  season-wide or bound to this season (ignore monitored flags: search is explicit), collect matched candidates. Sleep `search_delay_seconds`
  between fetches; cap at 6 fetches per call. Candidates are grouped by episode_number; order within a group: rule priority desc, then published_at desc.
  Each candidate: `{entry: FeedEntry, episode_number, rule_id, rule_name, conditions, save_path, episode_status (from episodes table + downloads),
  already_have: bool (status in downloaded/downloading/pending)}`. Result also has `queries`, `feeds_searched`, `fetched`, `errors[]`.
- `grab_missing(db, season, settings, result?) -> {grabbed: Download[], skipped: [{episode_number, reason}]}`: for every episode whose status is `missing`
  (or `unknown` when the season has no metadata) with at least one candidate, grab the first candidate via the existing dispatcher path
  (`forced=False`, normal duplicate rules); skip with reason otherwise ("no candidate", "already have", "unaired").
- Scheduler job `search_missing` every `search_interval_hours` when `auto_search_missing` is true: for each monitored season with `missing_count > 0`
  (requires episode metadata), run `search_season` + `grab_missing`; log one activity event per season with counts; stop after 20 seasons per run.

## API additions
- `GET /api/seasons/{id}/episodes` -> `{items: Episode[], summary: {episode_count, downloaded_count, missing_count, unaired_count}}`
  Episode = `{id, season_id, episode_number, title, air_date, source, status, download: Download | null}`
- `POST /api/seasons/{id}/episodes/refresh` -> same shape; 400 if the season has no anilist_id; 502 on AniList failure.
- `PUT /api/seasons/{id}/episodes/{number}` `{title?: string | null, air_date?: string | null}` -> Episode (source becomes 'manual'); creates the row if missing.
- `POST /api/seasons/{id}/search` `{query?: string}` -> SearchResult `{queries, feeds_searched, fetched, candidates: Candidate[], errors}`; 400 if no feed has a search template.
- `POST /api/seasons/{id}/search/grab-missing` `{query?: string}` -> `{grabbed: Download[], skipped: [{episode_number, reason}]}` (runs the search first).
- `GET /api/calendar?from=<iso>&to=<iso>` (defaults: from = now-7d, to = now+14d; max span 62 days) -> `{items: CalendarItem[]}` sorted by air_date.
  CalendarItem = `{series_id, series_name, cover_url, season_id, season_number, episode_number, title, air_date, status, monitored}` (monitored = series and season monitored).
- `GET /api/wanted?limit=&offset=` -> `{items: CalendarItem[], total}`: episodes with status `missing` in monitored seasons, newest air_date first.
- `POST /api/wanted/search-all` -> `{seasons: [{season_id, series_name, season_number, grabbed, skipped, errors}]}` (sync; cap 10 seasons; 409 if already running).
- `SeasonIn`/`Season` gain `anilist_id: number | null`; `Season` gains `episode_count, downloaded_count, missing_count` (computed, cheap aggregate).
- `FeedSource`/feed input gain `search_url_template: string | null` (400 if it lacks `{query}` or fails SSRF validation).
- `AppSettings` gains `auto_search_missing, search_interval_hours, metadata_refresh_hours, search_delay_seconds`.
- `Dashboard` gains `upcoming: CalendarItem[]` (next 7 days, max 10, monitored only) and `counts.wanted`.
- `AnilistSuggestion.seasons[*]` and `AnilistRelated` already carry ids; suggestion seasons now include `anilist_id`.

## Frontend
- Series detail: each season card gets an **Episodes** table (number, title or "Episode N", air date as date + relative, status badge
  downloaded=green / downloading=blue with % / pending=grey / missing=orange / unaired=purple / unknown=grey, actions: "Search" (scoped to that episode:
  opens the search drawer filtered to its number) and "Grab" when a candidate is already known), a progress line "12 of 24 downloaded · 3 missing",
  buttons **Refresh metadata** and **Search releases**, and an AniList id field (with inline AnilistSearch to pick the season's entry; show title).
- Search drawer: shows queries used, feeds searched, per-episode groups with candidate rows (group, title, resolution, size, published, rule, conditions
  expandable, save path), "Grab" per candidate (uses the existing grab preview -> confirm flow in-drawer) and **Grab all missing** (confirm step listing what will be sent).
- New page `/calendar`: list grouped by day for the window (default past 7 / next 14 days, prev/next week buttons), each row = cover thumb, series, SxxEyy, title, time, status badge; toggle "monitored only" (default on).
- New page `/wanted`: table of missing episodes, "Search" per row (opens the season search drawer), "Search all" button with the summary result.
- Feeds form: "Search URL template" field with help text and `{query}` validation hint. Settings: the four new fields with explanations
  (auto search is OFF by default and only grabs episodes whose status is missing).
- Dashboard: "Upcoming" card (next 7 days) and "Wanted" count card linking to `/wanted`.
- Wizard: suggestion seasons and "Add as season" set the season's `anilist_id`; review step mentions "episode metadata will be fetched after creation".
- Sidebar: add Calendar and Wanted entries (after Releases). Bundle budget unchanged.

## Tests (backend)
- status derivation table (every branch above); metadata refresh with respx AniList fixture (airing + streaming titles; paginated), Jikan failure ignored,
  manual rows preserved; search: template validation, query building (with/without absolute range), SSRF rejection of a bad template, candidates grouped and ordered,
  entries stored as 'searched' and never dispatched by the poller, grab_missing grabs only missing episodes and respects duplicates; calendar window + defaults;
  wanted only monitored; dashboard upcoming; API codes (400 no template / no anilist id, 502 upstream, 409 search-all running).

## Implemented deviations (backend, 2026-10-14) — these are the truth now
- Season (provider, id) index is NOT unique (TMDB seasons share the TV id). Migration 0003 uses native `ALTER TABLE DROP COLUMN` (SQLite >= 3.35) because
  Alembic's table rebuild with foreign keys ON cascade-deleted child rows; a test upgrades a populated 0002 DB.
- Env `JIKAN_ENABLED` (default true). Jikan is also used to fill missing air dates, not only titles.
- `GET /api/calendar` accepts `monitored_only` (default false). `grab-missing` returns `errors[]` and more skip reasons. `feeds_searched` is a list of feed names.
  `search-all` returns 400 when no feed has a template; its `grabbed`/`skipped` are counts. Suggestions carry `provider` and `id`; TMDB `episode_max` only when the show ended.
- Seasons without metadata return an empty episode list. Fields omitted by older clients are kept, not wiped.
- Live verified 2026-10-14 (feedcatch image + qBittorrent 5.2.4 + AniList + AnimeTosho search): Black Clover S2 linked to 195604 -> 12 episodes, E01/E02 missing ->
  search `Black Clover S02` -> DKB candidates -> grab-missing -> both `submitted` at `/home/qbittorrent-nox/media/Black Clover/Season 02`; calendar/wanted/dashboard consistent.

## Fixes decided 2026-10-14 (after the first user report "getting the episode list doesn't work")
- Root cause 1: after upgrading from 0002, the series link migrates but seasons stay unlinked -> empty list + 400 "season is not linked". Fix:
  (a) startup task `backfill_season_links` (once per season, best effort, logged): for every series with a metadata link, link season 1 to the series entry when
  unlinked (anilist and tmdb); for anilist, link other unlinked seasons N when the series detail's related list has a SEQUEL with suggested_season_number == N
  (chain: follow SEQUEL of SEQUEL up to 5 hops to find season N; each hop one cached detail call); for tmdb, link every unlinked season whose number exists upstream.
  Then schedule an immediate metadata refresh for newly linked seasons. (b) UI: an unlinked season shows a prominent call-to-action card
  "Link this season to AniList/TMDB to see its episodes" with the inline MetadataSearch, instead of an empty table.
- Root cause 2: Jikan unreachable costs 8 s per refresh ("Network is unreachable" after the full timeout). Fix: connect timeout 3 s, read 8 s; after any Jikan
  failure, skip Jikan for 6 h (module-level backoff, reset by `JIKAN_ENABLED` toggle or restart); log once per backoff window.
- Downloads can be deleted: `DELETE /api/downloads/{id}` removes feedcatch's record only (the torrent stays in qBittorrent; invariant 6). After deletion the episode
  becomes `missing` again and can be re-grabbed. UI: "Delete" with inline confirm on the Downloads page and in the episode row's download popover; the confirm text says
  the torrent is not removed from qBittorrent.

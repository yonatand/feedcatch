# Metadata providers (decided 2026-10-14; supersedes the provider-specific parts of anilist.md)

feedcatch is for any ongoing series, not only anime. Metadata (names, aliases, covers, seasons, episode titles and air dates) comes from
pluggable providers. Matching never depends on a provider; it only uses the user's rules and aliases.

| Provider | Key needed | Kind | Search | Seasons | Episodes (titles + air dates) |
|---|---|---|---|---|---|
| `anilist` | no | anime | GraphQL `Page.media(search)` | one season per AniList entry (sequels are separate entries, offered as "Add as season") | `airingSchedule` + `streamingEpisodes` (+ Jikan best effort) |
| `tmdb` | yes (`TMDB_API_KEY` env or Settings) | tv | `GET /3/search/tv?query=` | `GET /3/tv/{id}` -> `seasons[]` (skip season 0) | `GET /3/tv/{id}/season/{n}` -> `episodes[]` |

TMDB facts (API v3, from the public docs; NOT verified live here because no key was available): base `https://api.themoviedb.org/3`, auth via
`?api_key=` (v3 key) or `Authorization: Bearer <v4 token>`; accept both: if the configured key is longer than 40 chars treat it as a v4 token.
Poster url `https://image.tmdb.org/t/p/w342{poster_path}`; site url `https://www.themoviedb.org/tv/{id}`; 401 -> bad key; 404 -> unknown id;
429 -> rate limited (rare). `status` values: "Returning Series", "Ended", "Canceled", "In Production", "Planned".

## Data model (migration 0003, together with the episodes tables)
- `series`: `metadata_provider` (String nullable: 'anilist' | 'tmdb'), `metadata_id` (String nullable), `cover_url` (kept), `metadata_json` (ORM attr `metadata_info`;
  dict `{provider, id, title, original_title, alt_titles: [], kind: 'anime' | 'tv', format, status, year, episodes, site_url}`), unique index `(metadata_provider, metadata_id)`.
  Existing `anilist_id` -> provider 'anilist' + `str(id)`; `anilist_json` -> `metadata_json` with `kind: 'anime'`. Drop the old columns (SQLite: alembic batch mode).
- `seasons`: `metadata_provider`, `metadata_id`, `metadata_refreshed_at`. For tmdb the season's `metadata_id` is the TV id (the season number is the season's own number);
  for anilist it is the AniList media id of that entry.
- settings: `tmdb_api_key` (Fernet-encrypted; never returned; `tmdb_api_key_set` reported; env `TMDB_API_KEY` overrides and shows `sources.tmdb_api_key = 'env'`).

## Service layer: `app/services/metadata/`
- `base.py`: `MediaResult {provider, id (str), title, original_title, alt_titles, kind, format, status, year, episodes, cover_url, site_url}`;
  `SeasonInfo {season_number, name, episode_count, air_date}`; `RelatedInfo {relation_type, provider, id, title, format, episodes, year, status, suggested_season_number}`;
  `MediaDetail = MediaResult + seasons: [SeasonInfo] + related: [RelatedInfo]`; `EpisodeInfo {number, title, air_date}`;
  `MetadataError(transient, not_found, not_configured, retry_after)`; `class MetadataProvider(Protocol)`: `name`, `label`, `kind`, `configured(db, settings) -> bool`,
  `search(q, limit)`, `detail(id)`, `episodes(id, season_number)`; `get_provider(name, db, settings)`; `list_providers(db, settings)`;
  `build_suggestion(detail) -> Suggestion {name, aliases, cover_url, metadata (info dict), seasons: [SeasonIn-like incl. metadata_provider/metadata_id], related}`.
  Name/alias rules as in anilist.md (sanitize for path, Latin-script aliases only, original_title becomes an alias when it differs).
- `anilist.py`: existing client moved here; same cache; `detail().seasons = [{season_number: 1, name: null, episode_count: episodes, air_date: start date}]`;
  related as before (SEQUEL suggested_season_number 2).
- `tmdb.py`: httpx client, timeout 10 s, cache 10 min; `search` maps `results[]` (name, original_name, first_air_date -> year, poster_path, id);
  `detail` maps `/tv/{id}` (seasons without season 0; related = []); `episodes(id, n)` maps `/tv/{id}/season/{n}`.

## API
- `GET /api/metadata/providers` -> `{items: [{name, label, kind, configured}]}`
- `GET /api/metadata/search?provider=&q=&limit=10` -> `{items: MediaResult[]}`; 400 bad provider / short q / provider not configured; 429 passthrough with detail; 502 upstream.
- `GET /api/metadata/{provider}/{id}` -> MediaDetail; 404 unknown id.
- `GET /api/metadata/{provider}/{id}/suggest` -> Suggestion.
- `PUT /api/series/{id}/metadata` `{provider: 'anilist' | 'tmdb' | null, id: string | null}` -> Series (links: sets provider/id/cover/metadata, merges aliases; also sets
  season 1's provider/id when empty; for tmdb, every suggested season that exists by number gets provider/id too). 409 if another series has the same link.
- `Series`/`SeriesIn`: `metadata_provider`, `metadata_id`, `cover_url`, `metadata` (info | null). `Season`/`SeasonIn`: `metadata_provider`, `metadata_id` (+ `warnings` on Season out).
- `AppSettings`: `tmdb_api_key_set: bool` (GET), `tmdb_api_key?: string` (PUT; "" clears), `sources.tmdb_api_key`.
- `/api/anilist/*` routes are removed (never released as stable; the UI is rebuilt at the same time).

## Seed / onboarding
- No demo series, rule or feed. If `FEED_URL` is set, create that one feed on first start (name = hostname), with `search_url_template` prefilled only when the host is
  `feed.animetosho.net`. Dashboard shows an onboarding card when there are no feeds or no series: "1. Add a feed  2. Connect qBittorrent  3. Add a series".
- Feed form offers client-side presets (no server knowledge): "AnimeTosho (anime)": url `https://feed.animetosho.net/rss2`, search `https://feed.animetosho.net/rss2?q={query}`;
  "Nyaa (anime)": url `https://nyaa.si/?page=rss`, search `https://nyaa.si/?page=rss&q={query}`; "Custom RSS/Atom". Presets only fill the form.

## Frontend (replaces the AniList-specific UI)
- `MetadataSearch` component = the former AnilistSearch with a provider select (from `/api/metadata/providers`; unconfigured providers are disabled with a hint
  "needs a TMDB API key (Settings)"). Default provider: the first configured one.
- Everywhere "AniList" was shown generically ("View on AniList"), show the provider label ("View on AniList" / "View on TMDB"); covers from either CDN.
- Settings: TMDB API key field (write-only with "key set" indicator and Clear), link to https://www.themoviedb.org/settings/api.
- README: reframe as "RSS -> qBittorrent automation for ongoing series (anime or TV)"; AnimeTosho/Nyaa are presets, not defaults; TMDB key instructions.

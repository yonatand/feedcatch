# AniList integration (decided 2026-10-13; SUPERSEDED 2026-10-14 by `metadata.md`: AniList is now one provider behind `/api/metadata/*`; the facts below about the AniList API and alias rules still apply)

Purpose: search anime by name and add it as a tracked series with one click, prefilled with canonical name, aliases, cover and
suggested seasons. AniList is metadata only; it never affects matching except through the aliases the user keeps.

## Facts (observed live 2026-10-13)
- Endpoint `POST https://graphql.anilist.co`, JSON `{query, variables}`, headers `Content-Type: application/json`, `Accept: application/json`. No auth for public data.
- Rate limit headers: `X-RateLimit-Limit: 30`, `X-RateLimit-Remaining`; 429 with `Retry-After` when exceeded. Treat the budget as 30/min.
- Useful fields: `id`, `title{romaji english native}`, `synonyms` (many non-Latin), `format` (TV, TV_SHORT, MOVIE, SPECIAL, OVA, ONA, MUSIC),
  `status` (FINISHED, RELEASING, NOT_YET_RELEASED, CANCELLED, HIATUS), `seasonYear`, `season`, `episodes` (null while airing/unknown),
  `coverImage{medium large}`, `siteUrl`, `relations{edges{relationType node{id title{romaji english} format episodes seasonYear status}}}`.
  Relation types seen: SEQUEL, PREQUEL, PARENT, SIDE_STORY, SPIN_OFF, ALTERNATIVE, OTHER, ADAPTATION (manga/novel; ignore).
- Example: Black Clover = id 97940, TV, 170 episodes, SEQUEL -> 195604 "Black Clover 2nd Season" (TV, 2026).

## Backend
- `app/services/anilist.py`: `AnilistError(transient: bool)`, `AnilistClient(timeout=10)` with `search(q, limit=10) -> list[AnilistMedia]`,
  `get(id) -> AnilistMediaDetail`. Module-level TTL cache (dict, 10 min, max 500 keys) keyed by query/id so repeated UI keystrokes do not burn the budget;
  on 429 raise `AnilistError(transient=True, retry_after=<s>)`. Requests use `User-Agent: feedcatch/<version>`. Fixed host, so no SSRF check needed.
  Pure helper `build_suggestion(detail) -> AnilistSuggestion`:
  - `name` = english title if present else romaji, passed through `paths.sanitize_component` (so it is a valid folder name); if sanitizing changes it, add the original to aliases.
  - `aliases` = [romaji, english, synonyms...] that contain at least one ASCII letter, de-duplicated case-insensitively, excluding `name`. Native title is never an alias.
  - `seasons` = `[{season_number: 1, episode_min: null, episode_max: episodes or null, absolute_min: null, absolute_max: null}]`.
  - `related` = relations filtered to type in {SEQUEL, PREQUEL, PARENT, SIDE_STORY, ALTERNATIVE} and format in {TV, TV_SHORT, ONA, OVA, MOVIE, SPECIAL}, each with `suggested_season_number` (PREQUEL chain not computed; just null) and `episodes`.
- Migration `0002_anilist`: `series.anilist_id` (Integer, nullable, unique), `series.cover_url` (String, nullable), `series.anilist_json` (JSON, nullable: {title_romaji, title_english, title_native, format, status, season_year, episodes, site_url}).
  ORM attribute `Series.anilist` for the JSON column (consistent with the `_json` convention).
- Schemas: `AnilistMediaOut`, `AnilistRelatedOut`, `AnilistMediaDetailOut` (media + `related`), `AnilistSuggestionOut`, `SeriesIn` gains optional `anilist_id`, `cover_url`, `anilist` (AnilistInfo dict) — all nullable, default null; `SeriesOut` returns them. `LinkAnilistIn {anilist_id: int | null}`.
- API (all require auth):
  - `GET /api/anilist/search?q=<str>&limit=10` -> `{items: AnilistMedia[]}`; 400 if `q` shorter than 2 chars; 502 `{detail}` on AniList failure; 429 `{detail: "AniList rate limit, retry in N s"}` passthrough.
  - `GET /api/anilist/{id}` -> AnilistMediaDetail (404 if AniList has no such id).
  - `GET /api/anilist/{id}/suggest` -> AnilistSuggestion.
  - `PUT /api/series/{id}/anilist` `{anilist_id}` -> Series. With a number: fetch detail, set `anilist_id`, `cover_url`, `anilist`, and merge suggested aliases into the series aliases (keep existing; do not rename the series). With null: clear the three fields (aliases untouched). 409 if another series already has that anilist_id.
- Tests (respx against `https://graphql.anilist.co`): search parses a fixture response (store `tests/fixtures/anilist_black_clover.json` copied from a real response); 429 -> AnilistError transient with retry_after; cache hit makes no second request; `build_suggestion` for Black Clover gives name "Black Clover", aliases without Hebrew/Thai/Russian synonyms and without the native title, 1 season with episode_max 170, related includes the SEQUEL 195604 and excludes ADAPTATION; API tests for search/detail/suggest/link (409 on duplicate link, null unlinks); migration adds the columns and the unique index.

## Frontend
- `types.ts`: add `AnilistMedia`, `AnilistRelated`, `AnilistMediaDetail`, `AnilistSuggestion`; extend `Series`/`SeriesIn` with `anilist_id`, `cover_url`, `anilist`.
- `components/AnilistSearch.tsx`: text input (debounced 400 ms, min 2 chars) -> result list with cover thumbnail (lazy `loading="lazy"`, 40x56), english + romaji title, format, year, episodes, status badge; "Use" button per row. Shows a small note that covers are loaded from AniList's CDN. Handles 429 with the retry message.
- Wizard `/series/new` step 1: "Search AniList" box above the manual fields. Choosing a result fetches `/api/anilist/{id}/suggest` and prefills name, aliases, cover, anilist info; the fields stay editable. Step 2: if a suggestion exists, prefill its `seasons` and show "Related on AniList" (sequels/prequels/parent) with an "Add as season" button that appends a season row with the next season number and `episode_max` = that entry's episodes. Step 4: show the cover next to the review.
- `/series` list: cover thumbnail column (placeholder box when none). `/series/:id`: cover + AniList link (`site_url`) + "Link to AniList" (AnilistSearch inline; on pick -> `PUT /api/series/{id}/anilist`) and "Unlink".
- No new runtime dependencies. Bundle budget unchanged (initial < 120 KB gzip).

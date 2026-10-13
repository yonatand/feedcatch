# Build a self-hosted anime RSS → qBittorrent automation system

You are Claude, acting as a senior full-stack engineer. **Build the working application**, not merely an architecture proposal. Create the source code, configuration, tests, Docker deployment, and a concise README. Prefer a functioning, maintainable MVP over aspirational features. Ask questions only if a decision truly blocks implementation; otherwise use the defaults below and document assumptions.

## Goal

Replace Sonarr/autobrr/FlexGet for one narrowly defined job:

1. Poll an AnimeTosho-compatible **RSS2 feed** for newly posted anime releases.
2. Let me configure the anime I follow, release groups, title patterns, seasons, episode numbers, codecs, resolution, and other inclusion/exclusion rules from a web UI.
3. Automatically match new releases against these rules and deduplicate episodes/releases.
4. Send the torrent or magnet to **an existing qBittorrent-nox instance** using its Web API, with an **explicit per-torrent save path** such as `/home/qbittorrent-nox/media/Black Clover/Season 02`.
5. **Only qBittorrent writes to the media folder**. This application must never download, move, rename, import, create directories within, or delete media files.
6. Show transparent match/reject decisions, download-submission status, errors, and history.

This must be a **standalone, self-hosted, Docker Compose-deployable application**, with no Sonarr, autobrr, Prowlarr, or FlexGet dependency. It should be usable through a clean, responsive web interface.

## Environment and integration constraints

- Host: Debian Linux VM under Proxmox.
- Existing qBittorrent-nox installation; its WebUI may use VueTorrent, which **does not change the qBittorrent Web API**.
- qBittorrent may be reachable from the app container via `http://host.docker.internal:8080`; include Linux Compose mapping `extra_hosts: ["host.docker.internal:host-gateway"]`. Make URL/port configurable.
- qBittorrent may require username/password. Implement `/api/v2/auth/login` using a persistent HTTP session/cookies, followed by API requests. Account for qBittorrent's WebUI host-header/CSRF configuration without recommending global security disablement.
- Default qBittorrent media base path: `/home/qbittorrent-nox/media` **as seen by qBittorrent**, not necessarily a path accessible inside the app container.
- Do **not** mount the media directory into the application container; it should not need filesystem access to that path.
- The AnimeTosho-compatible RSS source should default to `https://feed.animetosho.net/rss2`, but must be configurable and verified in runtime/tests rather than presumed always available. Support generic RSS2/Atom feeds with magnet or `.torrent` links/enclosures. Do not assume the feed has a valid Torznab API; previous Torznab parsing failed on text category `Anime` where numeric categories were expected.
- qBittorrent torrents should continue seeding and remain owned/managed by qBittorrent. Do not automatically remove torrents or their data.

## Required application features

### 1. RSS sources

- Add/edit/delete RSS sources with URL, enabled toggle, polling interval (default 15 minutes), last-check timestamp, status, and error details.
- HTTP timeouts, retries with bounded exponential backoff, conditional GET (`ETag`/`Last-Modified`) where supported, and safe XML parsing.
- Parse feed GUID, title, published date, content/link/enclosure and all usable magnet and torrent URLs.
- Handle feed entries that offer NZB and torrent links simultaneously: **only choose magnet/torrent**, never send NZB to qBittorrent.
- Never re-process the same feed entry unnecessarily; persisted deduplication across app restarts.
- First-time startup/backfill behavior configurable: default **do not automatically grab historical RSS entries**; show them in a preview and start automatic processing from subsequent entries.

### 2. Series and season management

- CRUD for tracked series with friendly display name, aliases, monitored/unmonitored state, and optional manually defined seasons.
- Per-series **explicit season mapping** independent of RSS title conventions. For example, I can define `Black Clover`, season `02`, and give it release-title patterns even if upstream uses anime absolute numbering (171, 172, ...).
- Episode parser should recognize common forms such as `S02E01`, `Season 2 - 01`, `- 171`, and `[DKB] Black Clover ...`; avoid guessing season from absolute numbers without mapping.
- Allow explicit episode number ranges and optional mapping from absolute episode number to season episode number. When ambiguous, require a mapping or use a user-configured fallback, not an invented season.
- Season folder format defaults to `Season 02` (zero-padded), configurable at series level.
- A new-series wizard with feed preview and "test these filters against recent releases" before enabling auto-grab.

### 3. Matching and filtering

- Rules configurable in WebUI per tracked series/season:
  - series name/aliases and include/exclude keywords;
  - release group (e.g. **DKB**) with an optional literal `[DKB]` title prefix check;
  - season or absolute episode range;
  - resolution, source, codec, subtitle/language keywords, file size (if provided);
  - optional regex advanced matcher, clearly showing regex syntax, validation, and sample matching results;
  - priority and selection preferences when multiple releases target the same episode.
- Make the common case work **without regex**. Support regex when the user explicitly wants it. Don't require PCRE lookaheads or present unsupported regexes as valid.
- Treat parsed metadata as fallible. Show exactly which conditions matched or rejected each release.
- Configurable duplicate policy: at most one accepted download per episode by default; upgrades/replacements off by default; manual force-grab override with confirmation. Track both feed GUID/magnet infohash when available and episode identity.
- Only consider automatic grabs for *new* RSS arrivals unless historical backfill is deliberately enabled.

### 4. qBittorrent integration

- qBittorrent connection config: URL, credentials, category (optional), timeout, "Test Connection" button, API version/client version diagnostics.
- On a match, send magnet via `POST /api/v2/torrents/add` using `urls` plus **`savepath` per torrent** (or an equivalent documented qBittorrent Web API argument). Do not use Sonarr-style library import semantics.
- Compute save path from configured media base + **canonical series name** + **season folder**, e.g. `/home/qbittorrent-nox/media/Black Clover/Season 02`.
- Provide per-series/per-season path overrides as well.
- Ensure safe path construction: normalize names; reject `..`, slashes, control characters, absolute-path escape, and unsafe template interpolation. Do not let a feed title dictate filesystem path components.
- Understand and handle qBittorrent category save paths and **Automatic Torrent Management**: ensure the explicit save path is honored; define an appropriate API addition option or warn/block when settings could override it. Validate using qBittorrent API state and explain mismatches in the UI.
- Handle duplicate torrent hashes and submission failures clearly. Retry transient failures idempotently; do not repeatedly enqueue a duplicate magnet after uncertain response without checking qBittorrent.
- A configurable "start immediately" setting. qBittorrent controls data download, storage, and seeding.
- Show whether submission was accepted, rejected, or pending retry; optionally poll qBittorrent for torrent state and download progress, but **do not manage completed files**.

### 5. Web interface

- Dashboard: feed health, recent matches, downloads sent, failed submissions, active rules.
- Screens: Feeds; Series; Seasons; Rules; Recent Releases; Match Inspector (why accepted/rejected); qBittorrent Connection; Activity/History; Settings.
- Quick actions: test feed, preview recent entries, simulate rule on sample title, manually grab a chosen release, enable/disable series, retry failed submissions.
- Clear UI showing the **exact qBittorrent destination path before submission**.
- Responsive desktop-first interface; straightforward styling and no unnecessary complexity.
- Configuration persisted across restarts.

### 6. Reliability and security

- Prefer SQLite for the MVP with migrations, durable uniqueness constraints, and a single scheduled worker; design so Postgres can be added later if needed.
- Never embed qBittorrent credentials in logs or return them to the browser after saving. Store secrets appropriately for a self-hosted app and support environment-variable configuration.
- Protect the management UI with authentication or explicitly constrain it to a trusted network behind a reverse proxy; do not expose unauthenticated controls publicly.
- Validate input URLs and guard against SSRF (including redirects) when fetching user-added feeds; document trusted-network assumptions.
- Structured logs with useful errors, healthcheck, graceful shutdown, no duplicate processing during concurrent polls, and bounded retry queue.
- Unit tests for parsing/filtering/path generation; integration tests with mocked AnimeTosho RSS and qBittorrent API, including `403`, timeouts, invalid feeds, NZB-only entries, and category/path overrides.
- No hardcoded credentials or API tokens.

## Example behavior: Black Clover Season 2 by DKB

Create a tracked series with:

- Name: `Black Clover`
- Season: `2`
- Release group: `DKB`
- Feed: AnimeTosho RSS
- Match aliases: `Black Clover`, `Black.Clover`, `Black_Clover`
- Season matching: explicit `S02` / `Season 2` **or a user-configured absolute episode range** (do not silently assume one)
- Root path: `/home/qbittorrent-nox/media`
- Computed qBittorrent save path: `/home/qbittorrent-nox/media/Black Clover/Season 02`
- Torrent category: configurable; optional `anime`
- Completed download handling/import/renaming: **none**

For a matching release, show a preview such as:

```
RSS title: [DKB] Black Clover Season 2 - 01 [1080p]
Decision: ACCEPT (series=Black Clover, group=DKB, season=2)
Magnet: magnet:?xt=urn:btih:...
Send to: qBittorrent
Save path: /home/qbittorrent-nox/media/Black Clover/Season 02
```

A different group, different series, or nonmatching season should be rejected with a visible reason. If an RSS entry is labeled seasonlessly (e.g. `[DKB] Black Clover - 171`), only accept it when explicit mapping/range makes the season unambiguous.

## Implementation instructions

Choose a pragmatic stack: **Python 3.12+ with FastAPI, SQLAlchemy, SQLite, APScheduler, httpx, feedparser, and a simple React/Vite + TypeScript UI** is preferred, but you can justify a simpler alternative if it reduces maintenance. Use typed schemas and clean separation of feed parsing, release normalization, rule evaluation, download dispatch, storage, scheduling, and HTTP API.

Provide:

1. Complete repo with all application source files; no pseudocode or placeholder endpoints.
2. Working `docker-compose.yml`, multi-stage `Dockerfile` where appropriate, `.env.example`, healthcheck and persistent data volume.
3. Database models and migrations; a seeded demo configuration for Black Clover/DKB that does not auto-download until the user enables it.
4. README with one-command Docker startup, setup wizard, qBittorrent connection/test, AnimeTosho feed configuration, and troubleshooting.
5. Automated tests and exact commands to run them.
6. A short **verification checklist** that exercises RSS fetch → rule match → qBittorrent submission → save path inspection in qBittorrent. Prefer a dry-run test without adding a real torrent, then an explicitly authorized live test.

Before declaring completion, run lint/typecheck/tests/build when the environment permits, fix failures, and report what was actually verified versus what still requires a live qBittorrent server/feed. Do not falsely claim a live integration test without access to those services.

**Critical acceptance criterion:** I can follow Black Clover Season 2 by DKB using an AnimeTosho RSS feed, and a new matching torrent is sent automatically to qBittorrent with `savepath=/home/qbittorrent-nox/media/Black Clover/Season 02`. The automation process itself has no media mount and never touches media files.

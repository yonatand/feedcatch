---
name: qbittorrent-api
description: Facts about the qBittorrent Web API v2 (v4.x and v5.x) that this app depends on: login/CSRF, torrents/add savepath + autoTMM, info, preferences, failure modes. Read before touching app/services/qbit.py or dispatcher.py.
---

# qBittorrent Web API notes

Base: `{url}/api/v2/...`. All requests are form-encoded POST or GET. Use one `httpx.Client` with cookie jar, explicit timeout.
VueTorrent is only an alternative WebUI; the API is unchanged.

## Auth
- `POST /api/v2/auth/login` form `username`, `password`. Response body `Ok.` (200) on success, `Fails.` (200) on bad credentials, 403 when IP is banned
  after too many failures. Sets `SID` cookie. Any other endpoint returns 403 when the session is missing/expired -> re-login once, then retry once.
- CSRF/host-header protection: qBittorrent validates `Origin`/`Referer` against its own host when enabled. Always send
  `Referer: {url}/` and `Origin: {url}` (scheme+host+port of the configured URL). Do NOT advise disabling "Enable Host header validation"
  or CSRF protection; instead the user can add the hostname they use (e.g. `host.docker.internal`) to "Server domains" in WebUI options if needed.
- If the user enabled "Bypass authentication for clients on localhost / in whitelisted IP subnets", login returns Ok. with empty creds; support empty username/password.

## Diagnostics
- `GET /api/v2/app/version` -> e.g. `v4.6.5` / `v5.0.2`.  `GET /api/v2/app/webapiVersion` -> e.g. `2.9.3` / `2.11.2`.
- `GET /api/v2/app/preferences` -> JSON. Relevant keys: `save_path` (default), `auto_tmm_enabled` (global default for new torrents),
  `torrent_changed_tmm_enabled`, `save_path_changed_tmm_enabled`, `category_changed_tmm_enabled`, `temp_path_enabled`, `temp_path`.
  Warn in Test Connection when `auto_tmm_enabled` is true ("we send autoTMM=false per torrent; the explicit save path is still honored") and when
  `temp_path_enabled` is true ("incomplete files go to temp_path first, then move to save path; this is qBittorrent's own behavior").
- `GET /api/v2/torrents/categories` -> `{ "<name>": {"name":..., "savePath":...}, ... }`. If the configured category does not exist, qBittorrent
  creates it on add (4.x+). Report `category_exists` in the test result. If a category has its own savePath AND autoTMM were on, that path would win;
  since we send `autoTMM=false`, our `savepath` wins.

## Adding
- `POST /api/v2/torrents/add` multipart/form-data (httpx: pass `data=` dict and `files={}`? No: qBittorrent accepts plain `application/x-www-form-urlencoded`
  for the `urls` form; use `data=`). Fields we send:
  - `urls`: one magnet or http(s) .torrent URL (newline-separated if several; we send one).
  - `savepath`: explicit absolute path as seen by qBittorrent. (Documented param name is `savepath`.)
  - `category`: optional.
  - `autoTMM`: `false` (string). Ensures savepath is honored regardless of global/category ATM.
  - `paused`: `true|false` (qBittorrent 4.x) and `stopped`: same value (5.x renamed it). Send both; unknown keys are ignored.
  - optional `tags`: `feedcatch` (helps users find what we added). Include it.
- Response: 200 `Ok.` on success. 200 `Fails.` when the URL is invalid / torrent could not be added. 415 when torrent file invalid.
  Duplicate hash: qBittorrent 4.x returns `Fails.`; 5.x may return `Ok.` while not re-adding. Therefore ALWAYS pre-check with `torrents/info?hashes=`.
- After add, the torrent appears in `torrents/info` within ~1s for magnets (metadata not required for listing).

## Inspecting
- `GET /api/v2/torrents/info?hashes=<hex>|<hex>` (lowercase hex, pipe separated) -> array of objects: `hash`, `name`, `state`
  (`downloading`, `stalledDL`, `metaDL`, `pausedDL`/`stoppedDL`, `uploading`, `stalledUP`, `pausedUP`/`stoppedUP`, `queuedDL`, `checkingDL`, `error`, `missingFiles`, ...),
  `progress` (0..1), `save_path`, `content_path`, `category`, `tags`, `added_on` (unix ts), `size`, `completed`.
  Empty array when unknown hash. `?category=<name>` filters; no params = all torrents.
- Save path comparison: qBittorrent may append a trailing slash or normalize; compare `rstrip('/')` on both sides.

## Infohash from magnet
`xt=urn:btih:<40 hex>` or `<32 base32>`; base32 -> `base64.b32decode(s.upper()).hex()`. Lowercase for storage. v2 `urn:btmh:` is ignored for matching.

## Failure classification (used by dispatcher)
- Transient: connect error, read timeout, HTTP 5xx, 403 that persists after one re-login (session/ban) -> keep pending, backoff.
- Permanent: `Fails.` on add, 415, HTTP 4xx other than 403, login `Fails.` (credentials) -> mark failed with clear last_error.

## Observed live on qBittorrent v5.2.4 (2026-10-13, official Docker image) — overrides the docs above where they differ
- Successful login: **HTTP 204, empty body**, cookie named **`QBT_SID_<port>`** (e.g. `QBT_SID_8080`), not `SID`. Let the httpx cookie jar handle it; never hardcode the cookie name.
- Wrong credentials: **HTTP 401 body `Unauthorized`** (no more 200 "Fails."). 4.x still answers 200 "Fails."; support both.
- Host-header validation: a request whose `Host` port differs from the WebUI port (e.g. `localhost:18080` published to `8080`) gets 401 `Unauthorized`
  even with correct credentials. From another container using `http://qbit-smoke:8080` it worked without any "Server domains" change.
  So a 401 on login means either bad credentials or Host rejection; the error message says both.
- An expired/missing session on other endpoints should be treated like 403 (re-login once) when it returns 401.
- `torrents/add` on 5.2.4 (API 2.15.1): HTTP 200 with **JSON** body `{"added_torrent_ids": ["<hex>"], "failure_count": 0, "pending_count": 0}`
  instead of `Ok.`. `pending_count` counts magnets still resolving. Treat `failure_count > 0` with nothing added/pending as rejection.
  Verified live: magnet added with `savepath=/home/qbittorrent-nox/media/Black Clover/Season 02`, `category=anime`, `tags=feedcatch`,
  `autoTMM=false`, `stopped=true` -> `torrents/info` shows exactly that save_path, `auto_tmm: false`, state `stoppedDL`.
- Preferences on 5.2.4 report `temp_path_enabled: true` by default in the official image (`/downloads/temp`); it is qBittorrent's own staging, harmless.

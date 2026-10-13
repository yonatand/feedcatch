# feedcatch

[![CI](https://github.com/yonatand/feedcatch/actions/workflows/ci.yml/badge.svg)](https://github.com/yonatand/feedcatch/actions/workflows/ci.yml)
[![Docker](https://github.com/yonatand/feedcatch/actions/workflows/docker.yml/badge.svg)](https://github.com/yonatand/feedcatch/actions/workflows/docker.yml)

**Catch new anime releases from RSS and hand them to qBittorrent with the right season folder.**

feedcatch is a small self-hosted service that polls an RSS feed (AnimeTosho by default), matches every new release
against the series, release group, season and quality rules you set in its web UI, and sends the magnet to your
**existing qBittorrent** with an explicit save path such as `/home/qbittorrent-nox/media/Black Clover/Season 02`.
It decides; qBittorrent downloads and seeds. feedcatch never mounts or touches your media folder, never processes a feed
entry twice, and shows you exactly why each release was accepted or rejected.

It replaces Sonarr, autobrr and FlexGet for this one job and depends on none of them.

![Dashboard](docs/screenshots/dashboard.png)

## How it works

1. Every 15 minutes (configurable) each enabled feed is fetched with a conditional GET and parsed safely.
2. New entries get their title parsed (`[DKB] Black Clover Season 2 - 01 [1080p]` -> group, title, season, episode, resolution, ...).
3. Each enabled rule of a monitored series is evaluated condition by condition. The best match per episode wins; duplicates by episode or infohash are skipped.
4. The save path is built from *media base + series name + season folder*, with per-series and per-season overrides, and the magnet is sent to qBittorrent with that path and `autoTMM=false`.
5. feedcatch reads the torrent back from qBittorrent, verifies the save path, and records everything in Downloads and Activity.

![Match inspector](docs/screenshots/match-inspector.png)

## What it does and does not do

**Does**
- Polls RSS2 and Atom feeds on a schedule (15 minutes by default), using conditional GET, bounded retries and SSRF guards.
  Entries are remembered across restarts, so none is processed twice.
- Parses release titles (`S02E01`, `Season 2 - 01`, `- 171`, `[DKB] ...`) and evaluates per-series and per-season rules:
  release group, keywords, resolution, source, codec, language, size and an optional Python regex.
- Shows why each release was accepted or rejected, condition by condition.
- Searches **AniList** when you add a series: pick a result and the name, aliases, cover and season count are prefilled;
  sequels show up as "Add as season". AniList is metadata only; matching still uses your rules. Covers load from AniList's CDN in your browser.
- Sends torrents with `POST /api/v2/torrents/add` using `savepath=<computed path>`, `autoTMM=false`, an optional category
  and the tag `feedcatch`. It then reads the torrent back from qBittorrent and checks that the save path matches.
- Allows one accepted download per episode by default, with deduplication by episode and by infohash.

**Does not**
- Mount, read, create, move, rename or delete anything in your media folder. The save path is only a string that it
  passes to qBittorrent, and qBittorrent does all file writes. The container has no media volume.
- Pause, resume, move, rename or remove torrents. qBittorrent owns them and keeps seeding.
- Import, rename or post-process completed files.
- Send NZB links to qBittorrent. Entries that only have NZB links are shown with the reason "no torrent/magnet link (NZB-only)".
- Grab historical feed entries automatically, unless you turn on backfill for that feed.

## Quick start (Docker Compose)

Requirements: Docker with the Compose v2 plugin, and qBittorrent-nox with its WebUI enabled.

```bash
git clone https://github.com/yonatand/feedcatch.git && cd feedcatch
cp .env.example .env          # optionally edit it (see below)
mkdir -p data                 # app state: SQLite DB + secret.key
docker compose up -d --build
```

Then open `http://<host>:8000`. If you set `APP_PORT` in `.env`, use that port instead.

- Health check: `curl http://<host>:8000/healthz` returns `{"status":"ok","db":"ok","scheduler":"running",...}`.
- The JSON API is under `/api`.
- Logs (JSON on stdout): `docker compose logs -f feedcatch`

### Data directory permissions (Linux hosts)

The container runs as a non-root user, uid:gid `1000:1000` by default, and needs write access to `./data`.
If your host user has a different id, set `PUID` and `PGID` in `.env` to the output of `id -u` and `id -g`.
You can also run `sudo chown -R 1000:1000 ./data`. If the directory isn't writable, the container exits at startup with a
message that explains the fix.

## Run from the published image (no build)

A prebuilt image is published to GitHub Container Registry for **linux/amd64** and **linux/arm64**
(for example a Raspberry Pi 4/5 with a 64-bit OS):

| Tag | Points to |
|---|---|
| `ghcr.io/yonatand/feedcatch:latest` | the latest build of `main` |
| `ghcr.io/yonatand/feedcatch:sha-<short>` | one specific commit, for pinning |
| `ghcr.io/yonatand/feedcatch:X.Y.Z` (and `X.Y`) | a release tagged `vX.Y.Z` |

You don't need to clone the repository. In an empty directory, save this as `docker-compose.yml`:

```yaml
services:
  feedcatch:
    image: ghcr.io/yonatand/feedcatch:latest
    container_name: feedcatch
    restart: unless-stopped
    # Run as the owner of ./data on the host (default 1000:1000).
    user: "${PUID:-1000}:${PGID:-1000}"
    ports:
      - "${APP_PORT:-8000}:8000"
    env_file:
      # Optional so the stack still starts with built-in defaults; normally: cp .env.example .env
      - path: .env
        required: false
    environment:
      # Fixed inside the container; change the published port with APP_PORT in .env.
      APP_DATA_DIR: /data
      APP_HOST: 0.0.0.0
      APP_PORT: "8000"
    extra_hosts:
      # Lets the container reach a qBittorrent-nox running on the Docker host (Linux).
      - "host.docker.internal:host-gateway"
    volumes:
      # App state only: SQLite DB (app.db) and secret.key.
      # The media directory is deliberately NOT mounted. The app never reads or writes media;
      # it only hands save-path strings (e.g. /home/qbittorrent-nox/media/Black Clover/Season 02)
      # to qBittorrent, which owns all file writes.
      - ./data:/data
    healthcheck:
      test: ["CMD", "python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"]
      interval: 30s
      timeout: 5s
      start_period: 30s
      retries: 3
    # Lets the scheduler finish an in-flight poll/submission on SIGTERM.
    stop_grace_period: 20s
```

Then:

```bash
mkdir -p data                 # app state: SQLite DB + secret.key (see permissions above)
docker compose up -d
```

`.env` is optional. To configure the app, create it next to the compose file with the variables from
[`.env.example`](.env.example) (see [Configuration](#configuration-env)).

If you cloned the repository, the same file is included as `docker-compose.ghcr.yml`:

```bash
cp .env.example .env && mkdir -p data
docker compose -f docker-compose.ghcr.yml up -d
```

To upgrade, pull the new image and recreate the container: `docker compose pull && docker compose up -d`
(add `-f docker-compose.ghcr.yml` if you use that file).

The package is published by GitHub Actions on every push to `main`; if a pull is denied, the package may still be
private in GitHub Packages settings. Packages created by a workflow start out private. The repository owner can make it
public once: on GitHub, open the repository > **Packages** > **feedcatch** > **Package settings** > **Change visibility** >
**Public**.

## First-run setup

1. **Password.** Authentication is on by default. If `APP_PASSWORD` is empty, the first visit sends you to a setup page
   where you choose a password (at least 8 characters). Only its bcrypt hash is stored. If `APP_PASSWORD` is set in `.env`,
   that value is the password and there is no setup page.
2. **qBittorrent.** On the qBittorrent page, enter the connection details and click **Test Connection** (see below).
3. **Settings.** Check **Media base path**. The default is `/home/qbittorrent-nox/media`. This is the path *as qBittorrent
   sees it*, not a path inside this container. The season folder format defaults to `Season {season:02d}`.
4. **Demo data.** On first start the app creates an AnimeTosho feed and a **Black Clover / Season 2 / DKB 1080p** rule.
   The series is **unmonitored**, so nothing is downloaded until you turn monitoring on (see the walkthrough).

## Configuration (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `APP_PORT` | `8000` | Host port to publish. The container always listens on 8000. |
| `PUID` / `PGID` | `1000` | User the container runs as. Must be able to write `./data`. |
| `APP_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR`. |
| `APP_SECRET_KEY` | empty | Key that encrypts the stored qBittorrent password and signs session cookies. Empty means a key is generated once into `./data/secret.key`. |
| `APP_PASSWORD` | empty | UI password. When set, it always wins over the password stored in the database. |
| `APP_AUTH_DISABLED` | `false` | `true` removes login completely. Use it only on a trusted network or behind an authenticating proxy. |
| `QBIT_URL` | `http://host.docker.internal:8080` | qBittorrent WebUI URL as seen from the container. |
| `QBIT_USERNAME` / `QBIT_PASSWORD` | empty | qBittorrent WebUI credentials. |
| `FEED_URL` | `https://feed.animetosho.net/rss2` | URL of the demo feed created on first start. |
| `ALLOW_PRIVATE_FEED_HOSTS` | empty, which means the UI setting is used (default `false`) | Allow feed URLs that resolve to private or loopback addresses. |

`QBIT_URL`, `QBIT_USERNAME`, `QBIT_PASSWORD`, `APP_PASSWORD` and `ALLOW_PRIVATE_FEED_HOSTS` **override** values saved in the
UI when they are set. The UI marks those fields as coming from `env` and ignores edits to them. To manage them in the UI
instead, leave them empty.

## qBittorrent connection

Tested against qBittorrent v5.2.4 (Web API 2.15.1) and written to the documented v4.x API as well: the client accepts both the `Ok.`/`Fails.` text replies of 4.x and the 204/401/JSON replies of 5.x.

- **URL.** qBittorrent usually runs on the Docker host, so use `http://host.docker.internal:8080`. `docker-compose.yml`
  maps that name to the host gateway with `extra_hosts`. qBittorrent must listen on an interface the container can reach.
  If the WebUI is bound to `127.0.0.1` only, the container can't reach it. Bind it to `0.0.0.0` or to the docker bridge
  address, and restrict access with a firewall if needed.
- **Credentials.** Enter the WebUI username and password. Leave both empty if qBittorrent's "Bypass authentication for
  clients in whitelisted IP subnets" covers the Docker network. The password is stored Fernet-encrypted and is never sent
  back to the browser; the UI only shows whether one is set.
- **Test Connection** logs in and reports:
  - `version` / `api_version`: the qBittorrent version (for example `v5.0.2`) and its Web API version.
  - `default_save_path`: qBittorrent's global default. It doesn't matter here because every torrent gets an explicit path.
  - `auto_tmm_enabled`: when true, you see a warning. Every torrent is sent with `autoTMM=false`, so the explicit save path
    is still used.
  - `category_exists`: whether the optional category exists yet. qBittorrent creates a missing category on the first add.
    A category save path can't override our path, because Automatic Torrent Management (ATM) is off for each torrent.
  - A warning about **temp path** (incomplete files) means qBittorrent downloads into its temp folder first and then moves
    the files to the save path itself. That is normal qBittorrent behavior.
- **Host header and CSRF validation.** The app sends `Origin` and `Referer` headers that match the configured URL. If
  qBittorrent still rejects requests with `403`, **add the hostname you use (for example `host.docker.internal`) to
  qBittorrent > Options > WebUI > "Server domains"**. Don't turn off host-header validation or CSRF protection.
- **Start immediately.** If you turn this off, torrents are added stopped (paused). From then on qBittorrent decides
  everything about downloading and seeding.
- **Category.** Optional, for example `anime`. You can also set a category per series.

## Feeds

The Feeds page lets you add, edit, delete and enable feeds and set their polling interval (5 to 1440 minutes).
- **Test URL** fetches a URL live and shows sample entries with their parsed fields.
- **Preview** lists the current entries of a saved feed without storing anything.
- **Poll now** runs one poll immediately.

The default is **AnimeTosho** (`https://feed.animetosho.net/rss2`). Any RSS2 or Atom feed with magnet links, `.torrent`
links or enclosures works. Feeds aren't parsed as Torznab. When an entry has both a magnet and a torrent link, the magnet
is used. NZB links are recorded but never sent.

**Backfill.** With the default `backfill_mode = skip`, a feed's first poll marks every existing entry as **historical**.
Those entries are evaluated and shown in Releases, so you can see what your rules would have matched, but they are
**never grabbed automatically**. Automatic grabbing starts with entries that appear in later polls. You can still grab a
historical entry manually, with a preview and a confirmation step. Set `backfill_mode = process` only if you really want
the current feed contents grabbed.

Feed URLs are checked against SSRF: only `http` and `https` are allowed, every resolved IP must be public, and every
redirect is checked again (at most 5). To allow a feed on your LAN, turn on **Allow private / LAN feed hosts** in Settings.

## Walkthrough: follow Black Clover Season 2 by DKB

The fastest way is **Series > New**, type `Black Clover` in the AniList box and click **Use**: the name, cover and the 170-episode
first season are prefilled, and the related "Black Clover 2nd Season" entry can be added as season 2 with one click.
The manual steps below show what every field means.

The demo data already contains this setup. To create it yourself, use **Series > New** (the wizard previews the save path and lets you test the rule against recent releases before anything is saved):

1. **Series.** Name `Black Clover`; aliases `Black.Clover` and `Black_Clover`. The name is the folder name, after removing
   `/`, `\`, `..`, control characters and similar. Feed titles never become path components.
2. **Season.** Season number `2`, monitored. The computed save path appears right away:
   `/home/qbittorrent-nox/media/Black Clover/Season 02` (media base + series name + `Season {season:02d}`). You can
   override the path for the whole series or for one season. An override must be an absolute POSIX path.
3. **Rule.** Release group `DKB`, with "require `[DKB]` title prefix" on, resolution `1080p`, and the rule bound to
   season 2. Use **Simulate** to paste sample titles, or **Test recent** (on the series page) to run the rule against stored
   feed entries without side effects.
4. **Absolute numbering.** A title like `[DKB] Black Clover - S02E01 [1080p]` or `... Season 2 - 01` carries an explicit
   season and maps directly. A title without a season, such as `[DKB] Black Clover - 171`, is **rejected as ambiguous**
   unless a season has an **Absolute episode range** covering that number. The app never guesses a season from an absolute number.
   If the releases you want use absolute numbers, set the **Absolute episode range** min on season 2 to the absolute number of season 2
   episode 1 (for example `171`), and set the max if you know it. Then `171` becomes `S02E01` and `172` becomes
   `S02E02`. Check the feed preview to see which numbering the group actually uses.
5. **Monitor.** Turn **Monitored** on for the series. From the next poll, a new matching release is sent to qBittorrent
   with `savepath=/home/qbittorrent-nox/media/Black Clover/Season 02`.

A release from another group, another series or another season, or a seasonless title without a mapping, is rejected,
and the Match Inspector shows the reason.

![Series page](docs/screenshots/series.png)

## Seeing matching decisions

- **Releases** lists every stored feed entry with its outcome: `accepted`, `rejected`, `no_match`, `historical` or
  `duplicate`, plus a summary. You can filter by feed, outcome or text.
- **Match Inspector** (open a release) shows the parsed fields (group, season, episode, resolution, ...) and, for every rule,
  a table of checks with pass/fail and a detail. Examples: `group: DKB`,
  `season: absolute 171 -> season 2 episode 1`, `season: ambiguous: no absolute range mapping for episode 171`.
  **Re-evaluate** runs the rules again without sending anything.
- **Downloads** shows the submission status: `pending` (waiting for a retry), `submitted`, `exists` (already in
  qBittorrent, not added again), `path_mismatch` (qBittorrent reports a different save path) or `failed`. It also shows
  the qBittorrent state and progress, and offers retry, retry all failed, and refresh status.
- **Activity** is the event log: polls, accepts, duplicates, submissions and errors.

### Manual grab

Open a release and click **Grab**. The first step is a **preview** that shows the exact save path, category, magnet or
torrent URL and any duplicate or warnings. Nothing is sent until you confirm. If the release has no explicit season, you
choose the season and episode. To grab an episode that already has a download, use the explicit **force** option.

### Duplicate policy

The default `one_per_episode` allows at most one active download per (season, episode) and per infohash. Before every add,
the app checks qBittorrent by infohash. If a response was uncertain, for example a timeout after the add request was sent,
the next attempt checks qBittorrent first instead of adding the torrent again. Transient failures are retried with backoff
up to 8 times. `allow_upgrades` is minimal in this version: it only lets a manual grab replace a `failed` download.
Automatic upgrades are not implemented.

## Verification checklist

Do this once after setup. Steps 1 to 5 are a **dry run**: nothing is added to qBittorrent.

1. **qBittorrent:** Test Connection returns `ok`, a version and an API version. Read any warnings.
2. **Feed fetch:** On Feeds, click **Test URL** on the AnimeTosho URL. You should see a feed title, an entry count and sample
   entries with magnet or torrent links.
3. **Preview:** Use **Preview** on the feed, or check Releases after the first poll. Existing entries show as `historical`.
4. **Simulate the rule:** On the Black Clover rule, simulate `[DKB] Black Clover Season 2 - 01 [1080p]`. Expected result:
   matched, season 2, episode 1, save path `/home/qbittorrent-nox/media/Black Clover/Season 02`. Then simulate a
   different group (`[SubsPlease] Black Clover - 01 (1080p)`) and a seasonless `[DKB] Black Clover - 171` without an
   absolute range. Both should be rejected with a visible reason.
5. **Grab preview:** Open a release in Releases, ideally a real Black Clover entry, click **Grab** and stop at the preview.
   Check that the save path is exactly what you expect.
6. **Live test (only if you explicitly decide to add a real torrent):** Confirm the grab. In qBittorrent (WebUI or
   VueTorrent), find the torrent (tag `feedcatch`) and check that its save path is
   `/home/qbittorrent-nox/media/Black Clover/Season 02`. In Downloads, the status should be `submitted`, not `path_mismatch`.
   You can remove the test torrent yourself in qBittorrent; this app never removes torrents.
7. **Go live:** Turn **Monitored** on for Black Clover. New matching releases are now sent automatically. Watch Dashboard
   and Activity after the next poll.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| qBittorrent test: `403` | Host-header or CSRF validation, or an IP ban after failed logins. Add `host.docker.internal` (or the host name in your URL) to qBittorrent's **Server domains** and check the credentials. A ban clears after qBittorrent's ban timeout or a restart. |
| qBittorrent test: `401` ("login failed") | qBittorrent 5.x answers 401 for wrong credentials **and** for a rejected `Host` header (for example when the port in the URL differs from the WebUI port). Check the credentials first, then add the host name you use to **Server domains**. |
| qBittorrent test: connection refused or timeout | The container can't reach qBittorrent. Check that the WebUI listens on a non-loopback interface, that the port is right, and that the firewall allows the docker bridge. Test with `docker compose exec feedcatch python -c "import urllib.request;print(urllib.request.urlopen('http://host.docker.internal:8080/api/v2/app/version').status)"`. A `403` here still proves the host is reachable. |
| qBittorrent login `Fails.` | Wrong username or password. If they are set in `.env`, they override the UI. Edit `.env` and run `docker compose up -d`. |
| Feed rejected: private or non-public address | The SSRF guard. Turn on **Allow private / LAN feed hosts** in Settings (or `ALLOW_PRIVATE_FEED_HOSTS=true`) only for feeds you trust. |
| Feed status `error`, malformed XML (feedparser "bozo") | The feed returned HTML (an error page or Cloudflare) or invalid XML. Use **Test URL** to see the error, and open the URL in a browser. AnimeTosho may be down for a while; polling retries with backoff. |
| Release `rejected`: "ambiguous: no absolute range mapping" | The title has no season (for example `- 171`). Set an absolute range on the right season, or grab it manually and choose the season. |
| Download `path_mismatch` | qBittorrent reports a different save path. The torrent was still added. Check that qBittorrent isn't forcing a path (category, temp path still in progress, scripts), and compare the paths in the download's error detail. |
| Download stays `pending` | qBittorrent was unreachable or returned 5xx. Downloads are retried with backoff, or you can use **Retry**. Look in Activity for the error. |
| Nothing is grabbed | The series or season is unmonitored, the rule is disabled, the entries are `historical`, or there's a duplicate. The Match Inspector shows which. |
| Forgot the UI password | Set `APP_PASSWORD=<new>` in `.env` and run `docker compose up -d`. While it is set, it is the password. |
| Container exits: `/data is not writable` | See [Data directory permissions](#data-directory-permissions-linux-hosts). |

## Security notes

- Authentication is **on by default**. The session cookie is HttpOnly and SameSite=Lax, and it is `Secure` when the request
  uses https. Login attempts are rate-limited.
- Don't expose the UI directly to the internet. Keep it on a trusted LAN or VPN, or put it behind a reverse proxy with TLS.
- Behind a TLS-terminating reverse proxy, set `FORWARDED_ALLOW_IPS` in `.env` to the proxy's IP so the session cookie is marked `Secure` (uvicorn reads `X-Forwarded-Proto` only from trusted proxies). Use `*` only if port 8000 is unreachable except through the proxy.
  Use `APP_AUTH_DISABLED=true` only when something in front of the app already does authentication.
- Secrets: the qBittorrent password is encrypted with a key from `APP_SECRET_KEY` or from `./data/secret.key`, and the UI
  password is stored as a bcrypt hash. Neither appears in API responses or logs. Logs redact keys that look like
  passwords, secrets, tokens or cookies. `.env` contains secrets, so keep it out of version control (it is gitignored).
- The container runs as non-root, mounts only `./data`, and needs no access to media.

## Running tests locally

Backend (Python 3.12+ and [uv](https://docs.astral.sh/uv/)):

```bash
cd backend
uv sync --all-extras
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest -q
```

Frontend ([Bun](https://bun.sh) 1.x):

```bash
cd frontend
bun install --frozen-lockfile
bun run typecheck
bun run build        # writes the SPA into backend/app/static
```

Docker:

```bash
docker build -t feedcatch:local .
docker compose config
docker compose up -d && curl -s localhost:8000/healthz
```

For local development without Docker, run `scripts/dev.sh`. It starts the backend on :8000 with auth disabled and data in
`backend/.data`, and Vite on :5173, which proxies `/api` to the backend.

## Data and backup

All state is in `./data`:
- `app.db`: SQLite database (WAL mode), holding configuration, feed entries, decisions and downloads.
- `secret.key`: the encryption key, unless you use `APP_SECRET_KEY`.

To make a backup, stop the container and copy the directory:

```bash
docker compose stop && tar czf feedcatch-backup-$(date +%F).tgz data && docker compose start
```

Without `secret.key` (or the same `APP_SECRET_KEY`), the stored qBittorrent password can't be decrypted. You would then
have to enter it again.

## Upgrading

If you build from source:

```bash
git pull
docker compose up -d --build
```

If you run the published image (pin a `sha-*` or `X.Y.Z` tag instead of `latest` to control when you upgrade):

```bash
docker compose pull           # add -f docker-compose.ghcr.yml if you use that file
docker compose up -d
```

Database migrations run automatically at startup. Back up `./data` before upgrading.

## Project layout

- `backend/` FastAPI + SQLAlchemy + SQLite + APScheduler (Python 3.12+, managed with uv). Tests with pytest and respx.
- `frontend/` React + Vite + TypeScript single-page app, built into `backend/app/static` and served by the backend.
- `Dockerfile`, `docker-compose.yml`, `.env.example` for the one-container deployment.
- `docs/requirements.md` the original specification this project was built from.

## Status

Working MVP. Verified end to end against the live AnimeTosho feed and qBittorrent v5.2.4: rule match, deduplication,
manual and automatic grabs, and the exact save path showing up in qBittorrent. Automatic quality upgrades and
Postgres are not implemented. Issues and pull requests are welcome.


## License

MIT, see [LICENSE](LICENSE).

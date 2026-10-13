# Safety invariants (hard constraints; tests must cover these)

1. **No media filesystem access.** The app never reads, writes, creates, moves, renames or deletes anything under the media base path.
   Save paths are strings handed to qBittorrent only. The compose file does not mount the media dir. No `os.makedirs`, `shutil`,
   `Path(...).mkdir` or any filesystem call on user- or feed-derived paths in `app/services/paths.py`, `dispatcher.py`, `poller.py`.
2. **Never send NZB links to qBittorrent.** Only `magnet:` URLs, or http(s) URLs whose path ends in `.torrent`, or enclosures typed
   `application/x-bittorrent`. NZB-only entries are stored and shown with reason "no torrent/magnet link (NZB-only)". Prefer magnet over .torrent.
3. **Path safety.** Path components come from `series.name`, the season folder format, and user overrides. Never from feed titles.
   `sanitize_component`: NFC-normalize, strip control chars (< 0x20, 0x7f), replace `/` and `\` with `-`, remove `<>:"|?*`, collapse whitespace,
   strip leading/trailing spaces and dots; reject empty, `.`, `..` (raise `PathError`). Overrides must be absolute posix paths, no `..` segment,
   no control chars, no backslash. Season folder format supports only tokens `{season}`, `{season:02d}`, `{season:03d}`, `{series}`;
   any other `{...}` -> validation error. Never call `str.format` on a user template. Build with `posixpath.join`; assert
   `posixpath.normpath(result) == result.rstrip('/') or result == '/'` and, without override, that it starts with `base + '/'`.
4. **Secrets.** qBittorrent password stored Fernet-encrypted; the API only ever returns `password_set: bool`. Structlog redaction processor masks
   values of any key matching `/pass|secret|token|cookie|authorization/i` (recursively in dicts). Never log request bodies of auth/qbit endpoints.
   No credentials in repo, tests use obviously fake values. `.env.example` has empty secrets.
5. **SSRF.** Feed URLs: http/https only; hostname resolved via `socket.getaddrinfo`; every resolved IP must be global
   (`ipaddress.ip_address(x).is_global`, which rejects private, loopback, link-local, multicast, reserved, unspecified)
   unless setting `allow_private_feed_hosts` is true. httpx `follow_redirects=False`; follow manually (max 5) re-validating each `Location`.
   The qBittorrent URL is admin-configured and exempt (it is expected to be private, e.g. host.docker.internal).
6. **qBittorrent owns torrents.** Never call `torrents/delete`, `torrents/setLocation`, `torrents/rename*`, `torrents/pause|stop|resume|start`
   on existing torrents. Only: `auth/login`, `auth/logout`, `app/version`, `app/webapiVersion`, `app/preferences`, `torrents/add`, `torrents/info`,
   `torrents/categories`.
7. **No duplicate submissions.** Before any add: check by infohash in DB and in qBittorrent. Uncertain responses never trigger a blind re-add.
8. **No historical auto-grab** unless `feed.backfill_mode == 'process'`. Manual grab of a historical entry is allowed (explicit user action with preview + confirm).
9. **Single worker.** `uvicorn --workers 1`; APScheduler jobs `max_instances=1, coalesce=True`; per-feed `threading.Lock`.
10. **Regex is Python `re` only.** Validate at save time with `re.compile`; surface the error message. Do not advertise PCRE features.

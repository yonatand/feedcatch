---
name: live-smoke-test
description: Procedure to verify the built Docker image end to end against the real AnimeTosho feed and a throwaway real qBittorrent container (login, add with savepath, dedupe, manual grab), as done on 2026-10-13. Use after any change to feeds.py, qbit.py, dispatcher.py, poller.py or the Dockerfile.
---

# Live smoke test (real feed + throwaway qBittorrent)

Takes ~5 minutes. Nothing touches real media; the throwaway qBittorrent has no media mount and torrents are added stopped.

```bash
# 1. network + throwaway qBittorrent (official image; temp password is printed in its log)
docker network create feedcatch-net 2>/dev/null
docker run -d --name qbit-smoke --network feedcatch-net -p 18080:8080 -e QBT_WEBUI_PORT=8080 -e QBT_LEGAL_NOTICE=confirm qbittorrentofficial/qbittorrent-nox:latest
sleep 12; docker logs qbit-smoke 2>&1 | grep -i "temporary password"     # -> PW

# 2. build + run the app on the same network (no volume: fresh DB each run)
docker build -t feedcatch:local .
docker rm -f feedcatch-smoke 2>/dev/null
docker run -d --name feedcatch-smoke --network feedcatch-net -p 8001:8000 -e APP_AUTH_DISABLED=true feedcatch:local
sleep 14   # scheduler does the first (historical) poll ~10s after start
B=localhost:8001; J='Content-Type: application/json'

# 3. qBittorrent config + test (expect ok=true, version v5.x, category warning)
curl -s -X PUT -H "$J" -d '{"url":"http://qbit-smoke:8080","username":"admin","password":"<PW>","category":"anime","timeout_seconds":15,"start_immediately":false,"poll_status":true}' $B/api/qbit
curl -s -X POST $B/api/qbit/test

# 4. manual grab of a stored Black Clover entry: preview (confirm:false) must show
#    save_path=/home/qbittorrent-nox/media/Black Clover/Season 02; then confirm:true -> status submitted
EID=$(curl -s "$B/api/entries?q=Black%20Clover" | python -I -c "import sys,json;print(json.load(sys.stdin)['items'][0]['id'])")
curl -s -X POST -H "$J" -d '{"season_id":1,"episode_number":2,"force":false,"confirm":false}' $B/api/entries/$EID/grab
curl -s -X POST -H "$J" -d '{"season_id":1,"episode_number":2,"force":false,"confirm":true}'  $B/api/entries/$EID/grab

# 5. automatic flow: monitor the series, add a rule for a group present in the feed, add a feed with backfill=process
#    (a URL query variant keeps the unique-url constraint happy), poll -> accepted/duplicate counts, downloads submitted
curl -s -X PUT -H "$J" -d '{"name":"Black Clover","aliases":["Black.Clover","Black_Clover","Black Clover (2017)"],"monitored":true,"season_folder_format":"Season {season:02d}","path_override":null,"category_override":null}' $B/api/series/1
curl -s -X POST -H "$J" -d '{"series_id":1,"season_id":1,"name":"Buzz-Subs 1080p","enabled":true,"priority":5,"release_group":"Buzz-Subs","require_group_prefix":true,"include_keywords":[],"exclude_keywords":[],"resolutions":["1080p"],"sources":[],"codecs":[],"language_keywords":[],"min_size_mb":null,"max_size_mb":null,"regex":null}' $B/api/rules
curl -s -X POST -H "$J" -d '{"name":"backfill test","url":"https://feed.animetosho.net/rss2?src=auto","enabled":true,"poll_interval_minutes":15,"backfill_mode":"process"}' $B/api/feeds
curl -s -X POST $B/api/feeds/2/poll; curl -s $B/api/downloads

# 6. verify inside qBittorrent (Host header must match the WebUI port, see qbittorrent-api skill)
curl -s -c qb.txt -X POST -H 'Host: localhost:8080' -d 'username=admin&password=<PW>' http://localhost:18080/api/v2/auth/login -o /dev/null
curl -s -b qb.txt -H 'Host: localhost:8080' http://localhost:18080/api/v2/torrents/info   # save_path, category=anime, auto_tmm=false, state stoppedDL

# 7. cleanup
docker rm -f feedcatch-smoke qbit-smoke; docker network rm feedcatch-net
```

## Expected results (observed 2026-10-13, qBittorrent v5.2.4 / API 2.15.1, feed with 75 items)
- First poll: all entries `historical`, nothing sent. Manual grab preview warns "historical" and "Series is not monitored" but still shows the exact path.
- Confirmed grab -> `submitted`, `qbit_save_path` identical to `save_path`, state `stoppedDL`; re-grab -> `exists` (no second add).
- Backfill feed poll -> `accepted 1, duplicate 1` (episode already present -> "duplicate of download #1"), activity log has `entry_accepted`, `download_submitted`, `entry_duplicate`, `feed_poll` events.
- Entries whose series name differs (e.g. `Black Clover (2017)`) need an alias; the inspector shows `series` failing.

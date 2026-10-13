---
name: animetosho-feed
description: Observed structure of the live AnimeTosho RSS2 feed (https://feed.animetosho.net/rss2) as of 2026-10-13, plus the real fixture file to test against. Read before touching app/services/feeds.py or writing feed tests.
---

# AnimeTosho RSS2 feed facts (observed live 2026-10-13)

Fixture: `backend/tests/fixtures/animetosho_rss2_sample.xml` (9 real items trimmed from a 75-item live response, ~29 KB).

## Response
- `Content-Type: application/rss+xml; charset=utf-8`, ~190 KB for 75 items, `Cache-Control: public`, **`last-modified` header present, no ETag**.
  So conditional GET must send `If-Modified-Since` (and `If-None-Match` only when an ETag was seen). Whether the server honors it with 304 is unverified; handle both 200 and 304.
- `<rss version="2.0">` with `<ttl>30</ttl>`, `<lastBuildDate>`.

## Item structure
```xml
<item>
  <title>[DKB] Psyren - S01E02 [1080p][HEVC x265 10bit][Multi-Subs][weekly]</title>
  <description><![CDATA[<p>Source: <a href="https://nyaa.si/view/...">Nyaa.si</a></p><p>Total Size: 820.3 MiB</p>
    <p>Download Links: <a href="https://storage.animetosho.net/.../xxx.torrent?filename=...">Torrent</a> | <a href="magnet:?xt=urn:btih:HEX40&amp;dn=...&amp;tr=...">Magnet</a>
    | <a href="https://feed.animetosho.net/nzb/696632">NZB</a> | <a href="https://fileditchvids.st/...">FileDitch</a> | <a href="https://zerofs.link/...">ZeroFS</a></p>]]></description>
  <link>https://animetosho.net/view/696633</link>
  <comments>https://animetosho.net/view/696633</comments>
  <enclosure url="https://storage.animetosho.net/.../xxx.torrent?filename=..." type="application/x-bittorrent" length="860187480"/>
  <enclosure url="https://feed.animetosho.net/nzb/696632" type="application/x-nzb" length="860198347"/>   <!-- present on ~90% of items -->
  <source url="https://nyaa.si/view/2173451">Nyaa.si</source>
  <category>Anime</category>            <!-- text category; this is why Torznab parsing failed -->
  <pubDate>Tue, 13 Oct 2026 13:11:38 +0000</pubDate>
  <guid isPermaLink="true">https://animetosho.net/view/696633</guid>
</item>
```

## Extraction rules for feeds.py
- guid: `<guid>` text (permalink URL). Fallback: `<link>`, then sha1 of title+pubDate.
- magnet: first `href="magnet:?..."` in description HTML (feedparser puts it in `entry.summary` / `entry.description`; `&amp;` already decoded to `&` by feedparser? Verify: feedparser returns the CDATA HTML with `&amp;` still encoded inside attributes; unescape with `html.unescape` before regex). Also accept `entry.link` if it starts with `magnet:` (other feeds).
- torrent url: enclosure with `type == "application/x-bittorrent"` or href ending with `.torrent` (before `?`), or an `<a>` in description whose href path ends with `.torrent`.
- nzb url: enclosure typed `application/x-nzb` or href containing `/nzb/` -> store in `nzb_url`, never dispatched.
- size: torrent enclosure `length` (bytes) preferred; fallback parse `Total Size: 820.3 MiB` (units B/KiB/MiB/GiB/TiB, also KB/MB/GB) from description.
- infohash: `xt=urn:btih:` from magnet (hex or base32) else the 40-hex segment in the storage torrent URL (`/torrents/594/b3280a...torrent` -> note the hash is split: first 3 hex chars are the directory, remaining 37 the filename; join dir + stem). Prefer the magnet.
- published: `pubDate` via feedparser `published_parsed` -> aware UTC.
- Title quirks: AnimeTosho may append ` | <alternate title>` to the torrent name; the parser strips a trailing ` | ...` segment before parsing. The `dn=` in the magnet equals the title.

## Other feeds to tolerate (generic RSS2/Atom)
- Nyaa RSS: `<link>` is the .torrent URL, `<nyaa:infoHash>`, `<nyaa:size>`, `<guid>` view URL. Treat any `<link>` ending in `.torrent` as the torrent URL. Unknown namespaces are fine; feedparser exposes them as `entry['nyaa_infohash']`.
- Atom: `entry.links` with `rel=enclosure`. Magnet in `entry.link` or `entry.content[0].value`.

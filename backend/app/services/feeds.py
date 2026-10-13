"""Feed fetching (SSRF-safe, conditional GET, size-capped) and RSS2/Atom entry extraction.

Safety invariant 2: an NZB URL is never chosen as `torrent_url`.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import html
import re
from calendar import timegm
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import feedparser
import httpx

from app import __version__
from app.services import ssrf
from app.services.parser import parse_title
from app.services.types import ParsedRelease

DEFAULT_USER_AGENT = f"feedcatch/{__version__}"
MAX_FEED_BYTES = ssrf.MAX_BYTES

_DOCTYPE_RE = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)
_HREF_RE = re.compile(r"""href\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)
_TOTAL_SIZE_RE = re.compile(r"Total\s+Size:\s*([\d.,]+)\s*([KMGT]i?B|B|bytes)\b", re.IGNORECASE)
_SIZE_RE = re.compile(r"^\s*([\d.,]+)\s*([KMGT]i?B|B|bytes)\s*$", re.IGNORECASE)
_BTIH_HEX_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_BTIH_B32_RE = re.compile(r"^[A-Za-z2-7]{32}$")
_STORAGE_HASH_RE = re.compile(r"/([0-9a-fA-F]{3})/([0-9a-fA-F]{37})\.torrent$")
_TAG_RE = re.compile(r"<[^>]+>")
_UNITS = {
    "b": 1,
    "bytes": 1,
    "kb": 1000,
    "mb": 1000**2,
    "gb": 1000**3,
    "tb": 1000**4,
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
}
NZB_TYPES = {"application/x-nzb", "application/nzb"}
TORRENT_TYPE = "application/x-bittorrent"


class FeedFetchError(Exception):
    """Fetching or parsing a feed failed. `transient` = worth retrying later (timeouts, 5xx...)."""

    def __init__(self, message: str, transient: bool) -> None:
        super().__init__(message)
        self.transient = transient


@dataclass
class ParsedEntry:
    guid: str
    title: str
    link: str | None
    published_at: datetime | None
    magnet_url: str | None
    torrent_url: str | None
    nzb_url: str | None
    size_bytes: int | None
    infohash: str | None
    parsed: ParsedRelease


@dataclass
class FetchResult:
    status: int
    not_modified: bool
    feed_title: str | None
    entries: list[ParsedEntry] = field(default_factory=list)
    etag: str | None = None
    last_modified: str | None = None


# ---------------------------------------------------------------- helpers


def _url_path(url: str) -> str:
    try:
        return urlsplit(url).path
    except ValueError:
        return ""


def _is_http(url: str) -> bool:
    return url.lower().startswith(("http://", "https://"))


def is_nzb_url(url: str, mime: str | None = None) -> bool:
    if mime and mime.lower().split(";")[0].strip() in NZB_TYPES:
        return True
    path = _url_path(url).lower()
    return "/nzb/" in path or path.endswith(".nzb")


def is_torrent_url(url: str, mime: str | None = None) -> bool:
    """http(s) URL whose path ends in `.torrent`, or typed application/x-bittorrent; never an NZB."""
    if not _is_http(url) or is_nzb_url(url, mime):
        return False
    if mime and mime.lower().split(";")[0].strip() == TORRENT_TYPE:
        return True
    return _url_path(url).lower().endswith(".torrent")


def infohash_from_magnet(magnet: str) -> str | None:
    try:
        query = urlsplit(magnet).query
    except ValueError:
        return None
    for xt in parse_qs(query).get("xt", []):
        if not xt.lower().startswith("urn:btih:"):
            continue
        value = xt[9:]
        if _BTIH_HEX_RE.match(value):
            return value.lower()
        if _BTIH_B32_RE.match(value):
            try:
                return base64.b32decode(value.upper()).hex()
            except (binascii.Error, ValueError):
                return None
    return None


def infohash_from_torrent_url(url: str) -> str | None:
    m = _STORAGE_HASH_RE.search(_url_path(url))
    if m:
        return (m.group(1) + m.group(2)).lower()
    return None


def parse_size(text: str) -> int | None:
    m = _SIZE_RE.match(text)
    if not m:
        return None
    return _size_from(m.group(1), m.group(2))


def _size_from(number: str, unit: str) -> int | None:
    try:
        value = float(number.replace(",", ""))
    except ValueError:
        return None
    mult = _UNITS.get(unit.lower())
    if mult is None:
        return None
    return int(value * mult)


def _hrefs(fragment: str) -> list[str]:
    out: list[str] = []
    for m in _HREF_RE.finditer(fragment or ""):
        href = html.unescape(m.group(1) if m.group(1) is not None else m.group(2)).strip()
        if href:
            out.append(href)
    return out


def _published(e: Any) -> datetime | None:
    t = e.get("published_parsed") or e.get("updated_parsed")
    if not t:
        return None
    try:
        return datetime.fromtimestamp(timegm(t), tz=UTC)
    except (OverflowError, ValueError, TypeError):
        return None


def _int_or_none(v: Any) -> int | None:
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


# ---------------------------------------------------------------- extraction


def _extract(e: Any) -> ParsedEntry:
    title = " ".join(str(e.get("title") or "").split())
    link = e.get("link") or None
    html_parts: list[str] = [str(e.get("summary") or e.get("description") or "")]
    for c in e.get("content") or []:
        html_parts.append(str(c.get("value") or ""))
    desc_html = "\n".join(html_parts)
    desc_hrefs = _hrefs(desc_html)

    # Enclosures: feedparser exposes them in `enclosures` and as links with rel=enclosure.
    enclosures: list[tuple[str, str | None, int | None]] = []
    seen: set[str] = set()
    for enc in list(e.get("enclosures") or []) + [ln for ln in (e.get("links") or []) if ln.get("rel") == "enclosure"]:
        href = str(enc.get("href") or "").strip()
        if not href or href in seen:
            continue
        seen.add(href)
        enclosures.append((href, enc.get("type"), _int_or_none(enc.get("length"))))
    other_links = [str(ln.get("href") or "") for ln in (e.get("links") or []) if ln.get("rel") != "enclosure"]

    # magnet
    magnet: str | None = None
    for cand in [*desc_hrefs, *(link and [link] or []), *other_links, *(h for h, _, _ in enclosures)]:
        if cand.lower().startswith("magnet:?"):
            magnet = cand
            break

    # torrent url (never NZB)
    torrent_url: str | None = None
    size: int | None = None
    for href, mime, length in enclosures:
        if is_torrent_url(href, mime):
            torrent_url = href
            size = length
            break
    if torrent_url is None:
        for cand in [*(link and [link] or []), *other_links, *desc_hrefs]:
            if is_torrent_url(cand):
                torrent_url = cand
                break

    # nzb (stored, never dispatched)
    nzb_url: str | None = None
    for href, mime, _ in enclosures:
        if is_nzb_url(href, mime):
            nzb_url = href
            break
    if nzb_url is None:
        nzb_url = next((h for h in desc_hrefs if _is_http(h) and is_nzb_url(h)), None)

    # size fallbacks
    if size is None:
        nyaa_size = e.get("nyaa_size")
        if nyaa_size:
            size = parse_size(str(nyaa_size))
    if size is None:
        text = html.unescape(_TAG_RE.sub(" ", desc_html))
        m = _TOTAL_SIZE_RE.search(text)
        if m:
            size = _size_from(m.group(1), m.group(2))

    # infohash: magnet > nyaa:infoHash > storage torrent URL
    infohash = infohash_from_magnet(magnet) if magnet else None
    if infohash is None:
        nyaa_hash = str(e.get("nyaa_infohash") or "").strip()
        if _BTIH_HEX_RE.match(nyaa_hash):
            infohash = nyaa_hash.lower()
    if infohash is None and torrent_url:
        infohash = infohash_from_torrent_url(torrent_url)

    published = _published(e)
    guid = str(e.get("id") or "").strip() or (link or "").strip()
    if not guid:
        guid = "sha1:" + hashlib.sha1(f"{title}|{e.get('published') or ''}".encode()).hexdigest()

    return ParsedEntry(
        guid=guid[:1024],
        title=title,
        link=link,
        published_at=published,
        magnet_url=magnet,
        torrent_url=torrent_url,
        nzb_url=nzb_url,
        size_bytes=size,
        infohash=infohash,
        parsed=parse_title(title),
    )


def parse_feed_bytes(data: bytes, content_type: str | None) -> tuple[str | None, list[ParsedEntry]]:
    """Parse RSS2/Atom bytes. Raises FeedFetchError(transient=False) for invalid/unsafe XML."""
    if _DOCTYPE_RE.search(data):
        raise FeedFetchError("invalid feed: DOCTYPE/ENTITY declarations are not allowed", transient=False)
    parsed = feedparser.parse(data, response_headers={"content-type": content_type or "application/xml"})
    entries = list(parsed.get("entries") or [])
    if parsed.get("bozo") and not entries:
        exc = parsed.get("bozo_exception")
        raise FeedFetchError(f"invalid feed: {exc or 'could not parse XML'}", transient=False)
    if not entries and not parsed.get("version"):
        raise FeedFetchError("invalid feed: not an RSS or Atom document", transient=False)
    title = (parsed.get("feed") or {}).get("title") or None
    out = [_extract(e) for e in entries if (e.get("title") or "").strip()]
    return title, out


def fetch_feed(
    url: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    timeout: float = 20,
    allow_private: bool = False,
    user_agent: str | None = None,
    max_bytes: int = MAX_FEED_BYTES,
) -> FetchResult:
    """Fetch and parse a feed with conditional GET. Raises FeedFetchError."""
    headers = {
        "User-Agent": user_agent or DEFAULT_USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5",
    }
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout), follow_redirects=False) as client:
            status, resp_headers, body = ssrf.fetch_with_safe_redirects(
                client, url, headers, allow_private, max_bytes=max_bytes
            )
    except ssrf.SsrfError as exc:
        raise FeedFetchError(f"URL not allowed: {exc}", transient=False) from exc
    except ssrf.ResponseTooLargeError as exc:
        raise FeedFetchError(str(exc), transient=False) from exc
    except httpx.TimeoutException as exc:
        raise FeedFetchError(f"timeout fetching feed after {timeout}s", transient=True) from exc
    except httpx.HTTPError as exc:
        raise FeedFetchError(f"network error fetching feed: {exc.__class__.__name__}: {exc}", transient=True) from exc

    new_etag = resp_headers.get("etag") or etag
    new_lm = resp_headers.get("last-modified") or last_modified
    if status == 304:
        return FetchResult(status=304, not_modified=True, feed_title=None, etag=new_etag, last_modified=new_lm)
    if status >= 400:
        transient = status >= 500 or status in (408, 429)
        raise FeedFetchError(f"feed returned HTTP {status}", transient=transient)
    if status != 200:
        raise FeedFetchError(f"unexpected HTTP status {status}", transient=False)
    title, entries = parse_feed_bytes(body, resp_headers.get("content-type"))
    return FetchResult(
        status=status,
        not_modified=False,
        feed_title=title,
        entries=entries,
        etag=resp_headers.get("etag"),
        last_modified=resp_headers.get("last-modified"),
    )

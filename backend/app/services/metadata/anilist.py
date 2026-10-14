"""AniList GraphQL client + the `anilist` metadata provider (anime), with Jikan as a best-effort episode-title fallback.

See `.claude/rules/anilist.md`, `.claude/rules/metadata.md`, `.claude/rules/episodes.md`. Fixed hosts (no SSRF check
needed), explicit timeouts, a small module-level TTL cache so repeated UI keystrokes do not burn AniList's 30
requests/minute budget.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from app import __version__
from app.services.metadata.base import (
    EpisodeInfo,
    Kind,
    MediaDetail,
    MediaResult,
    MetadataError,
    RelatedInfo,
    SeasonInfo,
)

log = structlog.get_logger("anilist")

ANILIST_URL = "https://graphql.anilist.co"
CACHE_TTL_SECONDS = 600.0
CACHE_MAX_KEYS = 500
DEFAULT_RETRY_AFTER = 60
MAX_SEARCH_LIMIT = 50

_MEDIA_FIELDS = (
    "id title{romaji english native} synonyms format status season seasonYear episodes "
    "coverImage{medium large} siteUrl startDate{year month day} "
    "relations{edges{relationType node{id title{romaji english} format episodes seasonYear status}}}"
)
SEARCH_QUERY = (
    "query ($q: String, $limit: Int) { Page(perPage: $limit) { "
    f"media(search: $q, type: ANIME, sort: SEARCH_MATCH) {{ {_MEDIA_FIELDS} }} }} }}"
)
DETAIL_QUERY = f"query ($id: Int) {{ Media(id: $id, type: ANIME) {{ {_MEDIA_FIELDS} }} }}"
EPISODES_QUERY = (
    "query ($id: Int, $page: Int) { Media(id: $id, type: ANIME) { id episodes idMal status "
    "nextAiringEpisode{episode airingAt} airingSchedule(page: $page, perPage: 50){ pageInfo{hasNextPage} "
    "nodes{episode airingAt} } streamingEpisodes{title site url} } }"
)
MAX_AIRING_PAGES = 12
_STREAMING_TITLE = re.compile(r"^Episode\s+(\d+)\s*[-:]\s*(.+)$")

JIKAN_URL = "https://api.jikan.moe/v4/anime/{mal_id}/episodes"
JIKAN_TIMEOUT_SECONDS = 8.0  # read
JIKAN_CONNECT_TIMEOUT_SECONDS = 3.0
JIKAN_BACKOFF_SECONDS = 6 * 3600.0  # skip Jikan for 6 h after any failure (episodes.md, fixes 2026-10-14)
JIKAN_MAX_PAGES = 5
JIKAN_PAGE_DELAY_SECONDS = 0.4  # tests set 0

RELATED_TYPES = frozenset({"SEQUEL", "PREQUEL", "PARENT", "SIDE_STORY", "ALTERNATIVE"})
RELATED_FORMATS = frozenset({"TV", "TV_SHORT", "ONA", "OVA", "MOVIE", "SPECIAL"})
_SERIAL_FORMATS = frozenset({"TV", "TV_SHORT", "ONA"})


class AnilistError(MetadataError):
    """AniList call failed. `transient` = worth retrying later; `retry_after` set on 429; `not_found` on unknown id."""

    def __init__(
        self, message: str, transient: bool = False, retry_after: int | None = None, not_found: bool = False
    ) -> None:
        super().__init__(message, transient=transient, retry_after=retry_after, not_found=not_found)


# ---------------------------------------------------------------- data


@dataclass(frozen=True)
class AnilistRelated:
    relation_type: str
    id: int
    title_romaji: str | None
    title_english: str | None
    format: str | None
    episodes: int | None
    season_year: int | None
    status: str | None


@dataclass(frozen=True)
class AnilistMedia:
    id: int
    title_romaji: str | None
    title_english: str | None
    title_native: str | None
    synonyms: list[str]
    format: str | None
    status: str | None
    season: str | None
    season_year: int | None
    episodes: int | None
    cover_medium: str | None
    cover_large: str | None
    site_url: str | None
    start_date: str | None = None  # YYYY-MM-DD (YYYY-MM / YYYY when partial)


@dataclass(frozen=True)
class AnilistMediaDetail(AnilistMedia):
    related: list[AnilistRelated] = field(default_factory=list)


def _str(v: Any) -> str | None:
    return v.strip() or None if isinstance(v, str) else None


def _int(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _date(raw: Any) -> str | None:
    if not isinstance(raw, dict):
        return None
    y, m, d = _int(raw.get("year")), _int(raw.get("month")), _int(raw.get("day"))
    if y is None:
        return None
    out = f"{y:04d}"
    if m is not None:
        out += f"-{m:02d}"
        if d is not None:
            out += f"-{d:02d}"
    return out


def parse_media(raw: dict[str, Any]) -> AnilistMediaDetail:
    """Map one GraphQL `Media` object to an `AnilistMediaDetail` (all relation edges kept)."""
    if not isinstance(raw, dict) or _int(raw.get("id")) is None:
        raise AnilistError("unexpected AniList response (media without id)")
    title = raw.get("title") or {}
    cover = raw.get("coverImage") or {}
    related: list[AnilistRelated] = []
    for edge in (raw.get("relations") or {}).get("edges") or []:
        node = (edge or {}).get("node") or {}
        node_id = _int(node.get("id"))
        if node_id is None:
            continue
        ntitle = node.get("title") or {}
        related.append(
            AnilistRelated(
                relation_type=_str(edge.get("relationType")) or "OTHER",
                id=node_id,
                title_romaji=_str(ntitle.get("romaji")),
                title_english=_str(ntitle.get("english")),
                format=_str(node.get("format")),
                episodes=_int(node.get("episodes")),
                season_year=_int(node.get("seasonYear")),
                status=_str(node.get("status")),
            )
        )
    synonyms = [s for s in (_str(x) for x in raw.get("synonyms") or []) if s]
    return AnilistMediaDetail(
        id=int(raw["id"]),
        title_romaji=_str(title.get("romaji")),
        title_english=_str(title.get("english")),
        title_native=_str(title.get("native")),
        synonyms=synonyms,
        format=_str(raw.get("format")),
        status=_str(raw.get("status")),
        season=_str(raw.get("season")),
        season_year=_int(raw.get("seasonYear")),
        episodes=_int(raw.get("episodes")),
        cover_medium=_str(cover.get("medium")),
        cover_large=_str(cover.get("large")),
        site_url=_str(raw.get("siteUrl")),
        start_date=_date(raw.get("startDate")),
        related=related,
    )


def as_media(detail: AnilistMediaDetail) -> AnilistMedia:
    """Drop `related` (search results are plain media)."""
    return AnilistMedia(**{f: getattr(detail, f) for f in AnilistMedia.__dataclass_fields__})


# ---------------------------------------------------------------- cache

_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def _now() -> float:
    return time.monotonic()


def _cache_get(key: str) -> Any | None:
    with _cache_lock:
        hit = _cache.get(key)
        if hit is None:
            return None
        expires, value = hit
        if expires <= _now():
            del _cache[key]
            return None
        return value


def _cache_put(key: str, value: Any) -> None:
    with _cache_lock:
        now = _now()
        if key not in _cache and len(_cache) >= CACHE_MAX_KEYS:
            for k in [k for k, (exp, _) in _cache.items() if exp <= now]:
                del _cache[k]
            while len(_cache) >= CACHE_MAX_KEYS:  # evict the oldest insertion
                del _cache[next(iter(_cache))]
        _cache[key] = (now + CACHE_TTL_SECONDS, value)


def clear_cache() -> None:
    """Empty the TTL cache (tests)."""
    with _cache_lock:
        _cache.clear()


def cache_size() -> int:
    with _cache_lock:
        return len(_cache)


# ---------------------------------------------------------------- client


def _retry_after(resp: httpx.Response) -> int:
    raw = resp.headers.get("Retry-After", "")
    try:
        return max(1, int(float(raw)))
    except ValueError:
        return DEFAULT_RETRY_AFTER


def _graphql_not_found(errors: Any) -> bool:
    for err in errors if isinstance(errors, list) else []:
        if not isinstance(err, dict):
            continue
        if err.get("status") == 404 or str(err.get("message", "")).lower().startswith("not found"):
            return True
    return False


def _first_error(errors: Any) -> str:
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        return str(errors[0].get("message", "unknown error"))[:200]
    return "unknown error"


class AnilistClient:
    def __init__(self, timeout: float = 10.0, transport: httpx.BaseTransport | None = None) -> None:
        self.timeout = timeout
        self._transport = transport

    def _post(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"feedcatch/{__version__}",
        }
        try:
            with httpx.Client(
                timeout=httpx.Timeout(self.timeout), follow_redirects=False, transport=self._transport
            ) as client:
                resp = client.post(ANILIST_URL, json={"query": query, "variables": variables}, headers=headers)
        except httpx.TimeoutException as exc:
            raise AnilistError("AniList timed out", transient=True) from exc
        except httpx.HTTPError as exc:
            raise AnilistError(f"AniList unreachable: {type(exc).__name__}", transient=True) from exc

        remaining = resp.headers.get("X-RateLimit-Remaining")
        if remaining is not None:
            log.debug("anilist_request", status=resp.status_code, ratelimit_remaining=remaining)
        if resp.status_code == 429:
            retry = _retry_after(resp)
            log.warning("anilist_rate_limited", retry_after=retry)
            raise AnilistError(f"AniList rate limit, retry in {retry} s", transient=True, retry_after=retry)

        body: Any
        try:
            body = resp.json()
        except ValueError:
            body = None
        errors = body.get("errors") if isinstance(body, dict) else None
        if resp.status_code == 404 or _graphql_not_found(errors):
            raise AnilistError("AniList entry not found", not_found=True)
        if resp.status_code >= 500:
            raise AnilistError(f"AniList HTTP {resp.status_code}", transient=True)
        if resp.status_code >= 400:
            detail = _first_error(errors) if errors else f"HTTP {resp.status_code}"
            raise AnilistError(f"AniList rejected the request: {detail}")
        if not isinstance(body, dict) or not isinstance(body.get("data"), dict):
            if errors:
                raise AnilistError(f"AniList error: {_first_error(errors)}")
            raise AnilistError("unexpected AniList response")
        if errors:
            raise AnilistError(f"AniList error: {_first_error(errors)}")
        data: dict[str, Any] = body["data"]
        return data

    def search(self, q: str, limit: int = 10) -> list[AnilistMedia]:
        q = " ".join(q.split())
        limit = max(1, min(int(limit), MAX_SEARCH_LIMIT))
        key = f"search:{limit}:{q.casefold()}"
        cached = _cache_get(key)
        if cached is not None:
            return list(cached)
        data = self._post(SEARCH_QUERY, {"q": q, "limit": limit})
        raw_items = ((data.get("Page") or {}).get("media")) or []
        details = [parse_media(m) for m in raw_items if isinstance(m, dict)]
        for d in details:  # a later "Use" click (suggest) then costs no extra request
            _cache_put(f"media:{d.id}", d)
        items = [as_media(d) for d in details]
        _cache_put(key, items)
        return list(items)

    def get(self, anilist_id: int) -> AnilistMediaDetail:
        key = f"media:{int(anilist_id)}"
        cached = _cache_get(key)
        if cached is not None:
            detail: AnilistMediaDetail = cached
            return detail
        data = self._post(DETAIL_QUERY, {"id": int(anilist_id)})
        raw = data.get("Media")
        if raw is None:
            raise AnilistError("AniList entry not found", not_found=True)
        detail = parse_media(raw)
        _cache_put(key, detail)
        return detail

    def episodes(self, anilist_id: int) -> dict[str, Any]:
        """`{episodes, idMal, status, airing: {ep: airingAt}, titles: {ep: title}}`.

        airingSchedule is paginated (max 12 pages); titles come from `streamingEpisodes` ("Episode 3 - Title").
        """
        key = f"episodes:{int(anilist_id)}"
        cached = _cache_get(key)
        if cached is not None:
            return dict(cached)
        airing: dict[int, int] = {}
        titles: dict[int, str] = {}
        media: dict[str, Any] = {}
        for page in range(1, MAX_AIRING_PAGES + 1):
            data = self._post(EPISODES_QUERY, {"id": int(anilist_id), "page": page})
            raw = data.get("Media")
            if raw is None:
                raise AnilistError("AniList entry not found", not_found=True)
            if page == 1:
                media = raw
                for se in raw.get("streamingEpisodes") or []:
                    m = _STREAMING_TITLE.match(str((se or {}).get("title") or "").strip())
                    if m:
                        titles.setdefault(int(m.group(1)), m.group(2).strip())
            sched = raw.get("airingSchedule") or {}
            for node in sched.get("nodes") or []:
                ep, at = _int((node or {}).get("episode")), _int((node or {}).get("airingAt"))
                if ep is not None and at is not None:
                    airing[ep] = at
            if not (sched.get("pageInfo") or {}).get("hasNextPage"):
                break
        out = {
            "episodes": _int(media.get("episodes")),
            "idMal": _int(media.get("idMal")),
            "status": _str(media.get("status")),
            "airing": airing,
            "titles": titles,
        }
        _cache_put(key, out)
        return dict(out)


# ---------------------------------------------------------------- Jikan (best effort)


def _parse_iso(v: Any) -> datetime | None:
    if not isinstance(v, str) or not v.strip():
        return None
    try:
        dt = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


# Module-level backoff (process-local, reset on restart): monotonic deadline until which Jikan is skipped.
jikan_backoff_until = 0.0
_jikan_skip_logged = False
_jikan_lock = threading.Lock()


def _jikan_clock() -> float:
    return time.monotonic()


def reset_jikan_backoff() -> None:
    global jikan_backoff_until, _jikan_skip_logged
    with _jikan_lock:
        jikan_backoff_until = 0.0
        _jikan_skip_logged = False


def jikan_in_backoff() -> bool:
    """True while in a backoff window; logs one info line per window."""
    global _jikan_skip_logged
    with _jikan_lock:
        if _jikan_clock() >= jikan_backoff_until:
            return False
        if not _jikan_skip_logged:
            _jikan_skip_logged = True
            log.info("jikan_backoff_skip", remaining_seconds=round(jikan_backoff_until - _jikan_clock()))
        return True


def _jikan_failed(mal_id: int, **fields: Any) -> None:
    global jikan_backoff_until, _jikan_skip_logged
    with _jikan_lock:
        jikan_backoff_until = _jikan_clock() + JIKAN_BACKOFF_SECONDS
        _jikan_skip_logged = False
    log.warning("jikan_failed", mal_id=mal_id, backoff_hours=JIKAN_BACKOFF_SECONDS / 3600, **fields)


def fetch_jikan_episodes(
    mal_id: int, transport: httpx.BaseTransport | None = None
) -> dict[int, tuple[str | None, datetime | None]]:
    """{episode: (title, aired)} from Jikan. Never raises and never retries: a failure ends the run and starts a
    6 h backoff during which Jikan is skipped (returns {})."""
    out: dict[int, tuple[str | None, datetime | None]] = {}
    if jikan_in_backoff():
        return out
    headers = {"Accept": "application/json", "User-Agent": f"feedcatch/{__version__}"}
    timeout = httpx.Timeout(JIKAN_TIMEOUT_SECONDS, connect=JIKAN_CONNECT_TIMEOUT_SECONDS)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, transport=transport) as client:
            for page in range(1, JIKAN_MAX_PAGES + 1):
                if page > 1 and JIKAN_PAGE_DELAY_SECONDS:
                    time.sleep(JIKAN_PAGE_DELAY_SECONDS)
                resp = client.get(JIKAN_URL.format(mal_id=int(mal_id)), params={"page": page}, headers=headers)
                if resp.status_code != 200:
                    _jikan_failed(mal_id, status=resp.status_code, page=page)
                    break
                body = resp.json()
                for item in body.get("data") or []:
                    ep = _int((item or {}).get("mal_id"))
                    if ep is not None:
                        out[ep] = (_str(item.get("title")), _parse_iso(item.get("aired")))
                if not (body.get("pagination") or {}).get("has_next_page"):
                    break
    except (httpx.HTTPError, ValueError, AttributeError, TypeError) as exc:
        _jikan_failed(mal_id, error=f"{type(exc).__name__}: {exc}"[:200])
    return out


# ---------------------------------------------------------------- provider


def to_result(d: AnilistMedia) -> MediaResult:
    title = d.title_english or d.title_romaji or d.title_native
    alt: list[str] = []
    for t in (d.title_romaji, d.title_english, *d.synonyms):
        if t and t != title and t not in alt:
            alt.append(t)
    return MediaResult(
        provider="anilist",
        id=str(d.id),
        title=title,
        original_title=d.title_native,
        alt_titles=alt,
        kind="anime",
        format=d.format,
        status=d.status,
        year=d.season_year,
        episodes=d.episodes,
        cover_url=d.cover_large or d.cover_medium,
        site_url=d.site_url,
    )


def suggested_related(detail: AnilistMediaDetail) -> list[RelatedInfo]:
    """Relations worth offering as extra seasons: anime only, sequel/prequel/parent/side-story/alternative."""
    out: list[RelatedInfo] = []
    for r in detail.related:
        if r.relation_type not in RELATED_TYPES or r.format not in RELATED_FORMATS:
            continue
        # A direct serial sequel of the suggested season 1 is season 2; anything else is left to the user.
        number = 2 if r.relation_type == "SEQUEL" and r.format in _SERIAL_FORMATS else None
        out.append(
            RelatedInfo(
                relation_type=r.relation_type,
                provider="anilist",
                id=str(r.id),
                title=r.title_english or r.title_romaji,
                format=r.format,
                episodes=r.episodes,
                year=r.season_year,
                status=r.status,
                suggested_season_number=number,
            )
        )
    return out


def to_detail(d: AnilistMediaDetail) -> MediaDetail:
    base = to_result(d)
    return MediaDetail(
        **{f: getattr(base, f) for f in MediaResult.__dataclass_fields__},
        seasons=[SeasonInfo(season_number=1, name=None, episode_count=d.episodes, air_date=d.start_date)],
        related=suggested_related(d),
    )


def parse_id(media_id: str | int) -> int:
    try:
        n = int(str(media_id).strip())
    except ValueError as exc:
        raise AnilistError("AniList entry not found (ids are numbers)", not_found=True) from exc
    if n <= 0:
        raise AnilistError("AniList entry not found (ids are numbers)", not_found=True)
    return n


class AnilistProvider:
    name = "anilist"
    label = "AniList"
    kind: Kind = "anime"

    def __init__(self, client: AnilistClient | None = None, jikan: bool = True) -> None:
        self.client = client or AnilistClient()
        self.jikan = jikan

    def search(self, q: str, limit: int = 10) -> list[MediaResult]:
        return [to_result(m) for m in self.client.search(q, limit)]

    def detail(self, media_id: str) -> MediaDetail:
        return to_detail(self.client.get(parse_id(media_id)))

    def episodes(self, media_id: str, season_number: int) -> list[EpisodeInfo]:
        """All known episodes of one AniList entry. `season_number` is ignored (one AniList entry = one season)."""
        raw = self.client.episodes(parse_id(media_id))
        airing: dict[int, int] = raw["airing"]
        titles: dict[int, str] = dict(raw["titles"])
        numbers = set(airing) | set(titles)
        if raw.get("episodes"):
            numbers |= set(range(1, int(raw["episodes"]) + 1))
        dates: dict[int, datetime | None] = {
            n: (datetime.fromtimestamp(airing[n], tz=UTC) if n in airing else None) for n in numbers
        }
        now = datetime.now(UTC)
        latest_aired = max((n for n, dt in dates.items() if dt is not None and dt <= now), default=0)
        finished = raw.get("status") == "FINISHED"

        def has_aired(n: int) -> bool:
            dt = dates.get(n)
            if dt is not None:
                return dt <= now
            return finished or n < latest_aired

        gaps = [n for n in numbers if has_aired(n) and (n not in titles or dates.get(n) is None)]
        jikan_titles: set[int] = set()
        mal_id = raw.get("idMal")
        if gaps and mal_id and self.jikan:
            for n, (title, aired) in fetch_jikan_episodes(int(mal_id)).items():
                if n not in numbers and not finished and n > latest_aired:
                    continue  # never invent future episodes from Jikan
                numbers.add(n)
                if title and n not in titles:
                    titles[n] = title
                    jikan_titles.add(n)
                if aired is not None and dates.get(n) is None:
                    dates[n] = aired
        return [
            EpisodeInfo(
                number=n,
                title=titles.get(n),
                air_date=dates.get(n),
                source="jikan" if n in jikan_titles else "anilist",
            )
            for n in sorted(numbers)
            if n > 0
        ]

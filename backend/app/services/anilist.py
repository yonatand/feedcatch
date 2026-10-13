"""AniList GraphQL client (metadata only) and the series-suggestion helper.

See `.claude/rules/anilist.md`. Fixed host (no SSRF check needed), explicit timeouts, a small module-level TTL cache
so repeated UI keystrokes do not burn AniList's 30 requests/minute budget.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

from app import __version__
from app.services import paths

log = structlog.get_logger("anilist")

ANILIST_URL = "https://graphql.anilist.co"
CACHE_TTL_SECONDS = 600.0
CACHE_MAX_KEYS = 500
DEFAULT_RETRY_AFTER = 60
MAX_SEARCH_LIMIT = 50

_MEDIA_FIELDS = (
    "id title{romaji english native} synonyms format status season seasonYear episodes "
    "coverImage{medium large} siteUrl "
    "relations{edges{relationType node{id title{romaji english} format episodes seasonYear status}}}"
)
SEARCH_QUERY = (
    "query ($q: String, $limit: Int) { Page(perPage: $limit) { "
    f"media(search: $q, type: ANIME, sort: SEARCH_MATCH) {{ {_MEDIA_FIELDS} }} }} }}"
)
DETAIL_QUERY = f"query ($id: Int) {{ Media(id: $id, type: ANIME) {{ {_MEDIA_FIELDS} }} }}"

RELATED_TYPES = frozenset({"SEQUEL", "PREQUEL", "PARENT", "SIDE_STORY", "ALTERNATIVE"})
RELATED_FORMATS = frozenset({"TV", "TV_SHORT", "ONA", "OVA", "MOVIE", "SPECIAL"})
_SERIAL_FORMATS = frozenset({"TV", "TV_SHORT", "ONA"})
_ASCII_LETTER = re.compile(r"[A-Za-z]")


class AnilistError(Exception):
    """AniList call failed. `transient` = worth retrying later; `retry_after` set on 429; `not_found` on unknown id."""

    def __init__(
        self, message: str, transient: bool = False, retry_after: int | None = None, not_found: bool = False
    ) -> None:
        super().__init__(message)
        self.transient = transient
        self.retry_after = retry_after
        self.not_found = not_found


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
    suggested_season_number: int | None = None


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


@dataclass(frozen=True)
class AnilistMediaDetail(AnilistMedia):
    related: list[AnilistRelated] = field(default_factory=list)


@dataclass(frozen=True)
class AnilistSuggestion:
    anilist_id: int
    name: str
    aliases: list[str]
    cover_url: str | None
    anilist: dict[str, Any]
    seasons: list[dict[str, Any]]
    related: list[AnilistRelated]


def _str(v: Any) -> str | None:
    return v.strip() or None if isinstance(v, str) else None


def _int(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


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
        related=related,
    )


def as_media(detail: AnilistMediaDetail) -> AnilistMedia:
    """Drop `related` (search results are plain media)."""
    return AnilistMedia(
        id=detail.id,
        title_romaji=detail.title_romaji,
        title_english=detail.title_english,
        title_native=detail.title_native,
        synonyms=list(detail.synonyms),
        format=detail.format,
        status=detail.status,
        season=detail.season,
        season_year=detail.season_year,
        episodes=detail.episodes,
        cover_medium=detail.cover_medium,
        cover_large=detail.cover_large,
        site_url=detail.site_url,
    )


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


# ---------------------------------------------------------------- suggestion


def info_of(detail: AnilistMedia) -> dict[str, Any]:
    """The JSON stored on `series.anilist_json`."""
    return {
        "title_romaji": detail.title_romaji,
        "title_english": detail.title_english,
        "title_native": detail.title_native,
        "format": detail.format,
        "status": detail.status,
        "season_year": detail.season_year,
        "episodes": detail.episodes,
        "site_url": detail.site_url,
    }


def suggested_related(detail: AnilistMediaDetail) -> list[AnilistRelated]:
    """Relations worth offering as extra seasons: anime only, sequel/prequel/parent/side-story/alternative."""
    out: list[AnilistRelated] = []
    for r in detail.related:
        if r.relation_type not in RELATED_TYPES or r.format not in RELATED_FORMATS:
            continue
        # A direct serial sequel of the suggested season 1 is season 2; anything else is left to the user.
        number = 2 if r.relation_type == "SEQUEL" and r.format in _SERIAL_FORMATS else None
        out.append(
            AnilistRelated(
                relation_type=r.relation_type,
                id=r.id,
                title_romaji=r.title_romaji,
                title_english=r.title_english,
                format=r.format,
                episodes=r.episodes,
                season_year=r.season_year,
                status=r.status,
                suggested_season_number=number,
            )
        )
    return out


def build_suggestion(detail: AnilistMediaDetail) -> AnilistSuggestion:
    """Prefill for a new series: folder-safe name, Latin-script aliases, one season, related entries."""
    raw_name = detail.title_english or detail.title_romaji or detail.title_native or f"AniList {detail.id}"
    try:
        name = paths.sanitize_component(raw_name)
    except paths.PathError:
        name = f"AniList {detail.id}"

    candidates: list[str] = []
    if name != raw_name:
        candidates.append(raw_name)
    candidates += [t for t in (detail.title_romaji, detail.title_english) if t]
    candidates += detail.synonyms

    seen = {name.casefold()}
    aliases: list[str] = []
    for c in candidates:
        c = " ".join(c.split())
        if not c or not _ASCII_LETTER.search(c) or c.casefold() in seen:
            continue
        seen.add(c.casefold())
        aliases.append(c)

    seasons = [
        {
            "season_number": 1,
            "episode_min": None,
            "episode_max": detail.episodes,
            "absolute_min": None,
            "absolute_max": None,
        }
    ]
    return AnilistSuggestion(
        anilist_id=detail.id,
        name=name,
        aliases=aliases,
        cover_url=detail.cover_large or detail.cover_medium,
        anilist=info_of(detail),
        seasons=seasons,
        related=suggested_related(detail),
    )

"""TMDB (The Movie Database) API v3 provider for TV series.

Built from the public v3 documentation; NOT verified live (no API key was available during development).
Auth: a v3 API key goes into `?api_key=`; a configured value longer than 40 chars is treated as a v4 read token
(`Authorization: Bearer`). Fixed host, so no SSRF check is needed. The key is never logged.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from app import __version__
from app.services.metadata.base import EpisodeInfo, Kind, MediaDetail, MediaResult, MetadataError, SeasonInfo, TTLCache

log = structlog.get_logger("tmdb")

TMDB_API = "https://api.themoviedb.org/3"
POSTER_BASE = "https://image.tmdb.org/t/p/w342"
SITE_BASE = "https://www.themoviedb.org/tv/"
MAX_SEARCH_LIMIT = 20  # one TMDB results page

cache = TTLCache(ttl=600.0, max_keys=500)


def _str(v: Any) -> str | None:
    return v.strip() or None if isinstance(v, str) else None


def _int(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _year(date: Any) -> int | None:
    s = _str(date)
    if s and len(s) >= 4 and s[:4].isdigit():
        return int(s[:4])
    return None


def _day(date: Any) -> datetime | None:
    """TMDB air dates are calendar days (YYYY-MM-DD); stored as 00:00 UTC of that day."""
    s = _str(date)
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def _poster(path: Any) -> str | None:
    p = _str(path)
    return f"{POSTER_BASE}{p}" if p and p.startswith("/") else None


def parse_id(media_id: str | int) -> int:
    try:
        n = int(str(media_id).strip())
    except ValueError as exc:
        raise MetadataError("TMDB entry not found (ids are numbers)", not_found=True) from exc
    if n <= 0:
        raise MetadataError("TMDB entry not found (ids are numbers)", not_found=True)
    return n


def to_result(raw: dict[str, Any], detail: bool = False) -> MediaResult:
    tid = _int(raw.get("id"))
    if tid is None:
        raise MetadataError("unexpected TMDB response (entry without id)")
    name = _str(raw.get("name"))
    original = _str(raw.get("original_name"))
    return MediaResult(
        provider="tmdb",
        id=str(tid),
        title=name or original,
        original_title=original if original != name else None,
        alt_titles=[],
        kind="tv",
        format="TV",
        status=_str(raw.get("status")),
        year=_year(raw.get("first_air_date")),
        episodes=_int(raw.get("number_of_episodes")) if detail else None,
        cover_url=_poster(raw.get("poster_path")),
        site_url=f"{SITE_BASE}{tid}",
    )


def to_detail(raw: dict[str, Any]) -> MediaDetail:
    base = to_result(raw, detail=True)
    seasons: list[SeasonInfo] = []
    for s in raw.get("seasons") or []:
        n = _int((s or {}).get("season_number"))
        if n is None or n <= 0:  # season 0 = specials
            continue
        seasons.append(
            SeasonInfo(
                season_number=n,
                name=_str(s.get("name")),
                episode_count=_int(s.get("episode_count")),
                air_date=_str(s.get("air_date")),
            )
        )
    return MediaDetail(
        **{f: getattr(base, f) for f in MediaResult.__dataclass_fields__},
        seasons=sorted(seasons, key=lambda x: x.season_number),
        related=[],
    )


class TmdbProvider:
    name = "tmdb"
    label = "TMDB"
    kind: Kind = "tv"

    def __init__(self, api_key: str, timeout: float = 10.0, transport: httpx.BaseTransport | None = None) -> None:
        self._api_key = api_key.strip()
        self.timeout = timeout
        self._transport = transport

    def __repr__(self) -> str:  # keep the key out of reprs/logs
        return "TmdbProvider(api_key=***)"

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._api_key:
            raise MetadataError("TMDB API key not configured", not_configured=True)
        headers = {"Accept": "application/json", "User-Agent": f"feedcatch/{__version__}"}
        query = dict(params or {})
        if len(self._api_key) > 40:
            headers["Authorization"] = f"Bearer {self._api_key}"
        else:
            query["api_key"] = self._api_key
        try:
            with httpx.Client(
                timeout=httpx.Timeout(self.timeout), follow_redirects=False, transport=self._transport
            ) as client:
                resp = client.get(f"{TMDB_API}{path}", params=query, headers=headers)
        except httpx.TimeoutException as exc:
            raise MetadataError("TMDB timed out", transient=True) from exc
        except httpx.HTTPError as exc:
            raise MetadataError(f"TMDB unreachable: {type(exc).__name__}", transient=True) from exc
        log.debug("tmdb_request", path=path, status=resp.status_code)
        if resp.status_code == 401:
            raise MetadataError("TMDB rejected the API key (401)")
        if resp.status_code == 404:
            raise MetadataError("TMDB entry not found", not_found=True)
        if resp.status_code == 429:
            try:
                retry = max(1, int(float(resp.headers.get("Retry-After", "10"))))
            except ValueError:
                retry = 10
            raise MetadataError(f"TMDB rate limit, retry in {retry} s", transient=True, retry_after=retry)
        if resp.status_code >= 500:
            raise MetadataError(f"TMDB HTTP {resp.status_code}", transient=True)
        if resp.status_code >= 400:
            raise MetadataError(f"TMDB rejected the request (HTTP {resp.status_code})")
        try:
            body = resp.json()
        except ValueError as exc:
            raise MetadataError("unexpected TMDB response") from exc
        if not isinstance(body, dict):
            raise MetadataError("unexpected TMDB response")
        return body

    def search(self, q: str, limit: int = 10) -> list[MediaResult]:
        q = " ".join(q.split())
        limit = max(1, min(int(limit), MAX_SEARCH_LIMIT))
        key = f"search:{limit}:{q.casefold()}"
        cached = cache.get(key)
        if cached is not None:
            return list(cached)
        body = self._get("/search/tv", {"query": q, "page": 1, "include_adult": "false"})
        items = [to_result(r) for r in (body.get("results") or []) if isinstance(r, dict) and _int(r.get("id"))]
        items = items[:limit]
        cache.put(key, items)
        return list(items)

    def detail(self, media_id: str) -> MediaDetail:
        tid = parse_id(media_id)
        key = f"tv:{tid}"
        cached = cache.get(key)
        if cached is not None:
            detail: MediaDetail = cached
            return detail
        detail = to_detail(self._get(f"/tv/{tid}"))
        cache.put(key, detail)
        return detail

    def episodes(self, media_id: str, season_number: int) -> list[EpisodeInfo]:
        tid = parse_id(media_id)
        body = self._get(f"/tv/{tid}/season/{int(season_number)}")
        out: dict[int, EpisodeInfo] = {}
        for e in body.get("episodes") or []:
            n = _int((e or {}).get("episode_number"))
            if n is None or n <= 0:
                continue
            out[n] = EpisodeInfo(number=n, title=_str(e.get("name")), air_date=_day(e.get("air_date")), source="tmdb")
        return [out[n] for n in sorted(out)]

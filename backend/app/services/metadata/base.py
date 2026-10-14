"""Provider-neutral metadata types, the provider protocol and the suggestion builder.

See `.claude/rules/metadata.md`. Metadata never affects matching except through the aliases the user keeps.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

from app.services import paths

Kind = Literal["anime", "tv"]
PROVIDER_NAMES = ("anilist", "tmdb")
_ASCII_LETTER = re.compile(r"[A-Za-z]")


class MetadataError(Exception):
    """A metadata call failed.

    `transient`: worth retrying later; `retry_after`: seconds (429); `not_found`: unknown id;
    `not_configured`: provider needs an API key; `not_linked`: the season/series has no provider link.
    """

    def __init__(
        self,
        message: str,
        *,
        transient: bool = False,
        retry_after: int | None = None,
        not_found: bool = False,
        not_configured: bool = False,
        not_linked: bool = False,
    ) -> None:
        super().__init__(message)
        self.transient = transient
        self.retry_after = retry_after
        self.not_found = not_found
        self.not_configured = not_configured
        self.not_linked = not_linked


@dataclass(frozen=True)
class SeasonInfo:
    season_number: int
    name: str | None = None
    episode_count: int | None = None
    air_date: str | None = None  # YYYY-MM-DD


@dataclass(frozen=True)
class RelatedInfo:
    relation_type: str
    provider: str
    id: str
    title: str | None
    format: str | None
    episodes: int | None
    year: int | None
    status: str | None
    suggested_season_number: int | None = None


@dataclass(frozen=True)
class MediaResult:
    provider: str
    id: str
    title: str | None
    original_title: str | None
    alt_titles: list[str]
    kind: Kind
    format: str | None
    status: str | None
    year: int | None
    episodes: int | None
    cover_url: str | None
    site_url: str | None


@dataclass(frozen=True)
class MediaDetail(MediaResult):
    seasons: list[SeasonInfo] = field(default_factory=list)
    related: list[RelatedInfo] = field(default_factory=list)


@dataclass(frozen=True)
class EpisodeInfo:
    number: int
    title: str | None = None
    air_date: datetime | None = None  # aware UTC
    source: str | None = None  # defaults to the provider name


@dataclass(frozen=True)
class Suggestion:
    provider: str
    id: str
    name: str
    aliases: list[str]
    cover_url: str | None
    metadata: dict[str, Any]
    seasons: list[dict[str, Any]]
    related: list[RelatedInfo]


class MetadataProvider(Protocol):
    name: str
    label: str
    kind: Kind

    def search(self, q: str, limit: int = 10) -> list[MediaResult]: ...

    def detail(self, media_id: str) -> MediaDetail: ...

    def episodes(self, media_id: str, season_number: int) -> list[EpisodeInfo]: ...


# ---------------------------------------------------------------- tiny TTL cache (shared by providers)


class TTLCache:
    def __init__(self, ttl: float = 600.0, max_keys: int = 500) -> None:
        self.ttl = ttl
        self.max_keys = max_keys
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def now(self) -> float:
        return time.monotonic()

    def get(self, key: str) -> Any | None:
        with self._lock:
            hit = self._data.get(key)
            if hit is None:
                return None
            expires, value = hit
            if expires <= self.now():
                del self._data[key]
                return None
            return value

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            now = self.now()
            if key not in self._data and len(self._data) >= self.max_keys:
                for k in [k for k, (exp, _) in self._data.items() if exp <= now]:
                    del self._data[k]
                while len(self._data) >= self.max_keys:
                    del self._data[next(iter(self._data))]
            self._data[key] = (now + self.ttl, value)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


# ---------------------------------------------------------------- suggestion


def info_of(m: MediaResult) -> dict[str, Any]:
    """The JSON stored on `series.metadata_json`."""
    return {
        "provider": m.provider,
        "id": m.id,
        "title": m.title,
        "original_title": m.original_title,
        "alt_titles": list(m.alt_titles),
        "kind": m.kind,
        "format": m.format,
        "status": m.status,
        "year": m.year,
        "episodes": m.episodes,
        "site_url": m.site_url,
    }


def _season_row(provider: str, media_id: str, number: int, episode_max: int | None) -> dict[str, Any]:
    return {
        "season_number": number,
        "monitored": True,
        "path_override": None,
        "episode_min": None,
        "episode_max": episode_max,
        "absolute_min": None,
        "absolute_max": None,
        "metadata_provider": provider,
        "metadata_id": media_id,
    }


_FINISHED = {"FINISHED", "ENDED", "CANCELED", "CANCELLED"}


def build_suggestion(detail: MediaDetail) -> Suggestion:
    """Prefill for a new series: folder-safe name, Latin-script aliases, seasons with provider links, related."""
    raw_name = detail.title or detail.original_title or f"{detail.provider} {detail.id}"
    try:
        name = paths.sanitize_component(raw_name)
    except paths.PathError:
        name = f"{detail.provider} {detail.id}"

    candidates: list[str] = []
    if name != raw_name:
        candidates.append(raw_name)
    candidates += detail.alt_titles
    if detail.original_title:
        candidates.append(detail.original_title)

    seen = {name.casefold()}
    aliases: list[str] = []
    for c in candidates:
        c = " ".join(c.split())
        if not c or not _ASCII_LETTER.search(c) or c.casefold() in seen:
            continue
        seen.add(c.casefold())
        aliases.append(c)

    finished = (detail.status or "").upper() in _FINISHED
    seasons: list[dict[str, Any]] = []
    for s in sorted(detail.seasons, key=lambda x: x.season_number):
        if s.season_number <= 0:  # specials
            continue
        # An episode cap is only safe once the season is complete (ongoing counts are provisional).
        cap = s.episode_count if (finished or detail.provider == "anilist") else None
        seasons.append(_season_row(detail.provider, detail.id, s.season_number, cap))
    if not seasons:
        seasons.append(_season_row(detail.provider, detail.id, 1, detail.episodes))
    return Suggestion(
        provider=detail.provider,
        id=detail.id,
        name=name,
        aliases=aliases,
        cover_url=detail.cover_url,
        metadata=info_of(detail),
        seasons=seasons,
        related=list(detail.related),
    )

"""Link unlinked seasons of metadata-linked series (DBs upgraded from 0002; episodes.md "Fixes decided 2026-10-14").

For every series with a metadata link:
- season 1 is linked to the series entry when unlinked (anilist and tmdb);
- anilist: other unlinked seasons are linked by following the SEQUEL chain from the series entry (max 5 hops, one cached
  detail call per hop). Only TV/TV_SHORT/ONA sequels count as the next season (previous + 1); other formats are
  passed through without a season number;
- tmdb: every unlinked season whose number exists upstream is linked to the TV id.
Newly linked seasons get one immediate best-effort episode refresh. Linked seasons are never touched (idempotent).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings
from app.models import Season, Series
from app.services import activity
from app.services.metadata import MetadataError, get_provider, refresh_season
from app.services.metadata.base import MediaDetail, RelatedInfo

log = structlog.get_logger("metadata")

MAX_SEQUEL_HOPS = 5
_lock = threading.Lock()


@dataclass
class BackfillResult:
    linked: int = 0
    refreshed: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"linked": self.linked, "refreshed": self.refreshed, "errors": list(self.errors)}


def _candidates_stmt() -> Any:
    """Linked series that have at least one unlinked season."""
    return (
        select(Series)
        .where(Series.metadata_provider.is_not(None), Series.metadata_id.is_not(None))
        .where(Series.seasons.any(Season.metadata_provider.is_(None)))
        .options(selectinload(Series.seasons))
        .order_by(Series.id)
    )


def has_candidates(db: Session) -> bool:
    return db.scalars(_candidates_stmt().limit(1)).first() is not None


SERIAL_FORMATS = frozenset({"TV", "TV_SHORT", "ONA"})


def _next_sequel(detail: MediaDetail) -> RelatedInfo | None:
    """The SEQUEL to follow: a serial (TV/TV_SHORT/ONA) one when present, else any (passed through)."""
    sequels = [r for r in detail.related if r.relation_type == "SEQUEL"]
    for r in sequels:
        if r.format in SERIAL_FORMATS:
            return r
    return sequels[0] if sequels else None


def _anilist_links(db: Session, settings: Settings, series: Series, unlinked: dict[int, Season]) -> dict[int, str]:
    """{season_number: anilist id} for unlinked seasons > 1 found along the SEQUEL chain. Raises MetadataError.

    Only serial entries (TV/TV_SHORT/ONA) count as the next season; a MOVIE/SPECIAL/OVA sequel is passed through
    (its own SEQUEL edges are followed within the hop budget) without incrementing the season number.
    """
    wanted = {n for n in unlinked if n > 1}
    out: dict[int, str] = {}
    if not wanted:
        return out
    provider = get_provider("anilist", db, settings)
    media_id, number = str(series.metadata_id), 1
    seen = {media_id}
    for _hop in range(MAX_SEQUEL_HOPS):
        if number >= max(wanted):
            break
        sequel = _next_sequel(provider.detail(media_id))
        if sequel is None or sequel.id in seen:
            break
        media_id = sequel.id
        seen.add(media_id)
        if sequel.format not in SERIAL_FORMATS:
            continue  # pass through: never link a non-TV entry as a numbered season
        number += 1
        if number in wanted:
            out[number] = media_id
    return out


def _tmdb_links(db: Session, settings: Settings, series: Series, unlinked: dict[int, Season]) -> dict[int, str]:
    wanted = {n for n in unlinked if n > 1}
    if not wanted:
        return {}
    detail = get_provider("tmdb", db, settings).detail(str(series.metadata_id))
    upstream = {s.season_number for s in detail.seasons}
    return {n: detail.id for n in wanted if n in upstream}


def _refresh(db: Session, season: Season, settings: Settings, result: BackfillResult) -> None:
    try:
        refresh_season(db, season, settings)
        db.commit()
        result.refreshed += 1
    except MetadataError as exc:
        db.rollback()
        msg = f"episode metadata could not be fetched: {exc}"
        result.errors.append(f"'{season.series.name}' season {season.season_number}: {msg}")
        activity.log_event(
            db,
            "warning",
            "metadata_refresh_failed",
            f"Season {season.season_number} of '{season.series.name}': {msg}",
            details={"season_id": season.id, "provider": season.metadata_provider},
        )
        db.commit()


def backfill_season_links(db: Session, settings: Settings) -> dict[str, Any]:
    """Link unlinked seasons of linked series; returns `{linked, refreshed, errors}`. Never raises MetadataError."""
    with _lock:
        result = BackfillResult()
        newly: list[int] = []
        skip_providers: set[str] = set()
        for series in list(db.scalars(_candidates_stmt())):
            provider_name = str(series.metadata_provider)
            unlinked = {s.season_number: s for s in series.seasons if not s.metadata_provider}
            links: dict[int, str] = {}
            if 1 in unlinked:
                links[1] = str(series.metadata_id)
            if provider_name not in skip_providers:
                try:
                    if provider_name == "anilist":
                        links.update(_anilist_links(db, settings, series, unlinked))
                    elif provider_name == "tmdb":
                        links.update(_tmdb_links(db, settings, series, unlinked))
                except MetadataError as exc:
                    result.errors.append(f"'{series.name}': {exc}")
                    if exc.retry_after is not None or exc.not_configured:
                        skip_providers.add(provider_name)  # do not hammer a rate-limited / keyless provider
            for number, media_id in sorted(links.items()):
                season = unlinked[number]
                season.metadata_provider = provider_name
                season.metadata_id = media_id
                newly.append(season.id)
                result.linked += 1
                log.info(
                    "season_link_backfilled",
                    series_id=series.id,
                    season_id=season.id,
                    season_number=number,
                    provider=provider_name,
                    metadata_id=media_id,
                )
            db.commit()
        for season_id in newly:
            season = db.get(Season, season_id)
            if season is not None:
                _refresh(db, season, settings, result)
        return result.as_dict()


def run_in_background(settings: Settings) -> threading.Thread | None:
    """Startup hook: run the backfill in a daemon thread when there is anything to link (cheap DB check first)."""
    from app.db import SessionLocal

    with SessionLocal() as db:
        if not has_candidates(db):
            return None

    def _run() -> None:
        log.info("season_link_backfill_started")
        db = SessionLocal()
        try:
            out = backfill_season_links(db, settings)
            log.info("season_link_backfill_finished", **out)
        except Exception:
            log.exception("season_link_backfill_failed")
            db.rollback()
        finally:
            db.close()

    thread = threading.Thread(target=_run, name="season-link-backfill", daemon=True)
    thread.start()
    return thread

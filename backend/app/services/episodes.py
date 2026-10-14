"""Episode status derivation (never stored), season summaries, calendar and wanted queries.

See `.claude/rules/episodes.md` "Episode status".
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Download, Episode, Season, Series, utcnow
from app.schemas import SeasonSummaryOut

ACTIVE_STATUSES = frozenset({"submitted", "exists", "path_mismatch"})
COMPLETE_STATES = frozenset({"uploading", "stalledUP", "pausedUP", "stoppedUP", "queuedUP", "forcedUP", "checkingUP"})
HAVE_STATUSES = frozenset({"downloaded", "downloading", "pending"})


class DownloadLike(Protocol):
    id: int
    status: str
    qbit_progress: float | None
    qbit_state: str | None


@dataclass
class EpisodeState:
    status: str
    download: Any | None  # the download shown next to the episode (may be a failed one)


def _newest(downloads: Iterable[DownloadLike]) -> tuple[DownloadLike | None, DownloadLike | None]:
    """(newest non-failed, newest failed) by id."""
    active: DownloadLike | None = None
    failed: DownloadLike | None = None
    for d in downloads:
        if d.status == "failed":
            if failed is None or d.id > failed.id:
                failed = d
        elif active is None or d.id > active.id:
            active = d
    return active, failed


def compute_status(air_date: datetime | None, downloads: Iterable[DownloadLike], now: datetime) -> EpisodeState:
    """Derive the status of one (season, episode) from its air date and its downloads."""
    active, failed = _newest(downloads)
    if active is not None:
        if active.status in ACTIVE_STATUSES:
            done = (active.qbit_progress is not None and active.qbit_progress >= 0.999) or (
                active.qbit_state in COMPLETE_STATES
            )
            return EpisodeState("downloaded" if done else "downloading", active)
        if active.status == "pending":
            return EpisodeState("pending", active)
    if air_date is None:
        return EpisodeState("unknown", failed)
    if air_date > now:
        return EpisodeState("unaired", failed)
    return EpisodeState("missing", failed)


def downloads_by_episode(db: Session, season_ids: Sequence[int]) -> dict[tuple[int, int], list[Download]]:
    out: dict[tuple[int, int], list[Download]] = {}
    if not season_ids:
        return out
    ids = list(dict.fromkeys(season_ids))
    for i in range(0, len(ids), 500):
        stmt = (
            select(Download)
            .where(Download.season_id.in_(ids[i : i + 500]))
            .options(
                selectinload(Download.entry),
                selectinload(Download.series),
                selectinload(Download.season),
                selectinload(Download.rule),
            )
        )
        for d in db.scalars(stmt):
            out.setdefault((d.season_id, d.episode_number), []).append(d)
    return out


def season_states(db: Session, season: Season, now: datetime | None = None) -> list[tuple[Episode, EpisodeState]]:
    now = now or utcnow()
    eps = list(db.scalars(select(Episode).where(Episode.season_id == season.id).order_by(Episode.episode_number)))
    dls = downloads_by_episode(db, [season.id])
    return [(e, compute_status(e.air_date, dls.get((season.id, e.episode_number), []), now)) for e in eps]


def summarize(states: Iterable[str]) -> SeasonSummaryOut:
    s = SeasonSummaryOut()
    for st in states:
        s.episode_count += 1
        if st == "downloaded":
            s.downloaded_count += 1
        elif st == "missing":
            s.missing_count += 1
        elif st == "unaired":
            s.unaired_count += 1
    return s


def season_summaries(
    db: Session, season_ids: Sequence[int], now: datetime | None = None
) -> dict[int, SeasonSummaryOut]:
    """Cheap aggregate for many seasons: two queries (episodes, downloads)."""
    now = now or utcnow()
    ids = list(dict.fromkeys(season_ids))
    out: dict[int, SeasonSummaryOut] = {sid: SeasonSummaryOut() for sid in ids}
    if not ids:
        return out
    rows = db.execute(
        select(Episode.season_id, Episode.episode_number, Episode.air_date).where(Episode.season_id.in_(ids))
    ).all()
    if not rows:
        return out
    dls: dict[tuple[int, int], list[Any]] = {}
    for d in db.execute(
        select(Download.id, Download.season_id, Download.episode_number, Download.status, Download.qbit_progress,
               Download.qbit_state).where(Download.season_id.in_(ids))
    ).all():  # fmt: skip
        dls.setdefault((d.season_id, d.episode_number), []).append(d)
    per_season: dict[int, list[str]] = {}
    for sid, num, air in rows:
        per_season.setdefault(sid, []).append(compute_status(air, dls.get((sid, num), []), now).status)
    for sid, states in per_season.items():
        out[sid] = summarize(states)
    return out


# ---------------------------------------------------------------- calendar / wanted


@dataclass
class CalendarRow:
    series: Series
    season: Season
    episode: Episode
    status: str

    @property
    def monitored(self) -> bool:
        return bool(self.series.monitored and self.season.monitored)

    def as_dict(self) -> dict[str, Any]:
        return {
            "series_id": self.series.id,
            "series_name": self.series.name,
            "cover_url": self.series.cover_url,
            "season_id": self.season.id,
            "season_number": self.season.season_number,
            "episode_number": self.episode.episode_number,
            "title": self.episode.title,
            "air_date": self.episode.air_date,
            "status": self.status,
            "monitored": self.monitored,
        }


def _rows(db: Session, stmt: Any, now: datetime) -> list[CalendarRow]:
    eps = list(db.scalars(stmt.options(selectinload(Episode.season).selectinload(Season.series))))
    dls = downloads_by_episode(db, [e.season_id for e in eps])
    return [
        CalendarRow(
            series=e.season.series,
            season=e.season,
            episode=e,
            status=compute_status(e.air_date, dls.get((e.season_id, e.episode_number), []), now).status,
        )
        for e in eps
    ]


def calendar(
    db: Session, start: datetime, end: datetime, monitored_only: bool = False, limit: int | None = None
) -> list[CalendarRow]:
    """Episodes with start <= air_date < end, sorted by air date."""
    now = utcnow()
    stmt = (
        select(Episode)
        .join(Season, Episode.season_id == Season.id)
        .join(Series, Season.series_id == Series.id)
        .where(Episode.air_date.is_not(None), Episode.air_date >= start, Episode.air_date < end)
        .order_by(Episode.air_date, Series.name, Episode.episode_number)
    )
    if monitored_only:
        stmt = stmt.where(Series.monitored.is_(True), Season.monitored.is_(True))
    if limit is not None:
        stmt = stmt.limit(limit)
    return _rows(db, stmt, now)


def wanted(db: Session) -> list[CalendarRow]:
    """Aired episodes with status `missing` in monitored seasons of monitored series, newest air date first."""
    now = utcnow()
    stmt = (
        select(Episode)
        .join(Season, Episode.season_id == Season.id)
        .join(Series, Season.series_id == Series.id)
        .where(
            Episode.air_date.is_not(None),
            Episode.air_date <= now,
            Series.monitored.is_(True),
            Season.monitored.is_(True),
        )
        .order_by(Episode.air_date.desc(), Episode.id.desc())
    )
    return [r for r in _rows(db, stmt, now) if r.status == "missing"]

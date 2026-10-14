"""Feed polling pipeline (architecture.md "Pipeline"), entry evaluation, simulation and manual grabs.

Safety: never dispatches historical entries (invariant 8); per-feed non-blocking lock (invariant 9);
no filesystem access (invariant 1).
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings
from app.models import Download, Evaluation, FeedEntry, FeedSource, Rule, Season, Series, utcnow
from app.schemas import (
    ConditionOut,
    DownloadOut,
    GrabPreviewOut,
    ParsedReleaseOut,
    PollResultOut,
    SimulationResultOut,
)
from app.services import activity, dispatcher, matcher, paths, settings_store
from app.services.feeds import FeedFetchError, fetch_feed
from app.services.matcher import RuleLike, SeasonLike, SeriesLike
from app.services.parser import parse_title
from app.services.types import Evaluation as EvalResult
from app.services.types import ParsedRelease

log = structlog.get_logger("poller")

_feed_locks: dict[int, threading.Lock] = {}
_feed_locks_guard = threading.Lock()


class PollInProgress(Exception):
    """A poll for this feed is already running."""


class GrabError(Exception):
    """Manual grab not possible. `status_code` hints the HTTP status (400/404/409)."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _lock_for(feed_id: int) -> threading.Lock:
    with _feed_locks_guard:
        lock = _feed_locks.get(feed_id)
        if lock is None:
            lock = _feed_locks[feed_id] = threading.Lock()
        return lock


def is_polling(feed_id: int) -> bool:
    return _lock_for(feed_id).locked()


# ---------------------------------------------------------------- evaluation


def _parsed(entry: FeedEntry) -> ParsedRelease:
    if entry.parsed:
        return ParsedRelease.from_dict(entry.parsed)
    return parse_title(entry.title)


def _rules_query(enabled_only: bool = True) -> Any:
    stmt = select(Rule).options(selectinload(Rule.series).selectinload(Series.seasons), selectinload(Rule.season))
    if enabled_only:
        stmt = stmt.where(Rule.enabled.is_(True))
    return stmt.order_by(Rule.priority.desc(), Rule.id)


def active_rules(db: Session) -> list[Rule]:
    """Enabled rules of monitored series (and monitored bound season, if any)."""
    return [r for r in db.scalars(_rules_query()) if r.series.monitored and (r.season is None or r.season.monitored)]


def _store_evaluation(db: Session, entry: FeedEntry, rule: Rule, res: EvalResult) -> Evaluation:
    row = db.scalar(select(Evaluation).where(Evaluation.entry_id == entry.id, Evaluation.rule_id == rule.id))
    if row is None:
        row = Evaluation(entry_id=entry.id, rule_id=rule.id)
        db.add(row)
    row.matched = res.matched
    row.season_id = res.season_id
    row.episode_number = res.episode_number
    row.conditions = res.conditions_as_dicts()
    row.evaluated_at = utcnow()
    return row


def _evaluate_rules(db: Session, entry: FeedEntry, rules: Sequence[Rule], store: bool) -> list[tuple[Rule, EvalResult]]:
    parsed = _parsed(entry)
    out: list[tuple[Rule, EvalResult]] = []
    for rule in rules:
        res = matcher.evaluate(parsed, entry.title, entry.size_bytes, rule, rule.series, rule.series.seasons)
        if store:
            _store_evaluation(db, entry, rule, res)
        out.append((rule, res))
    if store:
        db.flush()
    return out


def evaluate_entry(db: Session, entry: FeedEntry, settings: Settings, store: bool = True) -> list[Evaluation]:
    """Re-run every enabled rule (regardless of monitored state) against `entry`; store rows; no dispatch."""
    rules = list(db.scalars(_rules_query()))
    _evaluate_rules(db, entry, rules, store=store)
    db.flush()
    db.refresh(entry, ["evaluations"])
    return list(entry.evaluations)


# ---------------------------------------------------------------- simulation


@dataclass
class _SimSeries:
    id: int
    name: str
    aliases: list[str]
    season_folder_format: str
    path_override: str | None


@dataclass
class _SimSeason:
    id: int
    season_number: int
    monitored: bool
    episode_min: int | None
    episode_max: int | None
    absolute_min: int | None
    absolute_max: int | None
    path_override: str | None


def _sim_result(
    title: str,
    parsed: ParsedRelease,
    res: EvalResult,
    series: Any,
    seasons: Sequence[Any],
    media_base: str,
) -> SimulationResultOut:
    save_path: str | None = None
    if res.matched and res.season_id is not None:
        season = next((s for s in seasons if s.id == res.season_id), None)
        if season is not None:
            try:
                save_path = paths.build_save_path(media_base, series, season)
            except paths.PathError:
                save_path = None
    return SimulationResultOut(
        title=title,
        parsed=ParsedReleaseOut.from_parsed(parsed),
        matched=res.matched,
        season_number=res.season_number,
        episode_number=res.episode_number,
        save_path=save_path,
        conditions=[ConditionOut.from_any(c) for c in res.conditions],
    )


def simulate_rule(
    rule: RuleLike,
    titles: Sequence[str],
    series: SeriesLike,
    seasons: Sequence[SeasonLike],
    media_base: str,
    sizes: Sequence[int | None] | None = None,
) -> list[SimulationResultOut]:
    """Evaluate `rule` against raw titles without side effects (save_path computed when matched)."""
    out: list[SimulationResultOut] = []
    for i, title in enumerate(titles):
        parsed = parse_title(title)
        size = sizes[i] if sizes is not None else None
        res = matcher.evaluate(parsed, title, size, rule, series, seasons)
        out.append(_sim_result(title, parsed, res, series, seasons, media_base))
    return out


def build_sim_series(data: Any) -> tuple[_SimSeries, list[_SimSeason]]:
    """In-memory series/seasons from an unsaved `schemas.SeriesIn` (season ids are 0-based indexes)."""
    series = _SimSeries(
        id=0,
        name=data.name,
        aliases=list(data.aliases or []),
        season_folder_format=data.season_folder_format,
        path_override=data.path_override,
    )
    seasons = [
        _SimSeason(
            id=i,
            season_number=s.season_number,
            monitored=s.monitored,
            episode_min=s.episode_min,
            episode_max=s.episode_max,
            absolute_min=s.absolute_min,
            absolute_max=s.absolute_max,
            path_override=s.path_override,
        )
        for i, s in enumerate(data.seasons or [])
    ]
    return series, seasons


# ---------------------------------------------------------------- polling


def _summary_season(season: Season | None, ep: int | None) -> str:
    if season is None or ep is None:
        return ""
    return f"S{season.season_number:02d}E{ep:02d}"


def poll_feed(db: Session, feed_id: int, settings: Settings) -> PollResultOut:
    """Poll one feed (fetch, upsert, evaluate, dispatch). Raises PollInProgress / LookupError."""
    lock = _lock_for(feed_id)
    if not lock.acquire(blocking=False):
        log.info("poll_skipped_in_progress", feed_id=feed_id)
        raise PollInProgress(f"poll already in progress for feed {feed_id}")
    try:
        return _poll(db, feed_id, settings)
    finally:
        lock.release()


def _poll(db: Session, feed_id: int, settings: Settings) -> PollResultOut:
    feed = db.get(FeedSource, feed_id)
    if feed is None:
        raise LookupError(f"feed {feed_id} not found")
    result = PollResultOut()
    now = utcnow()
    feed.last_checked_at = now
    timeout = float(settings_store.get(db, settings_store.FEED_FETCH_TIMEOUT_SECONDS) or 20)
    try:
        fetched = fetch_feed(
            feed.url,
            etag=feed.etag,
            last_modified=feed.last_modified,
            timeout=timeout,
            allow_private=settings_store.allow_private_feed_hosts(db, settings),
        )
    except FeedFetchError as exc:
        feed.last_status = "error"
        feed.last_error = str(exc)
        feed.consecutive_failures = (feed.consecutive_failures or 0) + 1
        result.errors.append(str(exc))
        activity.log_event(
            db,
            "error" if not exc.transient else "warning",
            "feed_error",
            f"Feed '{feed.name}' fetch failed: {exc}",
            details={"feed_id": feed.id, "transient": exc.transient, "consecutive_failures": feed.consecutive_failures},
        )
        db.commit()
        return result

    feed.etag = fetched.etag
    feed.last_modified = fetched.last_modified
    if fetched.not_modified:
        feed.last_status = "ok"
        feed.last_success_at = now
        feed.last_error = None
        feed.consecutive_failures = 0
        activity.log_event(db, "info", "feed_poll", f"Feed '{feed.name}': not modified", details={"feed_id": feed.id})
        db.commit()
        return result

    result.fetched = len(fetched.entries)
    historical = (not feed.initial_poll_done) and feed.backfill_mode == "skip"

    # upsert new entries (oldest first so ids ascend with time)
    guids = list(dict.fromkeys(pe.guid for pe in fetched.entries))
    existing: set[str] = set()
    for i in range(0, len(guids), 500):
        existing.update(
            db.scalars(
                select(FeedEntry.guid).where(FeedEntry.feed_id == feed.id, FeedEntry.guid.in_(guids[i : i + 500]))
            )
        )
    new_entries: list[FeedEntry] = []
    seen: set[str] = set()
    for pe in reversed(fetched.entries):
        if pe.guid in existing or pe.guid in seen:
            continue
        seen.add(pe.guid)
        entry = FeedEntry(
            feed_id=feed.id,
            guid=pe.guid,
            title=pe.title,
            link=pe.link,
            published_at=pe.published_at,
            first_seen_at=now,
            magnet_url=pe.magnet_url,
            torrent_url=pe.torrent_url,
            nzb_url=pe.nzb_url,
            size_bytes=pe.size_bytes,
            infohash=pe.infohash,
            parsed=pe.parsed.to_dict(),
            is_historical=historical,
            outcome="historical" if historical else "unprocessed",
            outcome_summary="seen on first poll (backfill skipped)" if historical else None,
            processed_at=now if historical else None,
        )
        db.add(entry)
        new_entries.append(entry)
    db.flush()
    result.new_entries = len(new_entries)

    rules = active_rules(db)
    created: list[Download] = []
    for entry in new_entries:
        if entry.outcome == "searched":  # defensive: search results are never auto-dispatched
            continue
        evals = _evaluate_rules(db, entry, rules, store=True)
        if historical:
            result.historical += 1
            continue
        _process_entry(db, entry, evals, settings, result, created, now)

    feed.initial_poll_done = True
    feed.last_status = "ok"
    feed.last_success_at = now
    feed.last_error = None
    feed.consecutive_failures = 0
    db.commit()

    # dispatch inline
    for d in created:
        try:
            dispatcher.submit(db, d, settings)
        except Exception as exc:  # defensive: one bad download must not abort the poll
            log.exception("submit_crashed", download_id=d.id)
            result.errors.append(f"download {d.id}: {exc}")
        db.commit()
        if d.status in dispatcher.SENT_STATUSES:
            result.submitted += 1
        elif d.last_error and d.status in ("pending", "failed"):
            result.errors.append(f"download {d.id}: {d.last_error}")

    activity.log_event(
        db,
        "info",
        "feed_poll",
        (
            f"Feed '{feed.name}': {result.fetched} fetched, {result.new_entries} new, {result.historical} historical, "
            f"{result.accepted} accepted, {result.duplicate} duplicate, {result.rejected} rejected, "
            f"{result.no_match} no match, {result.submitted} submitted"
        ),
        details={"feed_id": feed.id, **result.model_dump(exclude={"errors"}), "errors": result.errors[:10]},
    )
    db.commit()
    return result


def _process_entry(
    db: Session,
    entry: FeedEntry,
    evals: list[tuple[Rule, EvalResult]],
    settings: Settings,
    result: PollResultOut,
    created: list[Download],
    now: Any,
) -> None:
    entry.processed_at = now
    if not evals:
        entry.outcome, entry.outcome_summary = "no_match", "no active rules"
        result.no_match += 1
        return
    matched = [(r, e) for r, e in evals if e.matched and e.season_id is not None and e.episode_number is not None]
    if not matched:
        entry.outcome, entry.outcome_summary = "no_match", f"no rule matched ({len(evals)} evaluated)"
        result.no_match += 1
        return

    groups: dict[tuple[int, int], list[tuple[Rule, EvalResult]]] = {}
    for r, e in matched:
        assert e.season_id is not None and e.episode_number is not None
        groups.setdefault((e.season_id, e.episode_number), []).append((r, e))

    outcomes: list[tuple[str, str]] = []
    for (season_id, ep), items in groups.items():
        rule, _ = sorted(items, key=lambda it: (-it[0].priority, it[0].id))[0]
        season = db.get(Season, season_id)
        if season is None:  # pragma: no cover - season deleted concurrently
            continue
        tag = _summary_season(season, ep)
        if dispatcher.choose_source(entry) is None:
            outcomes.append(("rejected", f"{dispatcher.no_source_reason(entry)} (matched rule '{rule.name}' {tag})"))
            continue
        dup = dispatcher.find_duplicate(db, season_id, ep, entry.infohash)
        if dup is not None:
            outcomes.append(("duplicate", f"duplicate of download #{dup.id} ({tag}, {dup.status})"))
            continue
        try:
            d = dispatcher.create_download(db, entry, season, ep, rule, settings)
        except paths.PathError as exc:
            outcomes.append(("rejected", f"invalid save path: {exc} (rule '{rule.name}')"))
            continue
        created.append(d)
        outcomes.append(("accepted", f"accepted by rule '{rule.name}': {tag} -> {d.save_path}"))

    rank = {"accepted": 0, "duplicate": 1, "rejected": 2}
    outcomes.sort(key=lambda o: rank[o[0]])
    entry.outcome = outcomes[0][0] if outcomes else "no_match"
    entry.outcome_summary = "; ".join(s for _, s in outcomes) if outcomes else "no rule matched"
    setattr(result, entry.outcome, getattr(result, entry.outcome) + 1)
    level: activity.ActivityLevel = {"accepted": "info", "duplicate": "info", "rejected": "warning"}.get(
        entry.outcome, "info"
    )  # type: ignore[assignment]
    activity.log_event(
        db,
        level,
        f"entry_{entry.outcome}",
        f"'{entry.title}': {entry.outcome_summary}",
        details={"feed_id": entry.feed_id},
        entry_id=entry.id,
        download_id=created[-1].id if entry.outcome == "accepted" and created else None,
    )


# ---------------------------------------------------------------- manual grab


def build_grab_preview(
    db: Session, entry: FeedEntry, season_id: int, episode_number: int, force: bool, settings: Settings
) -> GrabPreviewOut:
    season = db.get(Season, season_id)
    if season is None:
        raise GrabError("season not found", 404)
    source = dispatcher.choose_source(entry)
    if source is None:
        raise GrabError(dispatcher.no_source_reason(entry), 400)
    try:
        save_path, category = dispatcher.compute_target(db, season, settings)
    except paths.PathError as exc:
        raise GrabError(f"invalid save path: {exc}", 400) from exc
    dup = dispatcher.find_duplicate(db, season.id, episode_number, entry.infohash)
    warnings: list[str] = []
    if entry.is_historical:
        warnings.append("This entry is historical (seen on the feed's first poll).")
    if dup is not None:
        if entry.infohash and dup.infohash == entry.infohash:
            warnings.append(f"The same torrent is already tracked as download #{dup.id}; it cannot be grabbed again.")
        elif force:
            warnings.append(f"Download #{dup.id} already exists for this episode; force will add another.")
        else:
            warnings.append(f"Download #{dup.id} already exists for this episode; enable force to grab anyway.")
    parsed = _parsed(entry)
    if parsed.episode is not None and parsed.episode != episode_number and parsed.season is not None:
        warnings.append(f"Title says episode {parsed.episode}, but episode {episode_number} was chosen.")
    if not season.series.monitored:
        warnings.append("Series is not monitored.")
    if not season.monitored:
        warnings.append("Season is not monitored.")
    if not settings_store.get_qbit_credentials(db, settings).configured:
        warnings.append("qBittorrent is not configured; the download will stay pending.")
    return GrabPreviewOut(
        entry_id=entry.id,
        season_id=season.id,
        episode_number=episode_number,
        save_path=save_path,
        category=category,
        source_url=source[0],
        source_url_kind=source[1],  # type: ignore[arg-type]
        infohash=entry.infohash,
        duplicate_of=DownloadOut.from_model(dup) if dup is not None else None,
        warnings=warnings,
    )


def perform_grab(
    db: Session, entry: FeedEntry, season_id: int, episode_number: int, force: bool, settings: Settings
) -> Download:
    """Create + submit a manual download. Raises GrabError (409 on duplicate without force). Commits."""
    preview = build_grab_preview(db, entry, season_id, episode_number, force, settings)
    dup = dispatcher.find_duplicate(db, season_id, episode_number, entry.infohash)
    if dup is not None:
        if entry.infohash and dup.infohash == entry.infohash:
            raise GrabError(f"the same torrent is already tracked as download #{dup.id}", 409)
        if not force:
            raise GrabError(f"duplicate: download #{dup.id} already exists for this episode", 409)
    season = db.get(Season, season_id)
    assert season is not None
    d = dispatcher.create_download(db, entry, season, episode_number, None, settings, forced=dup is not None)
    activity.log_event(
        db,
        "info",
        "manual_grab",
        f"Manual grab of '{entry.title}' -> {preview.save_path}" + (" (forced)" if d.forced else ""),
        entry_id=entry.id,
        download_id=d.id,
    )
    db.commit()
    dispatcher.submit(db, d, settings)
    db.commit()
    return d

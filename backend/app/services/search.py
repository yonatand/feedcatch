"""Release search (historic / missed episodes) through feed search URL templates. See `.claude/rules/episodes.md`.

Entries found here are stored with outcome 'searched' (existing entries keep their outcome) and are never
auto-dispatched by the poller; only `grab_missing` (explicit user action or the opt-in `search_missing` job)
sends them, through the normal dispatcher path with the normal duplicate rules.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote_plus

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Download, FeedEntry, FeedSource, Rule, Season, utcnow
from app.services import activity, dispatcher, matcher, paths, settings_store, ssrf
from app.services.episodes import HAVE_STATUSES, compute_status, downloads_by_episode, wanted
from app.services.feeds import FeedFetchError, ParsedEntry, fetch_feed
from app.services.poller import _parsed, _store_evaluation

log = structlog.get_logger("search")

MAX_FETCHES_PER_SEARCH = 6
MAX_ALIASES = 2
SEARCH_ALL_MAX_SEASONS = 10
JOB_MAX_SEASONS = 20

# Held while a multi-season search runs (API search-all or the scheduler job): a second one gets 409 / is skipped.
search_all_lock = threading.Lock()
sleep: Callable[[float], None] = time.sleep  # tests replace it


class SearchError(Exception):
    """Search not possible (e.g. no feed has a search template). `status_code` hints the HTTP status."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class Candidate:
    entry: FeedEntry
    episode_number: int
    rule: Rule
    conditions: list[dict[str, Any]]
    save_path: str | None
    episode_status: str

    @property
    def already_have(self) -> bool:
        return self.episode_status in HAVE_STATUSES


@dataclass
class SearchResult:
    queries: list[str] = field(default_factory=list)
    feeds_searched: list[str] = field(default_factory=list)
    fetched: int = 0
    candidates: list[Candidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class GrabMissingResult:
    grabbed: list[Download] = field(default_factory=list)
    skipped: list[tuple[int, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class _SeasonView:
    """Season as seen by the matcher during a search: monitored flags are ignored (search is explicit)."""

    id: int
    season_number: int
    episode_min: int | None
    episode_max: int | None
    absolute_min: int | None
    absolute_max: int | None
    monitored: bool = True


# ---------------------------------------------------------------- templates / queries


def validate_template(template: str, allow_private: bool) -> str:
    """`{query}` exactly once; the URL with `{query}` -> `test` must pass SSRF checks. Raises ValueError/SsrfError."""
    template = template.strip()
    if template.count("{query}") != 1:
        raise ValueError("search URL template must contain {query} exactly once")
    ssrf.validate_feed_url(template.replace("{query}", "test"), allow_private)
    return template


def build_url(template: str, query: str) -> str:
    return template.replace("{query}", quote_plus(query))


def build_queries(series_name: str, aliases: list[str], season: Season, query: str | None = None) -> list[str]:
    """[query] if given, else unique [name] + aliases[:2], suffixed ` S02` unless the season is absolute-numbered."""
    if query and query.strip():
        return [" ".join(query.split())]
    names = [series_name, *(aliases or [])[:MAX_ALIASES]]
    suffix = "" if season.absolute_min is not None else f" S{season.season_number:02d}"
    out: list[str] = []
    seen: set[str] = set()
    for n in names:
        n = " ".join((n or "").split())
        if not n:
            continue
        q = f"{n}{suffix}"
        if q.casefold() not in seen:
            seen.add(q.casefold())
            out.append(q)
    return out


def searchable_feeds(db: Session) -> list[FeedSource]:
    return list(
        db.scalars(
            select(FeedSource)
            .where(FeedSource.enabled.is_(True), FeedSource.search_url_template.is_not(None))
            .order_by(FeedSource.id)
        )
    )


def _season_rules(db: Session, season: Season) -> list[Rule]:
    return list(
        db.scalars(
            select(Rule)
            .where(
                Rule.series_id == season.series_id,
                Rule.enabled.is_(True),
                (Rule.season_id.is_(None)) | (Rule.season_id == season.id),
            )
            .order_by(Rule.priority.desc(), Rule.id)
        )
    )


def _upsert(db: Session, feed: FeedSource, pe: ParsedEntry, now: Any) -> FeedEntry:
    entry = db.scalar(select(FeedEntry).where(FeedEntry.feed_id == feed.id, FeedEntry.guid == pe.guid))
    if entry is not None:
        return entry  # keeps its outcome (accepted / historical / ...)
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
        is_historical=False,
        outcome="searched",
        outcome_summary="found by release search",
        processed_at=now,
    )
    db.add(entry)
    db.flush()
    return entry


# ---------------------------------------------------------------- search


def search_season(db: Session, season: Season, settings: Settings, query: str | None = None) -> SearchResult:
    """Search every enabled feed with a template for this season's releases; evaluate the series' rules. Commits."""
    feeds = searchable_feeds(db)
    if not feeds:
        raise SearchError("no enabled feed has a search URL template", 400)
    series = season.series
    result = SearchResult(queries=build_queries(series.name, list(series.aliases or []), season, query))
    if not result.queries:
        raise SearchError("nothing to search for (empty query)", 400)
    timeout = float(settings_store.get(db, settings_store.FEED_FETCH_TIMEOUT_SECONDS) or 20)
    allow_private = settings_store.allow_private_feed_hosts(db, settings)
    delay = settings_store.get_int(db, settings_store.SEARCH_DELAY_SECONDS, 0)
    now = utcnow()

    entries: dict[int, FeedEntry] = {}
    fetches = 0
    for feed in feeds:
        for q in result.queries:
            if fetches >= MAX_FETCHES_PER_SEARCH:
                result.errors.append(f"stopped after {MAX_FETCHES_PER_SEARCH} search requests")
                break
            if fetches and delay:
                sleep(delay)
            fetches += 1
            template = feed.search_url_template or ""
            try:
                fetched = fetch_feed(build_url(template, q), timeout=timeout, allow_private=allow_private)
            except FeedFetchError as exc:
                result.errors.append(f"{feed.name} ({q}): {exc}")
                continue
            if feed.name not in result.feeds_searched:
                result.feeds_searched.append(feed.name)
            result.fetched += len(fetched.entries)
            for pe in fetched.entries:
                entry = _upsert(db, feed, pe, now)
                entries[entry.id] = entry
        else:
            continue
        break

    rules = _season_rules(db, season)
    views = [
        _SeasonView(
            id=s.id,
            season_number=s.season_number,
            episode_min=s.episode_min,
            episode_max=s.episode_max,
            absolute_min=s.absolute_min,
            absolute_max=s.absolute_max,
        )
        for s in series.seasons
    ]
    try:
        save_path: str | None = dispatcher.compute_target(db, season, settings)[0]
    except paths.PathError:
        save_path = None

    best: dict[tuple[int, int], tuple[Rule, list[dict[str, Any]]]] = {}
    for entry in entries.values():
        parsed = _parsed(entry)
        for rule in rules:
            res = matcher.evaluate(parsed, entry.title, entry.size_bytes, rule, series, views)
            _store_evaluation(db, entry, rule, res)
            if not res.matched or res.season_id != season.id or res.episode_number is None:
                continue
            key = (entry.id, res.episode_number)
            if key not in best:  # rules are ordered priority desc, id asc
                best[key] = (rule, res.conditions_as_dicts())
    db.flush()

    ep_dates = {e.episode_number: e.air_date for e in season.episodes}
    dls = downloads_by_episode(db, [season.id])
    for (entry_id, ep), (rule, conds) in best.items():
        status = compute_status(ep_dates.get(ep), dls.get((season.id, ep), []), now).status
        result.candidates.append(
            Candidate(
                entry=entries[entry_id],
                episode_number=ep,
                rule=rule,
                conditions=conds,
                save_path=save_path,
                episode_status=status,
            )
        )
    result.candidates.sort(
        key=lambda c: (
            c.episode_number,
            -c.rule.priority,
            -(c.entry.published_at.timestamp() if c.entry.published_at else 0),
            c.entry.id,
        )
    )
    db.commit()
    log.info(
        "release_search",
        season_id=season.id,
        queries=result.queries,
        fetched=result.fetched,
        candidates=len(result.candidates),
        errors=len(result.errors),
    )
    return result


# ---------------------------------------------------------------- grab missing


def grab_missing(
    db: Session, season: Season, settings: Settings, result: SearchResult | None = None, query: str | None = None
) -> GrabMissingResult:
    """Grab the best candidate for every missing episode (or unknown when the season has no metadata). Commits."""
    if result is None:
        result = search_season(db, season, settings, query)
    out = GrabMissingResult(errors=list(result.errors))
    now = utcnow()
    rows = {e.episode_number: e.air_date for e in season.episodes}
    has_metadata = bool(rows)
    by_ep: dict[int, list[Candidate]] = {}
    for c in result.candidates:
        by_ep.setdefault(c.episode_number, []).append(c)
    dls = downloads_by_episode(db, [season.id])

    for n in sorted(set(rows) | set(by_ep)):
        cands = by_ep.get(n, [])
        if has_metadata and n not in rows:
            out.skipped.append((n, "not in the episode list"))
            continue
        status = compute_status(rows.get(n), dls.get((season.id, n), []), now).status
        if status in HAVE_STATUSES:
            if cands:
                out.skipped.append((n, "already have"))
            continue
        if status == "unaired":
            if cands:
                out.skipped.append((n, "unaired"))
            continue
        if status == "unknown" and has_metadata:
            if cands:
                out.skipped.append((n, "air date unknown"))
            continue
        if not cands:
            out.skipped.append((n, "no candidate"))
            continue
        reason = "no usable candidate (no torrent/magnet link)"
        for c in cands:
            if dispatcher.choose_source(c.entry) is None:
                continue
            dup = dispatcher.find_duplicate(db, season.id, n, c.entry.infohash)
            if dup is not None:
                reason = f"already have (download #{dup.id})"
                break
            try:
                d = dispatcher.create_download(db, c.entry, season, n, c.rule, settings)
            except paths.PathError as exc:
                reason = f"invalid save path: {exc}"
                break
            activity.log_event(
                db,
                "info",
                "search_grab",
                f"Search grab of '{c.entry.title}' for S{season.season_number:02d}E{n:02d} -> {d.save_path}",
                details={"season_id": season.id, "episode_number": n, "rule_id": c.rule.id},
                entry_id=c.entry.id,
                download_id=d.id,
            )
            db.commit()
            try:
                dispatcher.submit(db, d, settings)
            except Exception as exc:  # defensive: one bad submit must not abort the batch
                log.exception("submit_crashed", download_id=d.id)
                out.errors.append(f"download {d.id}: {exc}")
            db.commit()
            out.grabbed.append(d)
            reason = ""
            break
        if reason:
            out.skipped.append((n, reason))
    db.commit()
    return out


# ---------------------------------------------------------------- multi-season


def seasons_with_missing(db: Session, limit: int) -> list[Season]:
    """Monitored seasons with missing episodes, the one with the newest missing episode first."""
    order: list[int] = []
    for row in wanted(db):
        if row.season.id not in order:
            order.append(row.season.id)
        if len(order) >= limit:
            break
    return [s for s in (db.get(Season, sid) for sid in order) if s is not None]


def search_and_grab_seasons(db: Session, settings: Settings, limit: int) -> list[dict[str, Any]]:
    """Run search + grab_missing for up to `limit` seasons with missing episodes. Caller holds `search_all_lock`."""
    out: list[dict[str, Any]] = []
    for season in seasons_with_missing(db, limit):
        item: dict[str, Any] = {
            "season_id": season.id,
            "series_name": season.series.name,
            "season_number": season.season_number,
            "grabbed": 0,
            "skipped": 0,
            "errors": [],
        }
        try:
            res = grab_missing(db, season, settings)
            item["grabbed"], item["skipped"], item["errors"] = len(res.grabbed), len(res.skipped), res.errors[:10]
        except SearchError as exc:
            item["errors"] = [str(exc)]
        except Exception as exc:  # one failing season must not stop the others
            db.rollback()
            log.exception("season_search_failed", season_id=season.id)
            item["errors"] = [f"{type(exc).__name__}: {exc}"]
        activity.log_event(
            db,
            "warning" if item["errors"] else "info",
            "missing_search",
            f"Missing-episode search for '{item['series_name']}' S{season.season_number:02d}: "
            f"{item['grabbed']} grabbed, {item['skipped']} skipped, {len(item['errors'])} errors",
            details={k: item[k] for k in ("season_id", "grabbed", "skipped", "errors")},
        )
        db.commit()
        out.append(item)
    return out

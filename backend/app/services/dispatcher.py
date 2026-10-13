"""Download creation and idempotent submission to qBittorrent.

Safety: no filesystem access (invariant 1); only magnet / .torrent URLs are sent (invariant 2);
every add is preceded by an infohash check in DB and qBittorrent, and uncertain results never
trigger a blind re-add (invariant 7).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import structlog
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Download, FeedEntry, Rule, Season, utcnow
from app.services import activity, paths, settings_store
from app.services.feeds import is_nzb_url, is_torrent_url
from app.services.matcher import norm
from app.services.qbit import QbitClient, QbitError
from app.services.settings_store import QbitCredentials

log = structlog.get_logger("dispatcher")

MAX_ATTEMPTS = 8
# Tunables (tests set these to 0).
POST_ADD_SETTLE_SECONDS = 1.0
RESOLVE_TIMEOUT_SECONDS = 10.0
RESOLVE_POLL_SECONDS = 1.0

SENT_STATUSES = ("submitted", "path_mismatch")


class NoSourceError(ValueError):
    """Entry has no magnet/.torrent URL (e.g. NZB-only)."""


def _default_client_factory(creds: QbitCredentials) -> QbitClient:
    return QbitClient(creds.url, creds.username, creds.password, timeout=creds.timeout_seconds)


client_factory: Callable[[QbitCredentials], QbitClient] = _default_client_factory


# ---------------------------------------------------------------- creation


def choose_source(entry: FeedEntry) -> tuple[str, str] | None:
    """(url, kind) preferring magnet over .torrent. Never an NZB URL."""
    if entry.magnet_url and entry.magnet_url.lower().startswith("magnet:?"):
        return entry.magnet_url, "magnet"
    if entry.torrent_url and is_torrent_url(entry.torrent_url) and not is_nzb_url(entry.torrent_url):
        return entry.torrent_url, "torrent"
    return None


def no_source_reason(entry: FeedEntry) -> str:
    return "no torrent/magnet link (NZB-only)" if entry.nzb_url else "no torrent/magnet link"


def find_duplicate(
    db: Session, season_id: int, episode_number: int, infohash: str | None, exclude_id: int | None = None
) -> Download | None:
    """An existing non-failed download for the same episode (non-forced) or the same infohash."""
    cond = and_(Download.season_id == season_id, Download.episode_number == episode_number, Download.forced.is_(False))
    if infohash:
        cond = or_(cond, Download.infohash == infohash.lower())
    stmt = select(Download).where(Download.status != "failed", cond)
    if exclude_id is not None:
        stmt = stmt.where(Download.id != exclude_id)
    return db.scalars(stmt.order_by(Download.id)).first()


def compute_target(db: Session, season: Season, settings: Settings) -> tuple[str, str | None]:
    """(save_path, category) for a season. Raises PathError."""
    series = season.series
    save_path = paths.build_save_path(settings_store.get_media_base_path(db), series, season)
    creds = settings_store.get_qbit_credentials(db, settings)
    return save_path, (series.category_override or creds.category)


def create_download(
    db: Session,
    entry: FeedEntry,
    season: Season,
    episode_number: int,
    rule: Rule | None,
    settings: Settings,
    forced: bool = False,
) -> Download:
    """Create a pending Download row (flushed). Raises NoSourceError / PathError."""
    source = choose_source(entry)
    if source is None:
        raise NoSourceError(no_source_reason(entry))
    save_path, category = compute_target(db, season, settings)
    d = Download(
        entry_id=entry.id,
        series_id=season.series_id,
        season_id=season.id,
        episode_number=episode_number,
        rule_id=rule.id if rule is not None else None,
        infohash=entry.infohash.lower() if entry.infohash else None,
        source_url=source[0],
        source_url_kind=source[1],
        save_path=save_path,
        category=category,
        status="pending",
        attempts=0,
        forced=forced,
    )
    db.add(d)
    db.flush()
    return d


# ---------------------------------------------------------------- submission


def _norm_path(p: str | None) -> str:
    return (p or "").rstrip("/") or "/"


def _apply_torrent(d: Download, t: dict[str, Any]) -> None:
    d.qbit_hash = str(t.get("hash") or d.qbit_hash or "") or None
    d.qbit_state = t.get("state")
    prog = t.get("progress")
    d.qbit_progress = float(prog) if isinstance(prog, int | float) else d.qbit_progress
    d.qbit_save_path = t.get("save_path")


def _path_matches(d: Download) -> bool:
    return d.qbit_save_path is None or _norm_path(d.qbit_save_path) == _norm_path(d.save_path)


def _event(db: Session, d: Download, level: activity.ActivityLevel, event_type: str, message: str) -> None:
    activity.log_event(
        db,
        level,
        event_type,
        message,
        details={"status": d.status, "save_path": d.save_path, "attempts": d.attempts, "last_error": d.last_error},
        entry_id=d.entry_id,
        download_id=d.id,
    )


def _label(d: Download) -> str:
    title = d.entry.title if d.entry is not None else f"entry {d.entry_id}"
    return f"'{title}'"


def _title_stem(title: str) -> str:
    t = title.split(" | ", 1)[0]
    for ext in (".mkv", ".mp4", ".avi", ".torrent"):
        if t.lower().endswith(ext):
            t = t[: -len(ext)]
    return norm(t)


def _find_by_name(client: QbitClient, title: str, since_ts: float) -> dict[str, Any] | None:
    stem = _title_stem(title)
    if not stem:
        return None
    for t in client.info():
        added = t.get("added_on")
        if isinstance(added, int | float) and added + 2 < since_ts:
            continue
        name = norm(str(t.get("name") or ""))
        if name and (name == stem or name.startswith(stem) or stem.startswith(name)):
            return t
    return None


def _mark_exists(db: Session, d: Download, t: dict[str, Any]) -> None:
    _apply_torrent(d, t)
    d.status = "exists"
    d.next_retry_at = None
    if _path_matches(d):
        d.last_error = None
        _event(db, d, "info", "download_exists", f"{_label(d)} is already in qBittorrent; not re-added")
    else:
        d.last_error = f"already in qBittorrent with save path {d.qbit_save_path!r} (expected {d.save_path!r})"
        _event(db, d, "warning", "download_exists", f"{_label(d)} already in qBittorrent at a different path")


def _fail_or_retry(db: Session, d: Download, exc: QbitError) -> None:
    d.last_error = str(exc)
    if exc.transient and d.attempts < MAX_ATTEMPTS:
        d.status = "pending"
        d.next_retry_at = utcnow() + timedelta(minutes=min(2**d.attempts, 60))
        _event(db, d, "warning", "download_retry_scheduled", f"{_label(d)}: {exc}; retry scheduled")
    else:
        d.status = "failed"
        d.next_retry_at = None
        if exc.transient:
            d.last_error = f"{exc} (gave up after {d.attempts} attempts)"
        _event(db, d, "error", "download_failed", f"{_label(d)} failed: {d.last_error}")


def submit(db: Session, download: Download, settings: Settings) -> Download:
    """Submit one download idempotently (see architecture.md). Flushes; caller commits."""
    d = download
    if d.status not in ("pending",):
        return d
    creds = settings_store.get_qbit_credentials(db, settings)
    d.attempts += 1
    if not creds.configured:
        _fail_or_retry(db, d, QbitError("qBittorrent is not configured", transient=True))
        db.flush()
        return d
    # Invariant 2 re-check: never send anything but magnet / .torrent.
    if d.source_url_kind == "magnet":
        sendable = d.source_url.lower().startswith("magnet:?")
    else:
        sendable = is_torrent_url(d.source_url)
    if not sendable:
        _fail_or_retry(db, d, QbitError("source URL is not a magnet or .torrent link", transient=False))
        db.flush()
        return d

    title = d.entry.title if d.entry is not None else ""
    try:
        client = client_factory(creds)
    except QbitError as exc:
        _fail_or_retry(db, d, exc)
        db.flush()
        return d
    with client:
        # 1. pre-check: already present?
        try:
            if d.infohash:
                present = client.info([d.infohash])
                if present:
                    _mark_exists(db, d, present[0])
                    db.flush()
                    return d
            elif d.attempts > 1:
                # previous attempt may have reached qBittorrent: look for it by name instead of blindly re-adding
                found = _find_by_name(client, title, d.created_at.timestamp())
                if found is not None:
                    _mark_exists(db, d, found)
                    db.flush()
                    return d
            submit_ts = time.time()
            client.add(d.source_url, d.save_path, d.category, paused=not creds.start_immediately)
        except QbitError as exc:
            _fail_or_retry(db, d, exc)
            db.flush()
            return d

        # 2. verify
        warn: str | None = None
        torrent: dict[str, Any] | None = None
        try:
            if POST_ADD_SETTLE_SECONDS:
                time.sleep(POST_ADD_SETTLE_SECONDS)
            if d.infohash:
                found_list = client.info([d.infohash])
                torrent = found_list[0] if found_list else None
                if torrent is None:
                    warn = "added; not yet visible in torrents/info"
            else:
                deadline = time.monotonic() + RESOLVE_TIMEOUT_SECONDS
                while True:
                    torrent = _find_by_name(client, title, submit_ts)
                    if torrent is not None or time.monotonic() >= deadline:
                        break
                    time.sleep(RESOLVE_POLL_SECONDS)
                if torrent is None:
                    warn = "added, but the torrent hash could not be resolved in qBittorrent"
        except QbitError as exc:
            warn = f"added, but verification failed: {exc}"

    d.next_retry_at = None
    if torrent is not None:
        _apply_torrent(d, torrent)
        if d.infohash is None and d.qbit_hash:
            d.infohash = d.qbit_hash.lower()
    elif d.infohash:
        d.qbit_hash = d.infohash
    if torrent is not None and not _path_matches(d):
        d.status = "path_mismatch"
        d.last_error = (
            f"qBittorrent reports save path {d.qbit_save_path!r} but {d.save_path!r} was requested; "
            "check qBittorrent's path settings"
        )
        _event(db, d, "warning", "download_path_mismatch", f"{_label(d)} sent, but save path differs")
    else:
        d.status = "submitted"
        d.last_error = warn
        _event(db, d, "info", "download_submitted", f"{_label(d)} sent to qBittorrent -> {d.save_path}")
    db.flush()
    return d


def retry_due(db: Session, settings: Settings) -> int:
    """Submit pending downloads whose retry time has come. Commits after each. Returns number attempted."""
    now = utcnow()
    due = list(
        db.scalars(
            select(Download)
            .where(
                Download.status == "pending",
                or_(Download.next_retry_at.is_(None), Download.next_retry_at <= now),
            )
            .order_by(Download.id)
        )
    )
    for d in due:
        submit(db, d, settings)
        db.commit()
    return len(due)


def refresh_status(db: Session, settings: Settings) -> int:
    """Update qbit_state/progress/save_path for downloads with a qbit_hash. Raises QbitError. Flushes."""
    creds = settings_store.get_qbit_credentials(db, settings)
    if not creds.configured:
        return 0
    rows = list(
        db.scalars(
            select(Download).where(
                Download.qbit_hash.is_not(None), Download.status.in_(("submitted", "exists", "path_mismatch"))
            )
        )
    )
    if not rows:
        return 0
    by_hash: dict[str, list[Download]] = {}
    for r in rows:
        by_hash.setdefault((r.qbit_hash or "").lower(), []).append(r)
    updated = 0
    with client_factory(creds) as client:
        hashes = list(by_hash)
        for i in range(0, len(hashes), 50):
            for t in client.info(hashes[i : i + 50]):
                for d in by_hash.get(str(t.get("hash") or "").lower(), []):
                    _apply_torrent(d, t)
                    updated += 1
    db.flush()
    return updated

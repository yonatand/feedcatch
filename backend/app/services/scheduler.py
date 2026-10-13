"""APScheduler BackgroundScheduler singleton: per-feed polls, retry queue, qBittorrent status, log retention.

Each job opens its own session and never raises (errors are logged).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import structlog
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import SessionLocal
from app.models import FeedSource
from app.services import activity, dispatcher, poller, settings_store
from app.services.qbit import QbitError

log = structlog.get_logger("scheduler")

FIRST_POLL_DELAY_SECONDS = 10
_scheduler: BackgroundScheduler | None = None


def build_scheduler() -> BackgroundScheduler:
    return BackgroundScheduler(
        timezone=UTC, job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 60}
    )


def is_running() -> bool:
    return _scheduler is not None and bool(_scheduler.running)


def _now() -> datetime:
    return datetime.now(UTC)


def _run_job(name: str, fn: Callable[[Session, Settings], None]) -> None:
    db = SessionLocal()
    try:
        fn(db, get_settings())
    except Exception:
        log.exception("job_failed", job=name)
        db.rollback()
    finally:
        db.close()


# ---------------------------------------------------------------- jobs


def backoff_minutes(feed: FeedSource) -> float:
    """Wait time after consecutive failures: interval * 2**(failures-1), capped at 24h."""
    if not feed.consecutive_failures:
        return 0
    return float(min(feed.poll_interval_minutes * 2 ** min(feed.consecutive_failures - 1, 10), 1440))


def _feed_job(db: Session, settings: Settings, feed_id: int) -> None:
    feed = db.get(FeedSource, feed_id)
    if feed is None or not feed.enabled:
        return
    wait = backoff_minutes(feed)
    if (
        wait
        and feed.last_checked_at is not None
        and _now() < feed.last_checked_at + timedelta(minutes=wait) - timedelta(seconds=30)
    ):
        log.info("feed_backoff_skip", feed_id=feed_id, consecutive_failures=feed.consecutive_failures)
        return
    try:
        poller.poll_feed(db, feed_id, settings)
    except poller.PollInProgress:
        log.info("feed_poll_skipped", feed_id=feed_id, reason="in progress")


def run_feed_job(feed_id: int) -> None:
    _run_job(f"feed:{feed_id}", lambda db, s: _feed_job(db, s, feed_id))


def run_retry_job() -> None:
    _run_job("retry", lambda db, s: log.debug("retry_done", attempted=dispatcher.retry_due(db, s)))


def _qbit_status(db: Session, settings: Settings) -> None:
    creds = settings_store.get_qbit_credentials(db, settings)
    if not creds.poll_status or not creds.configured:
        return
    try:
        dispatcher.refresh_status(db, settings)
        db.commit()
    except QbitError as exc:
        db.rollback()
        log.warning("qbit_status_failed", error=str(exc))


def run_qbit_status_job() -> None:
    _run_job("qbit_status", _qbit_status)


def _retention(db: Session, settings: Settings) -> None:
    days = int(settings_store.get(db, settings_store.LOG_RETENTION_DAYS) or 30)
    deleted = activity.purge_older_than(db, days)
    db.commit()
    log.info("retention_done", deleted=deleted, days=days)


def run_retention_job() -> None:
    _run_job("retention", _retention)


# ---------------------------------------------------------------- lifecycle


def sync_feed_jobs(db: Session) -> None:
    """Add/update/remove `feed:{id}` jobs to match enabled feeds. No-op when the scheduler is not running."""
    sched = _scheduler
    if sched is None:
        return
    feeds = list(db.scalars(select(FeedSource).where(FeedSource.enabled.is_(True))))
    wanted = {f"feed:{f.id}": f for f in feeds}
    for job in sched.get_jobs():
        if job.id.startswith("feed:") and job.id not in wanted:
            sched.remove_job(job.id)
    for job_id, feed in wanted.items():
        interval = timedelta(minutes=feed.poll_interval_minutes)
        job = sched.get_job(job_id)
        if job is None:
            sched.add_job(
                run_feed_job,
                IntervalTrigger(minutes=feed.poll_interval_minutes, timezone=UTC),
                id=job_id,
                args=[feed.id],
                next_run_time=_now() + timedelta(seconds=FIRST_POLL_DELAY_SECONDS),
                replace_existing=True,
            )
        elif getattr(job.trigger, "interval", None) != interval:
            sched.reschedule_job(job_id, trigger=IntervalTrigger(minutes=feed.poll_interval_minutes, timezone=UTC))


def start(app_settings: Settings) -> None:
    global _scheduler
    if is_running():
        return
    sched = build_scheduler()
    now = _now()
    sched.add_job(run_retry_job, IntervalTrigger(seconds=60, timezone=UTC), id="retry", replace_existing=True)
    sched.add_job(
        run_qbit_status_job, IntervalTrigger(seconds=120, timezone=UTC), id="qbit_status", replace_existing=True
    )
    sched.add_job(
        run_retention_job,
        IntervalTrigger(hours=24, timezone=UTC),
        id="retention",
        next_run_time=now + timedelta(minutes=5),
        replace_existing=True,
    )
    _scheduler = sched
    sched.start()
    db = SessionLocal()
    try:
        sync_feed_jobs(db)
    except Exception:
        log.exception("sync_feed_jobs_failed")
    finally:
        db.close()
    log.info("scheduler_started", jobs=[j.id for j in sched.get_jobs()])


def shutdown(wait: bool = True) -> None:
    global _scheduler
    sched = _scheduler
    _scheduler = None
    if sched is not None and sched.running:
        sched.shutdown(wait=wait)
        log.info("scheduler_stopped")


def next_feed_poll_at() -> datetime | None:
    sched = _scheduler
    if sched is None:
        return None
    times = [j.next_run_time for j in sched.get_jobs() if j.id.startswith("feed:") and j.next_run_time is not None]
    return min(times) if times else None

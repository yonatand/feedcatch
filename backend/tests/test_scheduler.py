from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import FeedSource, utcnow
from app.services import scheduler


@pytest.fixture
def running(db: Session, settings: Settings) -> Iterator[None]:
    scheduler.start(settings)
    try:
        yield
    finally:
        scheduler.shutdown(wait=True)


def test_jobs_and_feed_sync(db: Session, running: None) -> None:
    assert scheduler.is_running()
    sched = scheduler._scheduler
    assert sched is not None
    assert {j.id for j in sched.get_jobs()} == {"retry", "qbit_status", "retention"}
    assert scheduler.next_feed_poll_at() is None

    feed = FeedSource(name="F", url="https://feed.example.test/rss2", poll_interval_minutes=15)
    off = FeedSource(name="G", url="https://feed.example.test/other", enabled=False)
    db.add_all([feed, off])
    db.commit()
    scheduler.sync_feed_jobs(db)
    job = sched.get_job(f"feed:{feed.id}")
    assert job is not None and sched.get_job(f"feed:{off.id}") is None
    assert job.trigger.interval == timedelta(minutes=15)
    nxt = scheduler.next_feed_poll_at()
    assert nxt is not None and nxt <= utcnow() + timedelta(seconds=11)

    feed.poll_interval_minutes = 60
    db.commit()
    scheduler.sync_feed_jobs(db)
    job = sched.get_job(f"feed:{feed.id}")
    assert job is not None and job.trigger.interval == timedelta(minutes=60)

    feed.enabled = False
    db.commit()
    scheduler.sync_feed_jobs(db)
    assert sched.get_job(f"feed:{feed.id}") is None


def test_shutdown_and_noop_sync(db: Session, settings: Settings) -> None:
    scheduler.start(settings)
    scheduler.shutdown(wait=True)
    assert not scheduler.is_running()
    scheduler.sync_feed_jobs(db)  # no scheduler -> no-op, no error


def test_backoff_minutes() -> None:
    f = FeedSource(name="F", url="u", poll_interval_minutes=15, consecutive_failures=0)
    assert scheduler.backoff_minutes(f) == 0
    f.consecutive_failures = 3
    assert scheduler.backoff_minutes(f) == 60
    f.consecutive_failures = 20
    assert scheduler.backoff_minutes(f) == 1440

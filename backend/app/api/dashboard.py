"""/api/dashboard"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import AUTH, Session, Settings, get_db, get_settings
from app.api.downloads import with_relations
from app.api.feeds import entry_counts
from app.models import Download, FeedEntry, FeedSource, Rule, Series, utcnow
from app.schemas import (
    DashboardCounts,
    DashboardOut,
    DashboardQbit,
    DashboardScheduler,
    DownloadOut,
    FeedEntryOut,
    FeedSourceOut,
)
from app.services import scheduler, settings_store

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"], dependencies=AUTH)


def _n(db: Session, stmt) -> int:  # type: ignore[no-untyped-def]
    return int(db.scalar(stmt) or 0)


@router.get("", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> DashboardOut:
    since = utcnow() - timedelta(hours=24)
    counts_by_feed = entry_counts(db)
    feeds = [
        FeedSourceOut.from_model(f, counts_by_feed.get(f.id, 0))
        for f in db.scalars(select(FeedSource).order_by(FeedSource.id))
    ]
    cnt = func.count()
    counts = DashboardCounts(
        series_total=_n(db, select(cnt).select_from(Series)),
        series_monitored=_n(db, select(cnt).select_from(Series).where(Series.monitored.is_(True))),
        rules_active=_n(
            db,
            select(cnt).select_from(Rule).join(Series).where(Rule.enabled.is_(True), Series.monitored.is_(True)),
        ),
        entries_24h=_n(db, select(cnt).select_from(FeedEntry).where(FeedEntry.first_seen_at >= since)),
        downloads_submitted_24h=_n(
            db,
            select(cnt)
            .select_from(Download)
            .where(Download.status.in_(("submitted", "path_mismatch")), Download.updated_at >= since),
        ),
        downloads_pending=_n(db, select(cnt).select_from(Download).where(Download.status == "pending")),
        downloads_failed=_n(db, select(cnt).select_from(Download).where(Download.status == "failed")),
    )
    recent = db.scalars(with_relations(select(Download).order_by(Download.id.desc()).limit(10)))
    failed = db.scalars(
        with_relations(
            select(Download)
            .where(Download.status.in_(("failed", "path_mismatch")))
            .order_by(Download.updated_at.desc(), Download.id.desc())
            .limit(10)
        )
    )
    entries = db.scalars(
        select(FeedEntry)
        .options(selectinload(FeedEntry.feed))
        .order_by(FeedEntry.first_seen_at.desc(), FeedEntry.id.desc())
        .limit(10)
    )
    creds = settings_store.get_qbit_credentials(db, settings)
    return DashboardOut(
        feeds=feeds,
        counts=counts,
        recent_downloads=[DownloadOut.from_model(d) for d in recent],
        failed_downloads=[DownloadOut.from_model(d) for d in failed],
        recent_entries=[FeedEntryOut.from_model(e) for e in entries],
        qbit=DashboardQbit(configured=creds.configured, last_test=settings_store.get_qbit_last_test(db)),
        scheduler=DashboardScheduler(running=scheduler.is_running(), next_feed_poll_at=scheduler.next_feed_poll_at()),
    )

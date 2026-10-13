"""/api/feeds"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select

from app.api.deps import AUTH, Page, Session, Settings, count, get_db, get_or_404, get_settings, page_params
from app.models import FeedEntry, FeedSource
from app.schemas import (
    FeedEntryPreviewOut,
    FeedSourceIn,
    FeedSourceOut,
    FeedTestIn,
    FeedTestOut,
    Paginated,
    ParsedReleaseOut,
    PollResultOut,
)
from app.services import activity, poller, scheduler, settings_store, ssrf
from app.services.feeds import FeedFetchError, ParsedEntry, fetch_feed

router = APIRouter(prefix="/api/feeds", tags=["feeds"], dependencies=AUTH)


def entry_counts(db: Session) -> dict[int, int]:
    rows = db.execute(select(FeedEntry.feed_id, func.count()).group_by(FeedEntry.feed_id)).all()
    return {int(fid): int(n) for fid, n in rows}


def feed_out(db: Session, feed: FeedSource) -> FeedSourceOut:
    n = db.scalar(select(func.count()).select_from(FeedEntry).where(FeedEntry.feed_id == feed.id)) or 0
    return FeedSourceOut.from_model(feed, int(n))


def preview_out(pe: ParsedEntry) -> FeedEntryPreviewOut:
    return FeedEntryPreviewOut(
        guid=pe.guid,
        title=pe.title,
        link=pe.link,
        published_at=pe.published_at,
        magnet_url=pe.magnet_url,
        torrent_url=pe.torrent_url,
        has_nzb=bool(pe.nzb_url),
        size_bytes=pe.size_bytes,
        infohash=pe.infohash,
        parsed=ParsedReleaseOut.from_parsed(pe.parsed),
    )


def _validate_url(db: Session, settings: Settings, url: str) -> str:
    try:
        return ssrf.validate_feed_url(url, settings_store.allow_private_feed_hosts(db, settings))
    except ssrf.SsrfError as exc:
        raise HTTPException(status_code=400, detail=f"feed URL not allowed: {exc}") from exc


def _check_unique_url(db: Session, url: str, exclude_id: int | None = None) -> None:
    stmt = select(FeedSource.id).where(FeedSource.url == url)
    if exclude_id is not None:
        stmt = stmt.where(FeedSource.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise HTTPException(status_code=409, detail="a feed with this URL already exists")


def _timeout(db: Session) -> float:
    return float(settings_store.get(db, settings_store.FEED_FETCH_TIMEOUT_SECONDS) or 20)


@router.get("", response_model=Paginated[FeedSourceOut])
def list_feeds(page: Page = Depends(page_params), db: Session = Depends(get_db)) -> Paginated[FeedSourceOut]:
    stmt = select(FeedSource).order_by(FeedSource.id)
    counts = entry_counts(db)
    items = [
        FeedSourceOut.from_model(f, counts.get(f.id, 0)) for f in db.scalars(stmt.limit(page.limit).offset(page.offset))
    ]
    return Paginated[FeedSourceOut](items=items, total=count(db, stmt))


@router.post("", response_model=FeedSourceOut, status_code=201)
def create_feed(
    body: FeedSourceIn, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> FeedSourceOut:
    url = _validate_url(db, settings, body.url)
    _check_unique_url(db, url)
    feed = FeedSource(
        name=body.name,
        url=url,
        enabled=body.enabled,
        poll_interval_minutes=body.poll_interval_minutes,
        backfill_mode=body.backfill_mode,
    )
    db.add(feed)
    db.flush()
    activity.log_event(db, "info", "feed_created", f"Feed '{feed.name}' added", details={"feed_id": feed.id})
    db.commit()
    scheduler.sync_feed_jobs(db)
    return feed_out(db, feed)


@router.post("/test", response_model=FeedTestOut)
def test_feed(
    body: FeedTestIn, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> FeedTestOut:
    allow = settings_store.allow_private_feed_hosts(db, settings)
    try:
        ssrf.validate_feed_url(body.url, allow)
        result = fetch_feed(body.url.strip(), timeout=_timeout(db), allow_private=allow)
    except ssrf.SsrfError as exc:
        return FeedTestOut(ok=False, feed_title=None, entry_count=0, sample=[], error=f"URL not allowed: {exc}")
    except FeedFetchError as exc:
        return FeedTestOut(ok=False, feed_title=None, entry_count=0, sample=[], error=str(exc))
    return FeedTestOut(
        ok=True,
        feed_title=result.feed_title,
        entry_count=len(result.entries),
        sample=[preview_out(pe) for pe in result.entries[:5]],
        error=None,
    )


@router.get("/{feed_id}", response_model=FeedSourceOut)
def get_feed(feed_id: int, db: Session = Depends(get_db)) -> FeedSourceOut:
    return feed_out(db, get_or_404(db, FeedSource, feed_id, "feed"))


@router.put("/{feed_id}", response_model=FeedSourceOut)
def update_feed(
    feed_id: int, body: FeedSourceIn, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> FeedSourceOut:
    feed = get_or_404(db, FeedSource, feed_id, "feed")
    url = _validate_url(db, settings, body.url)
    _check_unique_url(db, url, exclude_id=feed.id)
    if url != feed.url:
        # different feed content: forget conditional-GET state and treat the next poll as a first poll
        feed.etag = None
        feed.last_modified = None
        feed.initial_poll_done = False
    feed.name = body.name
    feed.url = url
    feed.enabled = body.enabled
    feed.poll_interval_minutes = body.poll_interval_minutes
    feed.backfill_mode = body.backfill_mode
    activity.log_event(db, "info", "feed_updated", f"Feed '{feed.name}' updated", details={"feed_id": feed.id})
    db.commit()
    scheduler.sync_feed_jobs(db)
    return feed_out(db, feed)


@router.delete("/{feed_id}", status_code=204)
def delete_feed(feed_id: int, db: Session = Depends(get_db)) -> Response:
    feed = get_or_404(db, FeedSource, feed_id, "feed")
    name = feed.name
    db.delete(feed)
    activity.log_event(db, "info", "feed_deleted", f"Feed '{name}' deleted", details={"feed_id": feed_id})
    db.commit()
    scheduler.sync_feed_jobs(db)
    return Response(status_code=204)


@router.get("/{feed_id}/preview", response_model=Paginated[FeedEntryPreviewOut])
def preview_feed(
    feed_id: int,
    limit: int = Query(50, ge=1),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Paginated[FeedEntryPreviewOut]:
    feed = get_or_404(db, FeedSource, feed_id, "feed")
    try:
        result = fetch_feed(
            feed.url, timeout=_timeout(db), allow_private=settings_store.allow_private_feed_hosts(db, settings)
        )
    except FeedFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    items = [preview_out(pe) for pe in result.entries[: min(limit, 200)]]
    return Paginated[FeedEntryPreviewOut](items=items, total=len(result.entries))


@router.post("/{feed_id}/poll", response_model=PollResultOut)
def poll_feed(feed_id: int, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> PollResultOut:
    get_or_404(db, FeedSource, feed_id, "feed")
    try:
        return poller.poll_feed(db, feed_id, settings)
    except poller.PollInProgress as exc:
        raise HTTPException(status_code=409, detail="a poll for this feed is already in progress") from exc

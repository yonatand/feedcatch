"""/api/downloads"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.api.deps import AUTH, Page, Session, Settings, count, get_db, get_or_404, get_settings, page_params
from app.models import Download
from app.schemas import DownloadOut, DownloadStatus, Paginated, RetriedOut, UpdatedOut
from app.services import activity, dispatcher
from app.services.qbit import QbitError

router = APIRouter(prefix="/api/downloads", tags=["downloads"], dependencies=AUTH)


def with_relations(stmt):  # type: ignore[no-untyped-def]
    return stmt.options(
        selectinload(Download.entry),
        selectinload(Download.series),
        selectinload(Download.season),
        selectinload(Download.rule),
    )


def _reset_to_pending(db: Session, d: Download) -> bool:
    """Set a download back to pending (attempts unchanged). False if that would duplicate an active one."""
    previous = d.status
    d.status = "pending"
    d.next_retry_at = None
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        d.status = previous
        return False
    activity.log_event(db, "info", "download_retry", f"Retry requested for download #{d.id}", download_id=d.id)
    return True


@router.get("", response_model=Paginated[DownloadOut])
def list_downloads(
    status: DownloadStatus | None = Query(None),
    series_id: int | None = Query(None),
    page: Page = Depends(page_params),
    db: Session = Depends(get_db),
) -> Paginated[DownloadOut]:
    stmt = select(Download)
    if status is not None:
        stmt = stmt.where(Download.status == status)
    if series_id is not None:
        stmt = stmt.where(Download.series_id == series_id)
    stmt = stmt.order_by(Download.id.desc())
    items = [DownloadOut.from_model(d) for d in db.scalars(with_relations(stmt).limit(page.limit).offset(page.offset))]
    return Paginated[DownloadOut](items=items, total=count(db, stmt))


@router.post("/retry-failed", response_model=RetriedOut)
def retry_failed(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> RetriedOut:
    rows = list(db.scalars(select(Download).where(Download.status == "failed").order_by(Download.id)))
    retried = 0
    for d in rows:
        if not _reset_to_pending(db, d):
            continue
        db.commit()
        dispatcher.submit(db, d, settings)
        db.commit()
        retried += 1
    return RetriedOut(retried=retried)


@router.post("/refresh-status", response_model=UpdatedOut)
def refresh_status(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> UpdatedOut:
    try:
        updated = dispatcher.refresh_status(db, settings)
    except QbitError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=f"qBittorrent: {exc}") from exc
    db.commit()
    return UpdatedOut(updated=updated)


@router.get("/{download_id}", response_model=DownloadOut)
def get_download(download_id: int, db: Session = Depends(get_db)) -> DownloadOut:
    return DownloadOut.from_model(get_or_404(db, Download, download_id, "download"))


@router.post("/{download_id}/retry", response_model=DownloadOut)
def retry(download_id: int, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> DownloadOut:
    d = get_or_404(db, Download, download_id, "download")
    if not _reset_to_pending(db, d):
        raise HTTPException(status_code=409, detail="another active download exists for this episode or torrent")
    db.commit()
    dispatcher.submit(db, d, settings)
    db.commit()
    return DownloadOut.from_model(d)


@router.delete("/{download_id}", status_code=204)
def delete_download(download_id: int, db: Session = Depends(get_db)) -> Response:
    """Forget feedcatch's record only. The torrent stays in qBittorrent (safety invariant 6: no qBittorrent call)."""
    d = get_or_404(db, Download, download_id, "download")
    title = d.entry.title if d.entry is not None else None
    entry_id = d.entry_id
    details = {
        "download_id": d.id,
        "entry_id": d.entry_id,
        "entry_title": title,
        "infohash": d.infohash,
        "save_path": d.save_path,
        "series_id": d.series_id,
        "season_id": d.season_id,
        "episode_number": d.episode_number,
        "status": d.status,
    }
    db.delete(d)
    activity.log_event(
        db,
        "info",
        "download_deleted",
        f"Download #{download_id} '{title or '?'}' deleted (record only; the torrent stays in qBittorrent)",
        details=details,
        entry_id=entry_id,
    )
    db.commit()
    return Response(status_code=204)

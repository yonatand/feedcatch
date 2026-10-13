"""/api/entries (Recent Releases + Match Inspector)"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import AUTH, Page, Session, Settings, count, get_db, get_or_404, get_settings, page_params
from app.models import Evaluation, FeedEntry, Rule
from app.schemas import DownloadOut, FeedEntryDetailOut, FeedEntryOut, GrabIn, GrabPreviewOut, Outcome, Paginated
from app.services import poller

router = APIRouter(prefix="/api/entries", tags=["entries"], dependencies=AUTH)


def detail_out(db: Session, entry: FeedEntry) -> FeedEntryDetailOut:
    db.refresh(entry, ["evaluations", "downloads"])
    entry.evaluations.sort(key=lambda e: (not e.matched, -(e.rule.priority if e.rule else 0), e.rule_id))
    entry.downloads.sort(key=lambda d: -d.id)
    return FeedEntryDetailOut.from_model(entry)


@router.get("", response_model=Paginated[FeedEntryOut])
def list_entries(
    feed_id: int | None = Query(None),
    outcome: Outcome | None = Query(None),
    q: str | None = Query(None, max_length=200),
    page: Page = Depends(page_params),
    db: Session = Depends(get_db),
) -> Paginated[FeedEntryOut]:
    stmt = select(FeedEntry).options(selectinload(FeedEntry.feed))
    if feed_id is not None:
        stmt = stmt.where(FeedEntry.feed_id == feed_id)
    if outcome is not None:
        stmt = stmt.where(FeedEntry.outcome == outcome)
    if q:
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(FeedEntry.title.ilike(f"%{escaped}%", escape="\\"))
    stmt = stmt.order_by(FeedEntry.first_seen_at.desc(), FeedEntry.id.desc())
    items = [FeedEntryOut.from_model(e) for e in db.scalars(stmt.limit(page.limit).offset(page.offset))]
    return Paginated[FeedEntryOut](items=items, total=count(db, stmt))


@router.get("/{entry_id}", response_model=FeedEntryDetailOut)
def get_entry(entry_id: int, db: Session = Depends(get_db)) -> FeedEntryDetailOut:
    return detail_out(db, get_or_404(db, FeedEntry, entry_id, "entry"))


@router.post("/{entry_id}/evaluate", response_model=FeedEntryDetailOut)
def evaluate(
    entry_id: int, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> FeedEntryDetailOut:
    entry = get_or_404(db, FeedEntry, entry_id, "entry")
    poller.evaluate_entry(db, entry, settings, store=True)
    db.commit()
    # Load rule relationships for the response.
    db.scalars(
        select(Evaluation)
        .where(Evaluation.entry_id == entry.id)
        .options(selectinload(Evaluation.rule).selectinload(Rule.series))
    ).all()
    return detail_out(db, entry)


@router.post("/{entry_id}/grab", response_model=GrabPreviewOut | DownloadOut)
def grab(
    entry_id: int,
    body: GrabIn,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> GrabPreviewOut | DownloadOut:
    entry = get_or_404(db, FeedEntry, entry_id, "entry")
    try:
        if not body.confirm:
            return poller.build_grab_preview(db, entry, body.season_id, body.episode_number, body.force, settings)
        download = poller.perform_grab(db, entry, body.season_id, body.episode_number, body.force, settings)
    except poller.GrabError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    response.status_code = 201
    return DownloadOut.from_model(download)

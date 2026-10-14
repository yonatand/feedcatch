"""/api/calendar, /api/wanted (see `.claude/rules/episodes.md`)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import AUTH, Page, Session, Settings, get_db, get_settings, page_params
from app.models import utcnow
from app.schemas import CalendarItemOut, ItemsOut, Paginated, SearchAllOut, SearchAllSeasonOut
from app.services import episodes, search

router = APIRouter(tags=["calendar"], dependencies=AUTH)

DEFAULT_PAST_DAYS = 7
DEFAULT_FUTURE_DAYS = 14
MAX_SPAN_DAYS = 62


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def calendar_items(rows: list[episodes.CalendarRow]) -> list[CalendarItemOut]:
    return [CalendarItemOut.model_validate(r.as_dict()) for r in rows]


@router.get("/api/calendar", response_model=ItemsOut[CalendarItemOut])
def calendar(
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    monitored_only: bool = Query(False),
    db: Session = Depends(get_db),
) -> ItemsOut[CalendarItemOut]:
    now = utcnow()
    start = _aware(from_) if from_ is not None else now - timedelta(days=DEFAULT_PAST_DAYS)
    end = _aware(to) if to is not None else now + timedelta(days=DEFAULT_FUTURE_DAYS)
    if end <= start:
        raise HTTPException(status_code=400, detail="'to' must be after 'from'")
    if end - start > timedelta(days=MAX_SPAN_DAYS):
        raise HTTPException(status_code=400, detail=f"calendar window is limited to {MAX_SPAN_DAYS} days")
    return ItemsOut[CalendarItemOut](items=calendar_items(episodes.calendar(db, start, end, monitored_only)))


@router.get("/api/wanted", response_model=Paginated[CalendarItemOut])
def wanted(page: Page = Depends(page_params), db: Session = Depends(get_db)) -> Paginated[CalendarItemOut]:
    rows = episodes.wanted(db)
    return Paginated[CalendarItemOut](
        items=calendar_items(rows[page.offset : page.offset + page.limit]), total=len(rows)
    )


@router.post("/api/wanted/search-all", response_model=SearchAllOut)
def search_all(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> SearchAllOut:
    if not search.searchable_feeds(db):
        raise HTTPException(status_code=400, detail="no enabled feed has a search URL template")
    if not search.search_all_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="a search for missing episodes is already running")
    try:
        results = search.search_and_grab_seasons(db, settings, search.SEARCH_ALL_MAX_SEASONS)
    finally:
        search.search_all_lock.release()
    return SearchAllOut(seasons=[SearchAllSeasonOut.model_validate(r) for r in results])

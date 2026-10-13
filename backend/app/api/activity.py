"""/api/activity"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import AUTH, Page, Session, count, get_db, page_params
from app.models import ActivityLog
from app.schemas import ActivityEventOut, Level, Paginated

router = APIRouter(prefix="/api/activity", tags=["activity"], dependencies=AUTH)


@router.get("", response_model=Paginated[ActivityEventOut])
def list_activity(
    level: Level | None = Query(None),
    event_type: str | None = Query(None, max_length=64),
    page: Page = Depends(page_params),
    db: Session = Depends(get_db),
) -> Paginated[ActivityEventOut]:
    stmt = select(ActivityLog)
    if level is not None:
        stmt = stmt.where(ActivityLog.level == level)
    if event_type:
        stmt = stmt.where(ActivityLog.event_type == event_type)
    stmt = stmt.order_by(ActivityLog.ts.desc(), ActivityLog.id.desc())
    items = [ActivityEventOut.model_validate(a) for a in db.scalars(stmt.limit(page.limit).offset(page.offset))]
    return Paginated[ActivityEventOut](items=items, total=count(db, stmt))

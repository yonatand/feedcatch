"""Shared router dependencies: DB session, settings, pagination, auth."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.services.auth import require_auth

MAX_LIMIT = 200

__all__ = ["AUTH", "Page", "Settings", "Session", "count", "get_db", "get_or_404", "get_settings", "page_params"]

AUTH = [Depends(require_auth)]


@dataclass
class Page:
    limit: int
    offset: int


def page_params(limit: int = Query(50, ge=1), offset: int = Query(0, ge=0)) -> Page:
    """`?limit=` (default 50, clamped to 200) and `?offset=`."""
    return Page(limit=min(limit, MAX_LIMIT), offset=offset)


def count(db: Session, stmt: Any) -> int:
    return int(db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)


def get_or_404[T](db: Session, model: type[T], obj_id: int, what: str) -> T:
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{what} not found")
    return obj

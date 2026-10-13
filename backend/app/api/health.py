"""GET /healthz (open)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import __version__
from app.db import SessionLocal, get_engine
from app.schemas import HealthOut
from app.services import scheduler

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthOut)
def healthz() -> JSONResponse:
    db_ok = True
    try:
        get_engine()
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    out = HealthOut(
        status="ok" if db_ok else "error",
        db="ok" if db_ok else "error",
        scheduler="running" if scheduler.is_running() else "stopped",
        version=__version__,
    )
    return JSONResponse(out.model_dump(), status_code=200 if db_ok else 503)

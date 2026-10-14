"""/api/settings"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import AUTH, Session, Settings, get_db, get_settings
from app.schemas import AppSettingsIn, AppSettingsOut
from app.services import activity, scheduler, settings_store

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=AUTH)


@router.get("", response_model=AppSettingsOut)
def get_app_settings(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> AppSettingsOut:
    return settings_store.get_app_settings(db, settings)


@router.put("", response_model=AppSettingsOut)
def put_app_settings(
    body: AppSettingsIn, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> AppSettingsOut:
    out = settings_store.set_app_settings(db, settings, body)
    activity.log_event(db, "info", "settings_updated", "Application settings updated")
    db.commit()
    scheduler.sync_episode_jobs(db)
    return out

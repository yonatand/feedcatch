"""/api/qbit (the password is never returned; request bodies are never logged)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends

from app.api.deps import AUTH, Session, Settings, get_db, get_settings
from app.schemas import QbitConfigIn, QbitConfigOut, QbitTestIn, QbitTestResultOut
from app.services import activity, dispatcher, settings_store
from app.services.qbit import QbitError

router = APIRouter(prefix="/api/qbit", tags=["qbit"], dependencies=AUTH)


@router.get("", response_model=QbitConfigOut)
def get_config(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> QbitConfigOut:
    return settings_store.get_qbit_config(db, settings)


@router.put("", response_model=QbitConfigOut)
def put_config(
    body: QbitConfigIn, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> QbitConfigOut:
    out = settings_store.set_qbit_config(db, settings, body)
    activity.log_event(db, "info", "qbit_config_updated", "qBittorrent settings updated", details={"url": out.url})
    db.commit()
    return out


@router.post("/test", response_model=QbitTestResultOut)
def test_connection(
    body: Annotated[QbitTestIn | None, Body()] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> QbitTestResultOut:
    creds = settings_store.merge_qbit_test_input(db, settings, body)
    if not creds.url:
        result = QbitTestResultOut(ok=False, at=datetime.now(UTC), error="qBittorrent URL is not configured")
    elif not creds.url.lower().startswith(("http://", "https://")):
        result = QbitTestResultOut(
            ok=False, at=datetime.now(UTC), error="qBittorrent URL must start with http:// or https://"
        )
    else:
        try:
            with dispatcher.client_factory(creds) as client:
                result = client.test(creds.category)
        except QbitError as exc:
            result = QbitTestResultOut(ok=False, at=datetime.now(UTC), error=str(exc))
    settings_store.set_qbit_last_test(db, result)
    activity.log_event(
        db,
        "info" if result.ok else "warning",
        "qbit_test",
        f"qBittorrent connection test {'succeeded' if result.ok else 'failed'}"
        + (f": {result.error}" if result.error else ""),
        details={"version": result.version, "api_version": result.api_version, "warnings": result.warnings},
    )
    db.commit()
    return result

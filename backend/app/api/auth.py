"""/api/auth/* (open endpoints). Never logs request bodies."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.deps import Session, Settings, get_db, get_settings
from app.schemas import AuthStatusOut, LoginIn, SetupIn
from app.services import activity, auth

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("/status", response_model=AuthStatusOut)
def status(
    request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> AuthStatusOut:
    mode, setup_required = auth.auth_status(db, settings)
    return AuthStatusOut(
        auth_mode=mode, setup_required=setup_required, authenticated=auth.is_authenticated(request, settings)
    )


@router.post("/setup", status_code=204)
def setup(body: SetupIn, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> Response:
    mode, setup_required = auth.auth_status(db, settings)
    if mode != "password" or not setup_required:
        raise HTTPException(status_code=409, detail="setup is not required")
    auth.setup_password(db, body.password)
    activity.log_event(db, "info", "auth_setup", "Admin password configured")
    db.commit()
    return Response(status_code=204)


@router.post("/login", status_code=204)
def login(
    body: LoginIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    limiter: auth.LoginRateLimiter = request.app.state.login_limiter
    ip = _client_ip(request)
    if limiter.is_blocked(ip):
        raise HTTPException(status_code=429, detail="too many failed login attempts; try again in a minute")
    if not settings.APP_AUTH_DISABLED:
        mode, setup_required = auth.auth_status(db, settings)
        if setup_required:
            raise HTTPException(status_code=409, detail="setup required")
        if not auth.check_login_password(db, settings, body.password):
            limiter.record_failure(ip)
            raise HTTPException(status_code=401, detail="invalid password")
        limiter.reset(ip)
    response = Response(status_code=204)
    response.set_cookie(
        auth.SESSION_COOKIE,
        auth.create_session_token(auth.get_serializer(settings)),
        max_age=auth.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    return response


@router.post("/logout", status_code=204)
def logout(request: Request) -> Response:
    response = Response(status_code=204)
    response.delete_cookie(
        auth.SESSION_COOKIE, path="/", httponly=True, samesite="lax", secure=request.url.scheme == "https"
    )
    return response

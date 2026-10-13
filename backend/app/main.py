"""FastAPI application factory, lifespan, middleware, error mapping and SPA serving."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

from app import __version__
from app.api import activity, auth, dashboard, downloads, entries, feeds, health, qbit, rules, series, settings
from app.config import get_settings
from app.db import SessionLocal, configure_engine, run_migrations
from app.logging_setup import configure_logging
from app.services import scheduler, settings_store
from app.services.auth import LoginRateLimiter
from app.services.paths import PathError
from app.services.qbit import QbitError
from app.services.seed import seed_demo
from app.services.ssrf import SsrfError

log = structlog.get_logger("app")

STATIC_DIR = Path(__file__).resolve().parent / "static"
ASSETS_DIR = STATIC_DIR / "assets"
INDEX_HTML = STATIC_DIR / "index.html"

# RequestValidationErrors raised by these field validators are reported as 400 {detail} (api-contract):
# invalid regex, invalid paths / folder formats, bad qBittorrent URL.
_400_FIELDS = {
    "regex",
    "path_override",
    "season_path_override",
    "season_folder_format",
    "default_season_folder_format",
    "media_base_path",
    "url",
    "name",
}


class CachedStaticFiles(StaticFiles):
    """Hashed Vite assets: cache forever."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    configure_logging(s.APP_LOG_LEVEL)
    run_migrations()
    configure_engine(s.database_url)
    with SessionLocal() as db:
        settings_store.ensure_defaults(db)
        db.commit()
        seed_demo(db, s)
    if s.APP_SCHEDULER_ENABLED:
        scheduler.start(s)
    log.info("startup", version=__version__, auth_disabled=s.APP_AUTH_DISABLED, scheduler=s.APP_SCHEDULER_ENABLED)
    try:
        yield
    finally:
        scheduler.shutdown(wait=True)
        log.info("shutdown")


def _validation_to_400(exc: RequestValidationError) -> str | None:
    for err in exc.errors():
        msg = str(err.get("msg", ""))
        if msg.startswith("Value error, "):
            msg = msg[len("Value error, ") :]
        loc = err.get("loc") or ()
        field = str(loc[-1]) if loc else ""
        if msg.startswith("invalid regex"):
            return msg
        if err.get("type") == "value_error" and field in _400_FIELDS:
            return f"{field}: {msg}"
    return None


def _register_handlers(app: FastAPI) -> None:
    default_validation_handler = app.exception_handlers.get(RequestValidationError)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> Response:
        detail = _validation_to_400(exc)
        if detail is not None:
            return JSONResponse({"detail": detail}, status_code=400)
        if default_validation_handler is not None:
            return await default_validation_handler(request, exc)  # type: ignore[no-any-return,misc]
        return JSONResponse({"detail": exc.errors()}, status_code=422)

    @app.exception_handler(SsrfError)
    async def ssrf_handler(_request: Request, exc: SsrfError) -> Response:
        return JSONResponse({"detail": f"URL not allowed: {exc}"}, status_code=400)

    @app.exception_handler(PathError)
    async def path_handler(_request: Request, exc: PathError) -> Response:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(QbitError)
    async def qbit_handler(_request: Request, exc: QbitError) -> Response:
        return JSONResponse({"detail": f"qBittorrent: {exc}"}, status_code=502)


def _register_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def security_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    @app.middleware("http")
    async def request_log(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        path = request.url.path
        if path != "/healthz" and not path.startswith("/assets/"):
            log.info(
                "request",
                method=request.method,
                path=path,
                status=response.status_code,
                ms=round((time.perf_counter() - start) * 1000, 1),
            )
        return response

    app.add_middleware(GZipMiddleware, minimum_size=1000)


def _register_spa(app: FastAPI) -> None:
    if ASSETS_DIR.is_dir():
        app.mount("/assets", CachedStaticFiles(directory=str(ASSETS_DIR)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False, response_model=None)
    def spa(full_path: str) -> Any:
        if full_path == "api" or full_path.startswith(("api/", "healthz", "assets/")):
            raise HTTPException(status_code=404, detail="Not Found")
        # top-level static files emitted by Vite (favicon etc.)
        if full_path and "/" not in full_path and "." in full_path:
            candidate = (STATIC_DIR / full_path).resolve()
            if candidate.parent == STATIC_DIR and candidate.is_file():
                return FileResponse(candidate)
        if INDEX_HTML.is_file():
            return FileResponse(INDEX_HTML, headers={"Cache-Control": "no-cache"})
        return PlainTextResponse("UI not built; run frontend build", headers={"Cache-Control": "no-cache"})


def create_app() -> FastAPI:
    app = FastAPI(title="feedcatch", version=__version__, lifespan=lifespan)
    app.state.login_limiter = LoginRateLimiter()
    _register_handlers(app)
    _register_middleware(app)
    for module in (auth, dashboard, feeds, series, rules, entries, downloads, qbit, settings, activity, health):
        app.include_router(module.router)
    _register_spa(app)
    return app


app = create_app()

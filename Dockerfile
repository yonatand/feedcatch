# syntax=docker/dockerfile:1
# feedcatch: one container, one process.
#   stage "ui":      build the React SPA with Vite (outputs to backend/app/static)
#   stage "runtime": Python + FastAPI, serving /api, /healthz and the built SPA

############################ ui ############################
# --platform=$BUILDPLATFORM: the SPA build output is identical on every arch, so skip QEMU emulation for it.
FROM --platform=$BUILDPLATFORM oven/bun:1-alpine AS ui
# vite.config.ts uses build.outDir = ../backend/app/static, so mirror the repo layout.
WORKDIR /app/frontend
RUN mkdir -p /app/backend/app/static
COPY frontend/package.json frontend/bun.lock ./
RUN bun install --frozen-lockfile
COPY frontend/ ./
RUN bun run build

######################### runtime ##########################
FROM python:3.12-slim AS runtime

# Official Astral image (Docker Hub mirror of ghcr.io/astral-sh/uv; either works).
COPY --from=astral/uv:0.10 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/backend/.venv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/backend

# Dependencies first (cached layer). Non-package project ([tool.uv] package = false),
# runtime deps only (dev tools live in the `dev` extra and are not installed).
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Application code + migrations.
COPY backend/alembic.ini ./alembic.ini
COPY backend/alembic ./alembic
COPY backend/app ./app
# Built SPA from the ui stage (replaces anything copied from the build context).
RUN rm -rf ./app/static && mkdir -p ./app/static
COPY --from=ui /app/backend/app/static ./app/static

COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Non-root user. /data is the ONLY writable location (SQLite DB + secret.key).
# The media directory is never mounted: save paths are strings handed to qBittorrent.
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh \
 && chmod 0755 /usr/local/bin/docker-entrypoint.sh \
 && groupadd --gid 1000 app \
 && useradd --uid 1000 --gid 1000 --no-create-home --home-dir /data --shell /usr/sbin/nologin app \
 && mkdir -p /data \
 && chown 1000:1000 /data

ENV APP_DATA_DIR=/data \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    PATH="/app/backend/.venv/bin:${PATH}"

VOLUME /data
EXPOSE 8000
USER app

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"]

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
# Exactly one worker: the scheduler and per-feed locks live in-process.
# --no-access-log: the app emits its own structured request log line; uvicorn's would duplicate it.
# FORWARDED_ALLOW_IPS (env, read natively by uvicorn) controls X-Forwarded-* trust behind a reverse proxy.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log", "--proxy-headers"]

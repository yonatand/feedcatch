"""/api/metadata: provider list, search, detail and series prefill (see `.claude/rules/metadata.md`)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import AUTH, Session, Settings, get_db, get_settings
from app.schemas import ItemsOut, MediaDetailOut, MediaResultOut, MetadataProviderOut, SuggestionOut
from app.services import metadata
from app.services.metadata import MetadataError, MetadataProvider

router = APIRouter(prefix="/api/metadata", tags=["metadata"], dependencies=AUTH)

MIN_QUERY_CHARS = 2
MAX_LIMIT = 50


def metadata_http_error(exc: MetadataError) -> HTTPException:
    """400 not configured / unknown provider, 404 unknown id, 429 rate limit, 502 anything else."""
    if exc.not_configured:
        return HTTPException(status_code=400, detail=str(exc))
    if exc.not_found:
        return HTTPException(status_code=404, detail=str(exc))
    if exc.retry_after is not None:
        return HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": str(exc.retry_after)})
    return HTTPException(status_code=502, detail=str(exc))


def provider_or_400(name: str, db: Session, settings: Settings) -> MetadataProvider:
    if name not in metadata.PROVIDER_NAMES:
        raise HTTPException(status_code=400, detail=f"unknown metadata provider '{name}'")
    return metadata.get_provider(name, db, settings)


def _dump(obj: Any) -> dict[str, Any]:
    return asdict(obj)


@router.get("/providers", response_model=ItemsOut[MetadataProviderOut])
def providers(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> ItemsOut[MetadataProviderOut]:
    return ItemsOut[MetadataProviderOut](
        items=[MetadataProviderOut.model_validate(p) for p in metadata.list_providers(db, settings)]
    )


@router.get("/search", response_model=ItemsOut[MediaResultOut])
def search(
    provider: str = Query("anilist"),
    q: str = Query(""),
    limit: int = Query(10, ge=1, le=MAX_LIMIT),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ItemsOut[MediaResultOut]:
    q = " ".join(q.split())
    if len(q) < MIN_QUERY_CHARS:
        raise HTTPException(status_code=400, detail=f"query must be at least {MIN_QUERY_CHARS} characters")
    p = provider_or_400(provider, db, settings)
    try:
        items = p.search(q, limit)
    except MetadataError as exc:
        raise metadata_http_error(exc) from exc
    return ItemsOut[MediaResultOut](items=[MediaResultOut.model_validate(_dump(m)) for m in items])


@router.get("/{provider}/{media_id}", response_model=MediaDetailOut)
def detail(
    provider: str, media_id: str, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> MediaDetailOut:
    p = provider_or_400(provider, db, settings)
    try:
        media = p.detail(media_id)
    except MetadataError as exc:
        raise metadata_http_error(exc) from exc
    return MediaDetailOut.model_validate(_dump(media))


@router.get("/{provider}/{media_id}/suggest", response_model=SuggestionOut)
def suggest(
    provider: str, media_id: str, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> SuggestionOut:
    p = provider_or_400(provider, db, settings)
    try:
        media = p.detail(media_id)
    except MetadataError as exc:
        raise metadata_http_error(exc) from exc
    return SuggestionOut.model_validate(_dump(metadata.build_suggestion(media)))

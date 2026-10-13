"""/api/anilist: metadata search and series prefill (see `.claude/rules/anilist.md`)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import AUTH
from app.schemas import AnilistMediaDetailOut, AnilistMediaOut, AnilistSuggestionOut, ItemsOut
from app.services.anilist import MAX_SEARCH_LIMIT, AnilistClient, AnilistError, build_suggestion

router = APIRouter(prefix="/api/anilist", tags=["anilist"], dependencies=AUTH)

MIN_QUERY_CHARS = 2


def anilist_http_error(exc: AnilistError) -> HTTPException:
    """Map a service error to the contract's status codes: 404 unknown id, 429 rate limit, 502 anything else."""
    if exc.not_found:
        return HTTPException(status_code=404, detail="AniList entry not found")
    if exc.retry_after is not None:
        return HTTPException(
            status_code=429,
            detail=f"AniList rate limit, retry in {exc.retry_after} s",
            headers={"Retry-After": str(exc.retry_after)},
        )
    return HTTPException(status_code=502, detail=str(exc))


def get_client() -> AnilistClient:
    return AnilistClient()


@router.get("/search", response_model=ItemsOut[AnilistMediaOut])
def search(q: str = Query(""), limit: int = Query(10, ge=1, le=MAX_SEARCH_LIMIT)) -> ItemsOut[AnilistMediaOut]:
    q = " ".join(q.split())
    if len(q) < MIN_QUERY_CHARS:
        raise HTTPException(status_code=400, detail=f"query must be at least {MIN_QUERY_CHARS} characters")
    try:
        items = get_client().search(q, limit)
    except AnilistError as exc:
        raise anilist_http_error(exc) from exc
    return ItemsOut[AnilistMediaOut](items=[AnilistMediaOut.model_validate(m) for m in items])


@router.get("/{anilist_id}", response_model=AnilistMediaDetailOut)
def detail(anilist_id: int) -> AnilistMediaDetailOut:
    try:
        media = get_client().get(anilist_id)
    except AnilistError as exc:
        raise anilist_http_error(exc) from exc
    return AnilistMediaDetailOut.model_validate(media)


@router.get("/{anilist_id}/suggest", response_model=AnilistSuggestionOut)
def suggest(anilist_id: int) -> AnilistSuggestionOut:
    try:
        media = get_client().get(anilist_id)
    except AnilistError as exc:
        raise anilist_http_error(exc) from exc
    return AnilistSuggestionOut.model_validate(build_suggestion(media))

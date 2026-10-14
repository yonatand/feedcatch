"""/api/seasons/{id}/episodes, /api/seasons/{id}/search (see `.claude/rules/episodes.md`)."""

from __future__ import annotations

from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.deps import AUTH, Session, Settings, get_db, get_or_404, get_settings
from app.api.metadata import metadata_http_error
from app.models import Episode, Season, utcnow
from app.schemas import (
    CandidateOut,
    ConditionOut,
    DownloadOut,
    EpisodeIn,
    EpisodeListOut,
    EpisodeOut,
    FailedCheckOut,
    FeedEntryOut,
    GrabMissingOut,
    RejectedReleaseOut,
    SearchIn,
    SearchResultOut,
    SkippedOut,
)
from app.services import activity, episodes, metadata, search
from app.services.metadata import MetadataError

router = APIRouter(prefix="/api/seasons", tags=["episodes"], dependencies=AUTH)


def episode_out(e: Episode, state: episodes.EpisodeState) -> EpisodeOut:
    return EpisodeOut(
        id=e.id,
        season_id=e.season_id,
        episode_number=e.episode_number,
        title=e.title,
        air_date=e.air_date,
        source=e.source,  # type: ignore[arg-type]
        status=state.status,  # type: ignore[arg-type]
        download=DownloadOut.from_model(state.download) if state.download is not None else None,
    )


def episode_list(db: Session, season: Season) -> EpisodeListOut:
    rows = episodes.season_states(db, season)
    return EpisodeListOut(
        items=[episode_out(e, st) for e, st in rows],
        summary=episodes.summarize(st.status for _, st in rows),
    )


def search_out(result: search.SearchResult) -> SearchResultOut:
    return SearchResultOut(
        queries=result.queries,
        feeds_searched=result.feeds_searched,
        fetched=result.fetched,
        candidates=[
            CandidateOut(
                entry=FeedEntryOut.from_model(c.entry),
                episode_number=c.episode_number,
                rule_id=c.rule.id,
                rule_name=c.rule.name,
                conditions=[ConditionOut.from_any(x) for x in c.conditions],
                save_path=c.save_path,
                episode_status=c.episode_status,  # type: ignore[arg-type]
                already_have=c.already_have,
            )
            for c in result.candidates
        ],
        errors=result.errors,
        rejected=[
            RejectedReleaseOut(
                entry_id=r.entry_id,
                title=r.title,
                parsed_title=r.parsed_title,
                alt_titles=r.alt_titles,
                season_number=r.season_number,
                episode_number=r.episode_number,
                failed_checks=[FailedCheckOut(**vars(f)) for f in r.failed_checks],
            )
            for r in result.rejected
        ],
        rejected_total=result.rejected_total,
    )


def _search_error(exc: search.SearchError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("/{season_id}/episodes", response_model=EpisodeListOut)
def list_episodes(season_id: int, db: Session = Depends(get_db)) -> EpisodeListOut:
    return episode_list(db, get_or_404(db, Season, season_id, "season"))


@router.post("/{season_id}/episodes/refresh", response_model=EpisodeListOut)
def refresh_episodes(
    season_id: int, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> EpisodeListOut:
    season = get_or_404(db, Season, season_id, "season")
    if not season.metadata_provider or not season.metadata_id:
        raise HTTPException(status_code=400, detail="season is not linked to a metadata provider")
    try:
        metadata.refresh_season(db, season, settings)
    except MetadataError as exc:
        db.rollback()
        if exc.not_configured:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if exc.retry_after is not None:
            raise metadata_http_error(exc) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    db.commit()
    return episode_list(db, season)


@router.put("/{season_id}/episodes/{number}", response_model=EpisodeOut)
def put_episode(season_id: int, number: int, body: EpisodeIn, db: Session = Depends(get_db)) -> EpisodeOut:
    season = get_or_404(db, Season, season_id, "season")
    if number < 0 or number > 100000:
        raise HTTPException(status_code=400, detail="episode number out of range")
    row = db.scalar(select(Episode).where(Episode.season_id == season.id, Episode.episode_number == number))
    if row is None:
        row = Episode(season_id=season.id, episode_number=number)
        db.add(row)
    sent = body.model_fields_set
    if "title" in sent:
        row.title = body.title
    if "air_date" in sent:
        ad = body.air_date
        row.air_date = (ad.replace(tzinfo=UTC) if ad.tzinfo is None else ad.astimezone(UTC)) if ad else None
    row.source = "manual"
    activity.log_event(
        db,
        "info",
        "episode_edited",
        f"Episode {number} of '{season.series.name}' S{season.season_number:02d} edited",
        details={"season_id": season.id, "episode_number": number},
    )
    db.commit()
    dls = episodes.downloads_by_episode(db, [season.id]).get((season.id, number), [])
    return episode_out(row, episodes.compute_status(row.air_date, dls, utcnow()))


@router.post("/{season_id}/search", response_model=SearchResultOut)
def search_season(
    season_id: int,
    body: SearchIn | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SearchResultOut:
    season = get_or_404(db, Season, season_id, "season")
    try:
        result = search.search_season(db, season, settings, body.query if body else None)
    except search.SearchError as exc:
        raise _search_error(exc) from exc
    return search_out(result)


@router.post("/{season_id}/search/grab-missing", response_model=GrabMissingOut)
def grab_missing(
    season_id: int,
    body: SearchIn | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> GrabMissingOut:
    season = get_or_404(db, Season, season_id, "season")
    try:
        res = search.grab_missing(db, season, settings, query=body.query if body else None)
    except search.SearchError as exc:
        raise _search_error(exc) from exc
    for d in res.grabbed:
        db.refresh(d)
    return GrabMissingOut(
        grabbed=[DownloadOut.from_model(d) for d in res.grabbed],
        skipped=[SkippedOut(episode_number=n, reason=r) for n, r in res.skipped],
        errors=res.errors,
    )

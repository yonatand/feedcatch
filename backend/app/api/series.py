"""/api/series, /api/seasons"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import AUTH, Page, Session, Settings, count, get_db, get_or_404, get_settings, page_params
from app.api.metadata import metadata_http_error, provider_or_400
from app.models import Rule, Season, Series
from app.schemas import (
    ItemsOut,
    LinkMetadataIn,
    Paginated,
    PreviewPathIn,
    PreviewPathOut,
    SeasonIn,
    SeasonOut,
    SeasonPathOut,
    SeriesIn,
    SeriesOut,
)
from app.services import activity, episodes, metadata, paths, settings_store
from app.services.metadata import MetadataError

router = APIRouter(tags=["series"], dependencies=AUTH)


def _rule_counts(db: Session) -> dict[int, int]:
    rows = db.execute(select(Rule.series_id, func.count()).group_by(Rule.series_id)).all()
    return {int(sid): int(n) for sid, n in rows}


def series_out(db: Session, series: Series, warnings: dict[int, list[str]] | None = None) -> SeriesOut:
    db.refresh(series, ["seasons"])
    n = db.scalar(select(func.count()).select_from(Rule).where(Rule.series_id == series.id)) or 0
    summaries = episodes.season_summaries(db, [s.id for s in series.seasons])
    out = SeriesOut.from_model(series, settings_store.get_media_base_path(db), int(n), summaries)
    for s in out.seasons:
        s.warnings = list((warnings or {}).get(s.id, []))
    return out


def season_out(db: Session, season: Season, warnings: list[str] | None = None) -> SeasonOut:
    summary = episodes.season_summaries(db, [season.id]).get(season.id)
    out = SeasonOut.from_model(season, settings_store.get_media_base_path(db), summary)
    out.warnings = list(warnings or [])
    return out


def refresh_best_effort(db: Session, season: Season, settings: Settings) -> list[str]:
    """Fetch episode metadata for a linked season; failures become warnings (never raise). Commits."""
    if not season.metadata_provider or not season.metadata_id:
        return []
    try:
        metadata.refresh_season(db, season, settings)
        db.commit()
        return []
    except MetadataError as exc:
        db.rollback()
        msg = f"episode metadata could not be fetched: {exc}"
        activity.log_event(
            db,
            "warning",
            "metadata_refresh_failed",
            f"Season {season.season_number} of '{season.series.name}': {msg}",
            details={"season_id": season.id, "provider": season.metadata_provider},
        )
        db.commit()
        return [msg]


def _name_conflict(db: Session, name: str, exclude_id: int | None = None) -> None:
    stmt = select(Series.id).where(func.lower(Series.name) == name.lower())
    if exclude_id is not None:
        stmt = stmt.where(Series.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise HTTPException(status_code=409, detail=f"a series named '{name}' already exists")


def _metadata_conflict(db: Session, provider: str | None, media_id: str | None, exclude_id: int | None = None) -> None:
    if provider is None or media_id is None:
        return
    stmt = select(Series.id, Series.name).where(Series.metadata_provider == provider, Series.metadata_id == media_id)
    if exclude_id is not None:
        stmt = stmt.where(Series.id != exclude_id)
    row = db.execute(stmt).first()
    if row is not None:
        raise HTTPException(status_code=409, detail=f"{provider} id {media_id} is already linked to '{row.name}'")


def _apply_metadata(series: Series, body: SeriesIn, only_if_set: bool) -> None:
    """Copy the metadata fields; on update only those the client actually sent (older clients omit them)."""
    sent = body.model_fields_set
    if not only_if_set or {"metadata_provider", "metadata_id"} & sent:
        series.metadata_provider = body.metadata_provider
        series.metadata_id = body.metadata_id
    if not only_if_set or "cover_url" in sent:
        series.cover_url = body.cover_url
    if not only_if_set or "metadata" in sent:
        series.metadata_info = body.metadata.model_dump() if body.metadata is not None else None


def _season_conflict(db: Session, series_id: int, number: int, exclude_id: int | None = None) -> None:
    stmt = select(Season.id).where(Season.series_id == series_id, Season.season_number == number)
    if exclude_id is not None:
        stmt = stmt.where(Season.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise HTTPException(status_code=409, detail=f"season {number} already exists for this series")


def _apply_season(season: Season, body: SeasonIn, only_if_set: bool = False) -> None:
    season.season_number = body.season_number
    season.monitored = body.monitored
    season.path_override = body.path_override
    season.episode_min = body.episode_min
    season.episode_max = body.episode_max
    season.absolute_min = body.absolute_min
    season.absolute_max = body.absolute_max
    if not only_if_set or {"metadata_provider", "metadata_id"} & body.model_fields_set:
        season.metadata_provider = body.metadata_provider
        season.metadata_id = body.metadata_id


@router.get("/api/series", response_model=Paginated[SeriesOut])
def list_series(page: Page = Depends(page_params), db: Session = Depends(get_db)) -> Paginated[SeriesOut]:
    stmt = select(Series).options(selectinload(Series.seasons)).order_by(func.lower(Series.name))
    base = settings_store.get_media_base_path(db)
    counts = _rule_counts(db)
    rows = list(db.scalars(stmt.limit(page.limit).offset(page.offset)))
    summaries = episodes.season_summaries(db, [s.id for sr in rows for s in sr.seasons])
    items = [SeriesOut.from_model(s, base, counts.get(s.id, 0), summaries) for s in rows]
    return Paginated[SeriesOut](items=items, total=count(db, select(Series)))


@router.post("/api/series", response_model=SeriesOut, status_code=201)
def create_series(
    body: SeriesIn, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> SeriesOut:
    _name_conflict(db, body.name)
    _metadata_conflict(db, body.metadata_provider, body.metadata_id)
    series = Series(
        name=body.name,
        aliases=body.aliases,
        monitored=body.monitored,
        season_folder_format=body.season_folder_format,
        path_override=body.path_override,
        category_override=body.category_override,
    )
    _apply_metadata(series, body, only_if_set=False)
    db.add(series)
    db.flush()
    seasons: list[Season] = []
    for s in body.seasons or []:
        season = Season(series_id=series.id)
        _apply_season(season, s)
        db.add(season)
        seasons.append(season)
    db.flush()
    activity.log_event(db, "info", "series_created", f"Series '{series.name}' added", details={"series_id": series.id})
    db.commit()
    warnings = {s.id: refresh_best_effort(db, s, settings) for s in seasons}
    return series_out(db, series, warnings)


@router.post("/api/series/preview-path", response_model=PreviewPathOut)
def preview_path(body: PreviewPathIn, db: Session = Depends(get_db)) -> PreviewPathOut:
    try:
        p = paths.preview_path(
            settings_store.get_media_base_path(db),
            body.name,
            body.season_folder_format,
            body.path_override or None,
            body.season_number,
            body.season_path_override or None,
        )
    except paths.PathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PreviewPathOut(save_path=p)


@router.get("/api/series/{series_id}", response_model=SeriesOut)
def get_series(series_id: int, db: Session = Depends(get_db)) -> SeriesOut:
    return series_out(db, get_or_404(db, Series, series_id, "series"))


@router.put("/api/series/{series_id}", response_model=SeriesOut)
def update_series(series_id: int, body: SeriesIn, db: Session = Depends(get_db)) -> SeriesOut:
    series = get_or_404(db, Series, series_id, "series")
    _name_conflict(db, body.name, exclude_id=series.id)
    if {"metadata_provider", "metadata_id"} & body.model_fields_set:
        _metadata_conflict(db, body.metadata_provider, body.metadata_id, exclude_id=series.id)
    series.name = body.name
    series.aliases = body.aliases
    series.monitored = body.monitored
    series.season_folder_format = body.season_folder_format
    series.path_override = body.path_override
    series.category_override = body.category_override
    _apply_metadata(series, body, only_if_set=True)
    activity.log_event(
        db, "info", "series_updated", f"Series '{series.name}' updated", details={"series_id": series.id}
    )
    db.commit()
    return series_out(db, series)


@router.put("/api/series/{series_id}/metadata", response_model=SeriesOut)
def link_metadata(
    series_id: int, body: LinkMetadataIn, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> SeriesOut:
    """Link (fetch detail, merge suggested aliases, link empty seasons; never renames) or unlink (both null)."""
    series = get_or_404(db, Series, series_id, "series")
    if body.provider is None or body.id is None:
        series.metadata_provider = None
        series.metadata_id = None
        series.cover_url = None
        series.metadata_info = None
        activity.log_event(
            db,
            "info",
            "series_metadata_unlinked",
            f"Series '{series.name}' unlinked from its metadata provider",
            details={"series_id": series.id},
        )
        db.commit()
        return series_out(db, series)

    provider = provider_or_400(body.provider, db, settings)
    _metadata_conflict(db, body.provider, body.id, exclude_id=series.id)  # before spending an upstream call
    try:
        detail = provider.detail(body.id)
    except MetadataError as exc:
        raise metadata_http_error(exc) from exc
    _metadata_conflict(db, body.provider, detail.id, exclude_id=series.id)
    suggestion = metadata.build_suggestion(detail)
    aliases = list(series.aliases or [])
    seen = {a.casefold() for a in aliases} | {series.name.casefold()}
    for alias in [suggestion.name, *suggestion.aliases]:
        if alias.casefold() not in seen:
            seen.add(alias.casefold())
            aliases.append(alias)
    series.aliases = aliases
    series.metadata_provider = body.provider
    series.metadata_id = detail.id
    series.cover_url = suggestion.cover_url
    series.metadata_info = suggestion.metadata

    # Seasons without a link get one: season 1 for AniList (one entry = one season); every suggested season
    # number that exists for TMDB (the TV id covers all seasons).
    numbers = {1} if body.provider == "anilist" else {int(s["season_number"]) for s in suggestion.seasons}
    linked: list[Season] = []
    for season in series.seasons:
        if season.season_number in numbers and not season.metadata_provider:
            season.metadata_provider = body.provider
            season.metadata_id = detail.id
            linked.append(season)
    activity.log_event(
        db,
        "info",
        "series_metadata_linked",
        f"Series '{series.name}' linked to {provider.label} {detail.id}",
        details={"series_id": series.id, "provider": body.provider, "id": detail.id, "seasons_linked": len(linked)},
    )
    db.commit()
    warnings = {s.id: refresh_best_effort(db, s, settings) for s in linked}
    return series_out(db, series, warnings)


@router.delete("/api/series/{series_id}", status_code=204)
def delete_series(series_id: int, db: Session = Depends(get_db)) -> Response:
    series = get_or_404(db, Series, series_id, "series")
    name = series.name
    db.delete(series)
    activity.log_event(db, "info", "series_deleted", f"Series '{name}' deleted", details={"series_id": series_id})
    db.commit()
    return Response(status_code=204)


@router.get("/api/series/{series_id}/paths", response_model=ItemsOut[SeasonPathOut])
def series_paths(series_id: int, db: Session = Depends(get_db)) -> ItemsOut[SeasonPathOut]:
    series = get_or_404(db, Series, series_id, "series")
    base = settings_store.get_media_base_path(db)
    items: list[SeasonPathOut] = []
    for season in series.seasons:
        try:
            p = paths.build_save_path(base, series, season)
        except paths.PathError as exc:
            p = f"invalid path: {exc}"
        items.append(SeasonPathOut(season_id=season.id, season_number=season.season_number, save_path=p))
    return ItemsOut[SeasonPathOut](items=items)


@router.post("/api/series/{series_id}/seasons", response_model=SeasonOut, status_code=201)
def create_season(
    series_id: int, body: SeasonIn, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> SeasonOut:
    series = get_or_404(db, Series, series_id, "series")
    _season_conflict(db, series.id, body.season_number)
    season = Season(series_id=series.id)
    _apply_season(season, body)
    db.add(season)
    db.flush()
    activity.log_event(
        db,
        "info",
        "season_created",
        f"Season {season.season_number} added to '{series.name}'",
        details={"series_id": series.id, "season_id": season.id},
    )
    db.commit()
    warnings = refresh_best_effort(db, season, settings)
    return season_out(db, season, warnings)


@router.put("/api/seasons/{season_id}", response_model=SeasonOut)
def update_season(
    season_id: int, body: SeasonIn, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> SeasonOut:
    season = get_or_404(db, Season, season_id, "season")
    _season_conflict(db, season.series_id, body.season_number, exclude_id=season.id)
    before = (season.metadata_provider, season.metadata_id)
    _apply_season(season, body, only_if_set=True)
    changed = (season.metadata_provider, season.metadata_id) != before
    db.commit()
    warnings = refresh_best_effort(db, season, settings) if changed else []
    return season_out(db, season, warnings)


@router.delete("/api/seasons/{season_id}", status_code=204)
def delete_season(season_id: int, db: Session = Depends(get_db)) -> Response:
    season = get_or_404(db, Season, season_id, "season")
    activity.log_event(
        db,
        "info",
        "season_deleted",
        f"Season {season.season_number} of '{season.series.name}' deleted",
        details={"series_id": season.series_id, "season_id": season.id},
    )
    db.delete(season)
    db.commit()
    return Response(status_code=204)

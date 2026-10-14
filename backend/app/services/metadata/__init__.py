"""Pluggable metadata providers (`anilist`, `tmdb`) and the season episode refresh. See `.claude/rules/metadata.md`."""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Episode, Season, utcnow
from app.services import activity, settings_store
from app.services.metadata.anilist import AnilistProvider
from app.services.metadata.base import (
    PROVIDER_NAMES,
    EpisodeInfo,
    MediaDetail,
    MediaResult,
    MetadataError,
    MetadataProvider,
    RelatedInfo,
    SeasonInfo,
    Suggestion,
    build_suggestion,
    info_of,
)
from app.services.metadata.tmdb import TmdbProvider

__all__ = [
    "PROVIDER_NAMES",
    "EpisodeInfo",
    "MediaDetail",
    "MediaResult",
    "MetadataError",
    "MetadataProvider",
    "RelatedInfo",
    "SeasonInfo",
    "Suggestion",
    "build_suggestion",
    "get_provider",
    "info_of",
    "list_providers",
    "refresh_season",
]

log = structlog.get_logger("metadata")


def get_provider(name: str, db: Session, settings: Settings) -> MetadataProvider:
    """Provider instance by name. Raises MetadataError for unknown names (TMDB without a key raises on use)."""
    if name == "anilist":
        return AnilistProvider(jikan=settings.JIKAN_ENABLED)
    if name == "tmdb":
        return TmdbProvider(settings_store.get_tmdb_api_key(db, settings))
    raise MetadataError(f"unknown metadata provider '{name}'")


def list_providers(db: Session, settings: Settings) -> list[dict[str, Any]]:
    tmdb_ok = bool(settings_store.get_tmdb_api_key(db, settings))
    return [
        {"name": "anilist", "label": AnilistProvider.label, "kind": AnilistProvider.kind, "configured": True},
        {"name": "tmdb", "label": TmdbProvider.label, "kind": TmdbProvider.kind, "configured": tmdb_ok},
    ]


def refresh_season(db: Session, season: Season, settings: Settings) -> list[Episode]:
    """Fetch the season's episodes from its provider and upsert them (flush only; caller commits).

    Never overwrites rows with source 'manual' and never deletes rows. Raises MetadataError
    (`not_linked` when the season has no provider link).
    """
    if not season.metadata_provider or not season.metadata_id:
        raise MetadataError("season is not linked to a metadata provider", not_linked=True)
    provider = get_provider(season.metadata_provider, db, settings)
    infos = provider.episodes(season.metadata_id, season.season_number)
    existing = {e.episode_number: e for e in db.scalars(select(Episode).where(Episode.season_id == season.id))}
    created = updated = 0
    for info in infos:
        src = info.source or provider.name
        row = existing.get(info.number)
        if row is None:
            row = Episode(
                season_id=season.id, episode_number=info.number, title=info.title, air_date=info.air_date, source=src
            )
            db.add(row)
            existing[info.number] = row
            created += 1
            continue
        if row.source == "manual":
            continue
        changed = False
        if info.title is not None and row.title != info.title:
            row.title = info.title
            changed = True
        if info.air_date is not None and row.air_date != info.air_date:
            row.air_date = info.air_date
            changed = True
        if changed:
            row.source = src
            updated += 1
    season.metadata_refreshed_at = utcnow()
    series_name = season.series.name if season.series is not None else f"series {season.series_id}"
    activity.log_event(
        db,
        "info",
        "metadata_refreshed",
        f"Episode metadata for '{series_name}' S{season.season_number:02d}: "
        f"{len(infos)} from {provider.label}, {created} new, {updated} updated",
        details={
            "season_id": season.id,
            "provider": provider.name,
            "fetched": len(infos),
            "created": created,
            "updated": updated,
            "total": len(existing),
        },
    )
    db.flush()
    return sorted(existing.values(), key=lambda e: e.episode_number)

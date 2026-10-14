"""Pydantic v2 request/response models mirroring `.claude/rules/api-contract.md`.

Output models that need joins expose `from_model(...)` classmethods.
All datetimes serialize as ISO-8601 UTC with a trailing `Z`.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator, model_validator

from app.services import paths
from app.services.types import Condition, ParsedRelease

if TYPE_CHECKING:
    from app import models


def _to_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


UTCDatetime = Annotated[datetime, PlainSerializer(_to_z, return_type=str, when_used="json")]

BackfillMode = Literal["skip", "process"]
FeedStatus = Literal["never", "ok", "error"]
Outcome = Literal["unprocessed", "accepted", "rejected", "no_match", "historical", "duplicate", "searched"]
DownloadStatus = Literal["pending", "submitted", "failed", "exists", "path_mismatch"]
UrlKind = Literal["magnet", "torrent"]
Level = Literal["info", "warning", "error"]
Source = Literal["env", "db"]
DuplicatePolicy = Literal["one_per_episode", "allow_upgrades"]
ProviderName = Literal["anilist", "tmdb"]
MediaKind = Literal["anime", "tv"]
EpisodeSource = Literal["anilist", "jikan", "tmdb", "manual"]
EpisodeStatus = Literal["downloaded", "downloading", "pending", "missing", "unaired", "unknown"]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- shared


class ConditionOut(_Out):
    check: str
    passed: bool
    detail: str

    @classmethod
    def from_any(cls, c: Condition | dict[str, Any]) -> ConditionOut:
        if isinstance(c, Condition):
            return cls(check=c.check, passed=c.passed, detail=c.detail)
        return cls(check=str(c.get("check", "")), passed=bool(c.get("passed")), detail=str(c.get("detail", "")))


class ParsedReleaseOut(_Out):
    group: str | None
    title: str
    season: int | None
    episode: int | None
    episode_end: int | None
    absolute: bool
    version: int | None
    resolution: str | None
    source: str | None
    codec: str | None
    audio: str | None
    subs: list[str]
    is_batch: bool
    raw: str

    @classmethod
    def from_parsed(cls, p: ParsedRelease) -> ParsedReleaseOut:
        return cls.model_validate(p.to_dict())


class Paginated[T](BaseModel):
    items: list[T]
    total: int


class ItemsOut[T](BaseModel):
    items: list[T]


# ---------------------------------------------------------------- feeds


class FeedSourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=2048)
    enabled: bool = True
    poll_interval_minutes: int = Field(default=15, ge=5, le=1440)
    backfill_mode: BackfillMode = "skip"
    # URL with exactly one `{query}` placeholder (release search); SSRF-checked by the router.
    search_url_template: str | None = Field(default=None, max_length=2048)

    @field_validator("name", "url")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v

    @field_validator("search_url_template")
    @classmethod
    def _template(cls, v: str | None) -> str | None:
        if v is None or v.strip() == "":
            return None
        v = v.strip()
        if v.count("{query}") != 1:
            raise ValueError("must contain {query} exactly once")
        return v


class FeedSourceOut(_Out):
    id: int
    name: str
    url: str
    enabled: bool
    poll_interval_minutes: int
    backfill_mode: BackfillMode
    last_checked_at: UTCDatetime | None
    last_success_at: UTCDatetime | None
    last_status: FeedStatus
    last_error: str | None
    consecutive_failures: int
    initial_poll_done: bool
    search_url_template: str | None = None
    entry_count: int = 0
    created_at: UTCDatetime

    @classmethod
    def from_model(cls, feed: models.FeedSource, entry_count: int = 0) -> FeedSourceOut:
        return cls(
            id=feed.id,
            name=feed.name,
            url=feed.url,
            enabled=feed.enabled,
            poll_interval_minutes=feed.poll_interval_minutes,
            backfill_mode=feed.backfill_mode,  # type: ignore[arg-type]
            last_checked_at=feed.last_checked_at,
            last_success_at=feed.last_success_at,
            last_status=feed.last_status,  # type: ignore[arg-type]
            last_error=feed.last_error,
            consecutive_failures=feed.consecutive_failures,
            initial_poll_done=feed.initial_poll_done,
            search_url_template=feed.search_url_template,
            entry_count=entry_count,
            created_at=feed.created_at,
        )


class FeedEntryPreviewOut(_Out):
    guid: str
    title: str
    link: str | None
    published_at: UTCDatetime | None
    magnet_url: str | None
    torrent_url: str | None
    has_nzb: bool
    size_bytes: int | None
    infohash: str | None
    parsed: ParsedReleaseOut


def _parsed_of(entry: models.FeedEntry) -> ParsedReleaseOut:
    if entry.parsed:
        return ParsedReleaseOut.from_parsed(ParsedRelease.from_dict(entry.parsed))
    from app.services.parser import parse_title

    return ParsedReleaseOut.from_parsed(parse_title(entry.title))


class FeedEntryOut(FeedEntryPreviewOut):
    id: int
    feed_id: int
    feed_name: str
    first_seen_at: UTCDatetime
    is_historical: bool
    processed_at: UTCDatetime | None
    outcome: Outcome
    outcome_summary: str | None

    @staticmethod
    def _fields(entry: models.FeedEntry) -> dict[str, Any]:
        return {
            "id": entry.id,
            "feed_id": entry.feed_id,
            "feed_name": entry.feed.name if entry.feed is not None else "",
            "guid": entry.guid,
            "title": entry.title,
            "link": entry.link,
            "published_at": entry.published_at,
            "magnet_url": entry.magnet_url,
            "torrent_url": entry.torrent_url,
            "has_nzb": bool(entry.nzb_url),
            "size_bytes": entry.size_bytes,
            "infohash": entry.infohash,
            "parsed": _parsed_of(entry),
            "first_seen_at": entry.first_seen_at,
            "is_historical": entry.is_historical,
            "processed_at": entry.processed_at,
            "outcome": entry.outcome,
            "outcome_summary": entry.outcome_summary,
        }

    @classmethod
    def from_model(cls, entry: models.FeedEntry) -> FeedEntryOut:
        return cls(**cls._fields(entry))


class EvaluationOut(_Out):
    rule_id: int
    rule_name: str
    series_id: int
    series_name: str
    season_id: int | None
    season_number: int | None
    episode_number: int | None
    matched: bool
    conditions: list[ConditionOut]
    evaluated_at: UTCDatetime

    @classmethod
    def from_model(cls, ev: models.Evaluation) -> EvaluationOut:
        rule = ev.rule
        return cls(
            rule_id=ev.rule_id,
            rule_name=rule.name,
            series_id=rule.series_id,
            series_name=rule.series.name,
            season_id=ev.season_id,
            season_number=ev.season.season_number if ev.season is not None else None,
            episode_number=ev.episode_number,
            matched=ev.matched,
            conditions=[ConditionOut.from_any(c) for c in (ev.conditions or [])],
            evaluated_at=ev.evaluated_at,
        )


# ---------------------------------------------------------------- seasons / series


def _http_url(v: str | None) -> str | None:
    """Optional absolute http(s) URL (cover / AniList links rendered by the UI); blank -> None."""
    if v is None or v.strip() == "":
        return None
    v = v.strip()
    if len(v) > 2048 or not re.match(r"^https?://[^\s/]+", v, re.IGNORECASE) or any(ord(c) < 0x20 for c in v):
        raise ValueError("must be an absolute http(s) URL")
    return v


class MetadataInfo(BaseModel):
    """Stored on `series.metadata_json`; see `.claude/rules/metadata.md`."""

    provider: ProviderName | None = None
    id: str | None = None
    title: str | None = None
    original_title: str | None = None
    alt_titles: list[str] = Field(default_factory=list)
    kind: MediaKind | None = None
    format: str | None = None
    status: str | None = None
    year: int | None = None
    episodes: int | None = None
    site_url: str | None = None

    @field_validator("site_url")
    @classmethod
    def _site(cls, v: str | None) -> str | None:
        return _http_url(v)


def _metadata_id(v: str | int | None) -> str | None:
    if v is None:
        return None
    v = str(v).strip()
    if not v:
        return None
    if len(v) > 64 or not re.match(r"^[A-Za-z0-9_.:-]+$", v):
        raise ValueError("metadata_id must be a short alphanumeric id")
    return v


class SeasonIn(BaseModel):
    season_number: int = Field(ge=0, le=9999)
    monitored: bool = True
    path_override: str | None = None
    episode_min: int | None = Field(default=None, ge=0)
    episode_max: int | None = Field(default=None, ge=0)
    absolute_min: int | None = Field(default=None, ge=0)
    absolute_max: int | None = Field(default=None, ge=0)
    metadata_provider: ProviderName | None = None
    metadata_id: str | None = None

    @field_validator("path_override")
    @classmethod
    def _override(cls, v: str | None) -> str | None:
        if v is None or v.strip() == "":
            return None
        try:
            return paths.validate_override(v.strip())
        except paths.PathError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("metadata_id", mode="before")
    @classmethod
    def _mid(cls, v: str | int | None) -> str | None:
        return _metadata_id(v)

    @model_validator(mode="after")
    def _ranges(self) -> SeasonIn:
        if self.episode_min is not None and self.episode_max is not None and self.episode_min > self.episode_max:
            raise ValueError("episode_min must be <= episode_max")
        if self.absolute_min is not None and self.absolute_max is not None and self.absolute_min > self.absolute_max:
            raise ValueError("absolute_min must be <= absolute_max")
        if self.absolute_max is not None and self.absolute_min is None:
            raise ValueError("absolute_max requires absolute_min")
        if (self.metadata_provider is None) != (self.metadata_id is None):
            raise ValueError("metadata_provider and metadata_id must be set together")
        return self


class SeasonOut(_Out):
    id: int
    series_id: int
    season_number: int
    monitored: bool
    path_override: str | None
    episode_min: int | None
    episode_max: int | None
    absolute_min: int | None
    absolute_max: int | None
    computed_save_path: str
    metadata_provider: ProviderName | None = None
    metadata_id: str | None = None
    metadata_refreshed_at: UTCDatetime | None = None
    episode_count: int = 0
    downloaded_count: int = 0
    missing_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    created_at: UTCDatetime

    @classmethod
    def from_model(cls, season: models.Season, media_base: str, summary: SeasonSummaryOut | None = None) -> SeasonOut:
        try:
            computed = paths.build_save_path(media_base, season.series, season)
        except paths.PathError as exc:
            computed = f"invalid path: {exc}"
        summary = summary or SeasonSummaryOut()
        return cls(
            id=season.id,
            series_id=season.series_id,
            season_number=season.season_number,
            monitored=season.monitored,
            path_override=season.path_override,
            episode_min=season.episode_min,
            episode_max=season.episode_max,
            absolute_min=season.absolute_min,
            absolute_max=season.absolute_max,
            computed_save_path=computed,
            metadata_provider=season.metadata_provider,  # type: ignore[arg-type]
            metadata_id=season.metadata_id,
            metadata_refreshed_at=season.metadata_refreshed_at,
            episode_count=summary.episode_count,
            downloaded_count=summary.downloaded_count,
            missing_count=summary.missing_count,
            created_at=season.created_at,
        )


class SeriesIn(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    monitored: bool = True
    season_folder_format: str = paths.DEFAULT_SEASON_FOLDER_FORMAT
    path_override: str | None = None
    category_override: str | None = None
    seasons: list[SeasonIn] | None = None
    metadata_provider: ProviderName | None = None
    metadata_id: str | None = None
    cover_url: str | None = None
    metadata: MetadataInfo | None = None

    @field_validator("metadata_id", mode="before")
    @classmethod
    def _mid(cls, v: str | int | None) -> str | None:
        return _metadata_id(v)

    @field_validator("cover_url")
    @classmethod
    def _cover(cls, v: str | None) -> str | None:
        return _http_url(v)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        try:
            return paths.sanitize_component(v)
        except paths.PathError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("aliases")
    @classmethod
    def _aliases(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for a in v:
            a = a.strip()
            if a and a not in out:
                out.append(a)
        return out

    @field_validator("season_folder_format")
    @classmethod
    def _fmt(cls, v: str) -> str:
        try:
            return paths.validate_season_folder_format(v)
        except paths.PathError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("path_override")
    @classmethod
    def _override(cls, v: str | None) -> str | None:
        if v is None or v.strip() == "":
            return None
        try:
            return paths.validate_override(v.strip())
        except paths.PathError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("category_override")
    @classmethod
    def _cat(cls, v: str | None) -> str | None:
        return v.strip() or None if v is not None else None

    @model_validator(mode="after")
    def _unique_seasons(self) -> SeriesIn:
        if self.seasons:
            nums = [s.season_number for s in self.seasons]
            if len(nums) != len(set(nums)):
                raise ValueError("duplicate season_number in seasons")
        if (self.metadata_provider is None) != (self.metadata_id is None):
            raise ValueError("metadata_provider and metadata_id must be set together")
        return self


class SeriesOut(_Out):
    id: int
    name: str
    aliases: list[str]
    monitored: bool
    season_folder_format: str
    path_override: str | None
    category_override: str | None
    seasons: list[SeasonOut]
    rule_count: int
    metadata_provider: ProviderName | None = None
    metadata_id: str | None = None
    cover_url: str | None = None
    metadata: MetadataInfo | None = None
    created_at: UTCDatetime

    @classmethod
    def from_model(
        cls,
        series: models.Series,
        media_base: str,
        rule_count: int | None = None,
        summaries: dict[int, SeasonSummaryOut] | None = None,
    ) -> SeriesOut:
        summaries = summaries or {}
        return cls(
            id=series.id,
            name=series.name,
            aliases=list(series.aliases or []),
            monitored=series.monitored,
            season_folder_format=series.season_folder_format,
            path_override=series.path_override,
            category_override=series.category_override,
            seasons=[SeasonOut.from_model(s, media_base, summaries.get(s.id)) for s in series.seasons],
            rule_count=len(series.rules) if rule_count is None else rule_count,
            metadata_provider=series.metadata_provider,  # type: ignore[arg-type]
            metadata_id=series.metadata_id,
            cover_url=series.cover_url,
            metadata=info_or_none(series.metadata_info),
            created_at=series.created_at,
        )


def info_or_none(raw: dict[str, Any] | None) -> MetadataInfo | None:
    if not raw:
        return None
    try:
        return MetadataInfo.model_validate(raw)
    except ValueError:
        return None


class SeasonSummaryOut(BaseModel):
    episode_count: int = 0
    downloaded_count: int = 0
    missing_count: int = 0
    unaired_count: int = 0


class SeasonPathOut(BaseModel):
    season_id: int
    season_number: int
    save_path: str


class PreviewPathIn(BaseModel):
    name: str
    season_folder_format: str = paths.DEFAULT_SEASON_FOLDER_FORMAT
    path_override: str | None = None
    season_number: int = Field(ge=0)
    season_path_override: str | None = None


class PreviewPathOut(BaseModel):
    save_path: str


# ---------------------------------------------------------------- metadata providers


class MetadataProviderOut(BaseModel):
    name: ProviderName
    label: str
    kind: MediaKind
    configured: bool


class MediaResultOut(_Out):
    provider: ProviderName
    id: str
    title: str | None
    original_title: str | None
    alt_titles: list[str]
    kind: MediaKind
    format: str | None
    status: str | None
    year: int | None
    episodes: int | None
    cover_url: str | None
    site_url: str | None


class SeasonInfoOut(_Out):
    season_number: int
    name: str | None
    episode_count: int | None
    air_date: str | None  # YYYY-MM-DD as reported by the provider


class RelatedInfoOut(_Out):
    relation_type: str
    provider: ProviderName
    id: str
    title: str | None
    format: str | None
    episodes: int | None
    year: int | None
    status: str | None
    suggested_season_number: int | None


class MediaDetailOut(MediaResultOut):
    seasons: list[SeasonInfoOut]
    related: list[RelatedInfoOut]


class SuggestionOut(_Out):
    provider: ProviderName
    id: str
    name: str
    aliases: list[str]
    cover_url: str | None
    metadata: MetadataInfo
    seasons: list[SeasonIn]
    related: list[RelatedInfoOut]


class LinkMetadataIn(BaseModel):
    provider: ProviderName | None = None
    id: str | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _mid(cls, v: str | int | None) -> str | None:
        return _metadata_id(v)

    @model_validator(mode="after")
    def _both(self) -> LinkMetadataIn:
        if (self.provider is None) != (self.id is None):
            raise ValueError("provider and id must both be set (link) or both be null (unlink)")
        return self


# ---------------------------------------------------------------- rules


def _clean_list(v: list[str]) -> list[str]:
    out: list[str] = []
    for item in v:
        item = item.strip()
        if item and item not in out:
            out.append(item)
    return out


class RuleIn(BaseModel):
    series_id: int
    season_id: int | None = None
    name: str = Field(min_length=1, max_length=255)
    enabled: bool = True
    priority: int = 0
    release_group: str | None = None
    require_group_prefix: bool = False
    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    resolutions: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    codecs: list[str] = Field(default_factory=list)
    language_keywords: list[str] = Field(default_factory=list)
    min_size_mb: float | None = Field(default=None, ge=0)
    max_size_mb: float | None = Field(default=None, ge=0)
    regex: str | None = None

    @field_validator("include_keywords", "exclude_keywords", "resolutions", "sources", "codecs", "language_keywords")
    @classmethod
    def _lists(cls, v: list[str]) -> list[str]:
        return _clean_list(v)

    @field_validator("release_group")
    @classmethod
    def _group(cls, v: str | None) -> str | None:
        return v.strip() or None if v is not None else None

    @field_validator("regex")
    @classmethod
    def _regex(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"invalid regex: {exc}") from exc
        return v

    @model_validator(mode="after")
    def _sizes(self) -> RuleIn:
        if self.min_size_mb is not None and self.max_size_mb is not None and self.min_size_mb > self.max_size_mb:
            raise ValueError("min_size_mb must be <= max_size_mb")
        return self


class RuleOut(_Out):
    id: int
    series_id: int
    season_id: int | None
    name: str
    enabled: bool
    priority: int
    release_group: str | None
    require_group_prefix: bool
    include_keywords: list[str]
    exclude_keywords: list[str]
    resolutions: list[str]
    sources: list[str]
    codecs: list[str]
    language_keywords: list[str]
    min_size_mb: float | None
    max_size_mb: float | None
    regex: str | None
    series_name: str
    season_number: int | None
    created_at: UTCDatetime

    @classmethod
    def from_model(cls, rule: models.Rule) -> RuleOut:
        return cls(
            id=rule.id,
            series_id=rule.series_id,
            season_id=rule.season_id,
            name=rule.name,
            enabled=rule.enabled,
            priority=rule.priority,
            release_group=rule.release_group,
            require_group_prefix=rule.require_group_prefix,
            include_keywords=list(rule.include_keywords or []),
            exclude_keywords=list(rule.exclude_keywords or []),
            resolutions=list(rule.resolutions or []),
            sources=list(rule.sources or []),
            codecs=list(rule.codecs or []),
            language_keywords=list(rule.language_keywords or []),
            min_size_mb=rule.min_size_mb,
            max_size_mb=rule.max_size_mb,
            regex=rule.regex,
            series_name=rule.series.name,
            season_number=rule.season.season_number if rule.season is not None else None,
            created_at=rule.created_at,
        )


class SimulateIn(BaseModel):
    rule: RuleIn
    titles: list[str] = Field(max_length=500)
    # Optional unsaved series (incl. seasons). When given, rule.series_id is ignored and rule.season_id is a
    # 0-based index into series.seasons (or null).
    series: SeriesIn | None = None


class SimulationResultOut(BaseModel):
    title: str
    parsed: ParsedReleaseOut
    matched: bool
    season_number: int | None
    episode_number: int | None
    save_path: str | None
    conditions: list[ConditionOut]


class TestRecentResultOut(SimulationResultOut):
    entry_id: int


class ValidateRegexIn(BaseModel):
    pattern: str


class ValidateRegexOut(BaseModel):
    valid: bool
    error: str | None


# ---------------------------------------------------------------- downloads / grab


class DownloadOut(_Out):
    id: int
    entry_id: int
    entry_title: str
    series_id: int
    series_name: str
    season_id: int
    season_number: int
    episode_number: int
    rule_id: int | None
    rule_name: str | None
    infohash: str | None
    source_url: str
    source_url_kind: UrlKind
    save_path: str
    category: str | None
    status: DownloadStatus
    attempts: int
    next_retry_at: UTCDatetime | None
    last_error: str | None
    qbit_hash: str | None
    qbit_state: str | None
    qbit_progress: float | None
    qbit_save_path: str | None
    forced: bool
    created_at: UTCDatetime
    updated_at: UTCDatetime

    @classmethod
    def from_model(cls, d: models.Download) -> DownloadOut:
        return cls(
            id=d.id,
            entry_id=d.entry_id,
            entry_title=d.entry.title if d.entry is not None else "",
            series_id=d.series_id,
            series_name=d.series.name if d.series is not None else "",
            season_id=d.season_id,
            season_number=d.season.season_number if d.season is not None else 0,
            episode_number=d.episode_number,
            rule_id=d.rule_id,
            rule_name=d.rule.name if d.rule is not None else None,
            infohash=d.infohash,
            source_url=d.source_url,
            source_url_kind=d.source_url_kind,  # type: ignore[arg-type]
            save_path=d.save_path,
            category=d.category,
            status=d.status,  # type: ignore[arg-type]
            attempts=d.attempts,
            next_retry_at=d.next_retry_at,
            last_error=d.last_error,
            qbit_hash=d.qbit_hash,
            qbit_state=d.qbit_state,
            qbit_progress=d.qbit_progress,
            qbit_save_path=d.qbit_save_path,
            forced=d.forced,
            created_at=d.created_at,
            updated_at=d.updated_at,
        )


class FeedEntryDetailOut(FeedEntryOut):
    evaluations: list[EvaluationOut]
    downloads: list[DownloadOut]

    @classmethod
    def from_model(cls, entry: models.FeedEntry) -> FeedEntryDetailOut:  # type: ignore[override]
        return cls(
            **cls._fields(entry),
            evaluations=[EvaluationOut.from_model(e) for e in entry.evaluations],
            downloads=[DownloadOut.from_model(d) for d in entry.downloads],
        )


class GrabIn(BaseModel):
    season_id: int
    episode_number: int = Field(ge=0)
    force: bool = False
    confirm: bool = False


class GrabPreviewOut(BaseModel):
    entry_id: int
    season_id: int
    episode_number: int
    save_path: str
    category: str | None
    source_url: str
    source_url_kind: UrlKind
    infohash: str | None
    duplicate_of: DownloadOut | None
    warnings: list[str]


class RetriedOut(BaseModel):
    retried: int


class BackfillSeasonLinksOut(BaseModel):
    linked: int
    refreshed: int
    errors: list[str]


class UpdatedOut(BaseModel):
    updated: int


# ---------------------------------------------------------------- activity


class ActivityEventOut(_Out):
    id: int
    ts: UTCDatetime
    level: Level
    event_type: str
    message: str
    details: dict[str, Any] | None
    entry_id: int | None
    download_id: int | None


# ---------------------------------------------------------------- qbit


class QbitTestResultOut(BaseModel):
    ok: bool
    at: UTCDatetime
    version: str | None = None
    api_version: str | None = None
    auto_tmm_enabled: bool | None = None
    default_save_path: str | None = None
    category_exists: bool | None = None
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class QbitConfigIn(BaseModel):
    url: str = Field(default="", max_length=2048)
    username: str = Field(default="", max_length=255)
    password: str | None = None  # None/omitted = unchanged; "" = clear
    category: str | None = None
    timeout_seconds: int = Field(default=15, ge=1, le=120)
    start_immediately: bool = True
    poll_status: bool = True

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if v and not re.match(r"^https?://", v, re.IGNORECASE):
            raise ValueError("qBittorrent URL must start with http:// or https://")
        return v

    @field_validator("category")
    @classmethod
    def _cat(cls, v: str | None) -> str | None:
        return v.strip() or None if v is not None else None


class QbitTestIn(BaseModel):
    """Body of POST /api/qbit/test: `{}` (use stored config) or any subset of QbitConfigIn fields."""

    url: str | None = None
    username: str | None = None
    password: str | None = None
    category: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=120)
    start_immediately: bool | None = None
    poll_status: bool | None = None


class QbitConfigOut(BaseModel):
    url: str
    username: str
    password_set: bool
    category: str | None
    timeout_seconds: int
    start_immediately: bool
    poll_status: bool
    sources: dict[str, Source]
    last_test: QbitTestResultOut | None
    warnings: list[str] = Field(default_factory=list)  # extra (not in contract): env-overridden fields ignored on PUT


# ---------------------------------------------------------------- settings / auth / misc


class AppSettingsIn(BaseModel):
    media_base_path: str
    default_season_folder_format: str = paths.DEFAULT_SEASON_FOLDER_FORMAT
    duplicate_policy: DuplicatePolicy = "one_per_episode"
    allow_private_feed_hosts: bool = False
    feed_fetch_timeout_seconds: int = Field(default=20, ge=1, le=300)
    log_retention_days: int = Field(default=30, ge=1, le=3650)
    # Episodes / search (fields omitted by older clients keep their stored value).
    auto_search_missing: bool = False
    search_interval_hours: int = Field(default=24, ge=1, le=24 * 30)
    metadata_refresh_hours: int = Field(default=12, ge=1, le=24 * 30)
    search_delay_seconds: int = Field(default=3, ge=0, le=60)
    # Write-only: None/omitted = unchanged, "" = clear.
    tmdb_api_key: str | None = Field(default=None, max_length=1024)

    @field_validator("media_base_path")
    @classmethod
    def _base(cls, v: str) -> str:
        try:
            return paths.validate_override(v.strip())
        except paths.PathError as exc:
            raise ValueError(f"media_base_path: {exc}") from exc

    @field_validator("default_season_folder_format")
    @classmethod
    def _fmt(cls, v: str) -> str:
        try:
            return paths.validate_season_folder_format(v)
        except paths.PathError as exc:
            raise ValueError(str(exc)) from exc


class AppSettingsOut(BaseModel):
    media_base_path: str
    default_season_folder_format: str
    duplicate_policy: DuplicatePolicy
    allow_private_feed_hosts: bool
    feed_fetch_timeout_seconds: int
    log_retention_days: int
    auto_search_missing: bool
    search_interval_hours: int
    metadata_refresh_hours: int
    search_delay_seconds: int
    tmdb_api_key_set: bool
    sources: dict[str, Source]
    warnings: list[str] = Field(default_factory=list)  # extra (not in contract): env-overridden fields ignored on PUT


class AuthStatusOut(BaseModel):
    auth_mode: Literal["password", "disabled"]
    setup_required: bool
    authenticated: bool


class SetupIn(BaseModel):
    password: str = Field(min_length=8, max_length=1024)


class LoginIn(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class DashboardCounts(BaseModel):
    series_total: int
    series_monitored: int
    rules_active: int
    entries_24h: int
    downloads_submitted_24h: int
    downloads_pending: int
    downloads_failed: int
    wanted: int = 0


class DashboardQbit(BaseModel):
    configured: bool
    last_test: QbitTestResultOut | None


class DashboardScheduler(BaseModel):
    running: bool
    next_feed_poll_at: UTCDatetime | None


class DashboardOut(BaseModel):
    feeds: list[FeedSourceOut]
    counts: DashboardCounts
    recent_downloads: list[DownloadOut]
    failed_downloads: list[DownloadOut]
    recent_entries: list[FeedEntryOut]
    qbit: DashboardQbit
    scheduler: DashboardScheduler
    upcoming: list[CalendarItemOut] = Field(default_factory=list)


class HealthOut(BaseModel):
    status: Literal["ok", "error"]
    db: Literal["ok", "error"]
    scheduler: Literal["running", "stopped"]
    version: str


class FeedTestIn(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class FeedTestOut(BaseModel):
    ok: bool
    feed_title: str | None
    entry_count: int
    sample: list[FeedEntryPreviewOut]
    error: str | None


class PollResultOut(BaseModel):
    fetched: int = 0
    new_entries: int = 0
    historical: int = 0
    accepted: int = 0
    duplicate: int = 0
    rejected: int = 0
    no_match: int = 0
    submitted: int = 0
    errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- episodes / search / calendar


class EpisodeOut(BaseModel):
    id: int
    season_id: int
    episode_number: int
    title: str | None
    air_date: UTCDatetime | None
    source: EpisodeSource
    status: EpisodeStatus
    download: DownloadOut | None


class EpisodeListOut(BaseModel):
    items: list[EpisodeOut]
    summary: SeasonSummaryOut


class EpisodeIn(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    air_date: datetime | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, v: str | None) -> str | None:
        return v.strip() or None if v is not None else None


class SearchIn(BaseModel):
    query: str | None = Field(default=None, max_length=200)

    @field_validator("query")
    @classmethod
    def _q(cls, v: str | None) -> str | None:
        return " ".join(v.split()) or None if v is not None else None


class CandidateOut(BaseModel):
    entry: FeedEntryOut
    episode_number: int
    rule_id: int
    rule_name: str
    conditions: list[ConditionOut]
    save_path: str | None
    episode_status: EpisodeStatus
    already_have: bool


class SearchResultOut(BaseModel):
    queries: list[str]
    feeds_searched: list[str]
    fetched: int
    candidates: list[CandidateOut]
    errors: list[str]


class SkippedOut(BaseModel):
    episode_number: int
    reason: str


class GrabMissingOut(BaseModel):
    grabbed: list[DownloadOut]
    skipped: list[SkippedOut]
    errors: list[str] = Field(default_factory=list)


class CalendarItemOut(BaseModel):
    series_id: int
    series_name: str
    cover_url: str | None
    season_id: int
    season_number: int
    episode_number: int
    title: str | None
    air_date: UTCDatetime
    status: EpisodeStatus
    monitored: bool


class SearchAllSeasonOut(BaseModel):
    season_id: int
    series_name: str
    season_number: int
    grabbed: int
    skipped: int
    errors: list[str]


class SearchAllOut(BaseModel):
    seasons: list[SearchAllSeasonOut]

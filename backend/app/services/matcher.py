"""Rule evaluation. Every condition is evaluated (no short-circuit) so the Match Inspector shows all reasons."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from typing import Protocol

from app.services.parser import canonical_codec, canonical_resolution, canonical_source
from app.services.types import Condition, Evaluation, ParsedRelease

SKIPPED_UNRESOLVED = "skipped: season unresolved"


class SeriesLike(Protocol):
    id: int
    name: str
    aliases: list[str]


class SeasonLike(Protocol):
    id: int
    season_number: int
    monitored: bool
    episode_min: int | None
    episode_max: int | None
    absolute_min: int | None
    absolute_max: int | None


class RuleLike(Protocol):
    season_id: int | None
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


def norm(s: str) -> str:
    """Normalization for series/alias comparison (see release-title-parsing skill)."""
    return re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKC", s).lower()).strip()


def _kw_norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace(".", " ").replace("_", " ").lower()).strip()


def _contains(haystack_norm: str, keyword: str) -> bool:
    k = _kw_norm(keyword)
    return bool(k) and k in haystack_norm


def _resolve_season(
    parsed: ParsedRelease, rule: RuleLike, seasons: Sequence[SeasonLike]
) -> tuple[SeasonLike | None, int | None, Condition]:
    """Return (season, season_episode, condition)."""
    by_number = {s.season_number: s for s in seasons}
    bound = next((s for s in seasons if s.id == rule.season_id), None) if rule.season_id is not None else None

    if parsed.episode is None:
        return None, None, Condition("season", False, "no episode number in title")

    season: SeasonLike | None
    episode: int
    if parsed.season is not None:
        season = by_number.get(parsed.season)
        if season is None:
            return None, None, Condition("season", False, f"season {parsed.season} is not configured for this series")
        episode = parsed.episode
        how = f"explicit season {parsed.season}"
    else:
        ep = parsed.episode
        candidates = [
            s
            for s in seasons
            if s.absolute_min is not None and s.absolute_min <= ep and (s.absolute_max is None or ep <= s.absolute_max)
        ]
        if not candidates:
            return None, None, Condition("season", False, f"ambiguous: no absolute range mapping for episode {ep}")
        if len(candidates) > 1:
            nums = ", ".join(str(s.season_number) for s in candidates)
            return (
                None,
                None,
                Condition("season", False, f"ambiguous: absolute episode {ep} falls in multiple seasons ({nums})"),
            )
        season = candidates[0]
        assert season.absolute_min is not None
        episode = ep - season.absolute_min + 1
        how = f"absolute {ep} -> season {season.season_number} episode {episode}"

    if rule.season_id is not None and season.id != rule.season_id:
        want = bound.season_number if bound is not None else "?"
        return (
            None,
            None,
            Condition("season", False, f"season {season.season_number} does not match rule season {want}"),
        )
    if not season.monitored:
        return season, episode, Condition("season", False, f"season {season.season_number} is unmonitored")
    return season, episode, Condition("season", True, how)


def _series_condition(parsed: ParsedRelease, series: SeriesLike) -> Condition:
    """Any of [title] + alt_titles equal (after `norm`) to any of [name] + aliases. Strict equality, no prefixes."""
    titles = [("title", parsed.title), *(("alt title", t) for t in parsed.alt_titles or [])]
    names = [("name", series.name), *(("alias", a) for a in series.aliases or [])]
    for t_kind, t in titles:
        t_n = norm(t)
        if not t_n:
            continue
        for n_kind, n in names:
            if norm(n) == t_n:
                return Condition("series", True, f"{t_kind} '{t}' matches {n_kind} '{n}'")
    tried = ", ".join(f"'{t}'" for _, t in titles)
    if len(titles) == 1:
        return Condition("series", False, f"title {tried} does not match '{series.name}' or its aliases")
    return Condition("series", False, f"titles tried {tried}; none match '{series.name}' or its aliases")


def evaluate(
    parsed: ParsedRelease,
    raw_title: str,
    size_bytes: int | None,
    rule: RuleLike,
    series: SeriesLike,
    seasons: Sequence[SeasonLike],
) -> Evaluation:
    """Evaluate one release against one rule. `seasons` are the series' seasons."""
    conds: list[Condition] = []
    raw_norm = _kw_norm(raw_title)

    # series
    conds.append(_series_condition(parsed, series))

    # group
    if rule.release_group:
        ok = parsed.group is not None and parsed.group.lower() == rule.release_group.strip().lower()
        conds.append(
            Condition(
                "group",
                ok,
                f"group '{parsed.group}' == '{rule.release_group}'"
                if ok
                else f"group '{parsed.group}' != '{rule.release_group}'",
            )
        )

    # group_prefix
    if rule.require_group_prefix:
        if not rule.release_group:
            conds.append(Condition("group_prefix", False, "require_group_prefix is set but no release group"))
        else:
            prefix = f"[{rule.release_group.strip()}]"
            ok = raw_title.strip().lower().startswith(prefix.lower())
            conds.append(Condition("group_prefix", ok, f"title {'starts' if ok else 'does not start'} with '{prefix}'"))

    # season
    season, episode, season_cond = _resolve_season(parsed, rule, seasons)
    conds.append(season_cond)
    resolved = season_cond.passed and season is not None and episode is not None

    # episode_range (depends on resolved season)
    if not resolved or season is None or episode is None:
        conds.append(Condition("episode_range", False, SKIPPED_UNRESOLVED))
    else:
        lo, hi = season.episode_min, season.episode_max
        if lo is None and hi is None:
            conds.append(Condition("episode_range", True, "no episode range configured"))
        else:
            ok = (lo is None or episode >= lo) and (hi is None or episode <= hi)
            rng = f"{lo if lo is not None else '-inf'}..{hi if hi is not None else 'inf'}"
            conds.append(Condition("episode_range", ok, f"episode {episode} {'in' if ok else 'outside'} {rng}"))

    # include / exclude keywords
    if rule.include_keywords:
        missing = [k for k in rule.include_keywords if not _contains(raw_norm, k)]
        conds.append(
            Condition(
                "include_keywords", not missing, "all present" if not missing else f"missing: {', '.join(missing)}"
            )
        )
    if rule.exclude_keywords:
        found = [k for k in rule.exclude_keywords if _contains(raw_norm, k)]
        conds.append(
            Condition("exclude_keywords", not found, "none present" if not found else f"excluded: {', '.join(found)}")
        )

    # resolution / source / codec
    if rule.resolutions:
        allowed = {canonical_resolution(r) for r in rule.resolutions}
        ok = parsed.resolution is not None and parsed.resolution in allowed
        conds.append(
            Condition("resolution", ok, f"resolution {parsed.resolution} {'in' if ok else 'not in'} {sorted(allowed)}")
        )
    if rule.sources:
        allowed = {canonical_source(s).lower() for s in rule.sources}
        ok = parsed.source is not None and parsed.source.lower() in allowed
        conds.append(Condition("source", ok, f"source {parsed.source} {'in' if ok else 'not in'} {sorted(allowed)}"))
    if rule.codecs:
        allowed = {canonical_codec(c) for c in rule.codecs}
        ok = parsed.codec is not None and parsed.codec in allowed
        conds.append(Condition("codec", ok, f"codec {parsed.codec} {'in' if ok else 'not in'} {sorted(allowed)}"))

    # language
    if rule.language_keywords:
        subs_n = [_kw_norm(s) for s in parsed.subs]
        found = [k for k in rule.language_keywords if _contains(raw_norm, k) or _kw_norm(k) in subs_n]
        conds.append(
            Condition(
                "language",
                bool(found),
                f"found: {', '.join(found)}" if found else f"none of {', '.join(rule.language_keywords)} present",
            )
        )

    # size
    if rule.min_size_mb is not None or rule.max_size_mb is not None:
        if size_bytes is None:
            conds.append(Condition("size", True, "size unknown; not checked"))
        else:
            mb = size_bytes / (1024 * 1024)
            ok = (rule.min_size_mb is None or mb >= rule.min_size_mb) and (
                rule.max_size_mb is None or mb <= rule.max_size_mb
            )
            size_lo = rule.min_size_mb if rule.min_size_mb is not None else 0
            size_hi = rule.max_size_mb if rule.max_size_mb is not None else "inf"
            bounds = f"[{size_lo}, {size_hi}] MB"
            conds.append(Condition("size", ok, f"{mb:.1f} MB {'within' if ok else 'outside'} {bounds}"))

    # regex
    if rule.regex:
        try:
            ok = re.search(rule.regex, raw_title, re.IGNORECASE) is not None
            conds.append(Condition("regex", ok, f"/{rule.regex}/i {'matched' if ok else 'did not match'}"))
        except re.error as exc:
            conds.append(Condition("regex", False, f"invalid regex: {exc}"))

    # batch
    conds.append(
        Condition("batch", False, "batch releases are not auto-grabbed")
        if parsed.is_batch
        else Condition("batch", True, "single episode")
    )

    matched = all(c.passed for c in conds)
    return Evaluation(
        matched=matched,
        season_id=season.id if resolved and season is not None else None,
        season_number=season.season_number if resolved and season is not None else None,
        episode_number=episode if resolved else None,
        conditions=conds,
    )

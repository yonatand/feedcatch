"""Save-path construction for qBittorrent. PURE STRING OPERATIONS ONLY.

Safety invariant 1: nothing in this module touches the filesystem. Paths are strings handed to qBittorrent.
Safety invariant 3: components come from series name / season folder format / user overrides, never feed titles.
"""

from __future__ import annotations

import posixpath
import re
import unicodedata
from typing import Protocol

DEFAULT_MEDIA_BASE = "/home/qbittorrent-nox/media"
DEFAULT_SEASON_FOLDER_FORMAT = "Season {season:02d}"

_ALLOWED_TOKENS = {"{season}", "{season:02d}", "{season:03d}", "{series}"}
_TOKEN_RE = re.compile(r"\{[^{}]*\}")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_FORBIDDEN_RE = re.compile(r'[<>:"|?*]')


class PathError(ValueError):
    """Raised for unsafe or invalid path input."""


class SeriesLike(Protocol):
    name: str
    season_folder_format: str
    path_override: str | None


class SeasonLike(Protocol):
    season_number: int
    path_override: str | None


def sanitize_component(value: str) -> str:
    """Make `value` safe as a single path component, or raise PathError."""
    if not isinstance(value, str):
        raise PathError("path component must be a string")
    s = unicodedata.normalize("NFC", value)
    s = _CONTROL_RE.sub("", s)
    s = s.replace("/", "-").replace("\\", "-")
    s = _FORBIDDEN_RE.sub("", s)
    s = re.sub(r"\s+", " ", s)
    s = s.strip(" .")
    if s in ("", ".", ".."):
        raise PathError(f"invalid path component: {value!r}")
    return s


def validate_season_folder_format(fmt: str) -> str:
    """Allow only {season}, {season:02d}, {season:03d}, {series} tokens. Returns the format unchanged."""
    if not isinstance(fmt, str) or not fmt.strip():
        raise PathError("season folder format must not be empty")
    if _CONTROL_RE.search(fmt):
        raise PathError("season folder format contains control characters")
    for token in _TOKEN_RE.findall(fmt):
        if token not in _ALLOWED_TOKENS:
            raise PathError(f"unsupported token {token} (allowed: {', '.join(sorted(_ALLOWED_TOKENS))})")
    leftover = _TOKEN_RE.sub("", fmt)
    if "{" in leftover or "}" in leftover:
        raise PathError("unbalanced braces in season folder format")
    # Must render to a valid component.
    render_season_folder(fmt, 1, "Series")
    return fmt


def render_season_folder(fmt: str, season_number: int, series_name: str) -> str:
    """Render a validated format by literal token replacement (never str.format)."""
    for token in _TOKEN_RE.findall(fmt):
        if token not in _ALLOWED_TOKENS:
            raise PathError(f"unsupported token {token}")
    if season_number < 0:
        raise PathError("season number must be >= 0")
    out = (
        fmt.replace("{season:02d}", f"{season_number:02d}")
        .replace("{season:03d}", f"{season_number:03d}")
        .replace("{season}", str(season_number))
        .replace("{series}", sanitize_component(series_name) if "{series}" in fmt else "")
    )
    return sanitize_component(out)


def validate_override(path: str) -> str:
    """Validate an absolute posix path override; returns it without trailing slash (except '/')."""
    if not isinstance(path, str) or not path:
        raise PathError("path must be a non-empty string")
    if _CONTROL_RE.search(path):
        raise PathError("path contains control characters")
    if "\\" in path:
        raise PathError("path must not contain backslashes")
    if not path.startswith("/") or path.startswith("//"):
        raise PathError("path must be an absolute posix path (start with a single '/')")
    if ".." in path.split("/"):
        raise PathError("path must not contain '..'")
    stripped = path.rstrip("/") or "/"
    if posixpath.normpath(stripped) != stripped:
        raise PathError("path must be normalized (no '.', or repeated '/')")
    return stripped


def _check(result: str, base: str | None) -> str:
    if not (posixpath.normpath(result) == result.rstrip("/") or result == "/"):
        raise PathError(f"computed path is not normalized: {result!r}")
    if base is not None:
        prefix = base if base == "/" else base + "/"
        if not result.startswith(prefix):
            raise PathError(f"computed path escapes media base: {result!r}")
    return result


def preview_path(
    media_base: str,
    name: str,
    season_folder_format: str,
    path_override: str | None,
    season_number: int,
    season_path_override: str | None,
) -> str:
    """Compute a save path from raw values.

    Precedence: season override > series override + season folder > base/series name/season folder.
    """
    if season_path_override:
        return _check(validate_override(season_path_override), None)
    validate_season_folder_format(season_folder_format)
    folder = render_season_folder(season_folder_format, season_number, name)
    if path_override:
        root = validate_override(path_override)
        return _check(posixpath.join(root, folder), root)
    base = validate_override(media_base)
    series_dir = sanitize_component(name)
    return _check(posixpath.join(base, series_dir, folder), base)


def build_save_path(media_base: str, series: SeriesLike, season: SeasonLike) -> str:
    """Save path for a (series, season) pair, e.g. '/home/qbittorrent-nox/media/Black Clover/Season 02'."""
    return preview_path(
        media_base,
        series.name,
        series.season_folder_format or DEFAULT_SEASON_FOLDER_FORMAT,
        series.path_override,
        season.season_number,
        season.path_override,
    )

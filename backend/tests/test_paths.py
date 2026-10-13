from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import paths
from app.services.paths import (
    PathError,
    build_save_path,
    preview_path,
    render_season_folder,
    sanitize_component,
    validate_override,
    validate_season_folder_format,
)

BASE = "/home/qbittorrent-nox/media"


def test_black_clover_season_2() -> None:
    series = SimpleNamespace(name="Black Clover", season_folder_format="Season {season:02d}", path_override=None)
    season = SimpleNamespace(season_number=2, path_override=None)
    assert build_save_path(BASE, series, season) == "/home/qbittorrent-nox/media/Black Clover/Season 02"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Black Clover", "Black Clover"),
        ("Re:Zero", "ReZero"),
        ("a/b", "a-b"),
        ("a\\b", "a-b"),
        ("../etc", "-etc"),
        ("name.", "name"),
        ("...name...", "name"),
        ("  spaced   out  ", "spaced out"),
        ("bad\x00\x1f\x7fchars", "badchars"),
        ('w<h>a"t|?*', "what"),
        ("Cafe\u0301", "Caf\u00e9"),  # NFC
        ("葬送のフリーレン", "葬送のフリーレン"),
    ],
)
def test_sanitize(raw: str, expected: str) -> None:
    assert sanitize_component(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", ".", "..", "...", "\x00", "?*", " . "])
def test_sanitize_rejects(raw: str) -> None:
    with pytest.raises(PathError):
        sanitize_component(raw)


@pytest.mark.parametrize(
    "fmt", ["Season {season:02d}", "Season {season}", "S{season:03d}", "{series} - Season {season}", "Specials"]
)
def test_valid_formats(fmt: str) -> None:
    assert validate_season_folder_format(fmt) == fmt


@pytest.mark.parametrize(
    "fmt",
    ["", "Season {season:04d}", "{0}", "{season.__class__}", "{name}", "Season {", "Season }", "{}", "{{season}}"],
)
def test_invalid_formats(fmt: str) -> None:
    with pytest.raises(PathError):
        validate_season_folder_format(fmt)


def test_render_tokens() -> None:
    assert render_season_folder("Season {season:02d}", 2, "X") == "Season 02"
    assert render_season_folder("S{season:03d}", 2, "X") == "S002"
    assert render_season_folder("Season {season}", 12, "X") == "Season 12"
    assert render_season_folder("{series} S{season}", 1, "Re:Zero") == "ReZero S1"
    # slashes in the format cannot create extra directories
    assert render_season_folder("a/{season}", 1, "X") == "a-1"


@pytest.mark.parametrize("path", ["/srv/anime", "/srv/anime/", "/", "/a b/c"])
def test_valid_overrides(path: str) -> None:
    out = validate_override(path)
    assert out == (path.rstrip("/") or "/")


@pytest.mark.parametrize(
    "path",
    ["", "relative/path", "/a/../b", "/a/..", "C:\\media", "/a\\b", "/a\x00b", "//server/share", "/a//b", "/a/./b"],
)
def test_invalid_overrides(path: str) -> None:
    with pytest.raises(PathError):
        validate_override(path)


def test_precedence() -> None:
    # season override wins
    assert preview_path(BASE, "Black Clover", "Season {season:02d}", "/srv/bc", 2, "/srv/custom/s2") == "/srv/custom/s2"
    # series override + season folder
    assert preview_path(BASE, "Black Clover", "Season {season:02d}", "/srv/bc", 2, None) == "/srv/bc/Season 02"
    # default
    assert preview_path(BASE, "Black Clover", "Season {season:02d}", None, 0, None) == f"{BASE}/Black Clover/Season 00"


def test_series_name_cannot_escape_base() -> None:
    out = preview_path(BASE, "../../etc", "Season {season:02d}", None, 1, None)
    assert out.startswith(BASE + "/")
    assert ".." not in out.split("/")


def test_invalid_media_base() -> None:
    with pytest.raises(PathError):
        preview_path("media", "X", "Season {season}", None, 1, None)


def test_no_filesystem_calls_in_paths_module() -> None:
    import inspect

    src = inspect.getsource(paths)
    for forbidden in ("os.makedirs", "shutil", ".mkdir(", "open(", "os.path.exists"):
        assert forbidden not in src

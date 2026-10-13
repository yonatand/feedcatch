from __future__ import annotations

from typing import Any

import pytest

from app.models import Rule, Season, Series
from app.services.matcher import evaluate
from app.services.parser import parse_title
from app.services.types import Evaluation


def make_series(**kw: Any) -> Series:
    return Series(id=1, name="Black Clover", aliases=["Black.Clover", "Black_Clover"], **kw)


def make_season(**kw: Any) -> Season:
    base: dict[str, Any] = dict(id=10, series_id=1, season_number=2, monitored=True)
    base.update(kw)
    return Season(**base)


def make_rule(**kw: Any) -> Rule:
    base: dict[str, Any] = dict(
        id=100,
        series_id=1,
        season_id=10,
        name="DKB 1080p",
        enabled=True,
        priority=10,
        release_group="DKB",
        require_group_prefix=True,
        include_keywords=[],
        exclude_keywords=[],
        resolutions=["1080p"],
        sources=[],
        codecs=[],
        language_keywords=[],
        min_size_mb=None,
        max_size_mb=None,
        regex=None,
    )
    base.update(kw)
    return Rule(**base)


def run(
    title: str,
    rule: Rule | None = None,
    seasons: list[Season] | None = None,
    size_bytes: int | None = None,
) -> Evaluation:
    return evaluate(
        parse_title(title),
        title,
        size_bytes,
        rule or make_rule(),
        make_series(),
        seasons if seasons is not None else [make_season()],
    )


def cond(ev: Evaluation, check: str) -> tuple[bool, str]:
    c = next(c for c in ev.conditions if c.check == check)
    return c.passed, c.detail


def test_accept_dkb_season_2() -> None:
    ev = run("[DKB] Black Clover Season 2 - 01 [1080p]")
    assert ev.matched, ev.conditions
    assert (ev.season_id, ev.season_number, ev.episode_number) == (10, 2, 1)
    checks = [c.check for c in ev.conditions]
    assert checks[:5] == ["series", "group", "group_prefix", "season", "episode_range"]
    assert checks[-1] == "batch"


def test_alias_match() -> None:
    assert run("Black_Clover.S02E03.1080p.WEB.H264-DKB", rule=make_rule(require_group_prefix=False)).matched


def test_reject_other_group() -> None:
    ev = run("[SubsPlease] Black Clover Season 2 - 01 [1080p]")
    assert not ev.matched
    assert cond(ev, "group")[0] is False
    assert cond(ev, "group_prefix")[0] is False
    # all conditions still evaluated
    assert cond(ev, "season")[0] is True


def test_reject_other_series() -> None:
    ev = run("[DKB] Black Clover Mobile Season 2 - 01 [1080p]")
    assert not ev.matched
    assert cond(ev, "series")[0] is False


def test_reject_season_mismatch() -> None:
    ev = run("[DKB] Black Clover Season 3 - 01 [1080p]")
    assert not ev.matched
    passed, detail = cond(ev, "season")
    assert not passed and "season 3" in detail
    assert cond(ev, "episode_range") == (False, "skipped: season unresolved")
    assert ev.season_id is None and ev.episode_number is None


def test_reject_season_not_bound_rule() -> None:
    s1 = make_season(id=11, season_number=1)
    ev = run("[DKB] Black Clover Season 1 - 01 [1080p]", seasons=[s1, make_season()])
    passed, detail = cond(ev, "season")
    assert not passed and "does not match rule season 2" in detail


def test_absolute_without_mapping_rejected() -> None:
    ev = run("[DKB] Black Clover - 171 [1080p]")
    assert not ev.matched
    assert cond(ev, "season") == (False, "ambiguous: no absolute range mapping for episode 171")


def test_absolute_with_mapping_accepted() -> None:
    season = make_season(absolute_min=171, absolute_max=300)
    ev = run("[DKB] Black Clover - 171 [1080p]", seasons=[season])
    assert ev.matched, ev.conditions
    assert ev.episode_number == 1
    ev = run("[DKB] Black Clover - 180 [1080p]", seasons=[season])
    assert ev.episode_number == 180 - 171 + 1


def test_absolute_ambiguous_overlap() -> None:
    a = make_season(absolute_min=100, absolute_max=200)
    b = make_season(id=11, season_number=3, absolute_min=150, absolute_max=None)
    ev = run("[DKB] Black Clover - 171 [1080p]", seasons=[a, b])
    passed, detail = cond(ev, "season")
    assert not passed and detail.startswith("ambiguous")


def test_unmonitored_season() -> None:
    ev = run("[DKB] Black Clover Season 2 - 01 [1080p]", seasons=[make_season(monitored=False)])
    assert cond(ev, "season") == (False, "season 2 is unmonitored")
    assert not ev.matched


def test_episode_range() -> None:
    seasons = [make_season(episode_min=1, episode_max=12)]
    assert run("[DKB] Black Clover Season 2 - 12 [1080p]", seasons=seasons).matched
    ev = run("[DKB] Black Clover Season 2 - 13 [1080p]", seasons=seasons)
    assert cond(ev, "episode_range")[0] is False


def test_include_exclude_keywords() -> None:
    title = "[DKB] Black Clover Season 2 - 01 [1080p][HEVC x265 10bit][Multi-Subs]"
    assert run(title, rule=make_rule(include_keywords=["MULTI-SUBS", "10bit", "black.clover"])).matched
    ev = run(title, rule=make_rule(include_keywords=["dual audio"]))
    assert cond(ev, "include_keywords") == (False, "missing: dual audio")
    ev = run(title, rule=make_rule(exclude_keywords=["x265"]))
    assert cond(ev, "exclude_keywords") == (False, "excluded: x265")
    assert run(title, rule=make_rule(exclude_keywords=["720p"])).matched


def test_resolution() -> None:
    ev = run("[DKB] Black Clover Season 2 - 01 [720p]")
    assert cond(ev, "resolution")[0] is False
    assert run("[DKB] Black Clover Season 2 - 01 [720p]", rule=make_rule(resolutions=["720p", "1080P"])).matched


def test_source_codec_language() -> None:
    title = "[DKB] Black Clover - S02E02 [1080p CR WEB-DL H.264 AAC][ENG]"
    assert run(title, rule=make_rule(codecs=["x264"], language_keywords=["ENG"])).matched
    ev = run(title, rule=make_rule(codecs=["x265"]))
    assert cond(ev, "codec")[0] is False
    ev = run(title, rule=make_rule(sources=["BluRay"]))
    assert cond(ev, "source")[0] is False
    ev = run(title, rule=make_rule(language_keywords=["POR-BR"]))
    assert cond(ev, "language")[0] is False


@pytest.mark.parametrize(
    ("size_mb", "lo", "hi", "ok"),
    [(500, 100, 2000, True), (50, 100, 2000, False), (3000, 100, 2000, False), (500, None, 400, False)],
)
def test_size_bounds(size_mb: int, lo: float | None, hi: float | None, ok: bool) -> None:
    ev = run(
        "[DKB] Black Clover Season 2 - 01 [1080p]",
        rule=make_rule(min_size_mb=lo, max_size_mb=hi),
        size_bytes=size_mb * 1024 * 1024,
    )
    assert cond(ev, "size")[0] is ok
    assert ev.matched is ok


def test_size_unknown_passes() -> None:
    ev = run("[DKB] Black Clover Season 2 - 01 [1080p]", rule=make_rule(min_size_mb=100), size_bytes=None)
    assert cond(ev, "size")[0] is True


def test_regex() -> None:
    title = "[DKB] Black Clover Season 2 - 01 [1080p][HEVC x265 10bit]"
    assert run(title, rule=make_rule(regex=r"hevc.*10bit")).matched
    ev = run(title, rule=make_rule(regex=r"\bAV1\b"))
    assert cond(ev, "regex")[0] is False
    ev = run(title, rule=make_rule(regex=r"(unclosed"))
    passed, detail = cond(ev, "regex")
    assert not passed and detail.startswith("invalid regex")


def test_require_group_prefix() -> None:
    scene = "Black.Clover.S02E01.1080p.WEB.H264-DKB"
    ev = run(scene)
    assert cond(ev, "group")[0] is True
    assert cond(ev, "group_prefix")[0] is False
    assert not ev.matched
    assert run(scene, rule=make_rule(require_group_prefix=False)).matched
    assert run("[dkb] Black Clover Season 2 - 01 [1080p]").matched  # case-insensitive


def test_batch_rejected() -> None:
    seasons = [make_season()]
    ev = run("[DKB] Black Clover Season 2 - 01 [1080p][Batch]", seasons=seasons)
    assert cond(ev, "batch") == (False, "batch releases are not auto-grabbed")
    assert not ev.matched


def test_no_episode() -> None:
    ev = run("[DKB] Black Clover S02 [1080p]")
    assert cond(ev, "season")[0] is False
    assert not ev.matched

"""Fixture table from .claude/skills/release-title-parsing/SKILL.md (both tables)."""

from __future__ import annotations

from typing import Any

import pytest

from app.services.parser import parse_title

ANY = object()

# raw, expected fields (values may be a set => "assert in set")
CASES: list[tuple[str, dict[str, Any]]] = [
    (
        "[DKB] Black Clover Season 2 - 01 [1080p]",
        dict(
            group="DKB",
            title="Black Clover",
            season=2,
            episode=1,
            episode_end=None,
            absolute=False,
            resolution="1080p",
            source=None,
            codec=None,
        ),
    ),
    (
        "[DKB] Black Clover - 171 [1080p][HEVC x265 10bit][Multi-Subs]",
        dict(
            group="DKB",
            title="Black Clover",
            season=None,
            episode=171,
            episode_end=None,
            absolute=True,
            resolution="1080p",
            source=None,
            codec="HEVC",
            subs_contains="Multi-Subs",
        ),
    ),
    (
        "[SubsPlease] Black Clover - 171 (1080p) [A1B2C3D4].mkv",
        dict(
            group="SubsPlease",
            title="Black Clover",
            season=None,
            episode=171,
            episode_end=None,
            absolute=True,
            resolution="1080p",
            source=None,
            codec=None,
        ),
    ),
    (
        "[Erai-raws] Black Clover - 171v2 [1080p][Multiple Subtitle][ENG][POR-BR]",
        dict(
            group="Erai-raws",
            title="Black Clover",
            season=None,
            episode=171,
            episode_end=None,
            absolute=True,
            resolution="1080p",
            source=None,
            codec=None,
            version=2,
        ),
    ),
    (
        "Black.Clover.S02E01.1080p.WEB.H264-GROUP",
        dict(
            group="GROUP",
            title="Black Clover",
            season=2,
            episode=1,
            episode_end=None,
            absolute=False,
            resolution="1080p",
            source="WEB",
            codec="H264",
        ),
    ),
    (
        "[Judas] Black Clover (Season 2) - 05 [1080p][HEVC x265 10bit][Dual-Audio][Multi-Subs]",
        dict(
            group="Judas",
            title="Black Clover",
            season=2,
            episode=5,
            episode_end=None,
            absolute=False,
            resolution="1080p",
            source=None,
            codec="HEVC",
            subs_contains="Dual-Audio",
        ),
    ),
    (
        "[DKB] Black Clover S02E13 [1080p][HEVC][x265 10bit]",
        dict(
            group="DKB",
            title="Black Clover",
            season=2,
            episode=13,
            episode_end=None,
            absolute=False,
            resolution="1080p",
            source=None,
            codec="HEVC",
        ),
    ),
    (
        "[Group] Spy x Family Season 2 - 03 [720p]",
        dict(
            group="Group",
            title="Spy x Family",
            season=2,
            episode=3,
            episode_end=None,
            absolute=False,
            resolution="720p",
            source=None,
            codec=None,
        ),
    ),
    (
        "[Group] Spy x Family - 28 [1080p]",
        dict(
            group="Group",
            title="Spy x Family",
            season=None,
            episode=28,
            episode_end=None,
            absolute=True,
            resolution="1080p",
            source=None,
            codec=None,
        ),
    ),
    (
        "[Group] Dungeon Meshi - 01-24 [BD 1080p] [Batch]",
        dict(
            group="Group",
            title="Dungeon Meshi",
            season=None,
            episode=1,
            episode_end=24,
            absolute=True,
            resolution="1080p",
            source="BD",
            codec=None,
            is_batch=True,
        ),
    ),
    (
        "[Group] Re:Zero kara Hajimeru Isekai Seikatsu 3rd Season - 04 [1080p]",
        dict(
            group="Group",
            title="Re:Zero kara Hajimeru Isekai Seikatsu",
            season=3,
            episode=4,
            episode_end=None,
            absolute=False,
            resolution="1080p",
            source=None,
            codec=None,
        ),
    ),
    (
        "[Group] Frieren - Beyond Journey's End - 12 [1080p]",
        dict(
            group="Group",
            title="Frieren - Beyond Journey's End",
            season=None,
            episode=12,
            episode_end=None,
            absolute=True,
            resolution="1080p",
            source=None,
            codec=None,
        ),
    ),
    (
        "[Group] One Piece - 1100 [1080p][AMZN WEB-DL][AAC]",
        dict(
            group="Group",
            title="One Piece",
            season=None,
            episode=1100,
            episode_end=None,
            absolute=True,
            resolution="1080p",
            source={"AMZN", "WEB-DL"},
            codec=None,
            audio="AAC",
        ),
    ),
    (
        "[Group] Some Show (2024) - 02 [1080p]",
        dict(
            group="Group",
            title="Some Show (2024)",
            season=None,
            episode=2,
            episode_end=None,
            absolute=True,
            resolution="1080p",
            source=None,
            codec=None,
        ),
    ),
    (
        "Some Show E05 1080p",
        dict(
            group=None,
            title="Some Show",
            season=None,
            episode=5,
            episode_end=None,
            absolute=True,
            resolution="1080p",
            source=None,
            codec=None,
        ),
    ),
    (
        "random text without numbers",
        dict(
            group=None,
            title="random text without numbers",
            season=None,
            episode=None,
            episode_end=None,
            absolute=False,
            resolution=None,
            source=None,
            codec=None,
        ),
    ),
    # --- Additional real-world cases (live AnimeTosho feed) ---
    (
        "[DKB] Psyren - S01E02 [1080p][HEVC x265 10bit][Multi-Subs][weekly]",
        dict(
            group="DKB",
            title="Psyren",
            season=1,
            episode=2,
            absolute=False,
            resolution="1080p",
            source=None,
            codec="HEVC",
        ),
    ),
    (
        "[FrixySubs] Black Clover - S02E02 [1080p CR WEB-DL H.264 AAC] [Napisy PL].mkv",
        dict(
            group="FrixySubs",
            title="Black Clover",
            season=2,
            episode=2,
            absolute=False,
            resolution="1080p",
            source={"CR", "WEB-DL"},
            codec="H264",
            audio="AAC",
        ),
    ),
    (
        "[Buzz-Subs] Black Clover (2017) S02E01 (1080p AV1 Opus) [Eng-Subs]",
        dict(
            group="Buzz-Subs",
            title="Black Clover (2017)",
            alt_titles=[],
            season=2,
            episode=1,
            absolute=False,
            resolution="1080p",
            source=None,
            codec="AV1",
            audio="Opus",
        ),
    ),
    (
        "[SubsPlus+] Nia Liston - The Merciless Maiden - S01E02 (ADN WEB-DL 1080p AVC AAC) | Kyouran Reijou Nia Liston",
        dict(
            group="SubsPlus+",
            title="Nia Liston - The Merciless Maiden",
            alt_titles=["Kyouran Reijou Nia Liston"],
            season=1,
            episode=2,
            absolute=False,
            resolution="1080p",
            source="WEB-DL",
            codec="H264",
        ),
    ),
    (
        "[SubsPlease] Kyouran Reijou Nia Liston - 02 (1080p) [69FFB377].mkv",
        dict(
            group="SubsPlease",
            title="Kyouran Reijou Nia Liston",
            season=None,
            episode=2,
            absolute=True,
            resolution="1080p",
            source=None,
            codec=None,
        ),
    ),
    (
        "[Shridhuu][1080p] A Good Day to Ascend / 择日飞升 / Zeri Feisheng - S01E15",
        dict(
            group="Shridhuu",
            title="A Good Day to Ascend",
            alt_titles=["择日飞升", "Zeri Feisheng"],
            season=1,
            episode=15,
            absolute=False,
            resolution="1080p",
            source=None,
            codec=None,
        ),
    ),
    (
        "[Doomdos] - Ascendants of the Nine Suns - 50 [1080p IQ WEB-DL]",
        dict(
            group="Doomdos",
            title="Ascendants of the Nine Suns",
            season=None,
            episode=50,
            absolute=True,
            resolution="1080p",
            source="WEB-DL",
            codec=None,
        ),
    ),
    (
        "Arabian Nights - Sindbad no Bouken TV 01-52 [ARR].",
        dict(
            group=None,
            title="Arabian Nights - Sindbad no Bouken TV",
            season=None,
            episode=1,
            episode_end=52,
            absolute=True,
            resolution=None,
            source=None,
            codec=None,
            is_batch=True,
        ),
    ),
    (
        "[Z-A] Re Zero kara Hajimeru Isekai Seikatsu S04 (WEB 1080p AAC)",
        dict(
            group="Z-A",
            title="Re Zero kara Hajimeru Isekai Seikatsu",
            season=4,
            episode=None,
            absolute=False,
            resolution="1080p",
            source="WEB",
            codec=None,
        ),
    ),
    (
        "Nia Liston The Merciless Maiden S01E02 A Job in the Royal Capital 1080p ADN WEB-DL AAC2.0 H.264-VARYG "
        "(Kyouran Reijou Nia Liston, Multi-Subs)",
        dict(
            group={"VARYG", None},
            title="Nia Liston The Merciless Maiden",
            alt_titles=["Kyouran Reijou Nia Liston"],
            subs_contains="Multi-Subs",
            season=1,
            episode=2,
            absolute=False,
            resolution="1080p",
            source="WEB-DL",
            codec="H264",
        ),
    ),
    # Alternate titles (2026-10-14): parenthetical English title, slash and pipe separators.
    (
        '[Judas] Kashita Maryoku wa "Revo Barai" de Kyousei Choushuu (Magic Repo Man: Dumped by My Party, '
        "I’ll Cash In With a Cute Support Fairy to Become the Strongest!) - S01E02 "
        "[1080p][HEVC x265 10bit][Multi-Subs] (Weekly)",
        dict(
            group="Judas",
            title='Kashita Maryoku wa "Revo Barai" de Kyousei Choushuu',
            alt_titles=[
                "Magic Repo Man: Dumped by My Party, I’ll Cash In With a Cute Support Fairy to Become the Strongest!",
                "Magic Repo Man: Dumped by My Party",
                "I’ll Cash In With a Cute Support Fairy to Become the Strongest!",
            ],
            season=1,
            episode=2,
            absolute=False,
            resolution="1080p",
            codec="HEVC",
            subs_contains="Multi-Subs",
            is_batch=False,
        ),
    ),
    (
        "Magic Repo Man Dumped by My Party S01E02 SUBFRENCH 720p CR WEB-DL AAC2.0 x264-Tsundere-Raws "
        "(VOSTFR, Kashita Maryoku wa Revo Barai de Kyousei Choushuu, "
        "Lent Magic Point Is Forcibly Collected by Revolving Payment)",
        dict(
            title="Magic Repo Man Dumped by My Party",
            alt_titles=[
                "Kashita Maryoku wa Revo Barai de Kyousei Choushuu",
                "Lent Magic Point Is Forcibly Collected by Revolving Payment",
            ],
            season=1,
            episode=2,
            resolution="720p",
            codec="H264",
        ),
    ),
    (
        "[Group] Main Title / Alt One / Alt Two - 07 [720p]",
        dict(group="Group", title="Main Title", alt_titles=["Alt One", "Alt Two"], episode=7, absolute=True),
    ),
    (
        "[Group] Main Title - 07 [1080p] | Alt One | Alt Two",
        dict(group="Group", title="Main Title", alt_titles=["Alt One", "Alt Two"], episode=7, resolution="1080p"),
    ),
    (
        "[Group] Fate/stay night - 05 [720p]",
        dict(group="Group", title="Fate/stay night", alt_titles=[], episode=5),
    ),
    (
        "[Group] Title ~Alt Name~ - 03 [1080p]",
        dict(group="Group", title="Title ~Alt Name~", alt_titles=[], episode=3),
    ),
    (
        '[Group] Title "Quoted Part" - 03 [1080p]',
        dict(group="Group", title='Title "Quoted Part"', alt_titles=[], episode=3),
    ),
    (
        "[Group] Show (TV) - 04 (Dual Audio) (Weekly) [1080p]",
        dict(group="Group", title="Show (TV)", alt_titles=[], episode=4, subs_contains="Dual Audio"),
    ),
]


@pytest.mark.parametrize(("raw", "expected"), CASES, ids=[c[0][:60] for c in CASES])
def test_fixture_table(raw: str, expected: dict[str, Any]) -> None:
    parsed = parse_title(raw)
    assert parsed.raw == raw
    for key, value in expected.items():
        if key == "subs_contains":
            assert value in parsed.subs, (key, parsed.subs)
            continue
        actual = getattr(parsed, key)
        if isinstance(value, set):
            assert actual in value, (key, actual)
        else:
            assert actual == value, (key, actual)


def test_not_batch_for_single_episode() -> None:
    assert parse_title("[DKB] Black Clover Season 2 - 01 [1080p]").is_batch is False


@pytest.mark.parametrize("raw", ["", "   ", "[", "]]]", "((((", "- - -", "S", "[A][B][C]", "\x00\x01"])
def test_never_raises(raw: str) -> None:
    parsed = parse_title(raw)
    assert isinstance(parsed.title, str)


def test_roundtrip_dict() -> None:
    from app.services.types import ParsedRelease

    parsed = parse_title("[DKB] Black Clover - 171 [1080p][HEVC x265 10bit][Multi-Subs]")
    assert ParsedRelease.from_dict(parsed.to_dict()) == parsed
    alt = parse_title("[G] A / B - 01")
    assert alt.to_dict()["alt_titles"] == ["B"]
    assert ParsedRelease.from_dict(alt.to_dict()) == alt
    assert ParsedRelease.from_dict({"raw": "x", "title": "x"}).alt_titles == []

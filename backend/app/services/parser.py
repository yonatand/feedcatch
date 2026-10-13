"""Anime release title parser. See `.claude/skills/release-title-parsing/SKILL.md`.

`parse_title(raw)` is pure, deterministic and never raises.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from app.services.types import ParsedRelease

# Boundaries: a token must not be glued to letters/digits on either side ('.', '-', ' ', '[', '_' are fine).
_B = r"(?<![A-Za-z0-9])"
_E = r"(?![A-Za-z0-9])"

_RESOLUTION_RE = re.compile(_B + r"(?i:(2160p|1080p|720p|480p|4K|1920x1080|1280x720))" + _E)
_RESOLUTION_CANON = {"4k": "2160p", "1920x1080": "1080p", "1280x720": "720p"}

# Long/unambiguous names are case-insensitive; short uppercase acronyms are case-sensitive.
_SOURCE_RE = re.compile(
    _B + r"((?i:WEB-DL|WEBRip|BluRay|BDRip|HDTV|Crunchyroll|HIDIVE|B-Global)|WEB|BD|DVD|AMZN|CR|NF|DSNP)" + _E
)
_SOURCE_CANON = {
    "web-dl": "WEB-DL",
    "webrip": "WEBRip",
    "web": "WEB",
    "bluray": "BluRay",
    "bdrip": "BD",
    "bd": "BD",
    "hdtv": "HDTV",
    "dvd": "DVD",
    "amzn": "AMZN",
    "cr": "CR",
    "crunchyroll": "CR",
    "nf": "NF",
    "dsnp": "DSNP",
    "hidive": "HIDIVE",
    "b-global": "B-Global",
}

_CODEC_RE = re.compile(_B + r"(?i:(x265|HEVC|H\.?265|x264|AVC|H\.?264|AV1))" + _E)
_CODEC_CANON = {
    "x265": "HEVC",
    "hevc": "HEVC",
    "h.265": "HEVC",
    "h265": "HEVC",
    "x264": "H264",
    "avc": "H264",
    "h.264": "H264",
    "h264": "H264",
    "av1": "AV1",
}

# Audio may be followed by channel digits (AAC2.0, DDP5.1), so only letters are excluded after it.
_AUDIO_RE = re.compile(_B + r"(?i:(E-AC-3|EAC3|AC3|AAC|FLAC|DDP|Opus|TrueHD|DTS))(?![A-Za-z])")
_AUDIO_CANON = {
    "e-ac-3": "EAC3",
    "eac3": "EAC3",
    "ac3": "AC3",
    "aac": "AAC",
    "flac": "FLAC",
    "ddp": "DDP",
    "opus": "Opus",
    "truehd": "TrueHD",
    "dts": "DTS",
}

_SUBS_RE = re.compile(
    _B
    + r"(?i:(Multiple Subtitles?|Multi-Subs?|MultiSubs?|English Dub|Dual[- ]Audio|Subbed|Dubbed|ENG|JAP|JPN|ESP))"
    + _E
)
_BITDEPTH_RE = re.compile(_B + r"(?i:\d{1,2}-?bits?)" + _E)
_BATCH_WORD_RE = re.compile(r"(?i)" + _B + r"(batch|complete)" + _E)

_LEADING_GROUP_RE = re.compile(r"^\s*(?:\[([^\]]+)\]|\(([^)]+)\))")
_BRACKET_RE = re.compile(r"\[([^\]]*)\]|\(([^)]*)\)")
_CHECKSUM_RE = re.compile(r"^[0-9A-Fa-f]{8}$")
_YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")
_SEASON_LABEL_RE = re.compile(r"(?i)^\s*(?:season\s*\d{1,2}|\d{1,2}(?:st|nd|rd|th)\s+season)\s*$")
_RANGE_TAG_RE = re.compile(r"^\s*\d{1,4}\s*[-~]\s*\d{1,4}\s*$")
_EXT_RE = re.compile(r"(?i)\.(mkv|mp4|avi)$")
_ALT_TITLE_RE = re.compile(r"\s\|\s.*$")
_SCENE_GROUP_RE = re.compile(r"^(.*?)([A-Za-z0-9]+)-([A-Za-z0-9]+)$")
_SCENE_NOT_GROUP = {"web-dl", "b-global", "ac-3", "multi-subs", "dual-audio"}

# Episode / season patterns (applied to the cleaned search text).
_P_SXXEXX = re.compile(r"(?i)" + _B + r"S(\d{1,2})E(\d{1,4})(?:v(\d))?(?:-E?(\d{1,4}))?(?!\d)")
_P_SEASON_EP = re.compile(
    r"(?i)" + _B + r"Season\s*(\d{1,2})(?:\s*[-–]\s*|\s+)(?:E|Ep|Episode)?\.?\s*(\d{1,4})(?:v(\d))?(?![\dA-Za-z])"
)
_P_NTH_SEASON_EP = re.compile(
    r"(?i)"
    + _B
    + r"(\d{1,2})(?:st|nd|rd|th)\s+Season(?:\s*[-–]\s*|\s+)(?:E|Ep|Episode)?\.?\s*(\d{1,4})(?:v(\d))?(?![\dA-Za-z])"
)
_P_SEASON_ONLY = (
    re.compile(r"(?i)" + _B + r"Season\s*(\d{1,2})(?!\d)"),
    re.compile(r"(?i)" + _B + r"(\d{1,2})(?:st|nd|rd|th)\s+Season" + _E),
    re.compile(r"(?i)" + _B + r"S(\d{1,2})" + _E),
)
_P_DASH_EP = re.compile(r" - (\d{1,4})(?:\s?[-~]\s?(\d{1,4}))?(?:v(\d))?(?=\s|$)")
_P_RANGE = re.compile(r"(?:^|\s)(\d{1,4})\s?[-~]\s?(\d{1,4})(?=\s|$)")
_P_E_EP = re.compile(_B + r"(?:E|Ep|EP|Episode|EPISODE)\.?\s?(\d{1,4})(?:v(\d))?(?!\d)")
_P_BARE = re.compile(r"(?<!\S)(\d{2,4})(?:v(\d))?(?!\S)")

_MARK = "\x00"  # placeholder for removed tags; keeps string positions stable


def canonical_resolution(value: str) -> str:
    v = value.strip().lower()
    return _RESOLUTION_CANON.get(v, v)


def canonical_source(value: str) -> str:
    return _SOURCE_CANON.get(value.strip().lower(), value.strip())


def canonical_codec(value: str) -> str:
    return _CODEC_CANON.get(value.strip().lower(), value.strip().upper())


def canonical_audio(value: str) -> str:
    return _AUDIO_CANON.get(value.strip().lower(), value.strip())


def _first(pattern: re.Pattern[str], text: str, canon: Callable[[str], str]) -> str | None:
    m = pattern.search(text)
    return canon(m.group(1)) if m else None


def _has_tag_token(content: str) -> bool:
    return any(p.search(content) for p in (_RESOLUTION_RE, _SOURCE_RE, _CODEC_RE, _AUDIO_RE, _SUBS_RE, _BITDEPTH_RE))


def _blank(match: re.Match[str]) -> str:
    return _MARK * len(match.group(0))


def _clean_title(text: str) -> str:
    t = text.replace(_MARK, " ")
    t = re.sub(r"\s+", " ", t).strip()
    # trim trailing separators (" -", "_", ".", "(", "–") and leading dashes
    t = re.sub(r"[\s\-–_.(\[]+$", "", t)
    t = re.sub(r"^[\s\-–_.]+", "", t)
    return t


def _parse(raw: str) -> ParsedRelease:
    s = raw.strip()
    # Pre-step: drop " | alternate title" suffix and trailing '.'
    s = _ALT_TITLE_RE.sub("", s).rstrip()
    s = s.rstrip(".").rstrip()
    s = _EXT_RE.sub("", s).rstrip()

    group: str | None = None
    m = _LEADING_GROUP_RE.match(s)
    if m:
        candidate = (m.group(1) or m.group(2) or "").strip()
        if candidate and not _YEAR_RE.match(candidate) and not _has_tag_token(candidate):
            group = candidate
            s = s[m.end() :]
            s = re.sub(r"^\s*-\s+", "", s)
    if group is None and not re.search(r"\s", s):
        sm = _SCENE_GROUP_RE.match(s)
        if sm and sm.group(1):
            pair = f"{sm.group(2)}-{sm.group(3)}".lower()
            if pair not in _SCENE_NOT_GROUP and not sm.group(3).isdigit():
                group = sm.group(3)
                s = s[: -(len(sm.group(3)) + 1)]

    # Tag scanning over the whole remainder (brackets + plain text), first occurrence wins.
    resolution = _first(_RESOLUTION_RE, s, canonical_resolution)
    source = _first(_SOURCE_RE, s, canonical_source)
    codec = _first(_CODEC_RE, s, canonical_codec)
    audio = _first(_AUDIO_RE, s, canonical_audio)
    subs: list[str] = []
    for sub in _SUBS_RE.finditer(s):
        if sub.group(1) not in subs:
            subs.append(sub.group(1))
    is_batch = bool(_BATCH_WORD_RE.search(s))

    # Build the search text: remove bracket tags (keeping positions via _MARK).
    def _bracket(match: re.Match[str]) -> str:
        nonlocal is_batch
        whole = match.group(0)
        content = match.group(1) if match.group(1) is not None else match.group(2)
        is_square = whole.startswith("[")
        if _RANGE_TAG_RE.match(content):
            is_batch = True
        if not is_square:
            if _YEAR_RE.match(content.strip()):
                return whole  # "(2024)" stays part of the title
            if _SEASON_LABEL_RE.match(content):
                return " " + content + " "  # "(Season 2)" -> " Season 2 "
            if not (_CHECKSUM_RE.match(content.strip()) or _has_tag_token(content) or _RANGE_TAG_RE.match(content)):
                return whole
        return _MARK * len(whole)

    text = _BRACKET_RE.sub(_bracket, s)
    for pattern in (_RESOLUTION_RE, _SOURCE_RE, _CODEC_RE, _AUDIO_RE, _SUBS_RE, _BITDEPTH_RE):
        text = pattern.sub(_blank, text)
    # '_' and '.' between words become spaces; keep '.' between digits.
    text = text.replace("_", " ")
    text = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", text)
    search = text.replace(_MARK, " ")

    season: int | None = None
    episode: int | None = None
    episode_end: int | None = None
    version: int | None = None
    cut: int | None = None

    def _ver(v: str | None) -> int | None:
        return int(v) if v else None

    if mm := _P_SXXEXX.search(search):
        season, episode, version = int(mm.group(1)), int(mm.group(2)), _ver(mm.group(3))
        episode_end = int(mm.group(4)) if mm.group(4) else None
        cut = mm.start()
    elif mm := (_P_SEASON_EP.search(search) or _P_NTH_SEASON_EP.search(search)):
        season, episode, version = int(mm.group(1)), int(mm.group(2)), _ver(mm.group(3))
        cut = mm.start()
    else:
        for sp in _P_SEASON_ONLY:
            if mm := sp.search(search):
                season = int(mm.group(1))
                cut = mm.start()
                # Lenient: an explicit episode after the season marker still counts.
                rest = search[mm.end() :]
                if em := (_P_DASH_EP.search(" " + rest) or _P_E_EP.search(rest)):
                    episode = int(em.group(1))
                break
        if season is None:
            dash = list(_P_DASH_EP.finditer(search))
            if dash:
                mm = dash[-1]
                episode, version = int(mm.group(1)), _ver(mm.group(3))
                if mm.group(2):
                    episode_end = int(mm.group(2))
                    is_batch = True
                cut = mm.start()
            elif mm := _P_RANGE.search(search):
                episode, episode_end = int(mm.group(1)), int(mm.group(2))
                is_batch = True
                cut = mm.start()
            elif mm := _P_E_EP.search(search):
                episode, version = int(mm.group(1)), _ver(mm.group(2))
                cut = mm.start()
            else:
                bare = list(_P_BARE.finditer(search))
                if len(bare) == 1:
                    mm = bare[0]
                    episode, version = int(mm.group(1)), _ver(mm.group(2))
                    cut = mm.start()

    if cut is not None:
        title = _clean_title(text[:cut])
    else:
        # Title = text before the first removed tag (ignoring tags at the very start).
        stripped = text.lstrip(_MARK + " ")
        offset = len(text) - len(stripped)
        idx = stripped.find(_MARK)
        title = _clean_title(text[offset : offset + idx] if idx >= 0 else stripped)
    if not title:
        title = _clean_title(text) or raw.strip()

    return ParsedRelease(
        raw=raw,
        title=title,
        group=group,
        season=season,
        episode=episode,
        episode_end=episode_end,
        absolute=episode is not None and season is None,
        version=version,
        resolution=resolution,
        source=source,
        codec=codec,
        audio=audio,
        subs=subs,
        is_batch=is_batch,
    )


def parse_title(raw: str) -> ParsedRelease:
    """Parse an anime release title. Never raises; falls back to `title=raw.strip()`."""
    try:
        return _parse(raw if isinstance(raw, str) else str(raw))
    except Exception:  # defensive: parser must never break the pipeline
        text = raw.strip() if isinstance(raw, str) else str(raw)
        return ParsedRelease(raw=text, title=text)

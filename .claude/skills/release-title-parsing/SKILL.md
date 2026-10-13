---
name: release-title-parsing
description: How app/services/parser.py must parse anime release titles (group, title, season, episode, absolute flag, resolution, codec...) and the fixture table tests must cover. Read before touching parser.py or matcher.py.
---

# Release title parsing

`parse_title(raw: str) -> ParsedRelease` (dataclass; fields per api-contract `ParsedRelease`). Pure function, no I/O, never raises on weird input
(returns best effort with `title=raw` stripped). Deterministic; tests assert exact fields.

## Algorithm (ordered)
1. `s = raw.strip()`. Group: leading `[Group]` or `(Group)` at start -> `group`; remove. Also accept trailing `-Group` scene style (`Title.S01E01.1080p.WEB.H264-GROUP`) only when no leading bracket group.
2. Strip trailing checksum `[A1B2C3D4]`/`(A1B2C3D4)` (8 hex) and file extension `.mkv|.mp4|.avi`.
3. Extract tags from remaining bracket/paren groups (`[1080p]`, `[HEVC x265]`, `(WEB-DL 1080p)`, `[Multiple Subtitle]`, `[ENG]`...) into `tags` list; also scan the plain text (dot/space separated) for the same tokens.
   - resolution: `2160p|1080p|720p|480p|4K(->2160p)|1920x1080(->1080p)|1280x720(->720p)`; lowercase canonical like `1080p`.
   - source: `WEB-DL|WEBRip|WEB|BluRay|BDRip|BD|HDTV|DVD|AMZN|CR|Crunchyroll(->CR)|NF|DSNP|HIDIVE|B-Global` (canonical uppercase; `WEB-DL`, `WEBRip`, `WEB`, `BluRay`, `BD`, `HDTV`, `DVD`, `AMZN`, `CR`, `NF`, `DSNP`, `HIDIVE`).
   - codec: `x265|HEVC|H.265|H265 -> HEVC`; `x264|AVC|H.264|H264 -> H264`; `AV1`.
   - audio: `AAC|FLAC|AC3|EAC3|E-AC-3|DDP|Opus|TrueHD|DTS` (first found).
   - subs: tokens like `Multiple Subtitle`, `Multi-Subs`, `MultiSub`, `ENG`, `English Dub`, `Dual Audio`, `Dual-Audio`, `JAP`, `JPN`, `ESP`, `Subbed`, `Dubbed` -> list of raw tokens as found (deduped).
   - `is_batch`: title contains `batch`, `complete`, or an episode range like `01-12`/`01~12`/`(01-24)`.
4. Episode/season from the text part (bracket tags removed, `_` and `.` between words treated as spaces, but keep `.` inside numbers like `v2`):
   Try in order, first match wins; set `absolute = season is None` when an episode was found:
   a. `S(\d{1,2})E(\d{1,4})(?:-E?(\d{1,4}))?` -> season, episode, episode_end.
   b. `Season (\d{1,2})\s*[-–]?\s*(?:E|Ep|Episode)?\s*(\d{1,4})(?:v(\d))?` and `(\d{1,2})(?:nd|rd|th) Season\s*[-–]?\s*(\d{1,4})` -> season + episode.
   c. `Season (\d{1,2})` / `(\d{1,2})(?:nd|rd|th) Season` / `S(\d{1,2})` (standalone token) alone -> season only (no episode).
   d. ` - (\d{1,4})(?:v(\d))?(?=\s|$|\[|\()` (dash-separated number) -> episode, absolute=True.
   e. ` E(?:p|pisode)?\.?\s?(\d{1,4})` -> episode, absolute=True.
   f. `(?:^|\s)(\d{2,4})(?:v\d)?(?:\s|$)` as a last resort ONLY if exactly one such standalone number exists and it is not followed/preceded by `p` or `x` (resolution) -> episode, absolute=True.
   Ranges `- 01-12`, `- 01~12` -> episode, episode_end, is_batch=True.
   Version: `v(\d)` immediately after the episode number.
5. `title`: the text before the matched season/episode pattern (or before the first bracket tag if no episode), with trailing ` -`, `_`, `.` and spaces trimmed, internal `.`/`_` turned into spaces, whitespace collapsed. Keep original case.
6. Do not infer a season from an absolute number. Do not parse years as episodes (4-digit 19xx/20xx in parentheses are ignored).

## Normalization for matching (matcher.py)
`norm(s) = re.sub(r'[^a-z0-9]+', ' ', unicodedata.normalize('NFKC', s).lower()).strip()`. Series matches when `norm(parsed.title) == norm(name_or_alias)`
OR `norm(parsed.title)` starts with `norm(alias) + ' '`? No: require equality with any of name/aliases after normalization, OR equality after also stripping a trailing
season marker already removed by the parser. Keep strict equality to avoid "Black Clover" matching "Black Clover Mobile". Users add aliases for variants.

## Fixture table (tests must assert these)
| raw | group | title | season | episode | episode_end | absolute | resolution | source | codec | extra |
|---|---|---|---|---|---|---|---|---|---|---|
| `[DKB] Black Clover Season 2 - 01 [1080p]` | DKB | Black Clover | 2 | 1 | null | false | 1080p | null | null | |
| `[DKB] Black Clover - 171 [1080p][HEVC x265 10bit][Multi-Subs]` | DKB | Black Clover | null | 171 | null | true | 1080p | null | HEVC | subs contains `Multi-Subs` |
| `[SubsPlease] Black Clover - 171 (1080p) [A1B2C3D4].mkv` | SubsPlease | Black Clover | null | 171 | null | true | 1080p | null | null | |
| `[Erai-raws] Black Clover - 171v2 [1080p][Multiple Subtitle][ENG][POR-BR]` | Erai-raws | Black Clover | null | 171 | null | true | 1080p | null | null | version=2 |
| `Black.Clover.S02E01.1080p.WEB.H264-GROUP` | GROUP | Black Clover | 2 | 1 | null | false | 1080p | WEB | H264 | |
| `[Judas] Black Clover (Season 2) - 05 [1080p][HEVC x265 10bit][Dual-Audio][Multi-Subs]` | Judas | Black Clover | 2 | 5 | null | false | 1080p | null | HEVC | subs contains `Dual-Audio` |
| `[DKB] Black Clover S02E13 [1080p][HEVC][x265 10bit]` | DKB | Black Clover | 2 | 13 | null | false | 1080p | null | HEVC | |
| `[Group] Spy x Family Season 2 - 03 [720p]` | Group | Spy x Family | 2 | 3 | null | false | 720p | null | null | |
| `[Group] Spy x Family - 28 [1080p]` | Group | Spy x Family | null | 28 | null | true | 1080p | null | null | |
| `[Group] Dungeon Meshi - 01-24 [BD 1080p] [Batch]` | Group | Dungeon Meshi | null | 1 | 24 | true | 1080p | BD | null | is_batch=true |
| `[Group] Re:Zero kara Hajimeru Isekai Seikatsu 3rd Season - 04 [1080p]` | Group | Re:Zero kara Hajimeru Isekai Seikatsu | 3 | 4 | null | false | 1080p | null | null | |
| `[Group] Frieren - Beyond Journey's End - 12 [1080p]` | Group | Frieren - Beyond Journey's End | null | 12 | null | true | 1080p | null | null | |
| `[Group] One Piece - 1100 [1080p][AMZN WEB-DL][AAC]` | Group | One Piece | null | 1100 | null | true | 1080p | AMZN (or WEB-DL; assert source in {AMZN, WEB-DL}) | null | audio=AAC |
| `[Group] Some Show (2024) - 02 [1080p]` | Group | Some Show (2024) | null | 2 | null | true | 1080p | null | null | year not an episode |
| `Some Show E05 1080p` | null | Some Show | null | 5 | null | true | 1080p | null | null | |
| `random text without numbers` | null | random text without numbers | null | null | null | false | null | null | null | |

## Additional real-world cases (from the live AnimeTosho feed, 2026-10-13; also required in tests)
Pre-step: strip a trailing ` | <anything>` segment (AnimeTosho appends alternate titles) and a trailing `.` before parsing.
Multiple leading bracket groups are possible: `[Shridhuu][1080p] Title - S01E15` -> group=Shridhuu, the second bracket is a tag.
A leading ` - ` right after the group (`[Doomdos] - Title - 50`) is ignored.

| raw | group | title | season | episode | absolute | resolution | source | codec | extra |
|---|---|---|---|---|---|---|---|---|---|
| `[DKB] Psyren - S01E02 [1080p][HEVC x265 10bit][Multi-Subs][weekly]` | DKB | Psyren | 1 | 2 | false | 1080p | null | HEVC | |
| `[FrixySubs] Black Clover - S02E02 [1080p CR WEB-DL H.264 AAC] [Napisy PL].mkv` | FrixySubs | Black Clover | 2 | 2 | false | 1080p | CR or WEB-DL (assert in set) | H264 | audio=AAC |
| `[Buzz-Subs] Black Clover (2017) S02E01 (1080p AV1 Opus) [Eng-Subs]` | Buzz-Subs | Black Clover (2017) | 2 | 1 | false | 1080p | null | AV1 | audio=Opus |
| `[SubsPlus+] Nia Liston - The Merciless Maiden - S01E02 (ADN WEB-DL 1080p AVC AAC) \| Kyouran Reijou Nia Liston` | SubsPlus+ | Nia Liston - The Merciless Maiden | 1 | 2 | false | 1080p | WEB-DL | H264 | the ` \| ...` suffix is dropped |
| `[SubsPlease] Kyouran Reijou Nia Liston - 02 (1080p) [69FFB377].mkv` | SubsPlease | Kyouran Reijou Nia Liston | null | 2 | true | 1080p | null | null | |
| `[Shridhuu][1080p] A Good Day to Ascend / 择日飞升 / Zeri Feisheng - S01E15` | Shridhuu | A Good Day to Ascend / 择日飞升 / Zeri Feisheng | 1 | 15 | false | 1080p | null | null | |
| `[Doomdos] - Ascendants of the Nine Suns - 50 [1080p IQ WEB-DL]` | Doomdos | Ascendants of the Nine Suns | null | 50 | true | 1080p | WEB-DL | null | |
| `Arabian Nights - Sindbad no Bouken TV 01-52 [ARR].` | null | Arabian Nights - Sindbad no Bouken TV | null | 1 | true | null | null | null | episode_end=52, is_batch=true |
| `[Z-A] Re Zero kara Hajimeru Isekai Seikatsu S04 (WEB 1080p AAC)` | Z-A | Re Zero kara Hajimeru Isekai Seikatsu | 4 | null | false | 1080p | WEB | null | season-only (batch-ish, no episode) |
| `Nia Liston The Merciless Maiden S01E02 A Job in the Royal Capital 1080p ADN WEB-DL AAC2.0 H.264-VARYG (Kyouran Reijou Nia Liston, Multi-Subs)` | VARYG (trailing scene group) or null (either accepted) | Nia Liston The Merciless Maiden | 1 | 2 | false | 1080p | WEB-DL | H264 | |

## Implemented leniencies (parser.py, 2026-10-13)
- After a season-only marker (`S2`, `Season 2`), a following ` - 05` or `E05` is still taken as the episode.
- When several ` - N` numbers appear, the last one wins.
- `(Season 2)` in parentheses is unwrapped; `(2024)`-style years stay in the title.
- Rule values for codec/source/resolution are canonicalised like the parser output (`x264` == `H264`).

"""Plain dataclasses shared by parser, matcher, poller and API layers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ParsedRelease:
    """Result of `parser.parse_title`. Field set mirrors api-contract `ParsedRelease`."""

    raw: str
    title: str
    group: str | None = None
    season: int | None = None
    episode: int | None = None
    episode_end: int | None = None
    absolute: bool = False
    version: int | None = None
    resolution: str | None = None
    source: str | None = None
    codec: str | None = None
    audio: str | None = None
    subs: list[str] = field(default_factory=list)
    is_batch: bool = False
    alt_titles: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ParsedRelease:
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        known.setdefault("raw", "")
        known.setdefault("title", known.get("raw", ""))
        known["subs"] = list(known.get("subs") or [])
        known["alt_titles"] = list(known.get("alt_titles") or [])
        return cls(**known)


@dataclass
class Condition:
    """One check in a rule evaluation (shown in the Match Inspector)."""

    check: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"check": self.check, "passed": self.passed, "detail": self.detail}


@dataclass
class Evaluation:
    """Result of `matcher.evaluate` for one (entry, rule) pair."""

    matched: bool
    season_id: int | None
    season_number: int | None
    episode_number: int | None
    conditions: list[Condition] = field(default_factory=list)

    def conditions_as_dicts(self) -> list[dict[str, Any]]:
        return [c.to_dict() for c in self.conditions]

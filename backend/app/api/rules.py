"""/api/rules"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import AUTH, Page, Session, count, get_db, get_or_404, page_params
from app.models import FeedEntry, Rule, Season, Series
from app.schemas import (
    ItemsOut,
    Paginated,
    RuleIn,
    RuleOut,
    SimulateIn,
    SimulationResultOut,
    TestRecentResultOut,
    ValidateRegexIn,
    ValidateRegexOut,
)
from app.services import activity, poller, settings_store

router = APIRouter(prefix="/api/rules", tags=["rules"], dependencies=AUTH)

_RULE_FIELDS = (
    "series_id",
    "season_id",
    "name",
    "enabled",
    "priority",
    "release_group",
    "require_group_prefix",
    "include_keywords",
    "exclude_keywords",
    "resolutions",
    "sources",
    "codecs",
    "language_keywords",
    "min_size_mb",
    "max_size_mb",
    "regex",
)


def _check_refs(db: Session, body: RuleIn) -> None:
    if db.get(Series, body.series_id) is None:
        raise HTTPException(status_code=400, detail=f"series {body.series_id} not found")
    if body.season_id is not None:
        season = db.get(Season, body.season_id)
        if season is None or season.series_id != body.series_id:
            raise HTTPException(status_code=400, detail=f"season {body.season_id} does not belong to this series")


def _apply(rule: Rule, body: RuleIn) -> None:
    for f in _RULE_FIELDS:
        setattr(rule, f, getattr(body, f))


@router.get("", response_model=Paginated[RuleOut])
def list_rules(
    series_id: int | None = Query(None), page: Page = Depends(page_params), db: Session = Depends(get_db)
) -> Paginated[RuleOut]:
    stmt = select(Rule).options(selectinload(Rule.series), selectinload(Rule.season))
    if series_id is not None:
        stmt = stmt.where(Rule.series_id == series_id)
    stmt = stmt.order_by(Rule.series_id, Rule.priority.desc(), Rule.id)
    items = [RuleOut.from_model(r) for r in db.scalars(stmt.limit(page.limit).offset(page.offset))]
    return Paginated[RuleOut](items=items, total=count(db, stmt))


@router.post("", response_model=RuleOut, status_code=201)
def create_rule(body: RuleIn, db: Session = Depends(get_db)) -> RuleOut:
    _check_refs(db, body)
    rule = Rule()
    _apply(rule, body)
    db.add(rule)
    db.flush()
    activity.log_event(db, "info", "rule_created", f"Rule '{rule.name}' added", details={"rule_id": rule.id})
    db.commit()
    db.refresh(rule)
    return RuleOut.from_model(rule)


@router.post("/simulate", response_model=ItemsOut[SimulationResultOut])
def simulate(body: SimulateIn, db: Session = Depends(get_db)) -> ItemsOut[SimulationResultOut]:
    media_base = settings_store.get_media_base_path(db)
    if body.series is not None:
        sim_series, sim_seasons = poller.build_sim_series(body.series)
        if body.rule.season_id is not None and not (0 <= body.rule.season_id < len(sim_seasons)):
            raise HTTPException(status_code=400, detail="rule.season_id must be an index into series.seasons")
        items = poller.simulate_rule(body.rule, body.titles, sim_series, sim_seasons, media_base)
    else:
        series = db.get(Series, body.rule.series_id)
        if series is None:
            raise HTTPException(status_code=400, detail=f"series {body.rule.series_id} not found")
        _check_refs(db, body.rule)
        items = poller.simulate_rule(body.rule, body.titles, series, series.seasons, media_base)
    return ItemsOut[SimulationResultOut](items=items)


@router.post("/validate-regex", response_model=ValidateRegexOut)
def validate_regex(body: ValidateRegexIn) -> ValidateRegexOut:
    try:
        re.compile(body.pattern)
    except re.error as exc:
        return ValidateRegexOut(valid=False, error=str(exc))
    return ValidateRegexOut(valid=True, error=None)


@router.get("/{rule_id}", response_model=RuleOut)
def get_rule(rule_id: int, db: Session = Depends(get_db)) -> RuleOut:
    return RuleOut.from_model(get_or_404(db, Rule, rule_id, "rule"))


@router.put("/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: int, body: RuleIn, db: Session = Depends(get_db)) -> RuleOut:
    rule = get_or_404(db, Rule, rule_id, "rule")
    _check_refs(db, body)
    _apply(rule, body)
    activity.log_event(db, "info", "rule_updated", f"Rule '{rule.name}' updated", details={"rule_id": rule.id})
    db.commit()
    db.refresh(rule)
    return RuleOut.from_model(rule)


@router.delete("/{rule_id}", status_code=204)
def delete_rule(rule_id: int, db: Session = Depends(get_db)) -> Response:
    rule = get_or_404(db, Rule, rule_id, "rule")
    name = rule.name
    db.delete(rule)
    activity.log_event(db, "info", "rule_deleted", f"Rule '{name}' deleted", details={"rule_id": rule_id})
    db.commit()
    return Response(status_code=204)


@router.post("/{rule_id}/test-recent", response_model=ItemsOut[TestRecentResultOut])
def test_recent(
    rule_id: int, limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)
) -> ItemsOut[TestRecentResultOut]:
    rule = get_or_404(db, Rule, rule_id, "rule")
    entries = list(
        db.scalars(select(FeedEntry).order_by(FeedEntry.first_seen_at.desc(), FeedEntry.id.desc()).limit(limit))
    )
    results = poller.simulate_rule(
        rule,
        [e.title for e in entries],
        rule.series,
        rule.series.seasons,
        settings_store.get_media_base_path(db),
        sizes=[e.size_bytes for e in entries],
    )
    items = [TestRecentResultOut(**r.model_dump(), entry_id=e.id) for r, e in zip(results, entries, strict=True)]
    return ItemsOut[TestRecentResultOut](items=items)

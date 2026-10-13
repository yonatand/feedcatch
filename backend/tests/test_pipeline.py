"""Dispatcher + poller integration against a fake feed and fake qBittorrent (respx)."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
import respx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import ActivityLog, Download, Evaluation, FeedEntry, FeedSource, Rule, Season, Series, utcnow
from app.services import crypto, dispatcher, poller, settings_store
from tests.helpers import (
    EXPECTED_BC_S2,
    FAKE_QBIT_PASS,
    FAKE_QBIT_USER,
    FEED_URL,
    QBIT_URL,
    FakeQbit,
    feed_with,
    make_item,
    mock_feed,
    sample_feed,
)

EP1 = "[DKB] Black Clover Season 2 - 01 [1080p]"


def seed(
    db: Session,
    settings: Settings,
    *,
    category_override: str | None = None,
    absolute: tuple[int, int] | None = None,
    qbit: bool = True,
) -> tuple[FeedSource, Series, Season, Rule]:
    feed = FeedSource(name="Test feed", url=FEED_URL, backfill_mode="skip")
    series = Series(name="Black Clover", aliases=[], monitored=True, category_override=category_override)
    season = Season(series=series, season_number=2, monitored=True)
    if absolute:
        season.absolute_min, season.absolute_max = absolute
    rule = Rule(
        series=series,
        season=season,
        name="DKB 1080p",
        enabled=True,
        priority=10,
        release_group="DKB",
        require_group_prefix=True,
        resolutions=["1080p"],
    )
    db.add_all([feed, series, season, rule])
    if qbit:
        settings_store.set(db, settings_store.QBIT_URL, QBIT_URL)
        settings_store.set(db, settings_store.QBIT_USERNAME, FAKE_QBIT_USER)
        settings_store.set(db, settings_store.QBIT_PASSWORD_ENC, crypto.encrypt(FAKE_QBIT_PASS, settings))
        settings_store.set(db, settings_store.QBIT_CATEGORY, "anime")
    db.commit()
    return feed, series, season, rule


def test_first_poll_marks_historical_and_sends_nothing(
    db: Session, settings: Settings, respx_mock: respx.MockRouter
) -> None:
    feed, *_ = seed(db, settings)
    fake = FakeQbit(respx_mock)
    mock_feed(respx_mock, sample_feed())
    r = poller.poll_feed(db, feed.id, settings)
    assert r.fetched == 9 and r.new_entries == 9 and r.historical == 9
    assert r.accepted == r.submitted == 0
    assert not fake.login_route.called and not fake.add_route.called
    entries = list(db.scalars(select(FeedEntry)))
    assert len(entries) == 9
    assert all(e.is_historical and e.outcome == "historical" for e in entries)
    # evaluations are still stored for preview
    assert db.scalar(select(func.count()).select_from(Evaluation)) == 9
    db.refresh(feed)
    assert feed.initial_poll_done and feed.last_status == "ok" and feed.consecutive_failures == 0
    assert db.scalar(select(func.count()).select_from(Download)) == 0
    # polling the same content again creates nothing new
    r2 = poller.poll_feed(db, feed.id, settings)
    assert r2.new_entries == 0 and not fake.add_route.called


def test_second_poll_dispatches_new_matching_entry(
    db: Session, settings: Settings, respx_mock: respx.MockRouter
) -> None:
    feed, _series, season, rule = seed(db, settings)
    fake = FakeQbit(respx_mock)
    body = {"data": sample_feed()}
    mock_feed(respx_mock, lambda: body["data"])
    poller.poll_feed(db, feed.id, settings)
    assert not fake.add_route.called

    body["data"] = feed_with(make_item(EP1, 1001))
    r = poller.poll_feed(db, feed.id, settings)
    assert r.new_entries == 1 and r.accepted == 1 and r.submitted == 1 and r.historical == 0, r
    assert fake.add_route.call_count == 1
    form = fake.adds[0]
    assert form["savepath"] == EXPECTED_BC_S2
    assert form["autoTMM"] == "false"
    assert form["urls"].startswith("magnet:?xt=urn:btih:")
    assert form["category"] == "anime"
    assert "/nzb/" not in form["urls"]

    d = db.scalars(select(Download)).one()
    assert d.status == "submitted", d.last_error
    assert d.save_path == EXPECTED_BC_S2
    assert d.season_id == season.id and d.episode_number == 1 and d.rule_id == rule.id
    assert d.qbit_hash == d.infohash and d.qbit_save_path == EXPECTED_BC_S2 + "/"
    entry = db.scalar(select(FeedEntry).where(FeedEntry.title == EP1))
    assert entry is not None and entry.outcome == "accepted" and not entry.is_historical
    types = set(db.scalars(select(ActivityLog.event_type)))
    assert {"feed_poll", "entry_accepted", "download_submitted"} <= types


def test_duplicate_episode_is_not_sent_twice(db: Session, settings: Settings, respx_mock: respx.MockRouter) -> None:
    feed, *_ = seed(db, settings)
    fake = FakeQbit(respx_mock)
    body = {"data": sample_feed()}
    mock_feed(respx_mock, lambda: body["data"])
    poller.poll_feed(db, feed.id, settings)
    body["data"] = feed_with(make_item(EP1, 1001))
    poller.poll_feed(db, feed.id, settings)
    assert fake.add_route.call_count == 1

    body["data"] = feed_with(make_item("[DKB] Black Clover Season 2 - 01v2 [1080p]", 1002), make_item(EP1, 1001))
    r = poller.poll_feed(db, feed.id, settings)
    assert r.new_entries == 1 and r.duplicate == 1 and r.accepted == 0
    assert fake.add_route.call_count == 1
    dup = db.scalar(select(FeedEntry).where(FeedEntry.guid.like("%/1002")))
    assert dup is not None and dup.outcome == "duplicate" and "duplicate of download" in (dup.outcome_summary or "")


def test_category_override_honored(db: Session, settings: Settings, respx_mock: respx.MockRouter) -> None:
    feed, *_ = seed(db, settings, category_override="black-clover")
    fake = FakeQbit(respx_mock)
    body = {"data": sample_feed()}
    mock_feed(respx_mock, lambda: body["data"])
    poller.poll_feed(db, feed.id, settings)
    body["data"] = feed_with(make_item(EP1, 1001))
    poller.poll_feed(db, feed.id, settings)
    assert fake.adds[0]["category"] == "black-clover"
    assert db.scalars(select(Download)).one().category == "black-clover"


def test_path_mismatch_detected(db: Session, settings: Settings, respx_mock: respx.MockRouter) -> None:
    feed, *_ = seed(db, settings)
    fake = FakeQbit(respx_mock, report_save_path="/downloads/incomplete")
    body = {"data": sample_feed()}
    mock_feed(respx_mock, lambda: body["data"])
    poller.poll_feed(db, feed.id, settings)
    body["data"] = feed_with(make_item(EP1, 1001))
    r = poller.poll_feed(db, feed.id, settings)
    d = db.scalars(select(Download)).one()
    assert d.status == "path_mismatch"
    assert d.qbit_save_path == "/downloads/incomplete"
    assert d.last_error and "/downloads/incomplete" in d.last_error
    assert r.submitted == 1  # still counts as sent
    assert fake.add_route.call_count == 1


def test_transient_failure_keeps_pending_with_backoff(
    db: Session, settings: Settings, respx_mock: respx.MockRouter
) -> None:
    feed, *_ = seed(db, settings)
    respx_mock.post(f"{QBIT_URL}/api/v2/auth/login").mock(side_effect=httpx.ConnectError("refused"))
    body = {"data": sample_feed()}
    mock_feed(respx_mock, lambda: body["data"])
    poller.poll_feed(db, feed.id, settings)
    body["data"] = feed_with(make_item(EP1, 1001))
    before = utcnow()
    r = poller.poll_feed(db, feed.id, settings)
    assert r.accepted == 1 and r.submitted == 0 and r.errors
    d = db.scalars(select(Download)).one()
    assert d.status == "pending" and d.attempts == 1
    assert d.next_retry_at is not None
    assert before + timedelta(minutes=2) - timedelta(seconds=5) <= d.next_retry_at <= utcnow() + timedelta(minutes=2)

    # not due yet -> retry_due does nothing
    assert dispatcher.retry_due(db, settings) == 0
    # after 8 attempts in total it gives up
    for _ in range(7):
        d.next_retry_at = utcnow() - timedelta(seconds=1)
        db.commit()
        dispatcher.retry_due(db, settings)
    db.refresh(d)
    assert d.attempts == 8 and d.status == "failed" and d.next_retry_at is None


def test_uncertain_add_then_present_becomes_exists(
    db: Session, settings: Settings, respx_mock: respx.MockRouter
) -> None:
    feed, *_ = seed(db, settings)
    fake = FakeQbit(respx_mock)
    fake.add_error = httpx.ReadTimeout("response lost")  # qBittorrent got it, we did not hear back
    body = {"data": sample_feed()}
    mock_feed(respx_mock, lambda: body["data"])
    poller.poll_feed(db, feed.id, settings)
    body["data"] = feed_with(make_item(EP1, 1001))
    poller.poll_feed(db, feed.id, settings)
    d = db.scalars(select(Download)).one()
    assert d.status == "pending" and d.attempts == 1
    assert fake.add_route.call_count == 1

    fake.add_error = None
    d.next_retry_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert dispatcher.retry_due(db, settings) == 1
    db.refresh(d)
    assert d.status == "exists"
    assert fake.add_route.call_count == 1  # no blind re-add


def test_add_fails_marks_failed(db: Session, settings: Settings, respx_mock: respx.MockRouter) -> None:
    feed, *_ = seed(db, settings)
    fake = FakeQbit(respx_mock, add_text="Fails.")
    body = {"data": sample_feed()}
    mock_feed(respx_mock, lambda: body["data"])
    poller.poll_feed(db, feed.id, settings)
    body["data"] = feed_with(make_item(EP1, 1001))
    poller.poll_feed(db, feed.id, settings)
    d = db.scalars(select(Download)).one()
    assert d.status == "failed" and "Fails." in (d.last_error or "")
    assert fake.add_route.call_count == 1


def test_nzb_only_match_is_rejected(db: Session, settings: Settings, respx_mock: respx.MockRouter) -> None:
    feed, *_ = seed(db, settings)
    fake = FakeQbit(respx_mock)
    body = {"data": sample_feed()}
    mock_feed(respx_mock, lambda: body["data"])
    poller.poll_feed(db, feed.id, settings)
    body["data"] = feed_with(make_item(EP1, 1001, magnet=False))
    r = poller.poll_feed(db, feed.id, settings)
    assert r.rejected == 1 and not fake.add_route.called
    e = db.scalar(select(FeedEntry).where(FeedEntry.title == EP1))
    assert e is not None and e.outcome == "rejected"
    assert "no torrent/magnet link (NZB-only)" in (e.outcome_summary or "")
    assert db.scalar(select(func.count()).select_from(Download)) == 0


@pytest.mark.parametrize(("absolute", "expected_ep"), [(None, None), ((52, 200), 120)])
def test_absolute_numbering(
    db: Session,
    settings: Settings,
    respx_mock: respx.MockRouter,
    absolute: tuple[int, int] | None,
    expected_ep: int | None,
) -> None:
    feed, *_ = seed(db, settings, absolute=absolute)
    fake = FakeQbit(respx_mock)
    body = {"data": sample_feed()}
    mock_feed(respx_mock, lambda: body["data"])
    poller.poll_feed(db, feed.id, settings)
    title = "[DKB] Black Clover - 171 [1080p]"
    body["data"] = feed_with(make_item(title, 2001))
    poller.poll_feed(db, feed.id, settings)
    entry = db.scalar(select(FeedEntry).where(FeedEntry.title == title))
    assert entry is not None
    ev = db.scalars(select(Evaluation).where(Evaluation.entry_id == entry.id)).one()
    if expected_ep is None:
        assert entry.outcome == "no_match"
        season_cond = next(c for c in ev.conditions if c["check"] == "season")
        assert season_cond["passed"] is False and "ambiguous" in season_cond["detail"]
        assert not fake.add_route.called
    else:
        assert entry.outcome == "accepted"
        d = db.scalars(select(Download)).one()
        assert d.episode_number == expected_ep and d.status == "submitted"
        assert fake.adds[0]["savepath"] == EXPECTED_BC_S2


def test_unmonitored_series_not_dispatched(db: Session, settings: Settings, respx_mock: respx.MockRouter) -> None:
    feed, series, *_ = seed(db, settings)
    series.monitored = False
    db.commit()
    fake = FakeQbit(respx_mock)
    body = {"data": sample_feed()}
    mock_feed(respx_mock, lambda: body["data"])
    poller.poll_feed(db, feed.id, settings)
    body["data"] = feed_with(make_item(EP1, 1001))
    r = poller.poll_feed(db, feed.id, settings)
    assert r.no_match == 1 and not fake.add_route.called
    entry = db.scalar(select(FeedEntry).where(FeedEntry.title == EP1))
    assert entry is not None and entry.outcome_summary == "no active rules"
    # the inspector still evaluates every enabled rule (hypothetical match)
    evals = poller.evaluate_entry(db, entry, settings)
    assert len(evals) == 1 and evals[0].matched


def test_backfill_process_dispatches_on_first_poll(
    db: Session, settings: Settings, respx_mock: respx.MockRouter
) -> None:
    feed, *_ = seed(db, settings)
    feed.backfill_mode = "process"
    db.commit()
    fake = FakeQbit(respx_mock)
    mock_feed(respx_mock, feed_with(make_item(EP1, 1001)))
    r = poller.poll_feed(db, feed.id, settings)
    assert r.historical == 0 and r.accepted == 1 and fake.add_route.call_count == 1


def test_feed_error_updates_status(db: Session, settings: Settings, respx_mock: respx.MockRouter) -> None:
    feed, *_ = seed(db, settings)
    respx_mock.get(FEED_URL).mock(return_value=httpx.Response(503))
    r = poller.poll_feed(db, feed.id, settings)
    assert r.errors and "503" in r.errors[0]
    db.refresh(feed)
    assert feed.last_status == "error" and feed.consecutive_failures == 1 and not feed.initial_poll_done


def test_not_modified_poll(db: Session, settings: Settings, respx_mock: respx.MockRouter) -> None:
    feed, *_ = seed(db, settings)
    feed.last_modified = "Tue, 13 Oct 2026 13:16:24 GMT"
    db.commit()
    route = respx_mock.get(FEED_URL).mock(return_value=httpx.Response(304))
    r = poller.poll_feed(db, feed.id, settings)
    assert r.fetched == 0 and not r.errors
    assert route.calls.last.request.headers["if-modified-since"] == "Tue, 13 Oct 2026 13:16:24 GMT"
    db.refresh(feed)
    assert feed.last_status == "ok"


def test_poll_lock_is_non_blocking(db: Session, settings: Settings) -> None:
    feed, *_ = seed(db, settings, qbit=False)
    lock = poller._lock_for(feed.id)
    lock.acquire()
    try:
        with pytest.raises(poller.PollInProgress):
            poller.poll_feed(db, feed.id, settings)
    finally:
        lock.release()


def test_manual_grab_of_historical_entry(db: Session, settings: Settings, respx_mock: respx.MockRouter) -> None:
    feed, _series, season, _rule = seed(db, settings)
    fake = FakeQbit(respx_mock)
    mock_feed(respx_mock, feed_with(make_item(EP1, 1001)))
    poller.poll_feed(db, feed.id, settings)
    entry = db.scalar(select(FeedEntry).where(FeedEntry.title == EP1))
    assert entry is not None and entry.is_historical and not fake.add_route.called

    preview = poller.build_grab_preview(db, entry, season.id, 1, False, settings)
    assert preview.save_path == EXPECTED_BC_S2 and preview.duplicate_of is None
    assert any("historical" in w for w in preview.warnings)
    d = poller.perform_grab(db, entry, season.id, 1, False, settings)
    assert d.status == "submitted" and fake.add_route.call_count == 1

    preview2 = poller.build_grab_preview(db, entry, season.id, 1, False, settings)
    assert preview2.duplicate_of is not None and preview2.duplicate_of.id == d.id
    with pytest.raises(poller.GrabError) as ei:
        poller.perform_grab(db, entry, season.id, 1, False, settings)
    assert ei.value.status_code == 409
    assert fake.add_route.call_count == 1


def test_refresh_status_updates_progress(db: Session, settings: Settings, respx_mock: respx.MockRouter) -> None:
    feed, *_ = seed(db, settings)
    fake = FakeQbit(respx_mock)
    body = {"data": sample_feed()}
    mock_feed(respx_mock, lambda: body["data"])
    poller.poll_feed(db, feed.id, settings)
    body["data"] = feed_with(make_item(EP1, 1001))
    poller.poll_feed(db, feed.id, settings)
    d = db.scalars(select(Download)).one()
    assert d.qbit_hash is not None
    fake.torrents[d.qbit_hash].update(state="uploading", progress=1.0)
    assert dispatcher.refresh_status(db, settings) == 1
    assert d.qbit_state == "uploading" and d.qbit_progress == 1.0

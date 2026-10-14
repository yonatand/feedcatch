"""Episodes, metadata refresh (AniList/Jikan/TMDB), release search, grab-missing, calendar, wanted, settings, jobs.

All outbound HTTP is mocked with respx (AniList and AnimeTosho fixtures are real captured responses; Jikan is never
called live; TMDB fixtures are built from the documented v3 schema).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import ActivityLog, Download, Episode, FeedEntry, FeedSource, Rule, Season, Series, utcnow
from app.services import crypto, metadata, poller, scheduler, search, settings_store
from app.services.episodes import compute_status, season_summaries
from app.services.metadata import MetadataError, anilist, tmdb
from app.services.metadata.anilist import ANILIST_URL, JIKAN_URL
from tests.helpers import FAKE_QBIT_PASS, FAKE_QBIT_USER, FEED_URL, FIXTURES, QBIT_URL, FakeQbit, mock_feed

EPISODES_97940 = json.loads((FIXTURES / "anilist_episodes_97940.json").read_text(encoding="utf-8"))
SEARCH_XML = (FIXTURES / "animetosho_search_black_clover_s02.xml").read_bytes()
SEARCH_TEMPLATE = "https://search.example.test/rss2?q={query}"
SEARCH_PREFIX = "https://search.example.test/rss2"
TMDB_SEARCH = json.loads((FIXTURES / "tmdb_search_tv.json").read_text(encoding="utf-8"))
TMDB_TV = json.loads((FIXTURES / "tmdb_tv_1399.json").read_text(encoding="utf-8"))
TMDB_SEASON = json.loads((FIXTURES / "tmdb_tv_1399_season_1.json").read_text(encoding="utf-8"))
JIKAN_MAL = "https://api.jikan.moe/v4/anime/34572/episodes"
NOW = utcnow()


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    anilist.clear_cache()
    tmdb.cache.clear()
    monkeypatch.setattr(anilist, "JIKAN_PAGE_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(search, "sleep", lambda _s: None)
    yield
    anilist.clear_cache()
    tmdb.cache.clear()


# ---------------------------------------------------------------- helpers


@dataclass
class D:
    id: int
    status: str
    qbit_progress: float | None = None
    qbit_state: str | None = None


def _episodes_page2() -> dict[str, Any]:
    """Synthetic page 2 continuing the real page 1 (episodes 158..170)."""
    data = json.loads(json.dumps(EPISODES_97940))
    media = data["data"]["Media"]
    media["airingSchedule"] = {
        "pageInfo": {"hasNextPage": False},
        "nodes": [{"episode": n, "airingAt": 1608629100 + (n - 157) * 604800} for n in range(158, 171)],
    }
    return data


def _anilist_episodes_route(router: respx.MockRouter, pages: dict[int, Any] | None = None) -> respx.Route:
    pages = pages or {1: EPISODES_97940, 2: _episodes_page2()}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "airingSchedule(page: $page, perPage: 50)" in body["query"]
        return httpx.Response(200, json=pages[body["variables"]["page"]])

    return router.post(ANILIST_URL).mock(side_effect=handler)


def _configure_qbit(db: Session, settings: Settings) -> None:
    settings_store.set(db, settings_store.QBIT_URL, QBIT_URL)
    settings_store.set(db, settings_store.QBIT_USERNAME, FAKE_QBIT_USER)
    settings_store.set(db, settings_store.QBIT_PASSWORD_ENC, crypto.encrypt(FAKE_QBIT_PASS, settings))
    db.commit()


def _bc(db: Session, *, monitored: bool = True, absolute: int | None = None) -> tuple[Series, Season]:
    series = Series(name="Black Clover", aliases=["Black.Clover", "Black_Clover", "Burakku"], monitored=monitored)
    season = Season(series=series, season_number=2, monitored=True, absolute_min=absolute)
    db.add_all([series, season])
    db.commit()
    return series, season


def _search_feed(db: Session, url: str = FEED_URL) -> FeedSource:
    feed = FeedSource(name="Tosho", url=url, search_url_template=SEARCH_TEMPLATE, initial_poll_done=True)
    db.add(feed)
    db.commit()
    return feed


def _rules(db: Session, series: Series, season: Season) -> tuple[Rule, Rule]:
    at = Rule(
        series=series, season=season, name="Anime Time", priority=5, release_group="Anime Time", resolutions=["1080p"]
    )
    anyr = Rule(series=series, season=None, name="Any 1080p", priority=0, resolutions=["1080p"])
    db.add_all([at, anyr])
    db.commit()
    return at, anyr


def _eps(db: Session, season: Season, dates: dict[int, datetime | None]) -> None:
    for n, dt in dates.items():
        db.add(Episode(season_id=season.id, episode_number=n, air_date=dt, source="anilist"))
    db.commit()


def _download(db: Session, season: Season, ep: int, status: str = "submitted", infohash: str | None = None) -> Download:
    feed = db.scalars(select(FeedSource)).first()
    if feed is None:
        feed = FeedSource(name="x", url="https://x.example.test/rss")
        db.add(feed)
        db.flush()
    entry = FeedEntry(feed_id=feed.id, guid=f"g-{season.id}-{ep}-{status}", title=f"ep {ep}")
    db.add(entry)
    db.flush()
    d = Download(
        entry_id=entry.id,
        series_id=season.series_id,
        season_id=season.id,
        episode_number=ep,
        source_url="magnet:?xt=urn:btih:" + (infohash or f"{ep:040x}"),
        source_url_kind="magnet",
        save_path="/home/qbittorrent-nox/media/Black Clover/Season 02",
        status=status,
        infohash=infohash,
    )
    db.add(d)
    db.commit()
    return d


# ---------------------------------------------------------------- status derivation


@pytest.mark.parametrize(
    ("air", "downloads", "expected", "shown"),
    [
        (None, [], "unknown", None),
        (NOW + timedelta(days=1), [], "unaired", None),
        (NOW - timedelta(days=1), [], "missing", None),
        (NOW, [], "missing", None),  # air_date <= now
        (NOW - timedelta(days=1), [D(1, "failed")], "missing", 1),  # failed download still shown
        (None, [D(1, "failed")], "unknown", 1),
        (NOW - timedelta(days=1), [D(1, "pending")], "pending", 1),
        (NOW + timedelta(days=1), [D(1, "pending")], "pending", 1),
        (NOW - timedelta(days=1), [D(1, "submitted", 0.5, "downloading")], "downloading", 1),
        (NOW - timedelta(days=1), [D(1, "exists", None, None)], "downloading", 1),
        (NOW - timedelta(days=1), [D(1, "path_mismatch", 0.2, "stalledDL")], "downloading", 1),
        (NOW - timedelta(days=1), [D(1, "submitted", 0.999, "downloading")], "downloaded", 1),
        (NOW - timedelta(days=1), [D(1, "submitted", 1.0, None)], "downloaded", 1),
        (None, [D(1, "exists", 0.3, "stalledUP")], "downloaded", 1),
        (NOW - timedelta(days=1), [D(1, "submitted", 0.1, "pausedUP")], "downloaded", 1),
        (NOW - timedelta(days=1), [D(1, "submitted", 0.1, "stoppedUP")], "downloaded", 1),
        (NOW - timedelta(days=1), [D(1, "failed"), D(2, "submitted", 0.4, "downloading")], "downloading", 2),
        (NOW - timedelta(days=1), [D(1, "submitted", 0.2, "x"), D(3, "pending")], "pending", 3),  # newest wins
        (NOW - timedelta(days=1), [D(5, "failed"), D(2, "failed")], "missing", 5),
    ],
)
def test_compute_status(air: datetime | None, downloads: list[D], expected: str, shown: int | None) -> None:
    st = compute_status(air, downloads, NOW)
    assert st.status == expected
    assert (st.download.id if st.download is not None else None) == shown


def test_season_summaries(db: Session) -> None:
    _, season = _bc(db)
    _eps(db, season, {1: NOW - timedelta(days=9), 2: NOW - timedelta(days=2), 3: NOW + timedelta(days=5), 4: None})
    d = _download(db, season, 1, "submitted")
    d.qbit_progress = 1.0
    db.commit()
    s = season_summaries(db, [season.id, 9999])
    assert s[season.id].model_dump() == {
        "episode_count": 4,
        "downloaded_count": 1,
        "missing_count": 1,
        "unaired_count": 1,
    }
    assert s[9999].episode_count == 0


# ---------------------------------------------------------------- metadata refresh (AniList + Jikan)


def test_anilist_client_episodes_paginates_and_parses(respx_mock: respx.MockRouter) -> None:
    route = _anilist_episodes_route(respx_mock)
    raw = anilist.AnilistClient().episodes(97940)
    assert route.call_count == 2
    assert [json.loads(c.request.content)["variables"]["page"] for c in route.calls] == [1, 2]
    assert raw["episodes"] == 170 and raw["idMal"] == 34572 and raw["status"] == "FINISHED"
    assert set(raw["airing"]) == set(range(133, 171))
    assert raw["airing"][133] == 1594113900
    assert len(raw["titles"]) == 170
    assert raw["titles"][1] == "Asta and Yuno" and raw["titles"][3] == "To the Royal Capital of the Clover Kingdom!"
    anilist.AnilistClient().episodes(97940)  # cached
    assert route.call_count == 2


def test_anilist_pagination_capped(respx_mock: respx.MockRouter) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = json.loads(request.content)["variables"]["page"]
        data = json.loads(json.dumps(EPISODES_97940))
        data["data"]["Media"]["airingSchedule"]["nodes"] = [{"episode": page, "airingAt": 1594113900}]
        return httpx.Response(200, json=data)  # hasNextPage stays true forever

    route = respx_mock.post(ANILIST_URL).mock(side_effect=handler)
    anilist.AnilistClient().episodes(97940)
    assert route.call_count == anilist.MAX_AIRING_PAGES == 12


def test_refresh_season_jikan_failure_ignored(db: Session, settings: Settings, respx_mock: respx.MockRouter) -> None:
    _anilist_episodes_route(respx_mock)
    jikan = respx_mock.get(url__startswith=JIKAN_MAL).mock(side_effect=httpx.ConnectTimeout("slow"))
    _, season = _bc(db)
    season.metadata_provider, season.metadata_id = "anilist", "97940"
    db.add(Episode(season_id=season.id, episode_number=1, title="My own title", source="manual"))
    db.add(Episode(season_id=season.id, episode_number=500, title="kept forever", source="anilist"))
    db.commit()
    rows = metadata.refresh_season(db, season, settings)
    db.commit()
    assert jikan.call_count == 1  # tried once (eps 1..132 have no air date), failure ignored, no retry
    by = {e.episode_number: e for e in rows}
    assert len(by) == 171  # 1..170 + the old row 500 that is never deleted
    assert by[1].title == "My own title" and by[1].source == "manual"  # manual row untouched
    assert by[500].title == "kept forever"
    assert by[2].title == "The Boys' Promise" and by[2].air_date is None and by[2].source == "anilist"
    assert by[133].air_date == datetime.fromtimestamp(1594113900, tz=UTC)
    assert by[170].air_date is not None
    assert season.metadata_refreshed_at is not None
    ev = db.scalars(select(ActivityLog).where(ActivityLog.event_type == "metadata_refreshed")).one()
    assert ev.details is not None and ev.details["created"] == 169 and ev.details["provider"] == "anilist"

    # second refresh: nothing new, rows updated in place
    anilist.clear_cache()
    metadata.refresh_season(db, season, settings)
    db.commit()
    assert db.scalar(select(Episode.id).where(Episode.episode_number == 2)) == by[2].id


def test_refresh_season_jikan_fills_titles_and_dates(
    db: Session, settings: Settings, respx_mock: respx.MockRouter
) -> None:
    data = json.loads(json.dumps(EPISODES_97940))
    media = data["data"]["Media"]
    media["streamingEpisodes"] = []  # a new season: no streaming titles
    media["airingSchedule"] = {"pageInfo": {"hasNextPage": False}, "nodes": [{"episode": 3, "airingAt": 1594113900}]}
    media["episodes"] = 3
    media["status"] = "FINISHED"
    _anilist_episodes_route(respx_mock, {1: data})
    jikan = respx_mock.get(url__startswith=JIKAN_MAL).mock(
        return_value=httpx.Response(
            200,
            json={
                "pagination": {"has_next_page": False, "last_visible_page": 1},
                "data": [
                    {"mal_id": 1, "title": "Asta and Yuno", "aired": "2017-10-03T00:00:00+00:00"},
                    {"mal_id": 2, "title": "The Boys' Promise", "aired": None},
                ],
            },
        )
    )
    _, season = _bc(db)
    season.metadata_provider, season.metadata_id = "anilist", "97940"
    db.commit()
    by = {e.episode_number: e for e in metadata.refresh_season(db, season, settings)}
    assert jikan.call_count == 1 and parse_qs(urlsplit(str(jikan.calls[0].request.url)).query)["page"] == ["1"]
    assert by[1].title == "Asta and Yuno" and by[1].source == "jikan"
    assert by[1].air_date == datetime(2017, 10, 3, tzinfo=UTC)
    assert by[2].air_date is None and by[3].title is None and by[3].source == "anilist"


def test_refresh_requires_link(db: Session, settings: Settings) -> None:
    _, season = _bc(db)
    with pytest.raises(MetadataError) as ei:
        metadata.refresh_season(db, season, settings)
    assert ei.value.not_linked


def test_jikan_url_shape() -> None:
    assert JIKAN_URL.format(mal_id=34572) == JIKAN_MAL


# ---------------------------------------------------------------- TMDB provider


def _tmdb_routes(router: respx.MockRouter) -> dict[str, respx.Route]:
    return {
        "search": router.get(f"{tmdb.TMDB_API}/search/tv").mock(return_value=httpx.Response(200, json=TMDB_SEARCH)),
        "tv": router.get(f"{tmdb.TMDB_API}/tv/1399").mock(return_value=httpx.Response(200, json=TMDB_TV)),
        "season": router.get(f"{tmdb.TMDB_API}/tv/1399/season/1").mock(
            return_value=httpx.Response(200, json=TMDB_SEASON)
        ),
        "missing": router.get(f"{tmdb.TMDB_API}/tv/9").mock(return_value=httpx.Response(404, json={})),
        "season2": router.get(f"{tmdb.TMDB_API}/tv/1399/season/2").mock(return_value=httpx.Response(404, json={})),
    }


def test_tmdb_provider(respx_mock: respx.MockRouter) -> None:
    routes = _tmdb_routes(respx_mock)
    p = tmdb.TmdbProvider("k" * 32)
    items = p.search("Game of Thrones", 5)
    assert [i.id for i in items] == ["1399", "254577"]
    got = items[0]
    assert (got.provider, got.kind, got.title, got.year) == ("tmdb", "tv", "Game of Thrones", 2011)
    assert got.cover_url == "https://image.tmdb.org/t/p/w342/1XS1oqL89opfnbLl8WnZY1O1uJx.jpg"
    assert got.site_url == "https://www.themoviedb.org/tv/1399" and items[1].cover_url is None
    params = routes["search"].calls[0].request.url.params
    assert params["query"] == "Game of Thrones" and params["api_key"] == "k" * 32
    assert "k" * 32 not in repr(p)

    d = p.detail("1399")
    assert d.episodes == 73 and d.status == "Ended" and d.related == []
    assert [s.season_number for s in d.seasons] == [1, 2]  # specials skipped
    s = metadata.build_suggestion(d)
    assert s.name == "Game of Thrones" and s.metadata["kind"] == "tv"
    assert [(x["season_number"], x["episode_max"], x["metadata_id"]) for x in s.seasons] == [
        (1, 10, "1399"),
        (2, 10, "1399"),
    ]

    eps = p.episodes("1399", 1)
    assert [(e.number, e.title) for e in eps] == [(1, "Winter Is Coming"), (2, "The Kingsroad"), (3, "Lord Snow")]
    assert eps[0].air_date == datetime(2011, 4, 17, tzinfo=UTC) and eps[2].air_date is None
    with pytest.raises(MetadataError) as ei:
        p.detail("9")
    assert ei.value.not_found


def test_tmdb_v4_token_and_errors(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{tmdb.TMDB_API}/search/tv").mock(return_value=httpx.Response(200, json=TMDB_SEARCH))
    tmdb.TmdbProvider("t" * 200).search("Game of Thrones")
    req = route.calls[0].request
    assert req.headers["Authorization"] == "Bearer " + "t" * 200 and "api_key" not in req.url.params
    route.mock(return_value=httpx.Response(401, json={"status_message": "Invalid API key"}))
    with pytest.raises(MetadataError, match="401"):
        tmdb.TmdbProvider("bad").search("other query")
    route.mock(return_value=httpx.Response(429, headers={"Retry-After": "4"}))
    with pytest.raises(MetadataError) as ei:
        tmdb.TmdbProvider("bad").search("third query")
    assert ei.value.retry_after == 4
    with pytest.raises(MetadataError) as ei2:
        tmdb.TmdbProvider("").search("x y")
    assert ei2.value.not_configured


def test_tmdb_refresh_uses_season_number(db: Session, settings: Settings, respx_mock: respx.MockRouter) -> None:
    _tmdb_routes(respx_mock)
    settings_store.set(db, settings_store.TMDB_API_KEY, crypto.encrypt("k" * 32, settings))
    series = Series(name="Game of Thrones", aliases=[])
    season = Season(series=series, season_number=1, metadata_provider="tmdb", metadata_id="1399")
    db.add_all([series, season])
    db.commit()
    rows = metadata.refresh_season(db, season, settings)
    assert [(e.episode_number, e.source) for e in rows] == [(1, "tmdb"), (2, "tmdb"), (3, "tmdb")]


# ---------------------------------------------------------------- search: templates and queries


def test_validate_template() -> None:
    assert search.validate_template(" https://feed.example.test/rss?q={query} ", False).endswith("{query}")
    for bad in ("https://feed.example.test/rss", "https://feed.example.test/{query}?q={query}"):
        with pytest.raises(ValueError, match="exactly once"):
            search.validate_template(bad, False)
    from app.services.ssrf import SsrfError

    with pytest.raises(SsrfError):
        search.validate_template("http://internal.example.test/rss?q={query}", False)
    assert search.validate_template("http://internal.example.test/rss?q={query}", True)
    assert search.build_url(SEARCH_TEMPLATE, "Black Clover S02") == f"{SEARCH_PREFIX}?q=Black+Clover+S02"


def test_build_queries(db: Session) -> None:
    series, season = _bc(db)
    assert search.build_queries(series.name, series.aliases, season) == [
        "Black Clover S02",
        "Black.Clover S02",
        "Black_Clover S02",
    ]  # aliases capped at 2
    season.absolute_min = 171
    assert search.build_queries(series.name, ["black clover", ""], season) == ["Black Clover"]  # absolute: no S02
    assert search.build_queries(series.name, series.aliases, season, "  custom   query ") == ["custom query"]


# ---------------------------------------------------------------- search: candidates


def test_search_season_candidates_grouped_and_ordered(
    db: Session, settings: Settings, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get(url__startswith=SEARCH_PREFIX).mock(
        return_value=httpx.Response(200, content=SEARCH_XML, headers={"content-type": "application/rss+xml"})
    )
    series, season = _bc(db)
    season.monitored = False  # search is explicit: monitored flags are ignored
    series.aliases = []
    db.commit()
    _search_feed(db)
    at, anyr = _rules(db, series, season)
    _eps(db, season, {1: NOW - timedelta(days=8), 2: NOW - timedelta(days=1)})
    _download(db, season, 2, "pending")

    res = search.search_season(db, season, settings)
    assert route.call_count == 1
    assert str(route.calls[0].request.url) == f"{SEARCH_PREFIX}?q=Black+Clover+S02"
    assert res.queries == ["Black Clover S02"] and res.feeds_searched == ["Tosho"] and res.fetched == 10
    assert res.errors == []
    got = [(c.episode_number, c.entry.title.split("]")[0] + "]", c.rule.name) for c in res.candidates]
    assert got == [
        (1, "[Anime Time]", "Anime Time"),  # priority 5 first
        (1, "[Feibanyama]", "Any 1080p"),  # then newest first
        (1, "[FrixySubs]", "Any 1080p"),
        (2, "[Anime Time]", "Anime Time"),
        (2, "[FrixySubs]", "Any 1080p"),
        (2, "[DKB]", "Any 1080p"),
        (2, "[Erai-raws]", "Any 1080p"),
    ]
    assert {c.episode_status for c in res.candidates if c.episode_number == 1} == {"missing"}
    assert all(c.already_have and c.episode_status == "pending" for c in res.candidates if c.episode_number == 2)
    assert res.candidates[0].save_path == "/home/qbittorrent-nox/media/Black Clover/Season 02"
    assert any(c["check"] == "group" and c["passed"] for c in res.candidates[0].conditions)

    entries = list(db.scalars(select(FeedEntry).where(FeedEntry.outcome == "searched")))
    assert len(entries) == 10 and all(not e.is_historical for e in entries)


def test_search_requires_template_and_caps_fetches(
    db: Session, settings: Settings, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    series, season = _bc(db)
    with pytest.raises(search.SearchError):
        search.search_season(db, season, settings)
    sleeps: list[float] = []
    monkeypatch.setattr(search, "sleep", sleeps.append)
    for i in range(3):
        db.add(FeedSource(name=f"f{i}", url=f"https://f{i}.example.test/rss", search_url_template=SEARCH_TEMPLATE))
    db.commit()
    route = respx_mock.get(url__startswith=SEARCH_PREFIX).mock(return_value=httpx.Response(503))
    res = search.search_season(db, season, settings)  # 3 feeds x 3 queries = 9 > cap 6
    assert route.call_count == search.MAX_FETCHES_PER_SEARCH == 6
    assert sleeps == [3] * 5  # search_delay_seconds between consecutive fetches
    assert len(res.errors) == 7 and "HTTP 503" in res.errors[0] and "stopped after 6" in res.errors[-1]


def test_search_rejects_private_template_target(db: Session, settings: Settings, respx_mock: respx.MockRouter) -> None:
    _, season = _bc(db)
    db.add(FeedSource(name="evil", url=FEED_URL, search_url_template="http://internal.example.test/?q={query}"))
    db.commit()
    res = search.search_season(db, season, settings)
    assert res.fetched == 0 and res.errors and "not allowed" in res.errors[0]


def test_searched_entries_never_dispatched_by_poller(
    db: Session, settings: Settings, respx_mock: respx.MockRouter
) -> None:
    _configure_qbit(db, settings)
    fake = FakeQbit(respx_mock)
    respx_mock.get(url__startswith=SEARCH_PREFIX).mock(
        return_value=httpx.Response(200, content=SEARCH_XML, headers={"content-type": "application/rss+xml"})
    )
    mock_feed(respx_mock, SEARCH_XML)  # the main feed later carries the very same releases
    series, season = _bc(db)
    feed = _search_feed(db)
    _rules(db, series, season)
    search.search_season(db, season, settings)
    res = poller.poll_feed(db, feed.id, settings)
    assert res.fetched == 10 and res.new_entries == 0 and res.accepted == 0
    assert not fake.add_route.called
    assert {e.outcome for e in db.scalars(select(FeedEntry))} == {"searched"}
    assert db.scalars(select(Download)).all() == []


def test_search_keeps_existing_outcomes(db: Session, settings: Settings, respx_mock: respx.MockRouter) -> None:
    mock_feed(respx_mock, SEARCH_XML)
    respx_mock.get(url__startswith=SEARCH_PREFIX).mock(
        return_value=httpx.Response(200, content=SEARCH_XML, headers={"content-type": "application/rss+xml"})
    )
    _, season = _bc(db)
    feed = _search_feed(db)
    feed.initial_poll_done = False
    db.commit()
    poller.poll_feed(db, feed.id, settings)  # first poll: everything historical
    res = search.search_season(db, season, settings)
    assert res.fetched == 30  # 3 queries (name + 2 aliases)
    assert {e.outcome for e in db.scalars(select(FeedEntry))} == {"historical"}


# ---------------------------------------------------------------- grab missing


def test_grab_missing_only_missing_and_respects_duplicates(
    db: Session, settings: Settings, respx_mock: respx.MockRouter
) -> None:
    _configure_qbit(db, settings)
    fake = FakeQbit(respx_mock)
    respx_mock.get(url__startswith=SEARCH_PREFIX).mock(
        return_value=httpx.Response(200, content=SEARCH_XML, headers={"content-type": "application/rss+xml"})
    )
    series, season = _bc(db)
    series.aliases = []
    db.commit()
    _search_feed(db)
    _rules(db, series, season)
    _eps(db, season, {1: NOW - timedelta(days=8), 2: NOW - timedelta(days=1), 3: NOW + timedelta(days=6)})
    _download(db, season, 2, "submitted")

    out = search.grab_missing(db, season, settings)
    assert [(d.episode_number, d.status) for d in out.grabbed] == [(1, "submitted")]
    assert out.grabbed[0].entry.title.startswith("[Anime Time] Black Clover Season 2 - 01")
    assert out.grabbed[0].rule is not None and out.grabbed[0].rule.name == "Anime Time"
    assert out.skipped == [(2, "already have")]  # ep 3 is unaired without candidates: not reported
    assert len(fake.adds) == 1 and fake.adds[0]["savepath"] == "/home/qbittorrent-nox/media/Black Clover/Season 02"

    # running again grabs nothing new (ep 1 is now downloading)
    again = search.grab_missing(db, season, settings)
    assert again.grabbed == [] and (1, "already have") in again.skipped
    assert len(fake.adds) == 1


def test_grab_missing_without_metadata_uses_unknown(
    db: Session, settings: Settings, respx_mock: respx.MockRouter
) -> None:
    _configure_qbit(db, settings)
    fake = FakeQbit(respx_mock)
    respx_mock.get(url__startswith=SEARCH_PREFIX).mock(
        return_value=httpx.Response(200, content=SEARCH_XML, headers={"content-type": "application/rss+xml"})
    )
    series, season = _bc(db)
    series.aliases = []
    db.commit()
    _search_feed(db)
    at, _ = _rules(db, series, season)
    db.delete(_)
    db.commit()
    # same infohash as the Anime Time E01 release already tracked elsewhere -> duplicate, not re-sent
    entry_hash = "38b000"
    res = search.search_season(db, season, settings)
    e1 = next(c.entry for c in res.candidates if c.episode_number == 1)
    assert e1.infohash and e1.infohash.startswith(entry_hash)
    other_series = Series(name="Other", aliases=[])
    other = Season(series=other_series, season_number=1)
    db.add_all([other_series, other])
    db.commit()
    _download(db, other, 9, "submitted", infohash=e1.infohash)
    out = search.grab_missing(db, season, settings, result=res)
    assert [d.episode_number for d in out.grabbed] == [2]  # no episode rows: candidates' episodes are "unknown"
    assert out.skipped and out.skipped[0][0] == 1 and out.skipped[0][1].startswith("already have (download #")
    assert len(fake.adds) == 1


# ---------------------------------------------------------------- API


@pytest.fixture
def api(client: TestClient) -> Iterator[tuple[TestClient, Session]]:
    from app.db import SessionLocal

    s = SessionLocal()
    try:
        yield client, s
    finally:
        s.close()


def _api_bc(client: TestClient, **season: Any) -> tuple[int, int]:
    body = {"name": "Black Clover", "aliases": [], "seasons": [{"season_number": 2, **season}]}
    r = client.post("/api/series", json=body)
    assert r.status_code == 201, r.text
    out = r.json()
    return out["id"], out["seasons"][0]["id"]


def _season_body(**kw: Any) -> dict[str, Any]:
    return {
        "season_number": 2,
        "monitored": True,
        "path_override": None,
        "episode_min": None,
        "episode_max": None,
        "absolute_min": None,
        "absolute_max": None,
        **kw,
    }


def test_api_put_season_links_and_refreshes(api: tuple[TestClient, Session], respx_mock: respx.MockRouter) -> None:
    client, _ = api
    _, sid = _api_bc(client)
    route = _anilist_episodes_route(respx_mock)
    respx_mock.get(url__startswith=JIKAN_MAL).mock(side_effect=httpx.ReadTimeout("slow"))
    r = client.put(f"/api/seasons/{sid}", json=_season_body(metadata_provider="anilist", metadata_id=97940))
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["metadata_provider"] == "anilist" and s["metadata_id"] == "97940" and s["warnings"] == []
    assert s["episode_count"] == 170 and s["metadata_refreshed_at"] is not None
    assert route.call_count == 2
    # unchanged link: no refresh; omitting the fields keeps the link (older clients)
    r = client.put(f"/api/seasons/{sid}", json=_season_body(monitored=False))
    assert r.status_code == 200 and r.json()["metadata_id"] == "97940" and route.call_count == 2

    eps = client.get(f"/api/seasons/{sid}/episodes").json()
    assert set(eps) == {"items", "summary"}
    assert set(eps["summary"]) == {"episode_count", "downloaded_count", "missing_count", "unaired_count"}
    first = eps["items"][0]
    assert set(first) == {"id", "season_id", "episode_number", "title", "air_date", "source", "status", "download"}
    assert first["episode_number"] == 1 and first["status"] == "unknown" and first["title"] == "Asta and Yuno"
    item133 = next(i for i in eps["items"] if i["episode_number"] == 133)
    assert item133["air_date"] == "2020-07-07T09:25:00Z" and item133["status"] == "missing"


def test_api_put_season_refresh_failure_is_warning(
    api: tuple[TestClient, Session], respx_mock: respx.MockRouter
) -> None:
    client, _ = api
    _, sid = _api_bc(client)
    respx_mock.post(ANILIST_URL).mock(return_value=httpx.Response(500))
    r = client.put(f"/api/seasons/{sid}", json=_season_body(metadata_provider="anilist", metadata_id="195604"))
    assert r.status_code == 200
    assert r.json()["metadata_id"] == "195604" and r.json()["warnings"][0].startswith("episode metadata")
    # explicit refresh: 502 upstream, 400 when unlinked or TMDB without key
    assert client.post(f"/api/seasons/{sid}/episodes/refresh").status_code == 502
    r = client.put(f"/api/seasons/{sid}", json=_season_body(metadata_provider=None, metadata_id=None))
    assert r.status_code == 200 and r.json()["metadata_provider"] is None
    r = client.post(f"/api/seasons/{sid}/episodes/refresh")
    assert r.status_code == 400 and "not linked" in r.json()["detail"]
    client.put(f"/api/seasons/{sid}", json=_season_body(metadata_provider="tmdb", metadata_id="1399"))
    r = client.post(f"/api/seasons/{sid}/episodes/refresh")
    assert r.status_code == 400 and r.json()["detail"] == "TMDB API key not configured"
    assert client.post("/api/seasons/9999/episodes/refresh").status_code == 404
    assert client.put(f"/api/seasons/{sid}", json=_season_body(metadata_provider="anilist")).status_code == 422


def test_api_refresh_and_manual_edit(api: tuple[TestClient, Session], respx_mock: respx.MockRouter) -> None:
    client, _ = api
    _anilist_episodes_route(respx_mock)
    respx_mock.get(url__startswith=JIKAN_MAL).mock(return_value=httpx.Response(500))
    _, sid = _api_bc(client, metadata_provider="anilist", metadata_id="97940")
    r = client.put(f"/api/seasons/{sid}/episodes/2", json={"title": "  Custom  ", "air_date": "2017-10-10T09:25:00"})
    assert r.status_code == 200, r.text
    ep = r.json()
    assert ep["title"] == "Custom" and ep["source"] == "manual" and ep["air_date"] == "2017-10-10T09:25:00Z"
    assert ep["status"] == "missing" and ep["download"] is None
    anilist.clear_cache()
    r = client.post(f"/api/seasons/{sid}/episodes/refresh")
    assert r.status_code == 200
    items = {i["episode_number"]: i for i in r.json()["items"]}
    assert items[2]["title"] == "Custom" and items[2]["source"] == "manual"
    # creating a row for an unknown episode; only the sent fields change
    r = client.put(f"/api/seasons/{sid}/episodes/999", json={"title": "Special"})
    assert r.status_code == 200 and r.json()["air_date"] is None and r.json()["status"] == "unknown"
    r = client.put(f"/api/seasons/{sid}/episodes/999", json={"air_date": None})
    assert r.json()["title"] == "Special"
    assert client.put("/api/seasons/9999/episodes/1", json={}).status_code == 404


def test_api_search_and_grab_missing(
    api: tuple[TestClient, Session], respx_mock: respx.MockRouter, settings: Settings
) -> None:
    client, db = api
    sid_series, sid = _api_bc(client)
    r = client.post(f"/api/seasons/{sid}/search", json={})
    assert r.status_code == 400 and "search URL template" in r.json()["detail"]

    feed = {"name": "Tosho", "url": FEED_URL, "search_url_template": SEARCH_TEMPLATE}
    r = client.post("/api/feeds", json=feed)
    assert r.status_code == 201 and r.json()["search_url_template"] == SEARCH_TEMPLATE
    rule = {
        "series_id": sid_series,
        "season_id": sid,
        "name": "Anime Time",
        "release_group": "Anime Time",
        "resolutions": ["1080p"],
    }
    assert client.post("/api/rules", json=rule).status_code == 201
    route = respx_mock.get(url__startswith=SEARCH_PREFIX).mock(
        return_value=httpx.Response(200, content=SEARCH_XML, headers={"content-type": "application/rss+xml"})
    )
    r = client.post(f"/api/seasons/{sid}/search")  # bodiless
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"queries", "feeds_searched", "fetched", "candidates", "errors"}
    assert body["queries"] == ["Black Clover S02"] and body["feeds_searched"] == ["Tosho"]
    cands = body["candidates"]
    assert [c["episode_number"] for c in cands] == [1, 2]
    assert set(cands[0]) == {
        "entry", "episode_number", "rule_id", "rule_name", "conditions", "save_path", "episode_status", "already_have",
    }  # fmt: skip
    assert cands[0]["entry"]["outcome"] == "searched" and cands[0]["entry"]["parsed"]["group"] == "Anime Time"
    assert cands[0]["episode_status"] == "unknown" and cands[0]["already_have"] is False

    r = client.post(f"/api/seasons/{sid}/search", json={"query": "black clover season 2"})
    assert r.json()["queries"] == ["black clover season 2"]
    assert str(route.calls[-1].request.url).endswith("?q=black+clover+season+2")

    # qBittorrent not configured: downloads are created and stay pending (no send)
    r = client.post(f"/api/seasons/{sid}/search/grab-missing", json={})
    assert r.status_code == 200, r.text
    out = r.json()
    assert set(out) == {"grabbed", "skipped", "errors"}
    assert [(d["episode_number"], d["status"], d["rule_name"]) for d in out["grabbed"]] == [
        (1, "pending", "Anime Time"),
        (2, "pending", "Anime Time"),
    ]
    out2 = client.post(f"/api/seasons/{sid}/search/grab-missing").json()
    assert out2["grabbed"] == [] and {s["reason"] for s in out2["skipped"]} == {"already have"}
    eps = client.get(f"/api/seasons/{sid}/episodes").json()
    assert eps["items"] == []  # no metadata rows; downloads are listed under /api/downloads
    series = client.get(f"/api/series/{sid_series}").json()
    assert series["seasons"][0]["episode_count"] == 0
    assert client.post("/api/seasons/9999/search").status_code == 404


def test_api_feed_template_validation(api: tuple[TestClient, Session]) -> None:
    client, _ = api
    base = {"name": "F", "url": FEED_URL}
    r = client.post("/api/feeds", json={**base, "search_url_template": "https://feed.example.test/rss?q=x"})
    assert r.status_code == 400 and "{query}" in r.json()["detail"]
    r = client.post("/api/feeds", json={**base, "search_url_template": "http://10.0.0.1/rss?q={query}"})
    assert r.status_code == 400 and "not allowed" in r.json()["detail"]
    r = client.post("/api/feeds", json={**base, "search_url_template": "   "})
    assert r.status_code == 201 and r.json()["search_url_template"] is None
    fid = r.json()["id"]
    r = client.put(f"/api/feeds/{fid}", json={**base, "search_url_template": SEARCH_TEMPLATE})
    assert r.json()["search_url_template"] == SEARCH_TEMPLATE
    r = client.put(f"/api/feeds/{fid}", json={**base, "name": "G"})  # older client omits it: kept
    assert r.json()["search_url_template"] == SEARCH_TEMPLATE
    r = client.put(f"/api/feeds/{fid}", json={**base, "search_url_template": None})
    assert r.json()["search_url_template"] is None


def _add_eps(db: Session, season_id: int, dates: dict[int, datetime | None]) -> None:
    for n, dt in dates.items():
        db.add(Episode(season_id=season_id, episode_number=n, air_date=dt, title=f"T{n}", source="anilist"))
    db.commit()


def test_api_calendar_wanted_dashboard(api: tuple[TestClient, Session]) -> None:
    client, db = api
    now = utcnow()
    _, s_mon = _api_bc(client)
    r = client.post("/api/series", json={"name": "Quiet", "monitored": False, "seasons": [{"season_number": 1}]})
    s_off = r.json()["seasons"][0]["id"]
    _add_eps(
        db,
        s_mon,
        {
            1: now - timedelta(days=10),
            2: now - timedelta(days=3),
            3: now + timedelta(days=2),
            4: now + timedelta(days=20),
            5: None,
        },
    )
    _add_eps(db, s_off, {1: now - timedelta(days=1), 2: now + timedelta(days=1)})

    cal = client.get("/api/calendar").json()["items"]  # default window: now-7d .. now+14d
    assert [(c["season_id"], c["episode_number"]) for c in cal] == [(s_mon, 2), (s_off, 1), (s_off, 2), (s_mon, 3)]
    c0 = cal[0]
    assert set(c0) == {
        "series_id", "series_name", "cover_url", "season_id", "season_number", "episode_number", "title", "air_date",
        "status", "monitored",
    }  # fmt: skip
    assert c0["status"] == "missing" and c0["monitored"] is True and cal[1]["monitored"] is False
    assert cal[3]["status"] == "unaired"
    mon = client.get("/api/calendar", params={"monitored_only": True}).json()["items"]
    assert [(c["season_id"], c["episode_number"]) for c in mon] == [(s_mon, 2), (s_mon, 3)]
    wide = client.get(
        "/api/calendar",
        params={"from": (now - timedelta(days=30)).isoformat(), "to": (now + timedelta(days=30)).isoformat()},
    ).json()["items"]
    assert len(wide) == 6
    too_wide = {"from": (now - timedelta(days=40)).isoformat(), "to": (now + timedelta(days=30)).isoformat()}
    assert client.get("/api/calendar", params=too_wide).status_code == 400
    backwards = {"from": now.isoformat(), "to": (now - timedelta(days=1)).isoformat()}
    assert client.get("/api/calendar", params=backwards).status_code == 400

    wanted = client.get("/api/wanted").json()
    assert wanted["total"] == 2  # ep 2 then ep 1 of the monitored season; unmonitored series excluded
    assert [w["episode_number"] for w in wanted["items"]] == [2, 1]
    assert client.get("/api/wanted", params={"limit": 1, "offset": 1}).json()["items"][0]["episode_number"] == 1

    dash = client.get("/api/dashboard").json()
    assert dash["counts"]["wanted"] == 2
    assert [(u["season_id"], u["episode_number"]) for u in dash["upcoming"]] == [(s_mon, 3)]


def test_api_search_all(api: tuple[TestClient, Session], respx_mock: respx.MockRouter) -> None:
    client, db = api
    assert client.post("/api/wanted/search-all").status_code == 400  # no searchable feed
    client.post("/api/feeds", json={"name": "Tosho", "url": FEED_URL, "search_url_template": SEARCH_TEMPLATE})
    assert search.search_all_lock.acquire(blocking=False)
    try:
        r = client.post("/api/wanted/search-all")
        assert r.status_code == 409 and "already running" in r.json()["detail"]
    finally:
        search.search_all_lock.release()

    series_id, sid = _api_bc(client)
    _add_eps(db, sid, {1: utcnow() - timedelta(days=8), 2: utcnow() - timedelta(days=1)})
    client.post("/api/rules", json={"series_id": series_id, "name": "AT", "release_group": "Anime Time"})
    respx_mock.get(url__startswith=SEARCH_PREFIX).mock(
        return_value=httpx.Response(200, content=SEARCH_XML, headers={"content-type": "application/rss+xml"})
    )
    r = client.post("/api/wanted/search-all")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "seasons": [
            {
                "season_id": sid,
                "series_name": "Black Clover",
                "season_number": 2,
                "grabbed": 2,
                "skipped": 0,
                "errors": [],
            }
        ]
    }
    assert client.get("/api/wanted").json()["total"] == 0  # both pending now
    assert not search.search_all_lock.locked()


def test_api_settings_episode_fields_and_tmdb_key(
    api: tuple[TestClient, Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = api
    cur = client.get("/api/settings").json()
    assert (cur["auto_search_missing"], cur["search_interval_hours"]) == (False, 24)
    assert (cur["metadata_refresh_hours"], cur["search_delay_seconds"], cur["tmdb_api_key_set"]) == (12, 3, False)
    assert cur["sources"]["tmdb_api_key"] == "db"
    base = {"media_base_path": cur["media_base_path"]}
    r = client.put(
        "/api/settings",
        json={**base, "auto_search_missing": True, "search_interval_hours": 6, "tmdb_api_key": "secret-tmdb-key"},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["auto_search_missing"] is True and out["search_interval_hours"] == 6 and out["tmdb_api_key_set"]
    assert "secret-tmdb-key" not in r.text and "secret-tmdb-key" not in client.get("/api/activity").text
    providers = client.get("/api/metadata/providers").json()["items"]
    assert [p["configured"] for p in providers] == [True, True]
    r = client.put("/api/settings", json=base)  # older client: new fields kept, key unchanged
    assert r.json()["search_interval_hours"] == 6 and r.json()["tmdb_api_key_set"] is True
    assert client.put("/api/settings", json={**base, "search_interval_hours": 0}).status_code == 422
    r = client.put("/api/settings", json={**base, "tmdb_api_key": ""})
    assert r.json()["tmdb_api_key_set"] is False


def test_tmdb_env_key_source(api: tuple[TestClient, Session], monkeypatch: pytest.MonkeyPatch) -> None:
    from app import config

    client, _ = api
    monkeypatch.setenv("TMDB_API_KEY", "env-key")
    config.get_settings.cache_clear()
    out = client.get("/api/settings").json()
    assert out["sources"]["tmdb_api_key"] == "env" and out["tmdb_api_key_set"] is True
    r = client.put("/api/settings", json={"media_base_path": out["media_base_path"], "tmdb_api_key": "x"})
    assert any("TMDB_API_KEY" in w for w in r.json()["warnings"])


def test_api_metadata_tmdb_search(api: tuple[TestClient, Session], respx_mock: respx.MockRouter) -> None:
    client, _ = api
    r = client.get("/api/metadata/search", params={"provider": "tmdb", "q": "Game of Thrones"})
    assert r.status_code == 400 and r.json()["detail"] == "TMDB API key not configured"
    client.put("/api/settings", json={"media_base_path": "/home/qbittorrent-nox/media", "tmdb_api_key": "k" * 32})
    _tmdb_routes(respx_mock)
    r = client.get("/api/metadata/search", params={"provider": "tmdb", "q": "Game of Thrones"})
    assert r.status_code == 200 and r.json()["items"][0]["id"] == "1399"
    s = client.get("/api/metadata/tmdb/1399/suggest").json()
    assert [x["season_number"] for x in s["seasons"]] == [1, 2] and s["metadata"]["kind"] == "tv"
    sid = client.post(
        "/api/series", json={"name": "GoT", "seasons": [{"season_number": 1}, {"season_number": 2}]}
    ).json()["id"]
    r = client.put(f"/api/series/{sid}/metadata", json={"provider": "tmdb", "id": "1399"})
    assert r.status_code == 200, r.text
    s1, s2 = r.json()["seasons"]
    assert (s1["metadata_id"], s2["metadata_id"]) == ("1399", "1399")  # every existing season linked
    assert s1["episode_count"] == 3 and s1["warnings"] == []
    assert s2["warnings"] and "TMDB" in s2["warnings"][0]  # season 2 episodes not mocked: 404 -> warning


# ---------------------------------------------------------------- scheduler jobs


def test_metadata_refresh_job(db: Session, settings: Settings, respx_mock: respx.MockRouter) -> None:
    route = _anilist_episodes_route(respx_mock)
    respx_mock.get(url__startswith=JIKAN_MAL).mock(return_value=httpx.Response(500))
    series, season = _bc(db)
    season.metadata_provider, season.metadata_id = "anilist", "97940"
    unmon = Season(series=series, season_number=3, monitored=False, metadata_provider="anilist", metadata_id="1")
    db.add(unmon)
    db.commit()
    scheduler._metadata_refresh(db, settings)
    assert route.call_count == 2  # only the monitored, linked season
    assert db.scalar(select(Season.metadata_refreshed_at).where(Season.id == season.id)) is not None
    assert db.scalar(select(Season.metadata_refreshed_at).where(Season.id == unmon.id)) is None


def test_metadata_refresh_job_errors_logged(db: Session, settings: Settings, respx_mock: respx.MockRouter) -> None:
    respx_mock.post(ANILIST_URL).mock(return_value=httpx.Response(429, headers={"Retry-After": "30"}))
    series, season = _bc(db)
    season.metadata_provider, season.metadata_id = "anilist", "97940"
    db.add(Season(series=series, season_number=3, monitored=True, metadata_provider="anilist", metadata_id="2"))
    db.commit()
    scheduler._metadata_refresh(db, settings)  # never raises; stops at the rate limit
    assert respx_mock.calls.call_count == 1


def test_search_missing_job(db: Session, settings: Settings, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(url__startswith=SEARCH_PREFIX).mock(
        return_value=httpx.Response(200, content=SEARCH_XML, headers={"content-type": "application/rss+xml"})
    )
    series, season = _bc(db)
    series.aliases = []
    db.commit()
    _search_feed(db)
    _rules(db, series, season)
    _eps(db, season, {1: NOW - timedelta(days=8), 2: NOW + timedelta(days=3)})
    scheduler._search_missing(db, settings)  # auto_search_missing is off by default
    assert route.call_count == 0
    settings_store.set(db, settings_store.AUTO_SEARCH_MISSING, True)
    db.commit()
    assert search.search_all_lock.acquire(blocking=False)
    scheduler._search_missing(db, settings)  # another search is running: skipped
    search.search_all_lock.release()
    assert route.call_count == 0
    scheduler._search_missing(db, settings)
    assert route.call_count == 1
    assert [d.episode_number for d in db.scalars(select(Download))] == [1]  # ep 2 unaired
    ev = db.scalars(select(ActivityLog).where(ActivityLog.event_type == "missing_search")).one()
    assert ev.details is not None and ev.details["grabbed"] == 1


def test_episode_jobs_follow_settings(db: Session, settings: Settings) -> None:
    scheduler.start(settings)
    try:
        sched = scheduler._scheduler
        assert sched is not None
        job = sched.get_job("search_missing")
        assert job is not None and job.trigger.interval == timedelta(hours=24) and job.max_instances == 1
        settings_store.set(db, settings_store.SEARCH_INTERVAL_HOURS, 6)
        settings_store.set(db, settings_store.METADATA_REFRESH_HOURS, 2)
        db.commit()
        scheduler.sync_episode_jobs(db)
        assert sched.get_job("search_missing").trigger.interval == timedelta(hours=6)  # type: ignore[union-attr]
        assert sched.get_job("metadata_refresh").trigger.interval == timedelta(hours=2)  # type: ignore[union-attr]
    finally:
        scheduler.shutdown(wait=True)
    scheduler.sync_episode_jobs(db)  # no-op when stopped


# ---------------------------------------------------------------- migration 0003


def test_migration_0003_converts_anilist_and_keeps_children(db_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    from app.db import ALEMBIC_DIR, ALEMBIC_INI

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "0002_anilist")
    engine = create_engine(db_url)
    info = {"title_romaji": "Black Clover", "title_english": "Black Clover", "title_native": "ブラッククローバー",
            "format": "TV", "status": "FINISHED", "season_year": 2017, "episodes": 170,
            "site_url": "https://anilist.co/anime/97940"}  # fmt: skip
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.execute(
            text(
                "INSERT INTO series (id, created_at, name, aliases_json, monitored, season_folder_format, anilist_id,"
                " anilist_json) VALUES (1, '2026-01-01', 'Black Clover', '[]', 1, 'Season {season:02d}', 97940, :j)"
            ),
            {"j": json.dumps(info)},
        )
        conn.execute(
            text(
                "INSERT INTO seasons (id, created_at, series_id, season_number, monitored)"
                " VALUES (1, '2026-01-01', 1, 2, 1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO rules (id, created_at, series_id, season_id, name, enabled, priority,"
                " require_group_prefix,"
                " include_keywords_json, exclude_keywords_json, resolutions_json, sources_json, codecs_json,"
                " language_keywords_json)"
                " VALUES (1, '2026-01-01', 1, 1, 'r', 1, 0, 0, '[]', '[]', '[]', '[]', '[]', '[]')"
            )
        )
        conn.execute(
            text("INSERT INTO feed_sources (id, created_at, name, url, enabled, poll_interval_minutes, backfill_mode,"
                 " last_status, consecutive_failures, initial_poll_done) VALUES (1, '2026-01-01', 'AT',"
                 " 'https://feed.animetosho.net/rss2', 1, 15, 'skip', 'never', 0, 0)")
        )  # fmt: skip
    engine.dispose()

    command.upgrade(cfg, "head")
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT metadata_provider, metadata_id, metadata_json FROM series")).one()
            assert row[0] == "anilist" and row[1] == "97940"
            meta = json.loads(row[2])
            assert meta["title"] == "Black Clover" and meta["original_title"] == "ブラッククローバー"
            assert meta["kind"] == "anime" and meta["year"] == 2017 and meta["episodes"] == 170
            assert conn.execute(text("SELECT count(*) FROM seasons")).scalar() == 1  # not cascade-deleted
            assert conn.execute(text("SELECT count(*) FROM rules")).scalar() == 1
            assert conn.execute(text("SELECT search_url_template FROM feed_sources")).scalar() is None
            sql = conn.execute(text("SELECT sql FROM sqlite_master WHERE name='series'")).scalar()
            assert "NOCASE" in sql  # name stays case-insensitive unique
    finally:
        engine.dispose()
    command.downgrade(cfg, "0002_anilist")
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SELECT anilist_id FROM series")).scalar() == 97940
            assert conn.execute(text("SELECT count(*) FROM seasons")).scalar() == 1
    finally:
        engine.dispose()


def test_jikan_can_be_disabled(db: Session, settings: Settings, respx_mock: respx.MockRouter) -> None:
    _anilist_episodes_route(respx_mock)
    jikan = respx_mock.get(url__startswith=JIKAN_MAL).mock(return_value=httpx.Response(500))
    _, season = _bc(db)
    season.metadata_provider, season.metadata_id = "anilist", "97940"
    db.commit()
    off = Settings(APP_DATA_DIR=settings.APP_DATA_DIR, JIKAN_ENABLED=False)
    assert len(metadata.refresh_season(db, season, off)) == 170
    assert jikan.call_count == 0


# ---------------------------------------------------------------- fixes 2026-10-14: Jikan backoff

DETAIL_97940 = json.loads((FIXTURES / "anilist_detail_97940.json").read_text(encoding="utf-8"))


def test_jikan_timeouts_and_backoff(respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch) -> None:
    from structlog.testing import capture_logs

    clock = [1000.0]
    monkeypatch.setattr(anilist, "_jikan_clock", lambda: clock[0])
    route = respx_mock.get(url__startswith=JIKAN_MAL).mock(side_effect=httpx.ConnectError("Network is unreachable"))
    assert anilist.fetch_jikan_episodes(34572) == {}
    assert route.call_count == 1
    timeout = route.calls[0].request.extensions["timeout"]
    assert timeout["connect"] == 3.0 and timeout["read"] == 8.0
    assert anilist.jikan_backoff_until == 1000.0 + 6 * 3600

    with capture_logs() as logs:
        clock[0] += 3600
        assert anilist.fetch_jikan_episodes(34572) == {}
        clock[0] += 3600
        assert anilist.fetch_jikan_episodes(34572) == {}
    assert route.call_count == 1  # skipped silently while in backoff
    assert [e["event"] for e in logs] == ["jikan_backoff_skip"]  # one info line per window
    assert logs[0]["log_level"] == "info"

    clock[0] = 1000.0 + 6 * 3600 + 1  # window over: tried again; an HTTP error also starts a new window
    route.mock(return_value=httpx.Response(503))
    assert anilist.fetch_jikan_episodes(34572) == {}
    assert route.call_count == 2 and anilist.jikan_backoff_until == clock[0] + 6 * 3600
    with capture_logs() as logs:
        anilist.fetch_jikan_episodes(34572)
    assert route.call_count == 2 and [e["event"] for e in logs] == ["jikan_backoff_skip"]

    anilist.reset_jikan_backoff()  # what a restart does
    route.mock(
        return_value=httpx.Response(
            200, json={"pagination": {"has_next_page": False}, "data": [{"mal_id": 1, "title": "Asta and Yuno"}]}
        )
    )
    assert anilist.fetch_jikan_episodes(34572) == {1: ("Asta and Yuno", None)}
    assert route.call_count == 3


def test_refresh_skips_jikan_during_backoff(db: Session, settings: Settings, respx_mock: respx.MockRouter) -> None:
    _anilist_episodes_route(respx_mock)
    jikan = respx_mock.get(url__startswith=JIKAN_MAL).mock(side_effect=httpx.ConnectTimeout("slow"))
    _, season = _bc(db)
    season.metadata_provider, season.metadata_id = "anilist", "97940"
    db.commit()
    assert len(metadata.refresh_season(db, season, settings)) == 170
    anilist.clear_cache()
    assert len(metadata.refresh_season(db, season, settings)) == 170
    assert jikan.call_count == 1  # the second refresh did not wait for Jikan again


# ---------------------------------------------------------------- fixes 2026-10-14: season link backfill


def _anilist_detail(media_id: int, sequel: int | None, fmt: str = "TV") -> dict[str, Any]:
    data = json.loads(json.dumps(DETAIL_97940))
    media = data["data"]["Media"]
    media["id"] = media_id
    edges = [e for e in media["relations"]["edges"] if e["relationType"] != "SEQUEL"]
    if sequel is not None:
        node = {
            "id": sequel,
            "title": {"romaji": f"S {sequel}", "english": None},
            "format": fmt,
            "episodes": 12,
            "seasonYear": 2025,
            "status": "RELEASING",
        }
        edges.append({"relationType": "SEQUEL", "node": node})
    media["relations"]["edges"] = edges
    return data


def _small_episodes(media_id: int) -> dict[str, Any]:
    nodes = [{"episode": 1, "airingAt": 1594113900}, {"episode": 2, "airingAt": 1594718700}]
    media = {
        "id": media_id,
        "episodes": 2,
        "idMal": None,
        "status": "FINISHED",
        "nextAiringEpisode": None,
        "airingSchedule": {"pageInfo": {"hasNextPage": False}, "nodes": nodes},
        "streamingEpisodes": [],
    }
    return {"data": {"Media": media}}


def _anilist_router(
    router: respx.MockRouter, details: dict[int, dict[str, Any]], fail_episodes: frozenset[int] = frozenset()
) -> respx.Route:
    """Detail queries answered from `details` (others 404); episode queries: real 97940 pages or a small list."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        media_id = int(body["variables"]["id"])
        if "airingSchedule" in body["query"]:
            if media_id in fail_episodes:
                return httpx.Response(500)
            if media_id == 97940:
                return httpx.Response(200, json={1: EPISODES_97940, 2: _episodes_page2()}[body["variables"]["page"]])
            return httpx.Response(200, json=_small_episodes(media_id))
        if media_id not in details:
            return httpx.Response(404, json={"errors": [{"message": "Not Found.", "status": 404}], "data": None})
        return httpx.Response(200, json=details[media_id])

    return router.post(ANILIST_URL).mock(side_effect=handler)


def _detail_calls(route: respx.Route) -> list[int]:
    out = []
    for c in route.calls:
        body = json.loads(c.request.content)
        if "airingSchedule" not in body["query"]:
            out.append(int(body["variables"]["id"]))
    return out


def _episode_count(db: Session, season: Season) -> int:
    return len(list(db.scalars(select(Episode.id).where(Episode.season_id == season.id))))


def test_backfill_anilist_sequel_chain(db: Session, settings: Settings, respx_mock: respx.MockRouter) -> None:
    from app.services.metadata import backfill

    respx_mock.get(url__startswith=JIKAN_MAL).mock(return_value=httpx.Response(500))
    details = {
        97940: _anilist_detail(97940, 195604),
        195604: _anilist_detail(195604, 300001),
        300001: _anilist_detail(300001, None),
    }
    route = _anilist_router(respx_mock, details)
    series = Series(name="Black Clover", aliases=[], metadata_provider="anilist", metadata_id="97940")
    s1 = Season(series=series, season_number=1)
    s2 = Season(series=series, season_number=2)
    s3 = Season(series=series, season_number=3)
    s5 = Season(series=series, season_number=5)  # beyond the chain: stays unlinked
    unlinked_series = Series(name="No link", aliases=[])
    db.add_all([series, s1, s2, s3, s5, unlinked_series, Season(series=unlinked_series, season_number=1)])
    db.commit()

    out = backfill.backfill_season_links(db, settings)
    assert out == {"linked": 3, "refreshed": 3, "errors": []}
    got = {s.season_number: (s.metadata_provider, s.metadata_id) for s in series.seasons}
    assert got == {1: ("anilist", "97940"), 2: ("anilist", "195604"), 3: ("anilist", "300001"), 5: (None, None)}
    assert _detail_calls(route) == [97940, 195604, 300001]
    assert _episode_count(db, s1) == 170 and _episode_count(db, s3) == 2
    assert s2.metadata_refreshed_at is not None

    # idempotent: linked seasons are never relinked or refreshed again
    s2.metadata_id = "12345"
    db.commit()
    anilist.clear_cache()
    before = len(route.calls)
    out = backfill.backfill_season_links(db, settings)
    assert out == {"linked": 0, "refreshed": 0, "errors": []}
    assert s2.metadata_id == "12345" and s5.metadata_provider is None
    assert all("airingSchedule" not in json.loads(c.request.content)["query"] for c in list(route.calls)[before:])
    assert _detail_calls(route)[3:] == [97940, 195604, 300001]  # season 5 still unlinked: chain walked again


def test_backfill_movie_sequel_passed_through_and_errors(
    db: Session, settings: Settings, respx_mock: respx.MockRouter
) -> None:
    from app.services.metadata import backfill

    # 500 -SEQUEL-> 501 (MOVIE, passed through) -SEQUEL-> 502 (TV = season 2) -SEQUEL-> 503 (OVA, chain ends)
    details = {
        500: _anilist_detail(500, 501, fmt="MOVIE"),
        501: _anilist_detail(501, 502, fmt="TV"),
        502: _anilist_detail(502, 503, fmt="OVA"),
        503: _anilist_detail(503, None),
        600: _anilist_detail(600, 601, fmt="MOVIE"),
        601: _anilist_detail(601, None),
    }
    route = _anilist_router(respx_mock, details, fail_episodes=frozenset({502, 404404}))
    series = Series(name="Movie sequel", aliases=[], metadata_provider="anilist", metadata_id="500")
    s1 = Season(series=series, season_number=1, metadata_provider="anilist", metadata_id="500")  # already linked
    s2 = Season(series=series, season_number=2)
    s3 = Season(series=series, season_number=3)  # only an OVA after season 2: stays unlinked
    only_movie = Series(name="Only movie", aliases=[], metadata_provider="anilist", metadata_id="600")
    m1 = Season(series=only_movie, season_number=1, metadata_provider="anilist", metadata_id="600")
    m2 = Season(series=only_movie, season_number=2)  # the movie sequel is never season 2
    gone = Series(name="Gone", aliases=[], metadata_provider="anilist", metadata_id="404404")
    g1 = Season(series=gone, season_number=1)
    g2 = Season(series=gone, season_number=2)
    db.add_all([series, s1, s2, s3, only_movie, m1, m2, gone, g1, g2])
    db.commit()
    out = backfill.backfill_season_links(db, settings)
    assert s2.metadata_id == "502" and s1.metadata_refreshed_at is None  # TV entry behind the movie; s1 untouched
    assert s3.metadata_provider is None and m2.metadata_provider is None
    assert g1.metadata_id == "404404" and g2.metadata_provider is None  # season 1 linked although the chain failed
    assert _detail_calls(route)[:4] == [500, 501, 502, 503]
    assert out["linked"] == 2 and out["refreshed"] == 0
    assert len(out["errors"]) == 3, out["errors"]
    assert any(e.startswith("'Gone': ") and "not found" in e for e in out["errors"])
    assert any("'Movie sequel' season 2: episode metadata could not be fetched" in e for e in out["errors"])
    failed = db.scalars(select(ActivityLog).where(ActivityLog.event_type == "metadata_refresh_failed")).all()
    assert len(failed) == 2


def test_backfill_tmdb(db: Session, settings: Settings, respx_mock: respx.MockRouter) -> None:
    from app.services.metadata import backfill

    routes = _tmdb_routes(respx_mock)
    series = Series(name="Game of Thrones", aliases=[], metadata_provider="tmdb", metadata_id="1399")
    seasons = {n: Season(series=series, season_number=n) for n in (1, 2, 7)}
    db.add_all([series, *seasons.values()])
    db.commit()
    out = backfill.backfill_season_links(db, settings)  # no key: season 1 linked, upstream never asked
    assert out["linked"] == 1 and out["refreshed"] == 0 and len(out["errors"]) == 2, out
    assert routes["tv"].call_count == 0
    settings_store.set(db, settings_store.TMDB_API_KEY, crypto.encrypt("k" * 32, settings))
    db.commit()
    out = backfill.backfill_season_links(db, settings)
    assert out["linked"] == 1  # season 2 exists upstream, 7 does not
    assert len(out["errors"]) == 1 and "season 2" in out["errors"][0]  # season/2 is a 404 in the fixture routes
    assert {n: s.metadata_id for n, s in seasons.items()} == {1: "1399", 2: "1399", 7: None}


def test_api_backfill_endpoint(api: tuple[TestClient, Session], respx_mock: respx.MockRouter) -> None:
    client, db = api
    respx_mock.get(url__startswith=JIKAN_MAL).mock(return_value=httpx.Response(500))
    _anilist_router(respx_mock, {97940: _anilist_detail(97940, 195604), 195604: _anilist_detail(195604, None)})
    body = {"name": "Black Clover", "aliases": [], "seasons": [{"season_number": 1}, {"season_number": 2}]}
    r = client.post("/api/series", json=body)
    assert r.status_code == 201
    sid = r.json()["id"]
    series = db.get(Series, sid)
    assert series is not None
    series.metadata_provider, series.metadata_id = "anilist", "97940"  # an upgraded DB: series link only
    db.commit()
    r = client.post("/api/metadata/backfill-season-links")
    assert r.status_code == 200
    assert r.json() == {"linked": 2, "refreshed": 2, "errors": []}
    seasons = {x["season_number"]: x for x in client.get(f"/api/series/{sid}").json()["seasons"]}
    assert seasons[1]["metadata_id"] == "97940" and seasons[2]["metadata_id"] == "195604"
    assert seasons[1]["episode_count"] == 170 and seasons[2]["episode_count"] == 2
    assert client.post("/api/metadata/backfill-season-links").json() == {"linked": 0, "refreshed": 0, "errors": []}


def test_delete_download_makes_episode_missing(api: tuple[TestClient, Session]) -> None:
    client, db = api
    _, sid = _api_bc(client)
    season = db.get(Season, sid)
    assert season is not None
    _eps(db, season, {1: NOW - timedelta(days=7)})
    d = _download(db, season, 1)
    item = client.get(f"/api/seasons/{sid}/episodes").json()["items"][0]
    assert item["status"] == "downloading" and item["download"]["id"] == d.id
    assert client.delete(f"/api/downloads/{d.id}").status_code == 204
    item = client.get(f"/api/seasons/{sid}/episodes").json()["items"][0]
    assert item["status"] == "missing" and item["download"] is None


def test_startup_backfill_after_0002_upgrade(respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch) -> None:
    """A populated 0002 DB (series had anilist_id 97940, seasons 1 and 2) is upgraded at startup; the background
    backfill then links season 1 to 97940 and season 2 to its SEQUEL 195604 (suggested_season_number 2)."""
    from alembic import command
    from alembic.config import Config

    from app import config
    from app.db import ALEMBIC_DIR, ALEMBIC_INI
    from app.services.metadata import backfill

    respx_mock.get(url__startswith=JIKAN_MAL).mock(return_value=httpx.Response(500))
    _anilist_router(respx_mock, {97940: DETAIL_97940, 195604: _anilist_detail(195604, None)})
    monkeypatch.setenv("APP_AUTH_DISABLED", "true")
    config.get_settings.cache_clear()
    s = config.get_settings()
    s.ensure_data_dir()
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", s.database_url)
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "0002_anilist")
    engine = create_engine(s.database_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO series (id, created_at, name, aliases_json, monitored, season_folder_format, anilist_id,"
                " anilist_json) VALUES (1, '2026-01-01', 'Black Clover', '[]', 1, 'Season {season:02d}', 97940, '{}')"
            )
        )
        for n in (1, 2):
            conn.execute(
                text(
                    "INSERT INTO seasons (id, created_at, series_id, season_number, monitored)"
                    " VALUES (:n, '2026-01-01', 1, :n, 1)"
                ),
                {"n": n},
            )
    engine.dispose()

    threads: list[Any] = []
    real = backfill.run_in_background

    def spy(settings: Settings) -> Any:
        t = real(settings)
        threads.append(t)
        return t

    monkeypatch.setattr(backfill, "run_in_background", spy)
    from app.main import create_app

    with TestClient(create_app()) as client:
        assert len(threads) == 1 and threads[0] is not None
        threads[0].join(timeout=30)
        assert not threads[0].is_alive()
        seasons = {x["season_number"]: x for x in client.get("/api/series/1").json()["seasons"]}
    assert (seasons[1]["metadata_provider"], seasons[1]["metadata_id"]) == ("anilist", "97940")
    assert (seasons[2]["metadata_provider"], seasons[2]["metadata_id"]) == ("anilist", "195604")
    assert seasons[1]["episode_count"] == 170 and seasons[2]["episode_count"] == 2

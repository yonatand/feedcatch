"""AniList client, suggestion builder, API routes and migration 0002. All HTTP is mocked with respx."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import run_migrations
from app.models import Series
from app.services import anilist
from app.services.anilist import (
    ANILIST_URL,
    AnilistClient,
    AnilistError,
    AnilistMediaDetail,
    build_suggestion,
    parse_media,
)
from tests.helpers import FIXTURES


def _load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data


SEARCH = _load("anilist_search_black_clover.json")
DETAIL = _load("anilist_detail_97940.json")
NOT_FOUND = {"errors": [{"message": "Not Found.", "status": 404, "locations": [{"line": 1, "column": 23}]}],
             "data": {"Media": None}}  # fmt: skip


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    anilist.clear_cache()
    yield
    anilist.clear_cache()


def _detail_bc() -> AnilistMediaDetail:
    return parse_media(DETAIL["data"]["Media"])


def _route_by_kind(router: respx.MockRouter, detail_by_id: dict[int, Any] | None = None) -> respx.Route:
    """One route that answers search queries with the search fixture and detail queries by id."""
    details = {97940: DETAIL} if detail_by_id is None else detail_by_id

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "Page(" in body["query"]:
            return httpx.Response(200, json=SEARCH)
        payload = details.get(body["variables"]["id"])
        if payload is None:
            return httpx.Response(404, json=NOT_FOUND)
        return httpx.Response(200, json=payload)

    return router.post(ANILIST_URL).mock(side_effect=handler)


# ---------------------------------------------------------------- client


def test_search_parses_real_fixture(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(ANILIST_URL).mock(
        return_value=httpx.Response(200, json=SEARCH, headers={"X-RateLimit-Remaining": "29"})
    )
    items = AnilistClient().search("Black Clover", limit=3)
    assert [m.id for m in items] == [97940, 155017, 131680]
    bc = items[0]
    assert bc.title_romaji == "Black Clover" and bc.title_english == "Black Clover"
    assert bc.title_native == "ブラッククローバー"
    assert bc.format == "TV" and bc.status == "FINISHED" and bc.season == "FALL"
    assert bc.season_year == 2017 and bc.episodes == 170
    assert bc.cover_large and bc.cover_large.startswith("https://s4.anilist.co/")
    assert bc.site_url == "https://anilist.co/anime/97940"
    assert items[1].title_english is None  # Petit Clover Advance has no english title

    req = route.calls.last.request
    body = json.loads(req.content)
    assert body["variables"] == {"q": "Black Clover", "limit": 3}
    assert "sort: SEARCH_MATCH" in body["query"] and "type: ANIME" in body["query"]
    assert "relations{edges{relationType" in body["query"]
    assert req.headers["User-Agent"].startswith("feedcatch/")
    assert req.headers["Content-Type"] == "application/json"
    assert req.headers["Accept"] == "application/json"


def test_get_parses_detail_with_relations(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(ANILIST_URL).mock(return_value=httpx.Response(200, json=DETAIL))
    d = AnilistClient().get(97940)
    assert d.id == 97940 and d.episodes == 170
    assert len(d.related) == 8
    seq = next(r for r in d.related if r.id == 195604)
    assert seq.relation_type == "SEQUEL" and seq.format == "TV" and seq.season_year == 2026 and seq.episodes is None
    body = json.loads(route.calls.last.request.content)
    assert body["variables"] == {"id": 97940}
    assert "Media(id: $id, type: ANIME)" in body["query"]


def test_rate_limit_raises_transient_with_retry_after(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(ANILIST_URL).mock(
        return_value=httpx.Response(429, json={"errors": [{"message": "Too Many Requests."}]},
                                    headers={"Retry-After": "37", "X-RateLimit-Remaining": "0"})
    )  # fmt: skip
    with pytest.raises(AnilistError) as ei:
        AnilistClient().search("Black Clover")
    assert ei.value.transient is True
    assert ei.value.retry_after == 37
    assert not ei.value.not_found


def test_rate_limit_without_header_defaults(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(ANILIST_URL).mock(return_value=httpx.Response(429))
    with pytest.raises(AnilistError) as ei:
        AnilistClient().get(1)
    assert ei.value.retry_after == anilist.DEFAULT_RETRY_AFTER


def test_cache_hit_makes_no_second_request(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(ANILIST_URL).mock(return_value=httpx.Response(200, json=SEARCH))
    c = AnilistClient()
    first = c.search("Black Clover", 3)
    second = c.search("  black   CLOVER ", 3)  # normalized key
    assert route.call_count == 1
    assert [m.id for m in first] == [m.id for m in second]
    # search results also prime the detail cache
    assert c.get(97940).id == 97940
    assert route.call_count == 1


def test_detail_cache_and_expiry(respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch) -> None:
    route = respx_mock.post(ANILIST_URL).mock(return_value=httpx.Response(200, json=DETAIL))
    clock = [1000.0]
    monkeypatch.setattr(anilist, "_now", lambda: clock[0])
    c = AnilistClient()
    c.get(97940)
    c.get(97940)
    assert route.call_count == 1
    clock[0] += anilist.CACHE_TTL_SECONDS + 1
    c.get(97940)
    assert route.call_count == 2


def test_cache_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(anilist, "CACHE_MAX_KEYS", 3)
    for i in range(5):
        anilist._cache_put(f"k{i}", i)
    assert anilist.cache_size() == 3
    assert anilist._cache_get("k0") is None and anilist._cache_get("k4") == 4


def test_not_found_graphql_error(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(ANILIST_URL).mock(return_value=httpx.Response(404, json=NOT_FOUND))
    with pytest.raises(AnilistError) as ei:
        AnilistClient().get(999999999)
    assert ei.value.not_found and not ei.value.transient


def test_not_found_in_200_body(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(ANILIST_URL).mock(return_value=httpx.Response(200, json={"data": {"Media": None}}))
    with pytest.raises(AnilistError) as ei:
        AnilistClient().get(5)
    assert ei.value.not_found


def test_server_error_and_timeout_are_transient(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(ANILIST_URL)
    route.mock(return_value=httpx.Response(503, text="down"))
    with pytest.raises(AnilistError) as ei:
        AnilistClient().search("abc")
    assert ei.value.transient and ei.value.retry_after is None
    route.mock(side_effect=httpx.ConnectTimeout("slow"))
    with pytest.raises(AnilistError) as ei2:
        AnilistClient().search("abcd")
    assert ei2.value.transient


def test_graphql_validation_error_is_permanent(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(ANILIST_URL).mock(
        return_value=httpx.Response(400, json={"errors": [{"message": "Bad query", "status": 400}], "data": None})
    )
    with pytest.raises(AnilistError) as ei:
        AnilistClient().search("abc")
    assert not ei.value.transient and not ei.value.not_found
    assert "Bad query" in str(ei.value)


def test_errors_are_not_cached(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(ANILIST_URL)
    route.mock(return_value=httpx.Response(503))
    with pytest.raises(AnilistError):
        AnilistClient().get(97940)
    route.mock(return_value=httpx.Response(200, json=DETAIL))
    assert AnilistClient().get(97940).id == 97940
    assert route.call_count == 2


# ---------------------------------------------------------------- build_suggestion


def test_build_suggestion_black_clover() -> None:
    s = build_suggestion(_detail_bc())
    assert s.name == "Black Clover"
    assert s.anilist_id == 97940
    # Hebrew/Thai/Russian synonyms and the native title are not aliases; romaji == english == name.
    assert s.aliases == []
    assert s.seasons == [
        {"season_number": 1, "episode_min": None, "episode_max": 170, "absolute_min": None, "absolute_max": None}
    ]
    assert s.cover_url and s.cover_url.endswith("bx97940-fyh8o7gNbha0.png")
    assert s.anilist == {
        "title_romaji": "Black Clover",
        "title_english": "Black Clover",
        "title_native": "ブラッククローバー",
        "format": "TV",
        "status": "FINISHED",
        "season_year": 2017,
        "episodes": 170,
        "site_url": "https://anilist.co/anime/97940",
    }
    ids = {r.id: r for r in s.related}
    assert 195604 in ids and ids[195604].relation_type == "SEQUEL"
    assert ids[195604].suggested_season_number == 2
    assert 86123 not in ids and 100088 not in ids  # ADAPTATION (manga/novel)
    assert 110318 not in ids  # SPIN_OFF
    assert 106223 not in ids and 155017 not in ids  # OTHER
    assert 87528 in ids and ids[87528].suggested_season_number is None  # ALTERNATIVE special
    assert 131680 in ids  # SIDE_STORY movie
    assert {r.relation_type for r in s.related} <= anilist.RELATED_TYPES


def _media(**kw: Any) -> AnilistMediaDetail:
    base: dict[str, Any] = dict(
        id=1,
        title_romaji=None,
        title_english=None,
        title_native=None,
        synonyms=[],
        format="TV",
        status="RELEASING",
        season=None,
        season_year=None,
        episodes=None,
        cover_medium=None,
        cover_large=None,
        site_url=None,
    )
    base.update(kw)
    return AnilistMediaDetail(**base)


def test_build_suggestion_sanitizes_name_and_filters_aliases() -> None:
    s = build_suggestion(
        _media(
            title_romaji="Re:Zero kara Hajimeru Isekai Seikatsu",
            title_english="Re:ZERO -Starting Life in Another World-",
            title_native="Re:ゼロから始める異世界生活",
            synonyms=["re:zero kara hajimeru isekai seikatsu", "リゼロ", "Re: Zero", "Re/Zero?", "Рэ:Зеро"],
        )
    )
    assert s.name == "ReZERO -Starting Life in Another World-"
    assert s.aliases == [
        "Re:ZERO -Starting Life in Another World-",  # original of the sanitized name
        "Re:Zero kara Hajimeru Isekai Seikatsu",
        "Re: Zero",
        "Re/Zero?",
    ]
    assert s.seasons[0]["episode_max"] is None
    assert s.cover_url is None and s.related == []


def test_build_suggestion_falls_back_to_romaji() -> None:
    s = build_suggestion(_media(title_romaji="Petit Clover Advance", cover_medium="https://x.example.test/c.png"))
    assert s.name == "Petit Clover Advance" and s.aliases == []
    assert s.cover_url == "https://x.example.test/c.png"


# ---------------------------------------------------------------- API


def test_api_search(client: TestClient, respx_mock: respx.MockRouter) -> None:
    respx_mock.post(ANILIST_URL).mock(return_value=httpx.Response(200, json=SEARCH))
    r = client.get("/api/anilist/search", params={"q": "Black Clover", "limit": 3})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 3
    assert set(items[0]) == {
        "id", "title_romaji", "title_english", "title_native", "synonyms", "format", "status",
        "season", "season_year", "episodes", "cover_medium", "cover_large", "site_url",
    }  # fmt: skip
    assert items[0]["id"] == 97940 and items[0]["episodes"] == 170


def test_api_search_short_query(client: TestClient, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(ANILIST_URL)
    assert client.get("/api/anilist/search", params={"q": " a "}).status_code == 400
    assert client.get("/api/anilist/search").status_code == 400
    assert route.call_count == 0


def test_api_search_rate_limited(client: TestClient, respx_mock: respx.MockRouter) -> None:
    respx_mock.post(ANILIST_URL).mock(return_value=httpx.Response(429, headers={"Retry-After": "12"}))
    r = client.get("/api/anilist/search", params={"q": "Black Clover"})
    assert r.status_code == 429
    assert r.json() == {"detail": "AniList rate limit, retry in 12 s"}
    assert r.headers["Retry-After"] == "12"


def test_api_search_upstream_failure(client: TestClient, respx_mock: respx.MockRouter) -> None:
    respx_mock.post(ANILIST_URL).mock(return_value=httpx.Response(500))
    r = client.get("/api/anilist/search", params={"q": "Black Clover"})
    assert r.status_code == 502
    assert "AniList" in r.json()["detail"]


def test_api_detail_and_404(client: TestClient, respx_mock: respx.MockRouter) -> None:
    _route_by_kind(respx_mock)
    r = client.get("/api/anilist/97940")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == 97940 and len(body["related"]) == 8
    assert set(body["related"][0]) == {
        "relation_type", "id", "title_romaji", "title_english", "format", "episodes", "season_year", "status",
        "suggested_season_number",
    }  # fmt: skip
    r = client.get("/api/anilist/424242")
    assert r.status_code == 404


def test_api_suggest(client: TestClient, respx_mock: respx.MockRouter) -> None:
    _route_by_kind(respx_mock)
    r = client.get("/api/anilist/97940/suggest")
    assert r.status_code == 200, r.text
    s = r.json()
    assert set(s) == {"anilist_id", "name", "aliases", "cover_url", "anilist", "seasons", "related"}
    assert s["name"] == "Black Clover" and s["aliases"] == []
    assert s["seasons"] == [
        {
            "season_number": 1,
            "monitored": True,
            "path_override": None,
            "episode_min": None,
            "episode_max": 170,
            "absolute_min": None,
            "absolute_max": None,
        }
    ]
    assert s["anilist"]["site_url"] == "https://anilist.co/anime/97940"
    assert any(x["id"] == 195604 and x["relation_type"] == "SEQUEL" for x in s["related"])
    assert all(x["relation_type"] != "ADAPTATION" for x in s["related"])
    assert client.get("/api/anilist/424242/suggest").status_code == 404


def test_api_suggest_then_create_series_round_trip(client: TestClient, respx_mock: respx.MockRouter) -> None:
    _route_by_kind(respx_mock)
    s = client.get("/api/anilist/97940/suggest").json()
    body = {
        "name": "Black Clover AniList",
        "aliases": s["aliases"],
        "anilist_id": s["anilist_id"],
        "cover_url": s["cover_url"],
        "anilist": s["anilist"],
        "seasons": s["seasons"],
    }
    r = client.post("/api/series", json=body)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["anilist_id"] == 97940 and out["cover_url"] == s["cover_url"]
    assert out["anilist"]["episodes"] == 170
    assert out["seasons"][0]["episode_max"] == 170
    # same anilist_id on a second series -> 409
    body["name"] = "Another"
    assert client.post("/api/series", json=body).status_code == 409
    # a PUT that omits the AniList fields keeps the link (older clients)
    r = client.put(f"/api/series/{out['id']}", json={"name": "Black Clover AniList", "aliases": ["BC"]})
    assert r.status_code == 200
    assert r.json()["anilist_id"] == 97940 and r.json()["anilist"] is not None
    # a PUT that echoes the current AniList fields back (e.g. a Monitor toggle) is not a self-conflict
    cur = r.json()
    echo = {k: cur[k] for k in ("name", "aliases", "anilist_id", "cover_url", "anilist")} | {"monitored": False}
    r = client.put(f"/api/series/{out['id']}", json=echo)
    assert r.status_code == 200, r.text
    assert r.json()["monitored"] is False and r.json()["anilist_id"] == 97940
    assert r.json()["anilist"] == cur["anilist"] and r.json()["cover_url"] == cur["cover_url"]


def test_series_without_anilist_has_null_fields(client: TestClient) -> None:
    r = client.post("/api/series", json={"name": "Plain"})
    assert r.status_code == 201
    out = r.json()
    assert out["anilist_id"] is None and out["cover_url"] is None and out["anilist"] is None


def test_series_rejects_non_http_cover(client: TestClient) -> None:
    r = client.post("/api/series", json={"name": "X", "cover_url": "javascript:alert(1)"})
    assert r.status_code == 400
    assert "cover_url" in r.json()["detail"]


def test_api_link_and_unlink(client: TestClient, respx_mock: respx.MockRouter) -> None:
    route = _route_by_kind(respx_mock, {97940: DETAIL})
    sid = client.post("/api/series", json={"name": "BC", "aliases": ["Black Clover TV", "black clover"]}).json()["id"]
    r = client.put(f"/api/series/{sid}/anilist", json={"anilist_id": 97940})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["name"] == "BC"  # never renamed
    assert out["aliases"] == ["Black Clover TV", "black clover"]  # existing kept; "Black Clover" dup (case) skipped
    assert out["anilist_id"] == 97940
    assert out["cover_url"].startswith("https://s4.anilist.co/")
    assert out["anilist"]["title_romaji"] == "Black Clover" and out["anilist"]["episodes"] == 170
    assert route.call_count == 1

    # another series cannot take the same id
    other = client.post("/api/series", json={"name": "Other"}).json()["id"]
    r = client.put(f"/api/series/{other}/anilist", json={"anilist_id": 97940})
    assert r.status_code == 409
    assert route.call_count == 1  # conflict is checked before calling AniList

    # re-linking the same series to the same id is fine (cached)
    assert client.put(f"/api/series/{sid}/anilist", json={"anilist_id": 97940}).status_code == 200

    # unlink clears the three fields, aliases untouched
    r = client.put(f"/api/series/{sid}/anilist", json={"anilist_id": None})
    assert r.status_code == 200
    out = r.json()
    assert out["anilist_id"] is None and out["cover_url"] is None and out["anilist"] is None
    assert out["aliases"] == ["Black Clover TV", "black clover"]
    # now the other series may take it
    assert client.put(f"/api/series/{other}/anilist", json={"anilist_id": 97940}).status_code == 200


def test_api_link_merges_new_aliases(client: TestClient, respx_mock: respx.MockRouter) -> None:
    raw = json.loads(json.dumps(DETAIL))
    raw["data"]["Media"]["synonyms"].append("Burakku Kurōbā")
    raw["data"]["Media"]["title"]["english"] = "Black Clover (TV)"
    _route_by_kind(respx_mock, {97940: raw})
    # (the demo seed already owns the name "Black Clover")
    sid = client.post("/api/series", json={"name": "Clover", "aliases": ["BC"]}).json()["id"]
    out = client.put(f"/api/series/{sid}/anilist", json={"anilist_id": 97940}).json()
    assert out["name"] == "Clover"
    assert out["aliases"] == ["BC", "Black Clover (TV)", "Black Clover", "Burakku Kurōbā"]


def test_api_link_errors(client: TestClient, respx_mock: respx.MockRouter) -> None:
    _route_by_kind(respx_mock, {})
    sid = client.post("/api/series", json={"name": "BC"}).json()["id"]
    assert client.put(f"/api/series/{sid}/anilist", json={"anilist_id": 5}).status_code == 404
    assert client.put("/api/series/9999/anilist", json={"anilist_id": None}).status_code == 404
    respx_mock.routes.clear()
    respx_mock.post(ANILIST_URL).mock(return_value=httpx.Response(429, headers={"Retry-After": "3"}))
    r = client.put(f"/api/series/{sid}/anilist", json={"anilist_id": 6})
    assert r.status_code == 429 and r.json()["detail"] == "AniList rate limit, retry in 3 s"
    got = client.get(f"/api/series/{sid}").json()
    assert got["anilist_id"] is None


def test_anilist_requires_auth(auth_client: TestClient, respx_mock: respx.MockRouter) -> None:
    assert auth_client.get("/api/anilist/search", params={"q": "Black Clover"}).status_code == 401
    assert auth_client.get("/api/anilist/97940").status_code == 401
    assert auth_client.get("/api/anilist/97940/suggest").status_code == 401
    assert auth_client.put("/api/series/1/anilist", json={"anilist_id": None}).status_code == 401


# ---------------------------------------------------------------- migration


def test_migration_adds_columns_and_unique_index(db_url: str) -> None:
    run_migrations(db_url)
    engine = create_engine(db_url)
    try:
        insp = inspect(engine)
        cols = {c["name"]: c for c in insp.get_columns("series")}
        for name in ("anilist_id", "cover_url", "anilist_json"):
            assert name in cols and cols[name]["nullable"], name
        idx = {i["name"]: i for i in insp.get_indexes("series")}
        assert idx["ux_series_anilist_id"]["unique"]
        assert idx["ux_series_anilist_id"]["column_names"] == ["anilist_id"]
    finally:
        engine.dispose()


def test_anilist_id_unique_but_nulls_allowed(db: Session) -> None:
    db.add_all([Series(name="A", aliases=[]), Series(name="B", aliases=[])])
    db.add(Series(name="C", aliases=[], anilist_id=97940, anilist={"title_romaji": "Black Clover"}))
    db.flush()
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(Series(name="D", aliases=[], anilist_id=97940))
        db.flush()
    db.expire_all()
    c = db.query(Series).filter_by(name="C").one()
    assert c.anilist == {"title_romaji": "Black Clover"}

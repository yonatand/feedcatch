"""HTTP API tests (TestClient; auth disabled unless `auth_client`; scheduler off; respx for outbound HTTP)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

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

FEED_BODY = {
    "name": "Test",
    "url": FEED_URL,
    "enabled": True,
    "poll_interval_minutes": 15,
    "backfill_mode": "skip",
}


def _series(client: TestClient, name: str = "Frieren", **extra: Any) -> dict[str, Any]:
    body = {"name": name, "aliases": [], "monitored": True, "seasons": [{"season_number": 1, "monitored": True}]}
    body.update(extra)
    r = client.post("/api/series", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _bc_demo(client: TestClient, monitored: bool = False) -> dict[str, Any]:
    """The former demo seed: Black Clover S2 + rule 'DKB 1080p' (the production seed no longer creates it)."""
    body = {
        "name": "Black Clover",
        "aliases": ["Black.Clover", "Black_Clover"],
        "monitored": monitored,
        "seasons": [{"season_number": 2, "monitored": True}],
    }
    r = client.post("/api/series", json=body)
    assert r.status_code == 201, r.text
    series: dict[str, Any] = r.json()
    rule = _rule_body(
        series["id"],
        series["seasons"][0]["id"],
        name="DKB 1080p",
        priority=10,
        release_group="DKB",
        require_group_prefix=True,
    )
    assert client.post("/api/rules", json=rule).status_code == 201
    return series


def _rule_body(series_id: int, season_id: int | None = None, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "series_id": series_id,
        "season_id": season_id,
        "name": "SubsPlease 1080p",
        "enabled": True,
        "priority": 0,
        "release_group": "SubsPlease",
        "require_group_prefix": False,
        "include_keywords": [],
        "exclude_keywords": [],
        "resolutions": ["1080p"],
        "sources": [],
        "codecs": [],
        "language_keywords": [],
        "min_size_mb": None,
        "max_size_mb": None,
        "regex": None,
    }
    body.update(extra)
    return body


def _configure_qbit(client: TestClient) -> None:
    r = client.put(
        "/api/qbit",
        json={
            "url": QBIT_URL,
            "username": FAKE_QBIT_USER,
            "password": FAKE_QBIT_PASS,
            "category": "anime",
            "timeout_seconds": 5,
            "start_immediately": True,
            "poll_status": True,
        },
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------- health / spa


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["db"] == "ok" and body["scheduler"] == "stopped"
    assert body["version"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"


def test_spa_and_unknown_api(client: TestClient) -> None:
    r = client.get("/series/12")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


def test_dashboard(client: TestClient) -> None:
    r = client.get("/api/dashboard")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counts"]["series_total"] == 0  # no demo seed
    assert body["feeds"] == [] and body["upcoming"] == [] and body["counts"]["wanted"] == 0
    assert body["scheduler"] == {"running": False, "next_feed_poll_at": None}
    assert body["qbit"]["configured"] is False


# ---------------------------------------------------------------- auth


def test_auth_flow(auth_client: TestClient) -> None:
    c = auth_client
    st = c.get("/api/auth/status").json()
    assert st == {"auth_mode": "password", "setup_required": True, "authenticated": False}
    r = c.get("/api/feeds")
    assert r.status_code == 401 and r.json() == {"detail": "unauthenticated"}
    assert c.get("/healthz").status_code == 200

    assert c.post("/api/auth/setup", json={"password": "short"}).status_code == 422
    r = c.post("/api/auth/setup", json={"password": "correct horse battery"})
    assert r.status_code == 204
    assert "set-cookie" not in r.headers
    assert c.post("/api/auth/setup", json={"password": "another password"}).status_code == 409

    assert c.post("/api/auth/login", json={"password": "wrong password"}).status_code == 401
    r = c.post("/api/auth/login", json={"password": "correct horse battery"})
    assert r.status_code == 204
    cookie = r.headers["set-cookie"]
    assert "feedcatch_session=" in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    assert "Secure" not in cookie  # http test client
    assert c.get("/api/feeds").status_code == 200
    assert c.get("/api/auth/status").json()["authenticated"] is True

    assert c.post("/api/auth/logout").status_code == 204
    assert c.get("/api/feeds").status_code == 401


def test_login_rate_limit(auth_client: TestClient) -> None:
    c = auth_client
    c.post("/api/auth/setup", json={"password": "correct horse battery"})
    for _ in range(5):
        assert c.post("/api/auth/login", json={"password": "nope"}).status_code == 401
    assert c.post("/api/auth/login", json={"password": "correct horse battery"}).status_code == 429


# ---------------------------------------------------------------- feeds


def test_feeds_crud_and_ssrf(client: TestClient) -> None:
    r = client.post("/api/feeds", json=FEED_BODY)
    assert r.status_code == 201, r.text
    feed = r.json()
    assert feed["url"] == FEED_URL and feed["last_status"] == "never" and feed["entry_count"] == 0

    assert client.post("/api/feeds", json=FEED_BODY).status_code == 409
    for bad in ("http://internal.example.test/rss", "http://127.0.0.1/rss", "ftp://feed.example.test/x"):
        r = client.post("/api/feeds", json={**FEED_BODY, "url": bad})
        assert r.status_code == 400, (bad, r.text)
        assert "not allowed" in r.json()["detail"]
    assert (
        client.post(
            "/api/feeds", json={**FEED_BODY, "url": "https://x.example.test/a", "poll_interval_minutes": 1}
        ).status_code
        == 422
    )

    listing = client.get("/api/feeds").json()
    assert listing["total"] == 1 and len(listing["items"]) == 1

    r = client.put(f"/api/feeds/{feed['id']}", json={**FEED_BODY, "name": "Renamed", "poll_interval_minutes": 30})
    assert r.status_code == 200 and r.json()["name"] == "Renamed" and r.json()["poll_interval_minutes"] == 30
    assert client.put(f"/api/feeds/{feed['id']}", json={**FEED_BODY, "url": "http://10.0.0.1/"}).status_code == 400

    assert client.get(f"/api/feeds/{feed['id']}").status_code == 200
    assert client.delete(f"/api/feeds/{feed['id']}").status_code == 204
    assert client.get(f"/api/feeds/{feed['id']}").status_code == 404


def test_feed_test_preview_and_poll(client: TestClient, respx_mock: respx.MockRouter) -> None:
    mock_feed(respx_mock, sample_feed())
    r = client.post("/api/feeds/test", json={"url": FEED_URL})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["feed_title"] == "Anime Tosho" and body["entry_count"] == 9
    assert len(body["sample"]) == 5 and body["error"] is None
    assert body["sample"][0]["has_nzb"] is True and body["sample"][0]["parsed"]["group"] == "DKB"

    r = client.post("/api/feeds/test", json={"url": "http://internal.example.test/rss"})
    assert r.status_code == 200 and r.json()["ok"] is False and "not allowed" in r.json()["error"]

    feed = client.post("/api/feeds", json=FEED_BODY).json()
    r = client.get(f"/api/feeds/{feed['id']}/preview?limit=3")
    assert r.status_code == 200 and r.json()["total"] == 9 and len(r.json()["items"]) == 3

    r = client.post(f"/api/feeds/{feed['id']}/poll")  # bodiless POST
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["fetched"] == 9 and res["new_entries"] == 9 and res["historical"] == 9 and res["submitted"] == 0
    assert client.get(f"/api/feeds/{feed['id']}").json()["entry_count"] == 9


def test_feed_preview_502(client: TestClient, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(FEED_URL).mock(return_value=httpx.Response(500))
    feed = client.post("/api/feeds", json=FEED_BODY).json()
    assert client.get(f"/api/feeds/{feed['id']}/preview").status_code == 502


# ---------------------------------------------------------------- series / seasons


def test_series_and_seasons_crud(client: TestClient) -> None:
    s = _series(client, "Re:Zero", aliases=["ReZero", " ReZero "])
    assert s["name"] == "ReZero"  # ':' removed by sanitize
    assert s["aliases"] == ["ReZero"]
    assert s["seasons"][0]["computed_save_path"] == "/home/qbittorrent-nox/media/ReZero/Season 01"
    assert client.post("/api/series", json={"name": "rezero", "aliases": [], "monitored": True}).status_code == 409

    r = client.post(f"/api/series/{s['id']}/seasons", json={"season_number": 2, "absolute_min": 26})
    assert r.status_code == 201 and r.json()["computed_save_path"].endswith("/ReZero/Season 02")
    season2 = r.json()
    assert client.post(f"/api/series/{s['id']}/seasons", json={"season_number": 2}).status_code == 409

    r = client.put(f"/api/seasons/{season2['id']}", json={"season_number": 2, "path_override": "/media/other/S2"})
    assert r.status_code == 200 and r.json()["computed_save_path"] == "/media/other/S2"
    r = client.put(f"/api/seasons/{season2['id']}", json={"season_number": 2, "path_override": "/media/../etc"})
    assert r.status_code == 400

    paths = client.get(f"/api/series/{s['id']}/paths").json()["items"]
    assert [p["season_number"] for p in paths] == [1, 2]

    r = client.put(
        f"/api/series/{s['id']}",
        json={"name": "Re Zero", "aliases": [], "monitored": False, "season_folder_format": "S{season:02d}"},
    )
    assert r.status_code == 200 and r.json()["name"] == "Re Zero" and not r.json()["monitored"]
    assert r.json()["seasons"][0]["computed_save_path"] == "/home/qbittorrent-nox/media/Re Zero/S01"
    bad_fmt = {"name": "Re Zero", "aliases": [], "monitored": True, "season_folder_format": "{foo}"}
    r = client.put(f"/api/series/{s['id']}", json=bad_fmt)
    assert r.status_code == 400 and "season_folder_format" in r.json()["detail"]
    r = client.post("/api/series", json={"name": "X", "aliases": [], "monitored": True, "path_override": "relative"})
    assert r.status_code == 400

    assert client.delete(f"/api/seasons/{season2['id']}").status_code == 204
    assert client.delete(f"/api/series/{s['id']}").status_code == 204
    assert client.get(f"/api/series/{s['id']}").status_code == 404
    assert client.get("/api/series").json()["total"] == 0


def test_preview_path(client: TestClient) -> None:
    r = client.post(
        "/api/series/preview-path",
        json={"name": "Black Clover", "season_folder_format": "Season {season:02d}", "season_number": 2},
    )
    assert r.status_code == 200 and r.json() == {"save_path": EXPECTED_BC_S2}
    r = client.post(
        "/api/series/preview-path",
        json={"name": "..", "season_folder_format": "Season {season:02d}", "season_number": 2},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------- rules


def test_rules_crud_and_regex(client: TestClient) -> None:
    s = _series(client)
    season_id = s["seasons"][0]["id"]
    r = client.post("/api/rules", json=_rule_body(s["id"], season_id, regex="(unclosed"))
    assert r.status_code == 400 and r.json()["detail"].startswith("invalid regex")
    r = client.post("/api/rules", json=_rule_body(s["id"], season_id, regex=r"\bv2\b"))
    assert r.status_code == 201, r.text
    rule = r.json()
    assert rule["series_name"] == "Frieren" and rule["season_number"] == 1
    assert client.post("/api/rules", json=_rule_body(99999)).status_code == 400

    listing = client.get(f"/api/rules?series_id={s['id']}").json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == rule["id"]

    r = client.put(f"/api/rules/{rule['id']}", json=_rule_body(s["id"], None, priority=5, regex=None))
    assert r.status_code == 200 and r.json()["priority"] == 5 and r.json()["season_id"] is None
    assert client.get(f"/api/rules/{rule['id']}").status_code == 200
    assert client.delete(f"/api/rules/{rule['id']}").status_code == 204
    assert client.get(f"/api/rules/{rule['id']}").status_code == 404

    assert client.post("/api/rules/validate-regex", json={"pattern": "a+"}).json() == {"valid": True, "error": None}
    bad = client.post("/api/rules/validate-regex", json={"pattern": "a("}).json()
    assert bad["valid"] is False and bad["error"]


def test_simulate_saved_and_unsaved_series(client: TestClient) -> None:
    s = _series(client)
    titles = ["[SubsPlease] Frieren - S01E05 (1080p) [AAAA1111].mkv", "[Other] Frieren - S01E05 (1080p)"]
    r = client.post("/api/rules/simulate", json={"rule": _rule_body(s["id"], s["seasons"][0]["id"]), "titles": titles})
    assert r.status_code == 200, r.text
    a, b = r.json()["items"]
    assert a["matched"] is True and a["episode_number"] == 5 and a["season_number"] == 1
    assert a["save_path"] == "/home/qbittorrent-nox/media/Frieren/Season 01"
    assert b["matched"] is False and b["save_path"] is None
    assert any(c["check"] == "group" and not c["passed"] for c in b["conditions"])

    unsaved = {
        "name": "Dandadan",
        "aliases": [],
        "monitored": True,
        "seasons": [{"season_number": 1}, {"season_number": 2, "absolute_min": 13}],
    }
    r = client.post(
        "/api/rules/simulate",
        json={
            "rule": _rule_body(0, 1),
            "titles": ["[SubsPlease] Dandadan - 14 (1080p) [BBBB2222].mkv"],
            "series": unsaved,
        },
    )
    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    assert item["matched"] is True and item["season_number"] == 2 and item["episode_number"] == 2
    assert item["save_path"] == "/home/qbittorrent-nox/media/Dandadan/Season 02"
    r = client.post("/api/rules/simulate", json={"rule": _rule_body(0, 5), "titles": ["x"], "series": unsaved})
    assert r.status_code == 400


# ---------------------------------------------------------------- entries / grab / downloads


def _bc_setup(client: TestClient, respx_mock: respx.MockRouter) -> tuple[dict[str, Any], dict[str, Any], FakeQbit]:
    """Demo Black Clover (monitored) + feed polled once (historical) with an extra DKB S2E01 item."""
    series = _bc_demo(client, monitored=True)
    _configure_qbit(client)
    fake = FakeQbit(respx_mock)
    mock_feed(respx_mock, feed_with(make_item("[DKB] Black Clover Season 2 - 01 [1080p]", 1001)))
    feed = client.post("/api/feeds", json=FEED_BODY).json()
    assert client.post(f"/api/feeds/{feed['id']}/poll").json()["historical"] == 10
    return series, feed, fake


def test_entries_and_grab(client: TestClient, respx_mock: respx.MockRouter) -> None:
    series, feed, fake = _bc_setup(client, respx_mock)
    assert not fake.add_route.called

    listing = client.get(f"/api/entries?feed_id={feed['id']}&limit=5").json()
    assert listing["total"] == 10 and len(listing["items"]) == 5
    assert client.get("/api/entries?outcome=historical").json()["total"] == 10
    hits = client.get("/api/entries", params={"q": "black clover season 2"}).json()
    assert hits["total"] == 1
    entry = hits["items"][0]
    assert entry["is_historical"] is True and entry["feed_name"] == "Test"

    detail = client.get(f"/api/entries/{entry['id']}").json()
    assert detail["evaluations"][0]["matched"] is True and detail["downloads"] == []
    r = client.post(f"/api/entries/{entry['id']}/evaluate")  # bodiless
    assert r.status_code == 200 and r.json()["outcome"] == "historical"
    assert r.json()["evaluations"][0]["rule_name"] == "DKB 1080p"

    season_id = series["seasons"][0]["id"]
    grab = {"season_id": season_id, "episode_number": 1, "force": False, "confirm": False}
    r = client.post(f"/api/entries/{entry['id']}/grab", json=grab)
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["save_path"] == EXPECTED_BC_S2 and preview["source_url_kind"] == "magnet"
    assert preview["duplicate_of"] is None and preview["category"] == "anime"
    assert not fake.add_route.called

    r = client.post(f"/api/entries/{entry['id']}/grab", json={**grab, "confirm": True})
    assert r.status_code == 201, r.text
    download = r.json()
    assert download["status"] == "submitted" and download["save_path"] == EXPECTED_BC_S2
    assert fake.adds[0]["savepath"] == EXPECTED_BC_S2 and fake.adds[0]["autoTMM"] == "false"

    r = client.post(f"/api/entries/{entry['id']}/grab", json=grab)
    assert r.status_code == 200 and r.json()["duplicate_of"]["id"] == download["id"]
    assert client.post(f"/api/entries/{entry['id']}/grab", json={**grab, "confirm": True}).status_code == 409
    assert fake.add_route.call_count == 1

    # NZB-less? Grab of an entry without magnet/torrent -> 400 is covered in the pipeline tests; downloads API:
    dl = client.get("/api/downloads").json()
    assert dl["total"] == 1 and dl["items"][0]["entry_title"].startswith("[DKB] Black Clover")
    assert client.get("/api/downloads?status=failed").json()["total"] == 0
    assert client.get(f"/api/downloads/{download['id']}").json()["series_name"] == "Black Clover"
    r = client.post(f"/api/downloads/{download['id']}/retry")
    assert r.status_code == 200 and r.json()["status"] == "exists"
    assert fake.add_route.call_count == 1
    assert client.post("/api/downloads/retry-failed").json() == {"retried": 0}
    assert client.post("/api/downloads/refresh-status").json() == {"updated": 1}

    dash = client.get("/api/dashboard").json()
    assert dash["counts"]["series_monitored"] == 1 and len(dash["recent_downloads"]) == 1


def test_grab_nzb_only_entry_400(client: TestClient, respx_mock: respx.MockRouter) -> None:
    series = _bc_demo(client)
    mock_feed(respx_mock, feed_with(make_item("[DKB] Black Clover Season 2 - 02 [1080p]", 1002, magnet=False)))
    feed = client.post("/api/feeds", json=FEED_BODY).json()
    client.post(f"/api/feeds/{feed['id']}/poll")
    entry = client.get("/api/entries", params={"q": "Season 2 - 02"}).json()["items"][0]
    assert entry["magnet_url"] is None and entry["torrent_url"] is None and entry["has_nzb"] is True
    r = client.post(
        f"/api/entries/{entry['id']}/grab",
        json={"season_id": series["seasons"][0]["id"], "episode_number": 2, "force": False, "confirm": False},
    )
    assert r.status_code == 400 and "NZB-only" in r.json()["detail"]


def test_rule_test_recent(client: TestClient, respx_mock: respx.MockRouter) -> None:
    _bc_setup(client, respx_mock)
    rule = client.get("/api/rules").json()["items"][0]
    r = client.post(f"/api/rules/{rule['id']}/test-recent?limit=100")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 10 and all("entry_id" in i for i in items)
    assert [i["matched"] for i in items].count(True) == 1


# ---------------------------------------------------------------- qbit / settings / activity


def test_qbit_config_never_returns_password(client: TestClient, respx_mock: respx.MockRouter) -> None:
    _configure_qbit(client)
    r = client.get("/api/qbit")
    assert r.status_code == 200
    body = r.json()
    assert FAKE_QBIT_PASS not in r.text and "password" not in body
    assert body["password_set"] is True and body["url"] == QBIT_URL and body["sources"]["url"] == "db"

    FakeQbit(respx_mock)
    r = client.post("/api/qbit/test")  # no body
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["version"] == "v5.0.2"
    assert r.json()["category_exists"] is False
    r = client.post("/api/qbit/test", json={})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert client.get("/api/qbit").json()["last_test"]["ok"] is True
    assert FAKE_QBIT_PASS not in client.get("/api/activity").text

    respx_mock.post("http://unreachable.example.test:1/api/v2/auth/login").mock(
        side_effect=httpx.ConnectError("refused")
    )
    r = client.post("/api/qbit/test", json={"url": "http://unreachable.example.test:1"})
    assert r.status_code == 200 and r.json()["ok"] is False and r.json()["error"]

    assert client.put("/api/qbit", json={"url": "ftp://x"}).status_code == 400
    r = client.put("/api/qbit", json={"url": QBIT_URL, "password": ""})
    assert r.status_code == 200 and r.json()["password_set"] is False


def test_settings_put(client: TestClient) -> None:
    _bc_demo(client)
    current = client.get("/api/settings").json()
    assert current["media_base_path"] == "/home/qbittorrent-nox/media"
    payload = {k: v for k, v in current.items() if k not in ("sources", "warnings")}
    r = client.put("/api/settings", json={**payload, "media_base_path": "relative/path"})
    assert r.status_code == 400
    r = client.put("/api/settings", json={**payload, "media_base_path": "/srv/media/", "log_retention_days": 7})
    assert r.status_code == 200
    assert r.json()["media_base_path"] == "/srv/media" and r.json()["log_retention_days"] == 7
    series = client.get("/api/series").json()["items"][0]
    assert series["seasons"][0]["computed_save_path"] == "/srv/media/Black Clover/Season 02"


def test_activity_filters(client: TestClient) -> None:
    client.post("/api/feeds", json=FEED_BODY)
    r = client.get("/api/activity", params={"event_type": "feed_created"})
    assert r.status_code == 200 and r.json()["total"] == 1
    assert client.get("/api/activity", params={"event_type": "feed_"}).json()["total"] == 0
    assert client.get("/api/activity", params={"level": "error"}).json()["total"] == 0
    assert client.get("/api/activity?limit=500").status_code == 200


@pytest.mark.parametrize("path", ["/api/dashboard", "/api/series", "/api/rules", "/api/downloads", "/api/settings"])
def test_requires_auth(auth_client: TestClient, path: str) -> None:
    assert auth_client.get(path).status_code == 401

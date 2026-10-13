from __future__ import annotations

from urllib.parse import parse_qsl

import httpx
import pytest
import respx

from app.services.qbit import QbitClient, QbitError
from tests.helpers import FAKE_QBIT_PASS, FAKE_QBIT_USER, QBIT_URL

MAGNET = "magnet:?xt=urn:btih:" + "ab" * 20


def _client() -> QbitClient:
    return QbitClient(QBIT_URL, FAKE_QBIT_USER, FAKE_QBIT_PASS, timeout=5)


def _login_ok(router: respx.MockRouter) -> respx.Route:
    return router.post(f"{QBIT_URL}/api/v2/auth/login").mock(
        return_value=httpx.Response(200, text="Ok.", headers={"set-cookie": "SID=abc; path=/"})
    )


def test_login_then_add_sends_expected_form_and_headers(respx_mock: respx.MockRouter) -> None:
    login = _login_ok(respx_mock)
    add = respx_mock.post(f"{QBIT_URL}/api/v2/torrents/add").mock(return_value=httpx.Response(200, text="Ok."))
    with _client() as c:
        c.add(MAGNET, "/home/qbittorrent-nox/media/Black Clover/Season 02", "anime", paused=False)
    assert login.call_count == 1
    req = add.calls.last.request
    form = dict(parse_qsl(req.content.decode()))
    assert form["urls"] == MAGNET
    assert form["savepath"] == "/home/qbittorrent-nox/media/Black Clover/Season 02"
    assert form["autoTMM"] == "false"
    assert form["paused"] == "false" and form["stopped"] == "false"
    assert form["category"] == "anime"
    assert form["tags"] == "feedcatch"
    assert req.headers["referer"] == QBIT_URL + "/"
    assert req.headers["origin"] == QBIT_URL
    assert "SID=abc" in req.headers.get("cookie", "")
    login_req = login.calls.last.request
    assert login_req.headers["referer"] == QBIT_URL + "/"
    assert login_req.headers["origin"] == QBIT_URL


def test_login_fails_is_permanent(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(f"{QBIT_URL}/api/v2/auth/login").mock(return_value=httpx.Response(200, text="Fails."))
    with _client() as c, pytest.raises(QbitError) as ei:
        c.login()
    assert ei.value.transient is False
    assert FAKE_QBIT_PASS not in str(ei.value)


def test_403_on_add_relogins_once(respx_mock: respx.MockRouter) -> None:
    login = _login_ok(respx_mock)
    add = respx_mock.post(f"{QBIT_URL}/api/v2/torrents/add").mock(
        side_effect=[httpx.Response(403), httpx.Response(200, text="Ok.")]
    )
    with _client() as c:
        c.add(MAGNET, "/x", None, paused=True)
    assert login.call_count == 2
    assert add.call_count == 2
    assert "category" not in dict(parse_qsl(add.calls.last.request.content.decode()))


def test_403_persisting_is_transient(respx_mock: respx.MockRouter) -> None:
    _login_ok(respx_mock)
    respx_mock.post(f"{QBIT_URL}/api/v2/torrents/add").mock(return_value=httpx.Response(403))
    with _client() as c, pytest.raises(QbitError) as ei:
        c.add(MAGNET, "/x", None, paused=False)
    assert ei.value.transient is True


def test_timeout_is_transient(respx_mock: respx.MockRouter) -> None:
    _login_ok(respx_mock)
    respx_mock.post(f"{QBIT_URL}/api/v2/torrents/add").mock(side_effect=httpx.ReadTimeout("slow"))
    with _client() as c, pytest.raises(QbitError) as ei:
        c.add(MAGNET, "/x", None, paused=False)
    assert ei.value.transient is True
    assert ei.value.uncertain is True


def test_connect_error_is_transient(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(f"{QBIT_URL}/api/v2/auth/login").mock(side_effect=httpx.ConnectError("refused"))
    with _client() as c, pytest.raises(QbitError) as ei:
        c.version()
    assert ei.value.transient is True and ei.value.uncertain is False


def test_add_fails_is_permanent(respx_mock: respx.MockRouter) -> None:
    _login_ok(respx_mock)
    respx_mock.post(f"{QBIT_URL}/api/v2/torrents/add").mock(return_value=httpx.Response(200, text="Fails."))
    with _client() as c, pytest.raises(QbitError) as ei:
        c.add(MAGNET, "/x", None, paused=False)
    assert ei.value.transient is False


def test_5xx_is_transient(respx_mock: respx.MockRouter) -> None:
    _login_ok(respx_mock)
    respx_mock.get(f"{QBIT_URL}/api/v2/torrents/info").mock(return_value=httpx.Response(502))
    with _client() as c, pytest.raises(QbitError) as ei:
        c.info(["ab" * 20])
    assert ei.value.transient is True


def test_info_returns_save_path(respx_mock: respx.MockRouter) -> None:
    _login_ok(respx_mock)
    route = respx_mock.get(f"{QBIT_URL}/api/v2/torrents/info").mock(
        return_value=httpx.Response(
            200, json=[{"hash": "ab" * 20, "save_path": "/media/X/Season 01/", "state": "stalledDL", "progress": 0.5}]
        )
    )
    with _client() as c:
        items = c.info(["AB" * 20])
    assert items[0]["save_path"] == "/media/X/Season 01/"
    assert route.calls.last.request.url.params["hashes"] == "ab" * 20


def test_test_reports_diagnostics_and_warnings(respx_mock: respx.MockRouter) -> None:
    _login_ok(respx_mock)
    respx_mock.get(f"{QBIT_URL}/api/v2/app/version").mock(return_value=httpx.Response(200, text="v4.6.5"))
    respx_mock.get(f"{QBIT_URL}/api/v2/app/webapiVersion").mock(return_value=httpx.Response(200, text="2.9.3"))
    respx_mock.get(f"{QBIT_URL}/api/v2/app/preferences").mock(
        return_value=httpx.Response(
            200,
            json={"save_path": "/downloads", "auto_tmm_enabled": True, "temp_path_enabled": True, "temp_path": "/tmp"},
        )
    )
    respx_mock.get(f"{QBIT_URL}/api/v2/torrents/categories").mock(
        return_value=httpx.Response(200, json={"anime": {"name": "anime", "savePath": ""}})
    )
    with _client() as c:
        r = c.test("anime")
    assert r.ok is True
    assert r.version == "v4.6.5" and r.api_version == "2.9.3"
    assert r.auto_tmm_enabled is True and r.default_save_path == "/downloads"
    assert r.category_exists is True
    assert any("autoTMM=false" in w for w in r.warnings)
    assert any("temp_path" in w for w in r.warnings)


def test_test_returns_error_instead_of_raising(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(f"{QBIT_URL}/api/v2/auth/login").mock(return_value=httpx.Response(200, text="Fails."))
    with _client() as c:
        r = c.test()
    assert r.ok is False and r.error and "login failed" in r.error


# ---------------------------------------------------------------- qBittorrent 5.x semantics (observed live on v5.2.4)


def test_login_204_empty_body_is_success_v5(respx_mock: respx.MockRouter) -> None:
    login = respx_mock.post(f"{QBIT_URL}/api/v2/auth/login").mock(
        return_value=httpx.Response(204, headers={"set-cookie": "QBT_SID_8080=abc; path=/"})
    )
    respx_mock.get(f"{QBIT_URL}/api/v2/app/version").mock(return_value=httpx.Response(200, text="v5.2.4"))
    with QbitClient(QBIT_URL, "admin", "pw", timeout=5) as c:
        assert c.version() == "v5.2.4"
    assert login.call_count == 1


def test_login_401_is_permanent_credentials_error_v5(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(f"{QBIT_URL}/api/v2/auth/login").mock(return_value=httpx.Response(401, text="Unauthorized"))
    with QbitClient(QBIT_URL, "admin", "wrong", timeout=5) as c, pytest.raises(QbitError) as ei:
        c.login()
    assert ei.value.transient is False
    assert "401" in str(ei.value)


def test_401_on_add_relogins_once_v5(respx_mock: respx.MockRouter) -> None:
    login = respx_mock.post(f"{QBIT_URL}/api/v2/auth/login").mock(return_value=httpx.Response(204))
    add = respx_mock.post(f"{QBIT_URL}/api/v2/torrents/add").mock(
        side_effect=[httpx.Response(401, text="Unauthorized"), httpx.Response(200, text="Ok.")]
    )
    with QbitClient(QBIT_URL, "admin", "pw", timeout=5) as c:
        c.add("magnet:?xt=urn:btih:" + "a" * 40, "/media/X/Season 01", None, paused=True)
    assert add.call_count == 2
    assert login.call_count == 2


def test_add_accepts_v52_json_response(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(f"{QBIT_URL}/api/v2/auth/login").mock(return_value=httpx.Response(204))
    respx_mock.post(f"{QBIT_URL}/api/v2/torrents/add").mock(
        return_value=httpx.Response(
            200, json={"added_torrent_ids": ["ab" * 20], "failure_count": 0, "pending_count": 0}
        )
    )
    with QbitClient(QBIT_URL, "admin", "pw", timeout=5) as c:
        c.add(MAGNET, "/media/X/Season 01", "anime", paused=True)  # must not raise


def test_add_v52_json_failure_is_permanent(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(f"{QBIT_URL}/api/v2/auth/login").mock(return_value=httpx.Response(204))
    respx_mock.post(f"{QBIT_URL}/api/v2/torrents/add").mock(
        return_value=httpx.Response(200, json={"added_torrent_ids": [], "failure_count": 1, "pending_count": 0})
    )
    with QbitClient(QBIT_URL, "admin", "pw", timeout=5) as c, pytest.raises(QbitError) as ei:
        c.add(MAGNET, "/media/X/Season 01", None, paused=True)
    assert ei.value.transient is False

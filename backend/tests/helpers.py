"""Shared test helpers: feed fixture builders and a respx-backed fake qBittorrent."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

import httpx
import respx

from app.services.feeds import infohash_from_magnet

FIXTURES = Path(__file__).parent / "fixtures"
FEED_URL = "https://feed.example.test/rss2"
QBIT_URL = "http://qbit.example.test:8080"
FAKE_QBIT_USER = "test-user"
FAKE_QBIT_PASS = "not-a-real-password"  # obviously fake (safety invariant 4)
EXPECTED_BC_S2 = "/home/qbittorrent-nox/media/Black Clover/Season 02"


def sample_feed() -> bytes:
    return (FIXTURES / "animetosho_rss2_sample.xml").read_bytes()


def make_item(title: str, n: int, infohash: str | None = None, magnet: bool = True) -> str:
    h = infohash or f"{n:040x}"
    links = (
        f'<a href="magnet:?xt=urn:btih:{h}&amp;dn=x&amp;tr=udp%3A%2F%2Ft.example.test%3A1">Magnet</a>' if magnet else ""
    )
    return (
        f"<item><title>{title}</title>"
        f"<description><![CDATA[<p>Total Size: 1.2 GiB</p><p>Download Links: {links} | "
        f'<a href="https://feed.example.test/nzb/{n}">NZB</a></p>]]></description>'
        f"<link>https://feed.example.test/view/{n}</link>"
        f'<enclosure url="https://feed.example.test/nzb/{n}" type="application/x-nzb" length="1288490188"/>'
        f"<pubDate>Tue, 13 Oct 2026 14:00:00 +0000</pubDate>"
        f'<guid isPermaLink="true">https://feed.example.test/view/{n}</guid></item>'
    )


def feed_with(*items: str) -> bytes:
    """The AnimeTosho sample with extra items prepended (newest first)."""
    return sample_feed().replace(b"<item>", "".join(items).encode() + b"<item>", 1)


def mock_feed(router: respx.MockRouter, body: bytes | Callable[[], bytes], url: str = FEED_URL) -> respx.Route:
    def handler(_request: httpx.Request) -> httpx.Response:
        data = body() if callable(body) else body
        return httpx.Response(200, content=data, headers={"content-type": "application/rss+xml; charset=utf-8"})

    return router.get(url).mock(side_effect=handler)


class FakeQbit:
    """Stateful fake of the qBittorrent endpoints we use."""

    def __init__(
        self,
        router: respx.MockRouter,
        base: str = QBIT_URL,
        add_text: str = "Ok.",
        report_save_path: str | None = None,
    ) -> None:
        self.torrents: dict[str, dict[str, Any]] = {}
        self.adds: list[dict[str, str]] = []
        self.add_text = add_text
        self.report_save_path = report_save_path
        self.add_error: Exception | None = None  # raised AFTER registering the torrent (uncertain add)
        self.login_route = router.post(f"{base}/api/v2/auth/login").mock(
            return_value=httpx.Response(200, text="Ok.", headers={"set-cookie": "SID=fake; path=/"})
        )
        self.add_route = router.post(f"{base}/api/v2/torrents/add").mock(side_effect=self._add)
        self.info_route = router.get(f"{base}/api/v2/torrents/info").mock(side_effect=self._info)
        router.get(f"{base}/api/v2/app/version").mock(return_value=httpx.Response(200, text="v5.0.2"))
        router.get(f"{base}/api/v2/app/webapiVersion").mock(return_value=httpx.Response(200, text="2.11.2"))
        router.get(f"{base}/api/v2/app/preferences").mock(
            return_value=httpx.Response(
                200, json={"save_path": "/downloads", "auto_tmm_enabled": False, "temp_path_enabled": False}
            )
        )
        router.get(f"{base}/api/v2/torrents/categories").mock(return_value=httpx.Response(200, json={}))

    def _add(self, request: httpx.Request) -> httpx.Response:
        form = dict(parse_qsl(request.content.decode()))
        self.adds.append(form)
        if self.add_text == "Ok.":
            h = infohash_from_magnet(form["urls"]) if form["urls"].startswith("magnet:") else None
            h = h or f"{len(self.adds):040x}"
            self.torrents[h] = {
                "hash": h,
                "name": "torrent",
                "state": "downloading",
                "progress": 0.0,
                "save_path": self.report_save_path or form["savepath"] + "/",
                "added_on": int(time.time()),
                "category": form.get("category", ""),
            }
        if self.add_error is not None:
            raise self.add_error
        return httpx.Response(200, text=self.add_text)

    def _info(self, request: httpx.Request) -> httpx.Response:
        hashes = request.url.params.get("hashes")
        if hashes:
            wanted = hashes.split("|")
            return httpx.Response(200, json=[t for h, t in self.torrents.items() if h in wanted])
        return httpx.Response(200, json=list(self.torrents.values()))

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx

from app.services.feeds import (
    FeedFetchError,
    fetch_feed,
    infohash_from_magnet,
    infohash_from_torrent_url,
    parse_feed_bytes,
)
from tests.helpers import FEED_URL, FIXTURES, sample_feed


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_animetosho_fixture_parsed() -> None:
    title, entries = parse_feed_bytes(sample_feed(), "application/rss+xml; charset=utf-8")
    assert title == "Anime Tosho"
    assert len(entries) == 9
    e = entries[0]
    assert e.guid == "https://animetosho.net/view/696578"
    assert e.title.startswith("[DKB] Psyren - S01E02")
    assert e.link == "https://animetosho.net/view/696578"
    assert e.published_at == datetime(2026, 10, 12, 18, 25, 36, tzinfo=UTC)
    # magnet from description HTML, &amp; unescaped
    assert e.magnet_url is not None and e.magnet_url.startswith("magnet:?xt=urn:btih:19292fce")
    assert "&amp;" not in e.magnet_url and "&dn=" in e.magnet_url
    # torrent from the x-bittorrent enclosure, never the NZB
    assert e.torrent_url is not None and ".torrent" in e.torrent_url and "/nzb/" not in e.torrent_url
    assert e.nzb_url == "https://feed.animetosho.net/nzb/696578"
    assert e.size_bytes == 594394645
    assert e.infohash == "19292fce140dc39956c93fb0e4ef0b24417e004f"
    assert e.parsed.group == "DKB"
    for entry in entries:
        assert entry.torrent_url is None or "/nzb/" not in entry.torrent_url
        assert entry.infohash is not None and len(entry.infohash) == 40


def test_storage_url_infohash_matches_magnet() -> None:
    url = "https://storage.animetosho.net/legacy_tosho/storage/torrents/192/92fce140dc39956c93fb0e4ef0b24417e004f.torrent?filename=x"
    assert infohash_from_torrent_url(url) == "19292fce140dc39956c93fb0e4ef0b24417e004f"


def test_base32_magnet() -> None:
    m = "magnet:?xt=urn:btih:DLHSXGAOQHT2NTUAQPJPQPRZWQRWUPMT&dn=x"
    assert infohash_from_magnet(m) == "1acf2b980e81e7a6ce8083d2f83e39b4236a3d93"


def test_atom_fixture() -> None:
    title, entries = parse_feed_bytes(_read("atom_sample.xml"), "application/atom+xml")
    assert title == "Example Atom Releases"
    assert len(entries) == 2
    a, b = entries
    assert a.guid == "urn:example:entry:3"
    assert a.magnet_url is not None and a.infohash == "1acf2b980e81e7a6ce8083d2f83e39b4236a3d93"
    assert a.torrent_url == "https://atom.example.test/dl/3.torrent"
    assert a.size_bytes == 734003200
    # Nyaa-style: the link itself is the .torrent
    assert b.magnet_url is None and b.torrent_url == "https://atom.example.test/files/5.torrent"


def test_nzb_only_entry_has_no_torrent_url() -> None:
    _, entries = parse_feed_bytes(_read("nzb_only.xml"), "application/rss+xml")
    assert len(entries) == 1
    e = entries[0]
    assert e.magnet_url is None
    assert e.torrent_url is None
    assert e.nzb_url == "https://feed.example.test/nzb/1234"
    assert e.size_bytes == 1610612736


def test_invalid_xml() -> None:
    with pytest.raises(FeedFetchError) as ei:
        parse_feed_bytes(_read("invalid.xml"), "text/html")
    assert ei.value.transient is False


def test_doctype_rejected() -> None:
    with pytest.raises(FeedFetchError, match="DOCTYPE"):
        parse_feed_bytes(_read("doctype.xml"), "application/xml")


def test_total_size_fallback() -> None:
    xml = (
        b'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title><item><title>[G] X - 01 [1080p]</title>'
        b"<description><![CDATA[<p>Total Size: 820.3 MiB</p>"
        b'<a href="https://x.example.test/a.torrent?f=1">t</a>]]></description><guid>g1</guid></item></channel></rss>'
    )
    _, entries = parse_feed_bytes(xml, "application/rss+xml")
    assert entries[0].size_bytes == int(820.3 * 1024 * 1024)
    assert entries[0].torrent_url == "https://x.example.test/a.torrent?f=1"


def test_fetch_sends_headers_and_stores_validators(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(FEED_URL).mock(
        return_value=httpx.Response(
            200,
            content=sample_feed(),
            headers={"content-type": "application/rss+xml", "last-modified": "Tue, 13 Oct 2026 13:16:24 GMT"},
        )
    )
    result = fetch_feed(FEED_URL)
    assert result.status == 200 and not result.not_modified
    assert result.last_modified == "Tue, 13 Oct 2026 13:16:24 GMT"
    assert result.etag is None
    req = route.calls.last.request
    assert req.headers["user-agent"].startswith("feedcatch/")
    assert "if-modified-since" not in req.headers


def test_conditional_get_304(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(FEED_URL).mock(return_value=httpx.Response(304))
    result = fetch_feed(FEED_URL, etag='"abc"', last_modified="Tue, 13 Oct 2026 13:16:24 GMT")
    assert result.not_modified is True and result.entries == []
    req = route.calls.last.request
    assert req.headers["if-none-match"] == '"abc"'
    assert req.headers["if-modified-since"] == "Tue, 13 Oct 2026 13:16:24 GMT"
    assert result.etag == '"abc"'


def test_size_cap(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(FEED_URL).mock(return_value=httpx.Response(200, content=b"x" * 5000))
    with pytest.raises(FeedFetchError, match="exceeded|too large"):
        fetch_feed(FEED_URL, max_bytes=1000)


def test_default_size_cap_is_10_mib(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(FEED_URL).mock(return_value=httpx.Response(200, content=b"<" * (10 * 1024 * 1024 + 1)))
    with pytest.raises(FeedFetchError):
        fetch_feed(FEED_URL)


def test_timeout_is_transient(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(FEED_URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(FeedFetchError) as ei:
        fetch_feed(FEED_URL, timeout=1)
    assert ei.value.transient is True


def test_http_errors_classified(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(FEED_URL)
    route.mock(return_value=httpx.Response(503))
    with pytest.raises(FeedFetchError) as ei:
        fetch_feed(FEED_URL)
    assert ei.value.transient is True
    route.mock(return_value=httpx.Response(404))
    with pytest.raises(FeedFetchError) as ei:
        fetch_feed(FEED_URL)
    assert ei.value.transient is False

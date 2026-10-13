from __future__ import annotations

import httpx
import pytest
import respx

from app.services import ssrf
from app.services.feeds import FeedFetchError, fetch_feed
from tests.helpers import sample_feed


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/feed",
        "http://10.1.2.3/feed",
        "http://192.168.1.10:8080/rss",
        "http://172.16.0.1/rss",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/rss",
        "http://[::ffff:127.0.0.1]/rss",
        "http://0.0.0.0/rss",
        "http://224.0.0.1/rss",
        "http://internal.example.test/rss",
        "http://localhost/rss",
    ],
)
def test_private_targets_rejected(url: str) -> None:
    with pytest.raises(ssrf.SsrfError):
        ssrf.validate_feed_url(url, allow_private=False)


@pytest.mark.parametrize("url", ["ftp://feed.example.test/rss", "file:///etc/passwd", "gopher://x/", "feed", "http://"])
def test_non_http_or_hostless_rejected(url: str) -> None:
    with pytest.raises(ssrf.SsrfError):
        ssrf.validate_feed_url(url, allow_private=True)


def test_public_allowed() -> None:
    assert ssrf.validate_feed_url("https://feed.example.test/rss2", False) == "https://feed.example.test/rss2"
    assert ssrf.validate_feed_url("http://93.184.216.34/rss", False)


def test_allow_private_flag_honored() -> None:
    assert ssrf.validate_feed_url("http://internal.example.test/rss", allow_private=True)
    assert ssrf.validate_feed_url("http://192.168.1.10:8080/rss", allow_private=True)


def test_unresolvable_host_rejected() -> None:
    with pytest.raises(ssrf.SsrfError, match="resolve"):
        ssrf.validate_feed_url("https://nope.invalid/rss", False)


def test_redirect_to_private_rejected(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://feed.example.test/rss2").mock(
        return_value=httpx.Response(302, headers={"location": "http://internal.example.test/rss"})
    )
    inner = respx_mock.get("http://internal.example.test/rss").mock(return_value=httpx.Response(200, text="x"))
    with httpx.Client() as client, pytest.raises(ssrf.SsrfError):
        ssrf.fetch_with_safe_redirects(client, "https://feed.example.test/rss2", {}, allow_private=False)
    assert not inner.called
    with pytest.raises(FeedFetchError) as ei:
        fetch_feed("https://feed.example.test/rss2")
    assert ei.value.transient is False


def test_redirect_to_ip_literal_rejected(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://feed.example.test/rss2").mock(
        return_value=httpx.Response(301, headers={"location": "http://127.0.0.1:8080/admin"})
    )
    with httpx.Client() as client, pytest.raises(ssrf.SsrfError):
        ssrf.fetch_with_safe_redirects(client, "https://feed.example.test/rss2", {}, allow_private=False)


def test_public_redirect_followed(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://feed.example.test/old").mock(
        return_value=httpx.Response(301, headers={"location": "/rss2"})
    )
    respx_mock.get("https://feed.example.test/rss2").mock(return_value=httpx.Response(200, content=sample_feed()))
    result = fetch_feed("https://feed.example.test/old")
    assert len(result.entries) == 9


def test_too_many_redirects(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://feed.example.test/loop").mock(
        return_value=httpx.Response(302, headers={"location": "https://feed.example.test/loop"})
    )
    with httpx.Client() as client, pytest.raises(ssrf.SsrfError, match="too many redirects"):
        ssrf.fetch_with_safe_redirects(client, "https://feed.example.test/loop", {}, allow_private=False)

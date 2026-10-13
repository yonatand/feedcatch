"""SSRF protection for feed URLs (safety invariant 5).

- Only http/https.
- Hostnames are resolved with `socket.getaddrinfo`; every resolved address must be globally routable
  (`ipaddress.ip_address(x).is_global`) unless `allow_private` is true.
- Redirects are followed manually (max 5), re-validating each `Location`.
- Response bodies are streamed and aborted beyond `max_bytes`.

The qBittorrent URL is admin-configured and intentionally exempt (it is expected to be private).
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Mapping
from urllib.parse import urljoin, urlsplit

import httpx

MAX_REDIRECTS = 5
MAX_BYTES = 10 * 1024 * 1024
_REDIRECT_CODES = {301, 302, 303, 307, 308}


class SsrfError(ValueError):
    """The URL is not allowed (scheme, host, or resolved address)."""


class ResponseTooLargeError(Exception):
    """The response body exceeded the configured size cap."""


def _resolve(host: str, port: int) -> list[str]:
    """Resolve `host` to IP address strings. Separate function so tests can replace DNS."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def _is_public(ip_text: str) -> bool:
    ip = ipaddress.ip_address(ip_text.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return bool(ip.is_global) and not ip.is_multicast


def validate_feed_url(url: str, allow_private: bool) -> str:
    """Return the URL if it is allowed; else raise SsrfError with a human-readable reason."""
    if not isinstance(url, str) or not url.strip():
        raise SsrfError("URL must not be empty")
    url = url.strip()
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise SsrfError(f"invalid URL: {exc}") from exc
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise SsrfError(f"URL scheme must be http or https, not {parts.scheme or 'missing'!r}")
    host = parts.hostname
    if not host:
        raise SsrfError("URL has no host")
    if allow_private:
        return url
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not _is_public(str(literal)):
            raise SsrfError(f"host {host} is not a public address (set allow_private_feed_hosts to allow)")
        return url
    try:
        addresses = _resolve(host, port or (443 if scheme == "https" else 80))
    except (OSError, UnicodeError) as exc:
        raise SsrfError(f"could not resolve host {host}: {exc}") from exc
    if not addresses:
        raise SsrfError(f"could not resolve host {host}")
    for addr in addresses:
        try:
            public = _is_public(addr)
        except ValueError as exc:
            raise SsrfError(f"host {host} resolved to an unparsable address") from exc
        if not public:
            raise SsrfError(
                f"host {host} resolves to non-public address {addr} (set allow_private_feed_hosts to allow)"
            )
    return url


def fetch_with_safe_redirects(
    client: httpx.Client,
    url: str,
    headers: Mapping[str, str] | None,
    allow_private: bool,
    max_redirects: int = MAX_REDIRECTS,
    max_bytes: int = MAX_BYTES,
) -> tuple[int, httpx.Headers, bytes]:
    """GET `url`, following redirects manually with SSRF re-validation of every hop.

    Raises SsrfError (disallowed hop / too many redirects), ResponseTooLargeError, or httpx errors.
    """
    current = url
    for _hop in range(max_redirects + 1):
        validate_feed_url(current, allow_private)
        with client.stream("GET", current, headers=dict(headers or {}), follow_redirects=False) as resp:
            if resp.status_code in _REDIRECT_CODES:
                location = resp.headers.get("location")
                if not location:
                    raise SsrfError(f"redirect {resp.status_code} without Location header")
                current = urljoin(current, location)
                continue
            declared = resp.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise ResponseTooLargeError(f"response too large ({declared} bytes > {max_bytes})")
            buf = bytearray()
            for chunk in resp.iter_bytes():
                buf.extend(chunk)
                if len(buf) > max_bytes:
                    raise ResponseTooLargeError(f"response exceeded {max_bytes} bytes")
            return resp.status_code, resp.headers, bytes(buf)
    raise SsrfError(f"too many redirects (max {max_redirects})")

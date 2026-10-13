"""Minimal qBittorrent Web API v2 client (see skill qbittorrent-api).

Safety invariant 6: only auth/login, auth/logout, app/version, app/webapiVersion, app/preferences,
torrents/add, torrents/info and torrents/categories are ever called.
Never log the password.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import TracebackType
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.schemas import QbitTestResultOut

DEFAULT_TAG = "feedcatch"


class QbitError(Exception):
    """qBittorrent call failed. `transient` = retry later; `uncertain` = request may have reached qBittorrent."""

    def __init__(self, message: str, transient: bool, uncertain: bool = False) -> None:
        super().__init__(message)
        self.transient = transient
        self.uncertain = uncertain


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


class QbitClient:
    def __init__(
        self,
        url: str,
        username: str,
        password: str,
        timeout: float,
        verify_ssl: bool = True,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not url or not url.lower().startswith(("http://", "https://")):
            raise QbitError("qBittorrent URL must start with http:// or https://", transient=False)
        self.base_url = url.rstrip("/")
        self._username = username
        self._password = password
        self._logged_in = False
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout),
            verify=verify_ssl,
            follow_redirects=False,
            headers={"Referer": self.base_url + "/", "Origin": _origin(self.base_url)},
            transport=transport,
        )

    def __repr__(self) -> str:
        return f"QbitClient(url={self.base_url!r})"

    # -------------------------------------------------------------- lifecycle

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> QbitClient:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()

    # -------------------------------------------------------------- transport

    def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._client.request(method, path, **kwargs)
        except httpx.ConnectTimeout as exc:
            raise QbitError(f"timeout connecting to qBittorrent at {self.base_url}", transient=True) from exc
        except httpx.TimeoutException as exc:
            raise QbitError(f"timeout talking to qBittorrent ({path})", transient=True, uncertain=True) from exc
        except httpx.ConnectError as exc:
            raise QbitError(f"cannot connect to qBittorrent at {self.base_url}: {exc}", transient=True) from exc
        except httpx.HTTPError as exc:
            raise QbitError(
                f"network error talking to qBittorrent: {exc.__class__.__name__}", transient=True, uncertain=True
            ) from exc

    def login(self) -> None:
        resp = self._send("POST", "/api/v2/auth/login", data={"username": self._username, "password": self._password})
        if resp.status_code == 403:
            raise QbitError(
                "qBittorrent refused login (403): this IP may be temporarily banned after failed logins",
                transient=True,
            )
        if resp.status_code >= 500:
            raise QbitError(f"qBittorrent login returned HTTP {resp.status_code}", transient=True)
        if resp.status_code == 401:
            # qBittorrent 5.x: wrong credentials, or Host-header validation rejected the request
            raise QbitError(
                "qBittorrent login failed (401): wrong username/password, or the WebUI rejected the Host header "
                "(add this hostname to 'Server domains' in qBittorrent WebUI options)",
                transient=False,
            )
        if resp.status_code not in (200, 204):
            raise QbitError(f"qBittorrent login returned HTTP {resp.status_code}", transient=False)
        body = resp.text.strip()
        if body == "Fails.":
            # qBittorrent 4.x: 200 "Fails." on wrong credentials
            raise QbitError("qBittorrent login failed: wrong username or password", transient=False)
        # 4.x answers 200 "Ok."; 5.x answers 204 with an empty body (cookie QBT_SID_<port>)
        if body not in ("", "Ok."):
            raise QbitError(f"unexpected qBittorrent login response: {body[:100]!r}", transient=False)
        self._logged_in = True

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if not self._logged_in:
            self.login()
        resp = self._send(method, path, **kwargs)
        if resp.status_code in (401, 403):
            # session missing/expired (403 on 4.x, 401 on 5.x): re-login once, then retry once
            self._logged_in = False
            self.login()
            resp = self._send(method, path, **kwargs)
            if resp.status_code in (401, 403):
                raise QbitError(f"qBittorrent returned {resp.status_code} for {path} after re-login", transient=True)
        if resp.status_code >= 500:
            raise QbitError(f"qBittorrent returned HTTP {resp.status_code} for {path}", transient=True, uncertain=True)
        if resp.status_code >= 400:
            raise QbitError(f"qBittorrent returned HTTP {resp.status_code} for {path}", transient=False)
        return resp

    def _json(self, resp: httpx.Response, path: str) -> Any:
        try:
            return resp.json()
        except ValueError as exc:
            raise QbitError(f"invalid JSON from qBittorrent {path}", transient=True) from exc

    # -------------------------------------------------------------- API

    def version(self) -> str:
        return self._request("GET", "/api/v2/app/version").text.strip()

    def api_version(self) -> str:
        return self._request("GET", "/api/v2/app/webapiVersion").text.strip()

    def preferences(self) -> dict[str, Any]:
        data = self._json(self._request("GET", "/api/v2/app/preferences"), "app/preferences")
        return data if isinstance(data, dict) else {}

    def categories(self) -> dict[str, Any]:
        data = self._json(self._request("GET", "/api/v2/torrents/categories"), "torrents/categories")
        return data if isinstance(data, dict) else {}

    def add(
        self,
        url: str,
        savepath: str,
        category: str | None,
        paused: bool,
        tags: str = DEFAULT_TAG,
    ) -> None:
        """Add one magnet / .torrent URL with an explicit save path and autoTMM=false. Raises QbitError."""
        flag = "true" if paused else "false"
        data = {
            "urls": url,
            "savepath": savepath,
            "autoTMM": "false",
            "paused": flag,
            "stopped": flag,
            "tags": tags,
        }
        if category:
            data["category"] = category
        resp = self._request("POST", "/api/v2/torrents/add", data=data)
        body = resp.text.strip()
        if body == "Fails.":
            raise QbitError("qBittorrent rejected the torrent (Fails.)", transient=False)
        if resp.status_code == 415:
            raise QbitError("qBittorrent: torrent file is not valid (415)", transient=False)
        if body.startswith("{"):
            # qBittorrent 5.2+: JSON {"added_torrent_ids": [...], "failure_count": n, "pending_count": n}
            self._check_add_json(body)
            return
        if body and body != "Ok.":
            raise QbitError(f"unexpected qBittorrent add response: {body[:100]!r}", transient=False)

    @staticmethod
    def _check_add_json(body: str) -> None:
        try:
            parsed = json.loads(body)
        except ValueError as exc:
            raise QbitError(f"unexpected qBittorrent add response: {body[:100]!r}", transient=False) from exc
        if not isinstance(parsed, dict):
            raise QbitError(f"unexpected qBittorrent add response: {body[:100]!r}", transient=False)
        added = parsed.get("added_torrent_ids") or []
        failures = int(parsed.get("failure_count") or 0)
        pending = int(parsed.get("pending_count") or 0)
        if failures and not added and not pending:
            raise QbitError(f"qBittorrent rejected the torrent (failure_count={failures})", transient=False)

    def info(self, hashes: list[str] | None = None, category: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, str] = {}
        if hashes:
            params["hashes"] = "|".join(h.lower() for h in hashes)
        if category:
            params["category"] = category
        data = self._json(self._request("GET", "/api/v2/torrents/info", params=params), "torrents/info")
        return [t for t in data if isinstance(t, dict)] if isinstance(data, list) else []

    def test(self, category: str | None = None) -> QbitTestResultOut:
        """Connection diagnostics; never raises QbitError (returns ok=false with error)."""
        result = QbitTestResultOut(ok=False, at=datetime.now(UTC))
        try:
            self.login()
            result.version = self.version()
            result.api_version = self.api_version()
            prefs = self.preferences()
            auto_tmm = prefs.get("auto_tmm_enabled")
            result.auto_tmm_enabled = bool(auto_tmm) if auto_tmm is not None else None
            result.default_save_path = prefs.get("save_path")
            if auto_tmm:
                result.warnings.append(
                    "Automatic Torrent Management is enabled by default in qBittorrent; this app sends "
                    "autoTMM=false per torrent, so the explicit save path is still honored."
                )
            if prefs.get("temp_path_enabled"):
                result.warnings.append(
                    f"qBittorrent keeps incomplete files in temp_path ({prefs.get('temp_path')}) and moves them to "
                    "the save path when complete; this is qBittorrent's own behavior."
                )
            if category:
                cats = self.categories()
                result.category_exists = category in cats
                if not result.category_exists:
                    result.warnings.append(
                        f"Category '{category}' does not exist yet; qBittorrent creates it on the first add."
                    )
            result.ok = True
        except QbitError as exc:
            result.error = str(exc)
        return result
